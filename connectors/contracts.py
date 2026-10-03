"""Integration boundaries; no credentials, mock successes, or external writes."""
from typing import Protocol
from app.models import EventDraft

class DraftProvider(Protocol):
    def draft(self, idea: str) -> EventDraft: ...

class CalendarConnector(Protocol):
    def availability(self, event: EventDraft) -> dict: ...
    def create_holds(self, event: EventDraft, approved_snapshot: str) -> list[str]: ...

class CanvaConnector(Protocol):
    def template_fields(self, template_id: str) -> dict: ...
    def create_flyers(self, event: EventDraft, approved_snapshot: str) -> list[str]: ...

class NotConnectedError(RuntimeError):
    pass

def require_connected(name):
    raise NotConnectedError(f"{name} is not connected. No action was performed.")
