import copy
from datetime import date, time
from pathlib import Path
import pytest
import yaml
from fastapi.testclient import TestClient
from app.main import app
from app.models import EventDraft, Supply
from agents.drafting import create_draft
from validators.proposal import validate_event

@pytest.fixture
def cfg():
    return yaml.safe_load((Path(__file__).parents[1]/'config.yaml').read_text())

@pytest.fixture
def event(cfg):
    return EventDraft.model_validate(create_draft("S'mores for 25 first-years on October 2, 2026 at 7 pm to 8 pm in social lounge A with $25",cfg,today=date(2026,9,30))['event'])

@pytest.fixture
def client(tmp_path,monkeypatch):
    monkeypatch.setenv('COBU_DB_PATH',str(tmp_path/'test.sqlite3'))
    return TestClient(app, base_url='http://localhost')

def check(event,cfg):
    return validate_event(event,cfg,{'actual_cents':0,'reserved_cents':0})

def test_local_drafting_is_labeled_and_extracts_fields(cfg):
    result=create_draft('Craft night for 45 residents on 2026-10-03 at 6 pm to 7 pm in quiet lounge with $42',cfg)
    e=result['event']
    assert result['provider']=='local_template'
    assert e['headcount']==45 and e['event_date']=='2026-10-03'
    assert e['start_time']=='18:00:00' and e['location']=='quiet lounge'
    assert e['requested_budget_cents']==4200
    assert e['supplies'][0]['quantity']==2

def test_valid_draft_does_not_claim_external_checks(event,cfg):
    result=check(event,cfg)
    assert result['local_pass'] is True
    assert result['external_ready'] is False
    assert next(x['status'] for x in result['checks'] if x['key']=='calendar')=='pending'
    assert not any(x['key']=='canva' for x in result['checks'])

@pytest.mark.parametrize('start,end,passes',[('18:00','19:00',True),('21:00','22:00',True),('18:30','19:30',False),('20:30','21:30',False)])
def test_hall_council_boundaries(event,cfg,start,end,passes):
    event.event_date=date(2026,9,30);event.start_time=time.fromisoformat(start);event.end_time=time.fromisoformat(end)
    assert check(event,cfg)['local_pass'] is passes

def test_overnight_is_explicitly_rejected(event,cfg):
    event.start_time=time(23);event.end_time=time(1)
    assert not check(event,cfg)['local_pass']

def test_vague_outcome_and_wrong_count(event,cfg):
    event.outcomes=['Residents will be able to: understand community by the end of the event.']
    result=check(event,cfg)
    issues=next(x['issues'] for x in result['checks'] if x['key']=='outcomes')
    assert len(issues)>=2

def test_collab_week_is_derived_from_date(event,cfg):
    event.event_date=date(2026,9,4);event.collaborators=['Alex']
    assert check(event,cfg)['semester_week']==1
    assert not check(event,cfg)['local_pass']
    event.event_date=date(2026,10,2)
    assert check(event,cfg)['local_pass']

def test_shared_config_changes_validation(event,cfg):
    cfg['budget']['cap_cents']=1000
    assert not check(event,cfg)['local_pass']

def test_wrong_floor_engagement_date(event,cfg):
    event.event_type='Floor Engagement';event.event_date=date(2026,12,8)
    assert not check(event,cfg)['local_pass']
    event.event_date=date(2026,12,7)
    assert check(event,cfg)['local_pass']

def test_cdp_needs_pair_and_trend(event,cfg):
    event.event_type='CDP / All-Hall'
    assert not check(event,cfg)['local_pass']
    event.collaborators=['Alex'];event.building_trend='Residents asked for more introductions.'
    assert check(event,cfg)['local_pass']

def test_drafts_do_not_reserve_approved_estimates_do(client,event):
    saved=client.post('/api/events',json=event.model_dump(mode='json')).json()['event']
    assert client.get('/api/budget').json()['reserved_cents']==0
    v=client.post('/api/validate',json=saved).json()
    approval=client.post('/api/approve',json={'event':saved,'validation_token':v['validation_token'],'reviewed':True})
    assert approval.status_code==200
    assert client.get('/api/budget').json()['reserved_cents']==2100
    assert client.get(f"/api/events/{saved['id']}/export").status_code==200
    actual=client.post(f"/api/events/{saved['id']}/actual",json={'cents':1850}).json()
    assert actual['actual_cents']==1850 and actual['reserved_cents']==0 and actual['available_cents']==13150

def test_unreviewed_or_changed_snapshot_cannot_approve(client,event):
    e=event.model_dump(mode='json');v=client.post('/api/validate',json=e).json()
    assert client.post('/api/approve',json={'event':e,'validation_token':v['validation_token'],'reviewed':False}).status_code==400
    e['title']='Changed'
    assert client.post('/api/approve',json={'event':e,'validation_token':v['validation_token'],'reviewed':True}).status_code==409

def test_repeated_approval_does_not_duplicate(client,event):
    e=event.model_dump(mode='json');v=client.post('/api/validate',json=e).json()
    body={'event':e,'validation_token':v['validation_token'],'reviewed':True}
    assert client.post('/api/approve',json=body).status_code==200
    assert client.post('/api/approve',json=body).status_code==409
    assert len(client.get('/api/events').json()['events'])==1

def test_other_approval_invalidates_budget_snapshot(client,event):
    first=event.model_dump(mode='json');v=client.post('/api/validate',json=first).json()
    other={**first,'title':'Another event'};other_v=client.post('/api/validate',json=other).json()
    assert client.post('/api/approve',json={'event':other,'validation_token':other_v['validation_token'],'reviewed':True}).status_code==200
    assert client.post('/api/approve',json={'event':first,'validation_token':v['validation_token'],'reviewed':True}).status_code==409

def test_existing_reservation_not_double_counted(client,event):
    saved=client.post('/api/events',json=event.model_dump(mode='json')).json()['event']
    v=client.post('/api/validate',json=saved).json()
    assert client.post('/api/approve',json={'event':saved,'validation_token':v['validation_token'],'reviewed':True}).status_code==200
    repeated=client.post('/api/validate',json=saved).json()
    assert repeated['projected_remaining_cents']==12900

def test_negative_money_and_fractional_quantity_rejected(client,event):
    e=event.model_dump(mode='json');e['supplies'][0]['unit_cost_cents']=-1
    assert client.post('/api/validate',json=e).status_code==422
    e=event.model_dump(mode='json');e['supplies'][0]['quantity']=1.5
    assert client.post('/api/validate',json=e).status_code==422

def test_cross_origin_write_rejected(client,event):
    assert client.post('/api/events',json=event.model_dump(mode='json'),headers={'Origin':'https://unrelated.example'}).status_code==403

def test_approved_export_gate(client,event):
    e=client.post('/api/events',json=event.model_dump(mode='json')).json()['event']
    assert client.get(f"/api/events/{e['id']}/export").status_code==403

def test_zero_cost_is_valid_but_missing_supplies_are_not(event,cfg):
    event.supplies=[Supply(name='Existing reusable supplies',quantity=1,unit_cost_cents=0)]
    assert check(event,cfg)['local_pass']
    event.supplies=[]
    assert not check(event,cfg)['local_pass']

def test_offset_times_rejected_instead_of_crashing(client,event):
    e=event.model_dump(mode='json');e['event_date']='2026-09-30';e['start_time']='18:00:00Z'
    assert client.post('/api/validate',json=e).status_code==422

def test_blank_collaborator_does_not_count(event,cfg):
    e=event.model_dump(mode='json');e['event_type']='CDP / All-Hall';e['collaborators']=['   '];e['building_trend']='A need for community'
    assert not check(EventDraft.model_validate(e),cfg)['local_pass']

def test_prior_semester_excluded_from_budget_and_rules(client,event,cfg):
    from app.storage import connect,save_event
    old=event.model_copy(update={'event_date':date(2025,9,3)})
    with connect() as conn:
        save_event(conn,old,'approved_local')
    assert client.get('/api/budget').json()['reserved_cents']==0
    assert client.post('/api/validate',json=event.model_dump(mode='json')).json()['local_pass']

def test_floor_engagement_distribution(event,cfg):
    event.event_type='Floor Engagement';event.event_date=date(2026,11,4)
    peer={'event':{**event.model_dump(mode='json'),'id':'peer'},'status':'approved_local'}
    event.event_date=date(2026,11,11)
    assert not validate_event(event,cfg,{'actual_cents':0,'reserved_cents':0},[peer])['local_pass']
    event.event_date=date(2026,12,4)
    assert validate_event(event,cfg,{'actual_cents':0,'reserved_cents':0},[peer])['local_pass']

def test_untrusted_host_rejected(client):
    assert client.get('/api/budget',headers={'Host':'unrelated.example'}).status_code==400

def test_out_of_range_idea_returns_controlled_error(client):
    assert client.post('/api/draft',json={'idea':'smores with $100001'}).status_code==422

def test_actual_spend_locks_planning_record(client,event):
    e=client.post('/api/events',json=event.model_dump(mode='json')).json()['event']
    v=client.post('/api/validate',json=e).json()
    assert client.post('/api/approve',json={'event':e,'validation_token':v['validation_token'],'reviewed':True}).status_code==200
    assert client.post(f"/api/events/{e['id']}/actual",json={'cents':1850}).status_code==200
    assert client.post('/api/events',json=e).status_code==409
