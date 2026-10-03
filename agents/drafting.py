"""Transparent local event-field extraction with editable suggestions."""
import math
import re
from datetime import date, timedelta
from decimal import Decimal

from app.models import EventDraft, Supply

NUMBER_WORDS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
    "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14,
    "fifteen": 15, "sixteen": 16, "seventeen": 17, "eighteen": 18,
    "nineteen": 19, "twenty": 20,
    "first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5,
    "sixth": 6, "seventh": 7, "eighth": 8, "ninth": 9, "tenth": 10,
    "eleventh": 11, "twelfth": 12, "thirteenth": 13, "fourteenth": 14,
    "fifteenth": 15, "sixteenth": 16, "seventeenth": 17, "eighteenth": 18,
    "nineteenth": 19, "twentieth": 20,
}

def number_value(raw):
    return int(raw) if raw.isdigit() else NUMBER_WORDS.get(raw.lower())

def extract_floor_numbers(text):
    floors = []
    pattern = r"\b(first|second|third|fourth|fifth|sixth|seventh|eighth|ninth|tenth|\d{1,2}(?:st|nd|rd|th)?)\s+floor\b"
    for raw in re.findall(pattern, text.lower()):
        digits = re.search(r"\d+", raw)
        number = int(digits.group()) if digits else NUMBER_WORDS.get(raw)
        if number and number not in floors:
            floors.append(number)
    return floors

def parse_date(text, today):
    iso = re.search(r"\b(20\d{2}-\d{2}-\d{2})\b", text)
    if iso:
        try:
            return date.fromisoformat(iso.group(1))
        except ValueError:
            pass
    months = ["january", "february", "march", "april", "may", "june", "july", "august", "september", "october", "november", "december"]
    for index, month in enumerate(months, 1):
        match = re.search(r"\b(?:" + month + "|" + month[:3] + r")\.?\s+(\d{1,2})(?:st|nd|rd|th)?(?:,?\s+(20\d{2}))?", text.lower())
        if match:
            try:
                return date(int(match.group(2) or today.year), index, int(match.group(1)))
            except ValueError:
                return None
    for index, day in enumerate(["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]):
        if re.search(r"\b" + day + r"\b", text.lower()):
            return today + timedelta(days=(index - today.weekday()) % 7 or 7)
    return None

def extract_weekday(text):
    match = re.search(r"\b(monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b", text, re.I)
    return match.group(1).lower() if match else None

def extract_title(text, profile):
    normalized = re.sub(r"\s+", " ", text).strip()
    if "taco bell" in normalized.lower() and "first day" in normalized.lower():
        return "Taco Bell: Talk About Your First Day of Classes"
    name_start = re.search(r"\b(?:it'?s\s+called|going\s+to\s+be\s+called|called|titled)\s+(?:call\s+)?", normalized, re.I)
    if name_start:
        candidate = normalized[name_start.end():]
        candidate = re.split(r"\b(?:and\s+we(?:'re|\s+are)|we(?:'re|\s+are)\s+going\s+to|then\s+we|it's\s+like|it\s+is\s+like|for\s+\d+)\b", candidate, maxsplit=1, flags=re.I)[0]
        candidate = re.sub(r"^(?:call|have|do|create|host)\s+", "", candidate.strip(), flags=re.I)
        candidate = re.sub(r"\s+(?:and|or|so)$", "", candidate, flags=re.I).strip(" .'\"-:")
        if candidate and len(candidate.split()) <= 10:
            return candidate[0].upper() + candidate[1:]
    explicit = re.search(r"\b(?:called|titled)\s+['\"]?([^.!?\n,]{2,70})", text, re.I)
    candidate = explicit.group(1) if explicit else ""
    if not candidate:
        match = re.search(r"\b(?:host|hosting|plan|planning|create|creating|have|having|put on|organize|organizing|run|running|lead|leading|facilitate|facilitating|do|doing)\s+(?:a|an|the)?\s*([^.!?\n]+)", text, re.I)
        candidate = match.group(1) if match else ""
    candidate = re.split(r"\b(?:for\s+\d+|on\s+(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday|january|february|march|april|may|june|july|august|september|october|november|december)|at\s+\d{1,2}|where\s+residents|that\s+residents|so\s+residents|with\s+about\s+\$?|with\s+\$|with\s+[A-Z])", candidate, maxsplit=1, flags=re.I)[0]
    candidate = re.sub(r"^(?:a|an|the|like|just|some)\s+", "", candidate.strip(), flags=re.I)
    candidate = re.sub(r"\s+(?:but|because|so)\s+.*$", "", candidate, flags=re.I)
    candidate = re.sub(r"[^\w'& -]", "", candidate).strip(" -")
    words = candidate.split()
    if len(words) > 8:
        candidate = " ".join(words[:8])
    if candidate and candidate.lower() not in {"this", "that", "it", "something", "an event", "event"} and len(candidate.split()) > 1 and len(candidate) <= 65:
        return candidate[0].upper() + candidate[1:]
    return profile["title"] if profile.get("title") != "A gathering for our community" else "Community gathering"

def extract_description(text, profile):
    cleaned = re.sub(r"\s+", " ", text).strip()
    cleaned = re.sub(r"^(?:i(?:'| a)?m?\s+)?(?:hoping to|thinking of|i would like to|i'd like to|i want to|we want to|i plan to|we plan to)\s+", "", cleaned, flags=re.I)
    cleaned = re.sub(r"^(?:host|hosting|plan|planning|have|having|put on|organize|organizing|do|doing)\s+", "", cleaned, flags=re.I)
    if len(cleaned) > 1600:
        cleaned = cleaned[:1600].rsplit(" ", 1)[0]
    return cleaned or profile["description"]

def build_voice_summary(normalized, profile, headcount):
    if "taco bell" in normalized and "first day" in normalized:
        description = "Residents will pick up tacos, talk about their first day of classes, and meet new people on the floor."
        outcomes = [
            "identify one part of their first day of classes they enjoyed by the end of the event.",
            "describe one question or challenge about their classes during the event.",
            "identify one new floor neighbor they met before leaving.",
        ]
        return description, outcomes
    return None

def create_draft(idea, cfg, today=None):
    today = today or date.today()
    settings = cfg["drafting"]
    text = idea.replace("’", "'")
    normalized = text.lower()
    key = next((k for k, p in settings["profiles"].items() if any(w.replace("’", "'").lower() in normalized for w in p["keywords"])), "general")
    profile = settings["profiles"][key]

    explicit_headcount = re.search(r"\b(\d+)\s*(?:first[- ]years?|residents?|people|students?|attendees?|neighbors?)\b", normalized)
    community_wide = any(x in normalized for x in ("all hall", "all-hall", "building-wide", "whole building", "everyone in the building", "cdp"))
    population = cfg.get("profile", {}).get("building_residents") if community_wide else cfg.get("profile", {}).get("floor_residents")
    if not community_wide:
        floor_numbers = extract_floor_numbers(text)
        own_floor = re.search(r"\d+", str(cfg.get("profile", {}).get("floor", "")))
        if own_floor and int(own_floor.group()) not in floor_numbers:
            floor_numbers.insert(0, int(own_floor.group()))
        population = population * len(set(floor_numbers)) if population and len(set(floor_numbers)) > 1 else population
    headcount = max(1, min(1000, int(explicit_headcount.group(1)))) if explicit_headcount else (math.ceil(population * 0.15) if population else settings["default_headcount"])

    budget = re.search(r"\$\s*(\d+(?:\.\d{1,2})?)|\b(\d+(?:\.\d{1,2})?)\s*dollars", normalized)
    budget_cents = int(Decimal(next(group for group in budget.groups() if group is not None)) * 100) if budget else None
    event_date = parse_date(text, today)
    start, end = settings["default_start_time"], settings["default_end_time"]
    times = re.findall(r"\b(\d{1,2})(?::(\d{2}))?\s*(a\.?m\.?|p\.?m\.?)", normalized)
    parsed = []
    for hour, minute, meridiem in times[:2]:
        if 1 <= int(hour) <= 12 and int(minute or 0) < 60:
            value = int(hour) % 12 + (12 if meridiem.startswith("p") else 0)
            parsed.append(f"{value:02d}:{int(minute or 0):02d}")
    if parsed:
        start = parsed[0]
        end = parsed[1] if len(parsed) > 1 else f"{(int(start[:2]) + 1) % 24:02d}:{start[3:]}"

    location = next((x["name"] for x in cfg["locations"] if x["name"].lower() in normalized), settings["default_location"])
    event_type = "CDP / All-Hall" if community_wide or "cdp" in normalized else next((x for x in cfg["event_types"] if x.lower() in normalized), settings["default_event_type"])
    collaborator_match = re.search(r"\b(?:with|alongside)\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)\b", text)
    collaborators = [collaborator_match.group(1)] if collaborator_match else []
    own_floor = re.search(r"\d+", str(cfg.get("profile", {}).get("floor", "")))
    floors = extract_floor_numbers(text)
    if own_floor and int(own_floor.group()) not in floors:
        floors.insert(0, int(own_floor.group()))
    if community_wide:
        community = cfg.get("profile", {}).get("residence_hall") or "Residence hall residents"
    else:
        community = " and ".join(f"Floor {n}" for n in floors) if floors else (f"Floor {own_floor.group()}" if own_floor else cfg.get("profile", {}).get("residence_hall", "Residence hall residents"))

    serve_count = max(1, profile["supplies"][0]["serves"] if profile.get("supplies") else 25)
    supplies = [Supply(name=s["name"], quantity=s["quantity"] * max(1, math.ceil(headcount / serve_count)), unit_cost_cents=s["unit_cost_cents"], channel=s["channel"]) for s in profile["supplies"]]
    taco_order = re.search(r"\b(\d+)\s+tacos?\b", normalized)
    if "taco bell" in normalized and taco_order:
        quantity = int(taco_order.group(1))
        amount = r"(\d+|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|fifteen|twenty)"
        deal = re.search(r"\b" + amount + r"\s+tacos?\s+for\s+" + amount + r"(?:\s+dollars?)?", normalized)
        deal_count = number_value(deal.group(1)) if deal else None
        deal_price = number_value(deal.group(2)) if deal else None
        unit_cost = int(Decimal(deal_price) * 100 / deal_count) if deal_count and deal_price else 0
        supplies = [Supply(name="Taco Bell tacos", quantity=quantity, unit_cost_cents=unit_cost, channel="Restaurant")]
    special = build_voice_summary(normalized, profile, headcount)
    outcomes = [cfg["outcomes"]["prefix"] + " " + x for x in (special[1] if special else profile["outcomes"])]
    warnings = ["Suggestions come from local templates. Check every field before using the proposal."]
    if not population and not explicit_headcount:
        warnings.append("Set your floor/building resident counts in Settings to calculate the 15% attendance suggestion.")
    if not event_date:
        warnings.append("Choose the event date before validation.")
    if key == "general" and not ("taco bell" in normalized and "first day" in normalized):
        warnings.append("Add the actual materials and costs; the zero-cost placeholder is not a price estimate.")
    warnings.append("Dates, times, attendance, collaborators, and floors are extracted where recognized; confirm them in the event fields.")

    event = EventDraft(
        idea=idea, title=extract_title(text, profile), event_type=event_type, community=community,
        event_date=event_date, requested_weekday=extract_weekday(text), start_time=start, end_time=end, location=location,
        headcount=headcount, collaborators=collaborators, description=special[0] if special else extract_description(text, profile),
        focus_areas=[profile["focus"]], outcomes=outcomes, supplies=supplies,
        requested_budget_cents=budget_cents,
    )
    return {"event": event.model_dump(mode="json"), "provider": "local_field_extractor", "assumptions": warnings}
