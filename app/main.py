from pathlib import Path
import base64
import hashlib
import hmac
import json
import logging
import os
import secrets
import uuid
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import yaml
from pydantic import ValidationError
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware
from app.models import EventDraft, IdeaRequest, ApprovalRequest, ActualSpend, FlyerGenerationRequest, BudgetSettings, WorkspaceSettings
from app.storage import connect, list_events, budget_summary, save_event, delete_event
from agents.openai_drafting import create_ai_draft
from validators.proposal import validate_event

ROOT = Path(__file__).resolve().parent
app = FastAPI(title="CoBu Copilot", docs_url="/api/docs")
logger = logging.getLogger(__name__)
app.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost", "[::1]"])
app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")
SESSION_SECRET = secrets.token_bytes(32)
CALENDAR_SCOPES = ["https://www.googleapis.com/auth/calendar.events.freebusy"]

def local_data_dir():
    return ROOT.parent / "data" / "local"

def calendar_token_path():
    return local_data_dir() / "google_calendar_token.json"

def calendar_client_path():
    return Path(os.environ.get("GOOGLE_OAUTH_CLIENT_FILE", ROOT.parent / "credentials.json"))

def load_local_settings():
    overrides_path = local_data_dir() / "settings.json"
    if overrides_path.exists():
        try:
            return json.loads(overrides_path.read_text())
        except (OSError, json.JSONDecodeError):
            return {}
    return {}

def save_local_settings(settings):
    path = local_data_dir() / "settings.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(settings, indent=2))
    temp.replace(path)

def config():
    cfg = yaml.safe_load((ROOT.parent / "config.yaml").read_text())
    local = load_local_settings()
    cfg["profile"] = {
        "residence_hall": "", "floor": "", "floor_residents": None,
        "building_residents": None, **local.get("profile", {}),
    }
    semesters = local.get("semesters", {})
    active = local.get("active_semester", cfg["semester"]["name"])
    if active not in semesters:
        old_budget = local.get("budget", {})
        semesters[active] = {
            **cfg["semester"],
            "budget": {**cfg["budget"], **old_budget},
        }
    selected = semesters[active]
    cfg["semester"] = {key: selected.get(key, value) for key, value in cfg["semester"].items()}
    cfg["semester"]["name"] = active
    cfg["budget"].update(selected.get("budget", {}))
    cfg["active_semester"] = active
    defaults = {
        "Spring 2027": {"name": "Spring 2027", "start_date": "", "end_date": "", "budget": {"cap_cents": 15000, "hall_snacks_count": 6}},
        "Summer 2027": {"name": "Summer 2027", "start_date": "", "end_date": "", "budget": {"cap_cents": 15000, "hall_snacks_count": 6}},
    }
    cfg["semesters"] = [
        {"name": name, "start_date": item.get("start_date", ""), "end_date": item.get("end_date", ""), "budget": item.get("budget", cfg["budget"])}
        for name, item in {**defaults, **semesters}.items()
    ]
    return cfg

def calendar_credentials():
    token_path = calendar_token_path()
    if not token_path.exists():
        return None
    from google.auth.transport.requests import Request as GoogleRequest
    from google.oauth2.credentials import Credentials
    creds = Credentials.from_authorized_user_file(str(token_path), CALENDAR_SCOPES)
    if creds.expired and creds.refresh_token:
        creds.refresh(GoogleRequest())
        token_path.write_text(creds.to_json())
        token_path.chmod(0o600)
    return creds if creds.valid else None

def calendar_availability(event, cfg):
    if not event.event_date or not event.start_time or not event.end_time:
        return {"status": "pending", "detail": "Add the date and both times to check your connected calendar."}
    try:
        creds = calendar_credentials()
        if not creds:
            return {"status": "pending", "detail": "Connect Google Calendar in Settings to check your primary calendar. Nothing has been booked."}
        from googleapiclient.discovery import build
        tz = ZoneInfo(str(cfg["semester"]["timezone"]))
        start = datetime.combine(event.event_date, event.start_time, tzinfo=tz)
        end = datetime.combine(event.event_date, event.end_time, tzinfo=tz)
        day_start = datetime.combine(event.event_date, datetime.min.time(), tzinfo=tz)
        day_end = datetime.combine(event.event_date + timedelta(days=1), datetime.min.time(), tzinfo=tz)
        service = build("calendar", "v3", credentials=creds, cache_discovery=False)
        response = service.freebusy().query(body={
            "timeMin": day_start.isoformat(), "timeMax": day_end.isoformat(),
            "timeZone": str(cfg["semester"]["timezone"]), "items": [{"id": "primary"}],
        }).execute()
        calendar = response.get("calendars", {}).get("primary", {})
        if calendar.get("errors"):
            raise RuntimeError("Google could not check the primary calendar.")
        busy = calendar.get("busy", [])
        if busy:
            overlaps = any(datetime.fromisoformat(block["start"].replace("Z", "+00:00")) < end.astimezone(ZoneInfo("UTC")) and datetime.fromisoformat(block["end"].replace("Z", "+00:00")) > start.astimezone(ZoneInfo("UTC")) for block in busy)
            detail = "Your selected time overlaps another event on your connected primary calendar. Choose another time." if overlaps else "Your primary calendar already has an event on this date. Check the schedule and confirm or choose another date."
            return {"status": "fail", "detail": detail}
        return {"status": "pass", "detail": "No conflict was found on your connected primary calendar. This checks availability only; it does not reserve the space or book the event."}
    except Exception:
        logger.exception("Google Calendar availability check failed")
        return {"status": "review", "detail": "Google Calendar could not be checked, so availability is unknown. Reconnect in Settings or inspect the server log before relying on this check."}

@app.middleware("http")
async def local_boundary(request: Request, call_next):
    # A remote website must not mutate this unauthenticated loopback workspace.
    if request.method not in {"GET", "HEAD", "OPTIONS"}:
        origin = request.headers.get("origin")
        if origin and origin != str(request.base_url).rstrip("/"):
            return JSONResponse({"detail": "Only this local workspace can make changes."}, status_code=403)
        if not request.headers.get("content-type", "").startswith("application/json"):
            return JSONResponse({"detail": "JSON request required."}, status_code=415)
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Cache-Control"] = "no-store"
    return response

@app.get("/")
def index():
    return FileResponse(ROOT / "static" / "index.html")

@app.get("/api/health")
def health():
    return {"status": "ok"}

@app.get("/api/config")
def read_config():
    return config()

@app.post("/api/settings/budget")
def save_budget_settings(body: BudgetSettings):
    settings = load_local_settings()
    current = config()
    name = current["active_semester"]
    terms = settings.setdefault("semesters", {})
    terms.setdefault(name, {**current["semester"], "budget": current["budget"]})["budget"] = body.model_dump()
    save_local_settings(settings)
    return {"budget": config()["budget"]}

@app.post("/api/settings/workspace")
def save_workspace_settings(body: WorkspaceSettings):
    settings = load_local_settings()
    settings["profile"] = {
        "residence_hall": body.residence_hall.strip(), "floor": body.floor.strip(),
        "floor_residents": body.floor_residents, "building_residents": body.building_residents,
    }
    settings["active_semester"] = body.semester_name.strip()
    terms = settings.setdefault("semesters", {})
    terms[settings["active_semester"]] = {
        "name": settings["active_semester"], "start_date": body.semester_start.isoformat(),
        "end_date": body.semester_end.isoformat(), "timezone": body.timezone,
        "budget": {"cap_cents": body.cap_cents, "hall_snacks_count": body.hall_snacks_count},
    }
    save_local_settings(settings)
    return config()

@app.get("/api/calendar/status")
def calendar_status():
    try:
        connected = calendar_credentials() is not None
    except Exception:
        connected = False
    return {"connected": connected, "setup_ready": calendar_client_path().is_file(), "access": "availability only"}

@app.post("/api/calendar/connect")
def connect_calendar():
    client_path = calendar_client_path()
    if not client_path.is_file():
        raise HTTPException(409, "Set up Google Calendar OAuth first: enable the Calendar API, create a Desktop app OAuth client, and save its JSON as credentials.json in the CoBu folder. Then click Connect again.")
    try:
        from google_auth_oauthlib.flow import InstalledAppFlow
        flow = InstalledAppFlow.from_client_secrets_file(str(client_path), CALENDAR_SCOPES)
        creds = flow.run_local_server(port=0, host="127.0.0.1", open_browser=True, success_message="Google Calendar is connected to CoBu. You can close this tab.")
        token_path = calendar_token_path()
        token_path.parent.mkdir(parents=True, exist_ok=True)
        token_path.write_text(creds.to_json())
        token_path.chmod(0o600)
        return {"connected": True, "access": "availability only"}
    except Exception as exc:
        raise HTTPException(502, "Google Calendar connection did not complete. Check the OAuth setup and try again.") from exc

@app.post("/api/calendar/disconnect")
def disconnect_calendar():
    token_path = calendar_token_path()
    if token_path.exists():
        token_path.unlink()
    return {"connected": False}

@app.post("/api/draft")
def draft(body: IdeaRequest):
    if not os.environ.get("OPENAI_API_KEY"):
        raise HTTPException(503, "AI event drafting needs OPENAI_API_KEY. Set it in the terminal and restart CoBu; the app will not silently use the old local parser.")
    try:
        return create_ai_draft(body.idea, config())
    except ValidationError as exc:
        raise HTTPException(422, "The AI returned an event field outside CoBu's limits. Review the idea and try again.") from exc
    except Exception as exc:
        logger.exception("OpenAI event drafting failed")
        status = getattr(exc, "status_code", None)
        if status == 401:
            detail = "OpenAI rejected the API key. Check OPENAI_API_KEY in the terminal and restart CoBu."
        elif status == 403:
            detail = "OpenAI denied event drafting for this API project or model. Check model access and organization settings."
        elif status == 429:
            detail = "OpenAI event drafting hit a rate or billing limit. Check API billing and usage limits."
        else:
            detail = "AI event drafting failed. Check the CoBu server log in VS Code Terminal for the provider error."
        raise HTTPException(502, detail) from exc

@app.get("/api/events")
def events():
    with connect() as conn:
        return {"events": list_events(conn)}

@app.get("/api/budget")
def budget():
    with connect() as conn:
        return budget_summary(conn, config())

@app.post("/api/events")
def save(body: EventDraft):
    with connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        try:
            event = save_event(conn, body)
        except ValueError as exc:
            raise HTTPException(409, str(exc))
    return {"event": event.model_dump(mode="json"), "status":"draft"}

@app.delete("/api/events/{event_id}")
def delete_saved_event(event_id: str):
    with connect() as conn:
        if not delete_event(conn, event_id):
            raise HTTPException(404, "This saved event could not be found.")
    return {"deleted": True, "id": event_id}

def validate_snapshot(body, conn):
    cfg = config()
    budget = budget_summary(conn, cfg, exclude_id=body.id)
    result = validate_event(body, cfg, budget, budget["events"])
    calendar_check = calendar_availability(body, cfg)
    for check in result["checks"]:
        if check["key"] == "calendar":
            check.update(calendar_check)
    result["local_pass"] = not any(x["status"] == "fail" for x in result["checks"])
    result["approval_ready"] = result["local_pass"] and not any(x["key"] == "calendar" and x["status"] == "review" for x in result["checks"])
    payload = {"event":body.model_dump(mode="json"), "config":cfg, "budget":budget}
    result["validation_token"] = hmac.new(SESSION_SECRET, json.dumps(payload, sort_keys=True, default=str).encode(), hashlib.sha256).hexdigest()
    return result

@app.post("/api/validate")
def validate(body: EventDraft):
    with connect() as conn:
        return validate_snapshot(body, conn)

@app.post("/api/flyers/generate")
def generate_flyers(body: FlyerGenerationRequest):
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise HTTPException(503, "AI flyer generation needs an OPENAI_API_KEY environment variable. API usage is billed separately from ChatGPT.")
    styles = config().get("flyers", {}).get("styles", [])
    if body.style not in styles:
        raise HTTPException(422, "Choose a flyer style from the list.")
    event = body.event
    if not event.title or not event.event_date or not event.location:
        raise HTTPException(422, "Add an event title, date, and location before generating flyers.")
    prompt = (
        "Create a polished vertical poster BACKGROUND for a university resident-assistant community event. "
        "Do not include any words, letters, numbers, logos, or fake text; the app will add the event details in crisp, exact type. "
        f"Art direction: {body.style}. {body.custom_description.strip()} "
        f"Event type: {event.event_type}. Audience: {event.community or 'college residents'}. "
        f"Activity: {event.description or event.title}. Use an inviting, inclusive campus-community mood, strong visual hierarchy, "
        "generous clear space for an event title and a lower information block, and print-friendly contrast."
    )
    try:
        from openai import OpenAI
        result = OpenAI(api_key=api_key).images.generate(
            model=os.environ.get("COBU_IMAGE_MODEL", "gpt-image-2.5-flare"),
            prompt=prompt,
            n=3,
            size="1024x1536",
            quality="high",
            output_format="png",
        )
    except Exception as exc:
        # Log provider diagnostics locally, but never return credentials or raw responses.
        logger.exception("OpenAI flyer generation failed")
        status = getattr(exc, "status_code", None)
        if status == 401:
            detail = "OpenAI rejected the API key. Check that OPENAI_API_KEY is a valid API key, then restart CoBu."
        elif status == 403:
            detail = "OpenAI denied image generation for this account or model. Check organization verification and image-model access in the API platform."
        elif status == 429:
            detail = "OpenAI image generation hit a rate or billing limit. Check API billing and usage limits, then retry."
        elif status in (400, 404):
            detail = "OpenAI rejected the image request. Check the configured image model and request settings. The provider error is in the CoBu server log."
        else:
            detail = "OpenAI image generation failed. Check the CoBu server log for the provider error; the API key is never shown in the app."
        raise HTTPException(502, detail) from exc
    folder = ROOT.parent / "data" / "local" / "flyers"
    folder.mkdir(parents=True, exist_ok=True)
    generated = []
    for item in result.data:
        if not item.b64_json:
            continue
        flyer_id = str(uuid.uuid4())
        (folder / f"{flyer_id}.png").write_bytes(base64.b64decode(item.b64_json))
        generated.append({"id": flyer_id, "url": f"/api/flyers/{flyer_id}.png"})
    if len(generated) != 3:
        raise HTTPException(502, "OpenAI returned fewer than three flyer images. Retry generation.")
    return {"flyers": generated, "style": body.style}

@app.get("/api/flyers/{filename}")
def generated_flyer(filename: str):
    if not filename.endswith(".png"):
        raise HTTPException(404, "Flyer not found.")
    try:
        flyer_id = str(uuid.UUID(filename[:-4]))
    except ValueError:
        raise HTTPException(404, "Flyer not found.")
    path = ROOT.parent / "data" / "local" / "flyers" / f"{flyer_id}.png"
    if not path.is_file():
        raise HTTPException(404, "Flyer not found.")
    return FileResponse(path, media_type="image/png")

@app.post("/api/approve")
def approve(body: ApprovalRequest):
    if not body.reviewed:
        raise HTTPException(400, "Review and confirm the proposal before approval.")
    with connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        # Recheck data, rules and budget inside the write transaction.
        result = validate_snapshot(body.event, conn)
        if not hmac.compare_digest(result["validation_token"], body.validation_token):
            raise HTTPException(409, "The proposal, rules, or budget changed. Run validation again.")
        if not result["local_pass"]:
            raise HTTPException(400, "Resolve the local validation issues first.")
        if not result["approval_ready"]:
            raise HTTPException(400, "Google Calendar availability could not be checked. Reconnect or review the calendar status before approving.")
        try:
            event = save_event(conn, body.event, "approved_local")
        except ValueError as exc:
            raise HTTPException(409, str(exc))
    return {"event":event.model_dump(mode="json"), "status":"approved_local", "message":"Proposal approved locally and estimated funds reserved. No calendar events were created."}

@app.post("/api/events/{event_id}/actual")
def actual(event_id: str, body: ActualSpend):
    with connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute("SELECT status FROM events WHERE id=?", (event_id,)).fetchone()
        if not row:
            raise HTTPException(404, "Event not found.")
        if row["status"] != "approved_local":
            raise HTTPException(400, "Approve the local proposal before recording spend.")
        conn.execute("UPDATE events SET actual_cents=?, spend_note=? WHERE id=?", (body.cents, body.note, event_id))
        summary = budget_summary(conn, config())
    return summary

@app.get("/api/events/{event_id}/export")
def export(event_id: str):
    with connect() as conn:
        record = next((x for x in list_events(conn) if x["event"]["id"] == event_id), None)
    if not record:
        raise HTTPException(404, "Event not found.")
    if record["status"] != "approved_local":
        raise HTTPException(403, "Approve the local proposal before exporting.")
    return JSONResponse(record, headers={"Content-Disposition":f'attachment; filename="cobu-proposal-{event_id}.json"'})
