"""Local SQLite persistence. Approved estimates reserve funds; actuals replace them."""
import json
import os
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path

def connect():
    path = Path(os.getenv("COBU_DB_PATH", str(Path(__file__).resolve().parents[1] / "data" / "local" / "cobu.sqlite3")))
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("CREATE TABLE IF NOT EXISTS events (id TEXT PRIMARY KEY, payload TEXT NOT NULL, status TEXT NOT NULL, updated_at TEXT NOT NULL, actual_cents INTEGER, spend_note TEXT NOT NULL DEFAULT '')")
    conn.commit()
    return conn

def list_events(conn):
    return [{"event": json.loads(x["payload"]), "status": x["status"], "updated_at": x["updated_at"], "actual_cents": x["actual_cents"], "spend_note": x["spend_note"]} for x in conn.execute("SELECT * FROM events ORDER BY updated_at DESC")]

def budget_summary(conn, cfg, exclude_id=None):
    events = list_events(conn)
    current = [x for x in events if x["event"].get("event_date") and str(cfg["semester"]["start_date"]) <= x["event"]["event_date"] <= str(cfg["semester"]["end_date"])]
    actual = sum(x["actual_cents"] for x in current if x["actual_cents"] is not None and x["event"]["id"] != exclude_id)
    reserved = sum(sum(i["quantity"] * i["unit_cost_cents"] for i in x["event"]["supplies"]) for x in current if x["status"] == "approved_local" and x["actual_cents"] is None and x["event"]["id"] != exclude_id)
    return {"cap_cents": cfg["budget"]["cap_cents"], "actual_cents": actual, "reserved_cents": reserved, "available_cents": cfg["budget"]["cap_cents"] - actual - reserved, "event_allowance_cents": cfg["budget"]["cap_cents"] // cfg["budget"]["hall_snacks_count"], "events": events}

def save_event(conn, event, status="draft"):
    event = event.model_copy(update={"id": event.id or str(uuid.uuid4())})
    existing = conn.execute("SELECT actual_cents FROM events WHERE id=?", (event.id,)).fetchone()
    if existing and existing["actual_cents"] is not None:
        raise ValueError("This event has actual spending recorded. Start a new draft to plan another event.")
    stamp = datetime.now(timezone.utc).isoformat()
    conn.execute("INSERT INTO events(id,payload,status,updated_at) VALUES(?,?,?,?) ON CONFLICT(id) DO UPDATE SET payload=excluded.payload,status=excluded.status,updated_at=excluded.updated_at", (event.id, event.model_dump_json(), status, stamp))
    return event

def delete_event(conn, event_id):
    cursor = conn.execute("DELETE FROM events WHERE id=?", (event_id,))
    return cursor.rowcount > 0
