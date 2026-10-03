'use strict';
const $ = id => document.getElementById(id);
const money = cents => new Intl.NumberFormat('en-US',{style:'currency',currency:'USD'}).format(cents/100);
const esc = value => String(value ?? '').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const state = {config:null,budget:null,id:crypto.randomUUID(),validation:null,dirty:false,status:'draft',requestedBudget:null,requestedWeekday:null,flyerStyle:'Minimal',generatedFlyers:[],busy:false,view:'create',autoHeadcount:null};
let toastTimer;
function toast(message) { $('toast').textContent=message; $('toast').hidden=false; clearTimeout(toastTimer); toastTimer=setTimeout(()=>$('toast').hidden=true,6500); }
async function api(path, body, method) {
  const requestMethod=method||(body===undefined?'GET':'POST');
  const options=requestMethod==='GET'?{}:{method:requestMethod,headers:{'Content-Type':'application/json'},...(body===undefined?{}:{body:JSON.stringify(body)})};
  const response = await fetch(path, options);
  const result = await response.json();
  if(!response.ok) throw new Error(typeof result.detail==='string'?result.detail:Array.isArray(result.detail)?'Check the highlighted fields. Quantities must be whole numbers and costs cannot be negative.':'Could not complete this action. Please try again.');
  return result;
}
async function action(button, callback) {
  if(state.busy) return;
  state.busy=true;
  const label=button?.innerHTML;
  if(button){button.disabled=true;button.innerHTML='<span class="loading-spinner"></span> Working…';}
  try { return await callback(); } catch(error){toast(error.message);}
  finally {state.busy=false;if(button&&button.isConnected){button.disabled=false;button.innerHTML=label;}}
}
function estimate(event) {return event.supplies.reduce((sum,item)=>sum+item.quantity*item.unit_cost_cents,0);}
function readEvent() {
  const value=id=>$(id).value;
  return {id:state.id,idea:value('idea'),title:value('title'),event_type:value('event_type'),community:value('community'),event_date:value('event_date')||null,requested_weekday:state.requestedWeekday,start_time:value('start_time')||null,end_time:value('end_time')||null,location:value('location'),headcount:Number(value('headcount')),collaborators:value('collaborators').split(',').map(x=>x.trim()).filter(Boolean),description:value('description'),focus_areas:[...document.querySelectorAll('#focus-options input:checked')].map(x=>x.value),outcomes:[...document.querySelectorAll('.outcome-input')].map(x=>x.value),supplies:[...document.querySelectorAll('.supply-row')].map(row=>({name:row.querySelector('.supply-name').value,quantity:Number(row.querySelector('.supply-quantity').value),unit_cost_cents:Math.round(Number(row.querySelector('.supply-cost').value)*100),channel:row.querySelector('.supply-channel').value,link:row.querySelector('.supply-link').value})),notes:value('notes'),building_trend:value('building_trend'),requested_budget_cents:state.requestedBudget,flyer_style:state.flyerStyle};
}
function fillEvent(event) {
  state.id=event.id||crypto.randomUUID();state.requestedBudget=event.requested_budget_cents??null;state.requestedWeekday=event.requested_weekday||null;state.flyerStyle=event.flyer_style||'Minimal';state.validation=null;state.generatedFlyers=[];state.autoHeadcount=event.headcount??null;
  ['idea','title','event_type','community','event_date','start_time','end_time','location','headcount','description','notes','building_trend'].forEach(id=>$(id).value=event[id]??'');
  $('collaborators').value=(event.collaborators||[]).join(', ');
  document.querySelectorAll('#focus-options input').forEach(x=>x.checked=(event.focus_areas||[]).includes(x.value));
  $('outcome-fields').innerHTML='';
  Array.from({length:state.config.outcomes.count},(_,i)=>event.outcomes?.[i]||'').forEach((value,i)=>{
    const wrapper=document.createElement('div');wrapper.className='outcome-row';wrapper.innerHTML=`<span class="outcome-number" aria-hidden="true">${i+1}</span><label class="sr-only" for="outcome-${i}">Learning outcome ${i+1}</label><textarea class="outcome-input" id="outcome-${i}" rows="2" placeholder="Residents will design, identify, or create …">${esc(value)}</textarea>`;$('outcome-fields').append(wrapper);
  });
  $('supply-fields').innerHTML='';(event.supplies||[]).forEach(addSupply);
  $('event-limit').value=state.requestedBudget===null?'':(state.requestedBudget/100).toFixed(2);
  state.dirty=false;updatePreview();showCreation();
}
function addSupply(item={name:'',quantity:1,unit_cost_cents:0,channel:'Grocery',link:''}) {
  const wrapper=document.createElement('div');wrapper.className='supply-entry';
  wrapper.innerHTML=`<div class="supply-row"><input class="supply-name" aria-label="Supply name" value="${esc(item.name)}" placeholder="Item name" maxlength="300"><input class="supply-quantity" type="number" min="1" max="10000" step="1" aria-label="Supply quantity" value="${item.quantity}"><input class="supply-cost" type="number" min="0" step="0.01" aria-label="Estimated unit price in dollars" value="${(item.unit_cost_cents/100).toFixed(2)}"><button type="button" class="remove-supply" aria-label="Remove ${esc(item.name||'supply')}">×</button><select class="supply-channel" aria-label="Purchase source"><option${item.channel==='Grocery'?' selected':''}>Grocery</option><option${item.channel==='Amazon'?' selected':''}>Amazon</option><option${item.channel==='Restaurant'?' selected':''}>Restaurant</option><option${item.channel==='Other'?' selected':''}>Other</option></select><input class="supply-link" aria-label="Optional product link" placeholder="Product link (optional)" value="${esc(item.link||'')}"></div>`;
  wrapper.querySelector('.remove-supply').addEventListener('click',()=>{wrapper.remove();markEdited();});$('supply-fields').append(wrapper);
}
function suggestedAttendance(type){const p=state.config.profile,allHall=type==='CDP / All-Hall';const residents=allHall?p.building_residents:p.floor_residents;return residents?Math.max(1,Math.ceil(residents*.15)):state.config.drafting.default_headcount;}
function blankEvent() {const d=state.config.drafting,p=state.config.profile;const floor=p.floor?`Floor ${p.floor}`:'';return {title:'',idea:'',event_type:d.default_event_type,community:floor||p.residence_hall||'',event_date:null,start_time:d.default_start_time,end_time:d.default_end_time,location:'',headcount:suggestedAttendance(d.default_event_type),collaborators:[],description:'',focus_areas:[],outcomes:[],supplies:[],notes:'',building_trend:''};}
function displayDate(event) {
  if(!event.event_date)return 'Date & time to come';
  const d=new Date(event.event_date+'T12:00:00');
  const fmt=t=>t?new Date('2000-01-01T'+t).toLocaleTimeString('en-US',{hour:'numeric',minute:'2-digit'}):'';
  return d.toLocaleDateString('en-US',{weekday:'short',month:'short',day:'numeric'})+(event.start_time?' · '+fmt(event.start_time):'')+(event.end_time?'–'+fmt(event.end_time):'');
}
function currentAvailable() {
  let available=state.budget?.available_cents??0;
  const record=state.budget?.events.find(x=>x.event.id===state.id);
  if(record?.status==='approved_local'&&record.actual_cents===null&&record.event.event_date>=state.config.semester.start_date&&record.event.event_date<=state.config.semester.end_date)available+=estimate(record.event);
  return available;
}
function calendarTemplateUrl(event){
  if(!event.title||!event.event_date||!event.start_time||!event.end_time)return '';
  const compactTime=value=>value.replace(':','')+'00';
  const dates=event.event_date.replaceAll('-','')+'T'+compactTime(event.start_time)+'/'+event.event_date.replaceAll('-','')+'T'+compactTime(event.end_time);
  const details=[`Event type: ${event.event_type}`,`For: ${event.community}`,`Expected attendance: ${event.headcount}`,event.description,...(event.outcomes||[]).filter(Boolean).map(x=>'• '+x),...(event.supplies||[]).map(x=>`${x.quantity} × ${x.name} — ${money(x.unit_cost_cents)}/unit`)].filter(Boolean).join('\n');
  const params=new URLSearchParams({action:'TEMPLATE',text:event.title,dates,details,location:event.location||''});
  const timezone=state.config?.semester?.timezone;if(timezone)params.set('ctz',timezone);
  return 'https://calendar.google.com/calendar/render?'+params.toString();
}
function updatePreview() {
  if(!state.config)return;
  const event=readEvent(), cost=estimate(event), available=currentAvailable();
  const calendarLink=$('calendar-add-link');if(calendarLink){const url=calendarTemplateUrl(event);calendarLink.hidden=!url;if(url)calendarLink.href=url;}
  $('preview-title').textContent=event.title||'A little idea. A great evening.';
  $('preview-description').textContent=event.description||'Your event takes shape here as you fill in the details.';
  $('preview-date').textContent=displayDate(event);
  $('preview-location').textContent=event.location||'Find your gathering spot';
  $('preview-type').textContent=event.event_type.toUpperCase();
  $('preview-attendees').textContent=(event.headcount||0)+' residents';
  $('estimate-total').textContent=money(cost);$('preview-cost').textContent=money(cost);
  $('after-budget').textContent=money(available-cost)+' left';$('after-budget').classList.toggle('error-text',cost>available);
  $('budget-fill').style.width=Math.min(100,cost/(state.budget?.cap_cents||15000)*100)+'%';
  $('budget-fill').style.background=cost>available?'var(--red)':'#7084ee';
  $('trend-field').hidden=!state.config.event_types[event.event_type]?.building_trend_required;
  $('budget-guidance').textContent=cost>available?'This estimate exceeds the available semester balance.':'Plan around '+money(state.budget?.event_allowance_cents||0)+' per Hall Snacks event. All prices are estimates.';
}
function markEdited(){state.dirty=true;state.validation=null;state.generatedFlyers=[];state.status='draft';$('save-status').textContent='Unsaved changes · validate again after edits.';$('draft-label').textContent='EDITING DRAFT';updatePreview();}
async function refreshBudget(){state.budget=await api('/api/budget');$('side-remaining').textContent=money(state.budget.available_cents);$('side-budget-fill').style.width=Math.min(100,(state.budget.actual_cents+state.budget.reserved_cents)/state.budget.cap_cents*100)+'%';$('draft-count').textContent=state.budget.events.length;updatePreview();}
function showCreation(){ $('creation-panel').hidden=false;$('validation-panel').hidden=true;$('step-create').classList.add('active');$('step-create').setAttribute('aria-current','step');$('step-validate').classList.remove('active');$('step-validate').removeAttribute('aria-current');}
async function changeView(view){stopSpeech();state.view=view;document.querySelectorAll('.view').forEach(x=>x.hidden=x.id!==view+'-view');document.querySelectorAll('.nav-item').forEach(x=>x.classList.toggle('active',x.dataset.view===view));$('page-crumb').textContent={create:'Create an event',drafts:'My events',budget:'Semester budget',settings:'Settings'}[view];if(view==='drafts')await renderDrafts();if(view==='budget')await renderBudget();if(view==='settings')await renderSettings();window.scrollTo({top:0,behavior:'smooth'});}
async function saveDraft(){const result=await api('/api/events',readEvent());state.id=result.event.id;state.dirty=false;state.status='draft';state.validation=null;$('save-status').textContent='Draft saved on this computer.';$('draft-label').textContent='SAVED DRAFT';await refreshBudget();toast('Draft saved. You can find it in My events.');}
async function validateDraft(){
  if(!$('event-form').reportValidity())return;
  const event=readEvent();state.validation=await api('/api/validate',event);
  $('creation-panel').hidden=true;$('validation-panel').hidden=false;$('step-create').classList.remove('active');$('step-create').removeAttribute('aria-current');$('step-validate').classList.add('active');$('step-validate').setAttribute('aria-current','step');
  renderValidation();window.scrollTo({top:0,behavior:'smooth'});
}
function downloadFlyer(flyer,event){
  const image=new Image();image.src=flyer.url;
  image.onload=()=>{
    const canvas=document.createElement('canvas');canvas.width=1024;canvas.height=1536;
    const ctx=canvas.getContext('2d');ctx.drawImage(image,0,0,canvas.width,canvas.height);
    const gradient=ctx.createLinearGradient(0,820,0,1536);gradient.addColorStop(0,'rgba(18,29,50,0)');gradient.addColorStop(.28,'rgba(18,29,50,.76)');gradient.addColorStop(1,'rgba(18,29,50,.94)');ctx.fillStyle=gradient;ctx.fillRect(0,780,1024,756);
    ctx.fillStyle='#fff';ctx.textBaseline='top';ctx.font='700 30px Arial';ctx.fillText(String(event.event_type||'COMMUNITY EVENT').toUpperCase(),74,1000);
    const title=event.title||'Your gathering';ctx.font='700 78px Arial';const words=title.split(/\s+/);let line='',y=1060;const maxWidth=870;
    for(const word of words){const test=line?line+' '+word:word;if(ctx.measureText(test).width>maxWidth&&line){ctx.fillText(line,74,y);line=word;y+=88;}else line=test;}if(line)ctx.fillText(line,74,y);
    y+=108;ctx.font='500 42px Arial';ctx.fillText(displayDate(event),74,y);y+=62;ctx.fillText(event.location||'Location to come',74,y);
    canvas.toBlob(blob=>{if(!blob){toast('Could not export this flyer.');return;}const link=document.createElement('a');link.href=URL.createObjectURL(blob);link.download='cobu-flyer.png';link.click();URL.revokeObjectURL(link.href);},'image/png');
  };
  image.onerror=()=>toast('Could not load the flyer image. Try generating it again.');
}
function renderValidation(){
  const v=state.validation,event=readEvent();if(!v)return;
  const blocked=!v.approval_ready;
  const statusNames={pass:'Passed',fail:'Conflict',pending:'Connect in Settings',review:'Check needed'};
  $('validation-panel').innerHTML=`<div class="status-message ${blocked?'warning':''}"><strong>${blocked?'A check needs attention.':'Your local checks pass.'}</strong> ${blocked?'Fix the failed check or resolve Google Calendar access before approval.':'Review the suggestions before approving your proposal.'} Calendar status appears below; it never books an event.</div><div class="validation-grid"><div><section class="card validation-list"><div class="section-heading"><div><h2>A second set of eyes</h2><p>${esc(event.title||'Your event')} · ${esc(displayDate(event))}</p></div></div>${v.checks.map(c=>`<div class="validation-row"><span class="status-icon ${c.status}" aria-hidden="true">${c.status==='pass'?'✓':c.status==='fail'?'!':c.status==='pending'?'−':'○'}</span><div><h3>${esc(c.title)}</h3><p>${esc(c.detail)}</p>${c.issues.length?`<ul>${c.issues.map(x=>`<li>${esc(x)}</li>`).join('')}</ul>`:''}</div><span class="validation-label">${statusNames[c.status]}</span></div>`).join('')}</section><section class="card flyer-section"><h3>Generate three AI flyers</h3><p>Choose an art direction and add an optional style note. CoBu generates three image options and overlays the exact event details.</p><div class="flyer-generator-controls"><label class="field">Style<select id="flyer-generator-style">${state.config.flyers.styles.map(style=>`<option${style===state.flyerStyle?' selected':''}>${esc(style)}</option>`).join('')}</select></label><label class="field">Describe the look you want<textarea id="flyer-style-description" rows="2" maxlength="1200" placeholder="For example: cozy autumn colors, hand-drawn stars, warm and welcoming"></textarea></label><button class="button primary" id="generate-flyers" type="button">Generate 3 AI flyers</button><small>Uses the OpenAI API; charges are separate from a ChatGPT subscription.</small></div><div class="generated-flyers" id="generated-flyers">${state.generatedFlyers.map((flyer,index)=>`<article class="generated-flyer"><img src="${esc(flyer.url)}" alt="AI-generated ${esc(flyer.style)} flyer artwork, option ${index+1}"><div class="generated-flyer-copy"><small>${esc(event.event_type)}</small><h4>${esc(event.title||'Your gathering')}</h4><p>${esc(displayDate(event))}<br>${esc(event.location||'Location to come')}</p><button type="button" class="button secondary" data-download-flyer="${index}">Download flyer</button></div></article>`).join('')}</div><h4 class="local-options-title">Local style previews</h4><div class="flyer-options">${state.config.flyers.styles.map(style=>`<button class="flyer-option ${state.flyerStyle===style?'selected':''}" data-style="${esc(style)}" aria-pressed="${state.flyerStyle===style}"><span class="flyer-sample"><small>${esc(event.event_type.toUpperCase())}</small><strong>${esc(event.title||'Your gathering')}</strong><p>${esc(displayDate(event))}<br>${esc(event.location)}</p></span><span class="flyer-name">${esc(style)}${state.flyerStyle===style?' · Selected':''}</span></button>`).join('')}</div><button class="button secondary copy-flyer-details" id="copy-flyer-details" type="button">Copy event details</button></section><div class="bottom-actions"><button class="button secondary" id="back-edit">Back to editing</button><button class="button secondary" id="recheck">Run checks again</button></div></div><aside><section class="card review-card"><h3>Review, then approve</h3>${calendarTemplateUrl(event)?`<a class="button secondary" href="${esc(calendarTemplateUrl(event))}" target="_blank" rel="noreferrer">Open in Google Calendar</a><p class="save-time">Review the prefilled event and press Save in Google Calendar to add it.</p>`:""}<p>Approval saves this proposal locally and sets aside its estimated budget. Calendar availability is checked separately; it never books a room or event.</p><div class="summary-stat"><span>Event estimate</span><strong>${money(v.estimate_cents)}</strong></div><div class="summary-stat"><span>Semester balance after</span><strong>${money(v.projected_remaining_cents)}</strong></div><label class="review-check"><input type="checkbox" id="reviewed" ${!v.approval_ready?'disabled':''}><span>I reviewed the outcomes, activity, supplies, and costs.</span></label><button class="button primary" id="approve" disabled>Approve local proposal</button><p id="approval-status" class="save-time">${v.approval_ready?'Your approval applies to this version only.':'Resolve the checks above before approving.'}</p><div id="export-actions" hidden><button class="button secondary" id="export-json">Download proposal</button></div></section><section class="next-card"><span class="next-kicker">EVENT CHECKLIST</span><ul>${v.requirements.map(x=>`<li>${esc(x)}</li>`).join('')}</ul><p class="connection-footnote">These are planning tasks, not completed actions.</p></section></aside></div>`;
  document.querySelectorAll('[data-download-flyer]').forEach(button=>button.onclick=()=>downloadFlyer(state.generatedFlyers[Number(button.dataset.downloadFlyer)],event));
  $('generate-flyers').onclick=()=>action($('generate-flyers'),async()=>{
    const style=$('flyer-generator-style').value;
    const result=await api('/api/flyers/generate',{event,style,custom_description:$('flyer-style-description').value});
    state.generatedFlyers=result.flyers.map(x=>({...x,style}));
    $('generated-flyers').innerHTML=state.generatedFlyers.map((flyer,index)=>`<article class="generated-flyer"><img src="${esc(flyer.url)}" alt="AI-generated ${esc(style)} flyer artwork, option ${index+1}"><div class="generated-flyer-copy"><small>${esc(event.event_type)}</small><h4>${esc(event.title||'Your gathering')}</h4><p>${esc(displayDate(event))}<br>${esc(event.location||'Location to come')}</p><button type="button" class="button secondary" data-download-flyer="${index}">Download flyer</button></div></article>`).join('');
    document.querySelectorAll('[data-download-flyer]').forEach(button=>button.onclick=()=>downloadFlyer(state.generatedFlyers[Number(button.dataset.downloadFlyer)],event));
    toast('Three flyer options are ready.');
  });
  $('flyer-generator-style').onchange=event=>{state.flyerStyle=event.target.value;};
  $('copy-flyer-details').onclick=async()=>{
    const lines=[
      `Event: ${event.title||'Untitled event'}`,
      `Type: ${event.event_type}`,
      `Date: ${displayDate(event)}`,
      `Time: ${event.start_time||'TBD'}${event.end_time?`–${event.end_time}`:''}`,
      `Location: ${event.location||'TBD'}`,
      `For: ${event.community||'Residents'}`,
      `Description: ${event.description||'TBD'}`,
      ...(event.outcomes?.filter(Boolean).length?['Learning outcomes:',...event.outcomes.filter(Boolean).map(x=>`- ${x}`)]:[]),
    ];
    try{await navigator.clipboard.writeText(lines.join('\n'));toast('Event details copied. Paste them into ChatGPT or Canva.');}
    catch{toast('Clipboard access was blocked. Copy the event details from the form instead.');}
  };
  $('back-edit').onclick=()=>{showCreation();window.scrollTo({top:0,behavior:'smooth'});};
  $('recheck').onclick=()=>action($('recheck'),validateDraft);
  $('reviewed').onchange=()=>{$('approve').disabled=!$('reviewed').checked||!state.validation?.approval_ready;};
  $('approve').onclick=()=>action($('approve'),async()=>{
    const result=await api('/api/approve',{event:readEvent(),validation_token:state.validation.validation_token,reviewed:$('reviewed').checked});
    state.id=result.event.id;state.status=result.status;state.dirty=false;state.validation=null;
    $('approval-status').textContent=result.message;$('export-actions').hidden=false;$('reviewed').disabled=true;
    $('approve').remove();$('draft-label').textContent='APPROVED LOCALLY';$('save-status').textContent='Approved proposal saved on this computer.';
    document.querySelectorAll('.flyer-option').forEach(x=>x.disabled=true);
    await refreshBudget();toast('Proposal approved locally. Nothing has been booked or sent.');
  });
  $('export-json').onclick=()=>{window.location.href='/api/events/'+encodeURIComponent(state.id)+'/export';};
  document.querySelectorAll('.flyer-option').forEach(button=>button.onclick=()=>action(button,async()=>{state.flyerStyle=button.dataset.style;state.dirty=true;state.validation=null;await validateDraft();toast('Style updated. Review this version before approving.');}));
}
async function renderDrafts(){
  await refreshBudget();const records=state.budget.events;
  $('drafts-view').innerHTML=`<div class="page-heading"><div><div class="eyebrow">YOUR COMMUNITY, IN THE MAKING</div><h1>My events<span class="heading-dot">.</span></h1><p>Saved on this computer. Pick up where you left off.</p></div><button class="button primary" id="draft-new">Create an event</button></div>${records.length?`<div class="saved-grid">${records.map(r=>`<article class="card saved-event"><span class="list-tag ${r.status==='approved_local'?'success-tag':''}">${r.actual_cents!==null?'Actual spend recorded':r.status==='approved_local'?'Approved locally':'Draft'}</span><h2>${esc(r.event.title||'Untitled event')}</h2><p>${esc(displayDate(r.event))}<br>${esc(r.event.location||'Location to come')}</p><div class="summary-stat"><span>${r.actual_cents!==null?'Actual cost':'Estimated cost'}</span><strong>${money(r.actual_cents??estimate(r.event))}</strong></div><div class="saved-actions"><button class="button secondary" data-open="${r.event.id}">${r.actual_cents!==null?'Use as new draft':'Open event'}</button>${calendarTemplateUrl(r.event)?`<a class="button secondary" href="${esc(calendarTemplateUrl(r.event))}" target="_blank" rel="noreferrer">Open in Google Calendar</a>`:""}<button class="button secondary" data-copy="${r.event.id}">Copy to ${esc(state.config.active_semester)} draft</button>${r.status==='approved_local'?`<a class="button secondary" href="/api/events/${r.event.id}/export">Download proposal</a>`:''}<button class="button danger" data-delete="${r.event.id}">Delete event</button></div><div class="save-time">${new Date(r.updated_at).toLocaleString()}</div></article>`).join('')}</div>`:`<div class="card empty-state"><h2>Your next gathering starts here.</h2><p>Save an event draft and it will appear in this space.</p><button class="button primary" id="empty-create">Create your first event</button></div>`}`;
  $('draft-new').onclick=()=>startFresh();if($('empty-create'))$('empty-create').onclick=()=>startFresh();
  document.querySelectorAll('[data-open]').forEach(button=>button.onclick=async()=>{if(state.dirty&&!confirm('Replace your unsaved event with this saved draft?'))return;const r=records.find(x=>x.event.id===button.dataset.open);fillEvent({...r.event,id:r.actual_cents!==null?null:r.event.id});state.status=r.actual_cents!==null?'draft':r.status;$('save-status').textContent=r.actual_cents!==null?'Copied into a new draft. Review the date and costs.':'Saved event loaded. Edits need a new validation.';$('draft-label').textContent=r.actual_cents!==null?'NEW COPY':r.status==='approved_local'?'APPROVED LOCALLY':'SAVED DRAFT';await changeView('create');});
  document.querySelectorAll('[data-copy]').forEach(button=>button.onclick=async()=>{if(state.dirty&&!confirm('Replace your unsaved event with this copied event?'))return;const r=records.find(x=>x.event.id===button.dataset.copy);fillEvent({...r.event,id:null,event_date:null,headcount:suggestedAttendance(r.event.event_type)});state.status='draft';state.dirty=true;$('draft-label').textContent='NEW SEMESTER COPY';$('save-status').textContent=`Copy based on ${r.event.title||'saved event'} · choose a date for ${state.config.active_semester}.`;$('idea').value=`Copy of ${r.event.title||'event'} for ${state.config.active_semester}`;await changeView('create');toast('Copied as a new draft. The original event is preserved.');});
  document.querySelectorAll('[data-delete]').forEach(button=>button.onclick=()=>action(button,async()=>{const r=records.find(x=>x.event.id===button.dataset.delete);if(!r)return;if(!confirm(`Permanently delete “${r.event.title||'Untitled event'}” from this computer?${r.actual_cents!==null?' Its recorded actual spending will also be removed from the semester budget.':''}`))return;await api('/api/events/'+encodeURIComponent(r.event.id),undefined,'DELETE');await renderDrafts();toast('Event deleted.');}));
}
async function renderBudget(){
  await refreshBudget();const b=state.budget;const records=b.events.filter(x=>x.status==='approved_local'&&x.event.event_date>=state.config.semester.start_date&&x.event.event_date<=state.config.semester.end_date);
  $('budget-view').innerHTML=`<div class="page-heading"><div><div class="eyebrow">MAKE EVERY DOLLAR COUNT</div><h1>Semester budget<span class="heading-dot">.</span></h1><p>${esc(state.config.semester.name)} · ${money(b.cap_cents)} across ${state.config.budget.hall_snacks_count} Hall Snacks events</p></div></div><div class="budget-dashboard"><div class="card metric"><span>Actual spending</span><strong>${money(b.actual_cents)}</strong></div><div class="card metric"><span>Reserved for approved plans</span><strong>${money(b.reserved_cents)}</strong></div><div class="card metric"><span>Available to plan</span><strong class="${b.available_cents<0?'error-text':''}">${money(b.available_cents)}</strong></div></div><div class="status-message ${b.available_cents<0?'error':''}">${b.available_cents<0?'Actual spending and approved plans exceed the semester budget. Review upcoming event costs.':'Start with about '+money(b.event_allowance_cents)+' per Hall Snacks event. Drafts do not reserve money; approved proposals do.'}</div><section class="card budget-settings"><h2>Set your semester budget</h2><p>Change the total cap and the number of Hall Snacks events used to calculate a suggested per-event allowance.</p><form id="budget-settings-form" class="budget-settings-form"><label class="field">Total semester budget ($)<input id="budget-cap" type="number" min="1" max="100000" step="0.01" value="${(b.cap_cents/100).toFixed(2)}" required></label><label class="field">Hall Snacks events<input id="snacks-count" type="number" min="1" max="52" step="1" value="${state.config.budget.hall_snacks_count}" required></label><button class="button primary" type="submit">Save budget</button></form><small>Changing the cap may put your current plans over budget; approved events and receipts are retained.</small></section><section class="card budget-details"><h2>Estimates become actuals</h2><p class="drafting-note">Record the receipt total after an event. Actual spending replaces that event’s estimate; it is not counted twice.</p>${records.length?`<table class="budget-table"><thead><tr><th>Event</th><th>Estimate</th><th>Actual spend</th><th></th></tr></thead><tbody>${records.map(r=>`<tr><td>${esc(r.event.title)}<div class="save-time">${esc(r.event.event_date)}</div></td><td>${money(estimate(r.event))}</td><td><label class="sr-only" for="actual-${r.event.id}">Actual spending for ${esc(r.event.title)}</label><input id="actual-${r.event.id}" type="number" min="0" step="0.01" placeholder="0.00" value="${r.actual_cents===null?'':(r.actual_cents/100).toFixed(2)}"></td><td><button class="button secondary" data-actual="${r.event.id}">${r.actual_cents===null?'Record spend':'Update spend'}</button></td></tr>`).join('')}</tbody></table>`:'<div class="empty-state"><p>Approve a local proposal to start tracking its spending.</p><button class="button primary" id="budget-create">Create an event</button></div>'}</section>`;
  $('budget-settings-form').onsubmit=event=>{event.preventDefault();if(!$('budget-settings-form').reportValidity())return;action($('budget-settings-form').querySelector('button'),async()=>{const result=await api('/api/settings/budget',{cap_cents:Math.round(Number($('budget-cap').value)*100),hall_snacks_count:Number($('snacks-count').value)});state.config.budget=result.budget;const savedTerm=state.config.semesters.find(x=>x.name===state.config.active_semester);if(savedTerm)savedTerm.budget=result.budget;state.validation=null;await renderBudget();toast('Semester budget updated.');});};
  if($('budget-create'))$('budget-create').onclick=()=>changeView('create');
  document.querySelectorAll('[data-actual]').forEach(button=>button.onclick=()=>action(button,async()=>{const input=$('actual-'+button.dataset.actual);if(!input.value||!input.reportValidity())return toast('Enter the receipt total, including 0 for a free event.');await api('/api/events/'+button.dataset.actual+'/actual',{cents:Math.round(Number(input.value)*100),note:''});state.validation=null;await renderBudget();toast('Actual spending recorded. The balance has been updated.');}));
}
function updateWorkspaceIdentity(config){
  const label=config.semester.name.toUpperCase();
  $('semester-badge').textContent=label;$('semester-label').textContent=label;
  $('profile-hall').textContent=config.profile.residence_hall||'Set your residence hall';
  $('profile-floor').textContent=config.profile.floor?`Floor ${config.profile.floor}`:'Set your floor in Settings';
}
function fillSemesterForm(name){
  const term=state.config.semesters.find(x=>x.name===name);
  $('semester-name').value=name;
  $('semester-start').value=term?.start_date||'';$('semester-end').value=term?.end_date||'';
  $('semester-cap').value=((term?.budget?.cap_cents??15000)/100).toFixed(2);
  $('semester-snacks').value=term?.budget?.hall_snacks_count??6;
}
async function renderSettings(){
  const status=await api('/api/calendar/status');
  const options=state.config.semesters.map(x=>`<option value="${esc(x.name)}" ${x.name===state.config.active_semester?'selected':''}>${esc(x.name)}</option>`).join('');
  const profile=state.config.profile, term=state.config.semesters.find(x=>x.name===state.config.active_semester)||{};
  $('settings-view').innerHTML=`<div class="page-heading"><div><div class="eyebrow">YOUR WORKSPACE</div><h1>Settings<span class="heading-dot">.</span></h1><p>Set up your hall details and semesters.</p></div></div>
  <section class="card workspace-settings"><h2>Your residence hall</h2><p>These details help CoBu suggest the audience and floor for each event.</p><form id="workspace-settings-form">
  <div class="settings-grid"><label class="field">Residence hall<input id="residence-hall" maxlength="160" value="${esc(profile.residence_hall)}" placeholder="e.g. Bobst Hall"></label><label class="field">Your floor<input id="home-floor" maxlength="30" value="${esc(profile.floor)}" placeholder="e.g. 8"></label><label class="field">Residents on your floor<input id="floor-residents" type="number" min="1" max="10000" value="${profile.floor_residents??''}" placeholder="Enter floor count"></label><label class="field">Residents in your building<input id="building-residents" type="number" min="1" max="100000" value="${profile.building_residents??''}" placeholder="Enter building count"></label></div>
  <h2 class="settings-subheading">Semester</h2><div class="settings-grid"><label class="field">Switch to a saved semester<select id="semester-select">${options}<option value="__new__">＋ Add a semester</option></select></label><label class="field">Semester name<input id="semester-name" required maxlength="80" value="${esc(state.config.active_semester)}"></label><label class="field">Start date<input id="semester-start" type="date" required value="${esc(term.start_date||state.config.semester.start_date)}"></label><label class="field">End date<input id="semester-end" type="date" required value="${esc(term.end_date||state.config.semester.end_date)}"></label></div>
  <div class="settings-grid budget-inline"><label class="field">Semester budget ($)<input id="semester-cap" type="number" min="1" max="100000" step="0.01" required value="${((term.budget?.cap_cents??state.config.budget.cap_cents)/100).toFixed(2)}"></label><label class="field">Hall Snacks events<input id="semester-snacks" type="number" min="1" max="52" step="1" required value="${term.budget?.hall_snacks_count??state.config.budget.hall_snacks_count}"></label></div>
  <p class="save-time">Attendance suggestions use 15% of the floor count, or 15% of the building count for all-hall events. Multi-floor estimates multiply the floor count by the number of floors mentioned. Semester records and saved events remain available when you switch terms.</p><button class="button primary" type="submit">Save workspace settings</button></form></section>
  <section class="card connector-settings"><div class="connector-title"><div><div class="section-icon">◷</div></div><div><h2>Google Calendar</h2><p id="calendar-connection-state">${status.connected?'Connected':'Not connected'}</p></div><span class="pill ${status.connected?'success-tag':''}" id="calendar-pill">${status.connected?'CONNECTED':'OPTIONAL'}</span></div><p>CoBu checks availability on your primary calendar. It doesn’t create events or reserve rooms.</p><div class="connector-actions"><button class="button primary" id="calendar-connect" ${status.connected?'hidden':''}>Connect Google Calendar</button><button class="button secondary" id="calendar-disconnect" ${!status.connected?'hidden':''}>Disconnect</button></div><div class="calendar-setup" ${status.setup_ready?'hidden':''}><h3>One-time setup</h3><ol><li>Enable Google Calendar API.</li><li>Add yourself as a test user under Google Auth Platform → Audience.</li><li>Create a Desktop app OAuth client.</li><li>Save its JSON as <code>credentials.json</code> in the CoBu folder.</li></ol><p><a href="https://developers.google.com/workspace/calendar/api/quickstart/python" target="_blank" rel="noreferrer">Google’s setup guide</a>.</p></div><p class="save-time">Your sign-in token stays on this computer.</p></section>
  <section class="card connector-settings"><h2>AI event drafting and flyers</h2><p>Both features use the OpenAI API. Event dictation/text is sent to OpenAI for structured extraction. Set <code>OPENAI_API_KEY</code> in the terminal before starting CoBu; API charges and limits are separate from ChatGPT.</p></section>`;
  $('semester-select').onchange=()=>{
    const choice=$('semester-select').value;
    if(choice==='__new__'){
      const name=prompt('Name the semester (for example, Spring 2027):');
      if(!name){$('semester-select').value=state.config.active_semester;return;}
      $('semester-name').value=name.trim();$('semester-start').value='';$('semester-end').value='';$('semester-cap').value='150.00';$('semester-snacks').value='6';
    }else fillSemesterForm(choice);
  };
  $('workspace-settings-form').onsubmit=event=>{event.preventDefault();const form=event.currentTarget;if(!form.reportValidity())return;action(form.querySelector('[type=submit]'),async()=>{
    const body={residence_hall:$('residence-hall').value,floor:$('home-floor').value,floor_residents:$('floor-residents').value?Number($('floor-residents').value):null,building_residents:$('building-residents').value?Number($('building-residents').value):null,semester_name:$('semester-name').value.trim(),semester_start:$('semester-start').value,semester_end:$('semester-end').value,timezone:state.config.semester.timezone,cap_cents:Math.round(Number($('semester-cap').value)*100),hall_snacks_count:Number($('semester-snacks').value)};
    state.config=await api('/api/settings/workspace',body);updateWorkspaceIdentity(state.config);state.validation=null;await refreshBudget();toast('Workspace and semester settings saved.');await renderSettings();
  });};
  $('calendar-connect').onclick=()=>action($('calendar-connect'),async()=>{await api('/api/calendar/connect',{});toast('Google Calendar connected.');await renderSettings();});
  $('calendar-disconnect').onclick=()=>action($('calendar-disconnect'),async()=>{await api('/api/calendar/disconnect',{});toast('Google Calendar disconnected.');await renderSettings();});
}
async function startFresh(){if(state.dirty&&!confirm('Start fresh? Your unsaved changes will be replaced.'))return;stopSpeech();state.status='draft';fillEvent(blankEvent());$('draft-label').textContent='YOUR DRAFT';$('save-status').textContent='Your changes stay here until you save.';$('drafting-feedback').hidden=true;await changeView('create');}
let recognition=null, speechStarting=false, listening=false, baseline='';
function stopSpeech(){if(recognition&&(listening||speechStarting)){recognition.stop();}}
function setupSpeech(){
  const Recognition=window.SpeechRecognition||window.webkitSpeechRecognition;
  if(!Recognition){$('dictate').disabled=true;$('dictate').title='Dictation is not supported by this browser.';$('speech-status').textContent='Use your device’s keyboard dictation or type your idea.';$('speech-status').classList.add('speech-unavailable');return;}
  recognition=new Recognition();recognition.lang='en-US';recognition.continuous=true;recognition.interimResults=true;
  recognition.onstart=()=>{speechStarting=false;listening=true;$('dictate').innerHTML='<span class="record-dot"></span>Stop dictation';$('dictate').classList.add('listening');$('dictate').setAttribute('aria-pressed','true');$('speech-status').textContent='Listening. Speak naturally, then press Stop.';$('generate').disabled=true;$('idea').readOnly=true;};
  recognition.onresult=event=>{const text=Array.from(event.results).map(r=>r[0].transcript).join(' ');$('idea').value=(baseline+' '+text).trim();state.dirty=true;};
  recognition.onerror=event=>{const messages={'not-allowed':'Microphone permission was not granted. You can type your idea instead.','audio-capture':'No microphone is available. Type your idea or check your microphone.','network':'The browser speech service could not connect. Type your idea or try again.','no-speech':'No speech was detected. Try again when you are ready.','service-not-allowed':'This browser cannot use its speech service. Try Chrome or keyboard dictation.','language-not-supported':'English dictation is not available in this browser.'};if(event.error!=='aborted')toast(messages[event.error]||'Dictation stopped. Your text is still editable.');};
  recognition.onend=()=>{speechStarting=false;listening=false;$('dictate').innerHTML='<svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" aria-hidden="true"><rect x="9" y="2" width="6" height="12" rx="3"/><path d="M5 10v2a7 7 0 0 0 14 0v-2M12 19v3M8 22h8"/></svg>Dictate idea';$('dictate').classList.remove('listening');$('dictate').setAttribute('aria-pressed','false');$('speech-status').textContent='Your browser may send audio to its speech service.';$('generate').disabled=false;$('idea').readOnly=false;};
  $('speech-status').textContent='Your browser may send audio to its speech service.';
  $('dictate').onclick=()=>{if(listening||speechStarting){stopSpeech();return;}baseline=$('idea').value.trim();speechStarting=true;try{recognition.start();}catch{speechStarting=false;toast('Dictation could not start. Try again or type your idea.');}};
}
function registerTools(){
  const context=document.modelContext;if(!context?.registerTool)return;
  const lifecycle=new AbortController();
  const register=tool=>Promise.resolve(context.registerTool(tool,{signal:lifecycle.signal})).catch(()=>{});
  register({name:'read_event_draft',title:'Read event draft',description:'Read the editable local draft and its current validation status. Does not save, approve, book or send anything.',inputSchema:{type:'object',properties:{},additionalProperties:false},annotations:{readOnlyHint:true},execute:async()=>({event:readEvent(),local_pass:state.validation?.local_pass??null,calendar_connected:await api('/api/calendar/status').then(x=>x.connected).catch(()=>false)})});
  register({name:'validate_local_event',title:'Validate local event',description:'Run local rule and budget checks on the current visible draft. Does not approve or book the event.',inputSchema:{type:'object',properties:{},additionalProperties:false},annotations:{readOnlyHint:false},execute:async()=>{await changeView('create');await validateDraft();return state.validation?{checks:state.validation.checks,local_pass:state.validation.local_pass}: {error:'Fix the form fields before validation.'};}});
  window.addEventListener('pagehide',()=>lifecycle.abort(),{once:true});
}
async function init(){
  try{
    const [config,budget]=await Promise.all([api('/api/config'),api('/api/budget')]);state.config=config;state.budget=budget;
    $('event_type').innerHTML=Object.keys(config.event_types).map(x=>`<option>${esc(x)}</option>`).join('');
    $('location').innerHTML='<option value="">Choose a location</option>'+config.locations.map(x=>`<option>${esc(x.name)}</option>`).join('');
    $('focus-options').innerHTML=config.focus_areas.map(x=>`<label><input type="checkbox" value="${esc(x)}">${esc(x)}</label>`).join('');
    updateWorkspaceIdentity(config);
    const trend=document.createElement('label');trend.id='trend-field';trend.className='field full';trend.hidden=true;trend.innerHTML='Building trend this event addresses<textarea id="building_trend" rows="2" placeholder="What are you noticing in the building?"></textarea>';$('event-form').insertBefore(trend,$('description').closest('label'));
    const limit=document.createElement('label');limit.className='field full';limit.innerHTML='Event spending limit (optional)<input id="event-limit" type="number" min="0" step="0.01" placeholder="e.g. 25.00">';document.querySelector('.estimate-total').after(limit);
    const feedback=document.createElement('div');feedback.id='drafting-feedback';feedback.className='draft-feedback';feedback.hidden=true;document.querySelector('.idea-card').append(feedback);
    fillEvent(blankEvent());await refreshBudget();setupSpeech();
    $('event-form').addEventListener('submit',event=>event.preventDefault());
    $('event-form').addEventListener('input',event=>{if(event.target.id==='event-limit')state.requestedBudget=event.target.value===''?null:Math.round(Number(event.target.value)*100);if(event.target.id==='headcount')state.autoHeadcount=null;markEdited();});
    $('event-form').addEventListener('change',event=>{if(event.target.id==='event_type'&&state.autoHeadcount!==null&&Number($('headcount').value)===state.autoHeadcount){$('headcount').value=suggestedAttendance(event.target.value);state.autoHeadcount=Number($('headcount').value);}markEdited();});
    document.querySelectorAll('[data-open-settings]').forEach(link=>link.onclick=event=>{event.preventDefault();changeView('settings');});
    $('idea').addEventListener('input',()=>{state.dirty=true;state.validation=null;});
    $('add-supply').onclick=()=>{addSupply();markEdited();};
    $('generate').onclick=()=>action($('generate'),async()=>{const idea=$('idea').value.trim();if(idea.length<5)return toast('Tell us a little more about your event first.');if($('title').value&&state.dirty&&!confirm('Fill in a new draft from this idea? This replaces the fields below.'))return;const result=await api('/api/draft',{idea});state.status='draft';fillEvent(result.event);state.dirty=true;$('draft-label').textContent='SUGGESTED DRAFT';$('save-status').textContent='Suggestions filled in. Review and edit before checking.';$('drafting-feedback').innerHTML='<strong>Review these suggestions</strong><ul>'+result.assumptions.map(x=>`<li>${esc(x)}</li>`).join('')+'</ul>';$('drafting-feedback').hidden=false;toast('Your draft is ready to edit.');});
    const examples={smores:'S’mores night for 25 first-years on October 2, 2026 at 7 pm to 8 pm in social lounge A. A relaxed way to meet new neighbors, with a $25 budget.',study:'A study break for 20 residents on October 6, 2026 at 6 pm to 7 pm in the quiet lounge. Share study tips over snacks. Budget $20.',craft:'Craft night for 20 residents on October 3, 2026 at 7 pm to 8 pm in social lounge B, with $25 for supplies.'};
    document.querySelectorAll('[data-example]').forEach(button=>button.onclick=()=>{$('idea').value=examples[button.dataset.example];state.dirty=true;state.validation=null;$('idea').focus();});
    $('save-draft').onclick=()=>action($('save-draft'),saveDraft);$('validate').onclick=()=>action($('validate'),validateDraft);$('step-validate').onclick=()=>action(null,validateDraft);$('step-create').onclick=showCreation;$('new-event').onclick=startFresh;
    document.querySelectorAll('[data-view]').forEach(button=>button.onclick=()=>action(null,()=>changeView(button.dataset.view)));
    window.addEventListener('beforeunload',event=>{if(state.dirty){event.preventDefault();event.returnValue='';}});
    registerTools();
  }catch(error){toast('Could not load the local workspace. '+error.message);}
}
init();
