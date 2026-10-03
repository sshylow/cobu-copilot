from datetime import date, time
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

class Supply(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    name: str = Field(default="", max_length=300)
    quantity: int = Field(default=1, ge=1, le=10000, strict=True)
    unit_cost_cents: int = Field(default=0, ge=0, le=10000000, strict=True)
    channel: Literal["Grocery", "Amazon", "Restaurant", "Other"] = "Grocery"
    link: str = Field(default="", max_length=2000)

class EventDraft(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    id: str | None = Field(default=None, pattern=r"^[0-9a-f-]{36}$")
    idea: str = Field(default="", max_length=10000)
    title: str = Field(default="", max_length=160)
    event_type: str = "Hall Snacks"
    community: str = Field(default="", max_length=500)
    event_date: date | None = None
    requested_weekday: str | None = Field(default=None, max_length=12)
    start_time: time | None = None
    end_time: time | None = None
    location: str = ""
    headcount: int = Field(default=15, ge=1, le=1000)
    collaborators: list[str] = Field(default_factory=list, max_length=30)
    description: str = Field(default="", max_length=10000)
    focus_areas: list[str] = Field(default_factory=list, max_length=20)
    outcomes: list[str] = Field(default_factory=lambda: ["", "", ""], max_length=10)
    supplies: list[Supply] = Field(default_factory=list, max_length=100)
    notes: str = Field(default="", max_length=10000)
    building_trend: str = Field(default="", max_length=1000)
    requested_budget_cents: int | None = Field(default=None, ge=0, le=10000000, strict=True)
    flyer_style: str = "Minimal"

    @field_validator("start_time", "end_time")
    @classmethod
    def local_clock_only(cls, value):
        if value is not None and value.tzinfo is not None:
            raise ValueError("Use local clock times without an offset; the semester timezone is configured separately.")
        return value

    @field_validator("collaborators")
    @classmethod
    def named_collaborators(cls, names):
        return list(dict.fromkeys(name.strip() for name in names if name.strip()))

    @property
    def estimate_cents(self):
        return sum(x.quantity * x.unit_cost_cents for x in self.supplies)

class IdeaRequest(BaseModel):
    idea: str = Field(min_length=5, max_length=10000)

class ApprovalRequest(BaseModel):
    event: EventDraft
    validation_token: str
    reviewed: bool = False

class FlyerGenerationRequest(BaseModel):
    event: EventDraft
    style: str = Field(default="Minimal", max_length=80)
    custom_description: str = Field(default="", max_length=1200)

class BudgetSettings(BaseModel):
    cap_cents: int = Field(ge=100, le=10000000, strict=True)
    hall_snacks_count: int = Field(ge=1, le=52, strict=True)

class WorkspaceSettings(BaseModel):
    residence_hall: str = Field(default="", max_length=160)
    floor: str = Field(default="", max_length=30)
    floor_residents: int | None = Field(default=None, ge=1, le=10000)
    building_residents: int | None = Field(default=None, ge=1, le=100000)
    semester_name: str = Field(min_length=3, max_length=80)
    semester_start: date
    semester_end: date
    timezone: str = Field(default="America/New_York", max_length=80)
    cap_cents: int = Field(ge=100, le=10000000, strict=True)
    hall_snacks_count: int = Field(ge=1, le=52, strict=True)

    @model_validator(mode="after")
    def valid_semester_dates(self):
        if self.semester_end < self.semester_start:
            raise ValueError("Semester end must be on or after its start date.")
        return self

class ActualSpend(BaseModel):
    cents: int = Field(ge=0, le=10000000, strict=True)
    note: str = Field(default="", max_length=1000)
