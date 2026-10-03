from datetime import date, time, timedelta
import re

def week_of(event_date, cfg):
    return (event_date - date.fromisoformat(str(cfg["semester"]["start_date"]))).days // 7 + 1 if event_date else None

def validate_event(event, cfg, budget, semester_events=None):
    semester_events = semester_events or []
    checks = []
    def check(key, title, errors, success, status="pass", review_issues=None):
        review_issues = review_issues or []
        final_status = "fail" if errors else "review" if review_issues else status
        checks.append({"key": key, "title": title, "status": final_status, "detail": success, "issues": errors + review_issues})
    errors = []
    for name, value in [("event title", event.title), ("event floor or audience", event.community), ("description", event.description), ("event date", event.event_date), ("start time", event.start_time), ("end time", event.end_time)]:
        if not value or (isinstance(value, str) and not value.strip()):
            errors.append(f"Add the {name}.")
    if not event.supplies:
        errors.append("Add materials, including any supplies you already have at $0.")
    if any(not x.name.strip() or x.name == "Supplies to confirm" for x in event.supplies):
        errors.append("Name each supply and confirm its estimated cost.")
    if event.event_type not in cfg["event_types"]:
        errors.append("Choose a supported event type.")
    if event.location not in [x["name"] for x in cfg["locations"]]:
        errors.append("Choose an available location.")
    if not event.focus_areas or any(x not in cfg["focus_areas"] for x in event.focus_areas):
        errors.append("Choose at least one configured focus area.")
    check("proposal", "Proposal essentials", errors, "Required fields, materials, location, and focus-area selection checked. Review whether the activity fits the focus area.")
    rules = cfg["outcomes"]
    verbs = [v for group in rules["action_verbs"].values() for v in group]
    errors, smart = [], []
    if len(event.outcomes) != rules["count"]:
        errors.append(f"Write exactly {rules['count']} learning outcomes.")
    for i, outcome in enumerate(event.outcomes, 1):
        if not outcome.startswith(rules["prefix"]):
            errors.append(f"Outcome {i} must begin “{rules['prefix']}”.")
            continue
        body = outcome[len(rules["prefix"]):].strip().lower()
        first = body.split()[0].strip(".,:;") if body else ""
        if first not in verbs or any(body.startswith(x) for x in rules["vague_phrases"]):
            errors.append(f"Outcome {i} needs a concrete action verb, such as name, share, or create.")
        if not re.search(r"\b\d+\b", body) and not any(re.search(r"\b" + re.escape(x) + r"\b", body) for x in rules["measurable_markers"]):
            smart.append(f"Outcome {i}: add an observable measure, such as one example or two names.")
        if not any(x in body for x in rules["time_markers"]):
            smart.append(f"Outcome {i}: add when it will be demonstrated, such as by the end of the event.")
    check("outcomes", "Three concrete learning outcomes", errors, "AI drafted three Bloom-style outcomes. Review their relevance and attainability.", review_issues=smart)
    errors, guidance = [], []
    event_rules = cfg["event_types"].get(event.event_type, {})
    week = week_of(event.event_date, cfg)
    if event.event_date:
        if event.requested_weekday and event.event_date.strftime("%A").lower() != event.requested_weekday.lower():
            actual_weekday = event.event_date.strftime("%A")
            errors.append(f"You said {event.requested_weekday.title()}, but {event.event_date.strftime('%B')} {event.event_date.day}, {event.event_date.year} is a {actual_weekday}. Confirm the date or correct the weekday.")
        if not date.fromisoformat(str(cfg["semester"]["start_date"])) <= event.event_date <= date.fromisoformat(str(cfg["semester"]["end_date"])):
            errors.append("The date falls outside the configured semester.")
        if "first_week" in event_rules and not event_rules["first_week"] <= week <= event_rules["last_week"]:
            guidance.append(f"The starter configuration suggests {event.event_type} during semester weeks {event_rules['first_week']}–{event_rules['last_week']}; this date is week {week}. Confirm whether that applies to your hall.")
        if event_rules.get("no_collaborations_through_week", 0) >= week and event.collaborators:
            guidance.append(f"The starter configuration says no collaborations through week {event_rules['no_collaborations_through_week']}; confirm whether that applies to your hall.")
    if "collaborator_count" in event_rules and len(event.collaborators) != event_rules["collaborator_count"]:
        guidance.append(f"The starter configuration expects {event_rules['collaborator_count']} collaborator(s). Confirm whether that applies to your hall.")
    if event_rules.get("building_trend_required") and not event.building_trend.strip():
        errors.append("Describe the building trend this event responds to.")
    if event.start_time and event.end_time:
        if event.end_time <= event.start_time:
            errors.append("End time must be after start time. This first version supports same-day events.")
        if event.event_date:
            for block in cfg["blocked_windows"]:
                if event.event_type in block["event_types"] and event.event_date.weekday() == block["weekday"] and event.start_time < time.fromisoformat(block["end"]) and event.end_time > time.fromisoformat(block["start"]):
                    errors.append(f"This overlaps {block['label']} ({block['start']}–{block['end']}).")
    peers = [x for x in semester_events if x["event"]["id"] != event.id and x["status"] == "approved_local" and x["event"]["event_type"] == event.event_type and x["event"].get("event_date") and str(cfg["semester"]["start_date"]) <= x["event"]["event_date"] <= str(cfg["semester"]["end_date"])]
    if event_rules.get("weekly") and event.event_date and event.start_time:
        for peer in peers:
            other = peer["event"]
            if other.get("event_date") and other.get("start_time") and (date.fromisoformat(other["event_date"]).weekday() != event.event_date.weekday() or other["start_time"][:5] != event.start_time.strftime("%H:%M")):
                guidance.append("The starter configuration suggests keeping the same weekday and start time as other approved Hall Snacks events.")
                break
    check("rules", "Event rules & timing", errors, "Semester dates, date/weekday consistency, and blocked times checked. Some suggested policies come from the starter configuration and need your review.", review_issues=guidance)
    errors = []
    projected = budget["actual_cents"] + budget["reserved_cents"] + event.estimate_cents
    if projected > cfg["budget"]["cap_cents"]:
        errors.append(f"This event would exceed your semester budget by ${(projected-cfg['budget']['cap_cents'])/100:.2f}.")
    if event.requested_budget_cents is not None and event.estimate_cents > event.requested_budget_cents:
        errors.append(f"Supplies exceed your event limit by ${(event.estimate_cents-event.requested_budget_cents)/100:.2f}.")
    check("budget", "Budget & estimated supplies", [], f"${event.estimate_cents/100:.2f} estimated; ${(cfg['budget']['cap_cents']-projected)/100:.2f} remains after actual spend and other approved plans. Verify prices and review any budget flags.", review_issues=errors)
    checks.extend([
        {"key":"calendar", "title":"Google Calendar availability", "status":"pending", "detail":"Connect Google Calendar in Settings to check availability on your primary calendar. Nothing will be added or booked.", "issues":[]},
        {"key":"human", "title":"Your final review", "status":"review", "detail":"Confirm that outcomes are achievable, costs are realistic, and the activity meets residents’ needs. Then approve the local proposal.", "issues":[]}
    ])
    return {"checks": checks, "local_pass": not any(x["status"] == "fail" for x in checks), "external_ready": False, "estimate_cents": event.estimate_cents, "projected_remaining_cents": cfg["budget"]["cap_cents"] - projected, "requirements": cfg["requirements"]}
