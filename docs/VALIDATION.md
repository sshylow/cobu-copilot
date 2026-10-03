# Verified behavior — September 30, 2026

- Python test suite: **28 passed**, run locally with Python 3.12 and the pinned development dependencies.
- One non-failing dependency warning: Starlette's test client reports that its current httpx compatibility path is deprecated. Application behavior and all assertions passed.
- JavaScript syntax check: passed.
- Browser flow verified: example idea → local autofill → edit → validate → approve local proposal.
- A deliberately vague outcome blocked approval and displayed action-verb, measurement, and time-marker feedback. Correcting it cleared the failure.
- Local approval persisted across a reload and reserved $21.00 in an isolated fictional UI test event.
- Recording $18.50 of test actual spending replaced the $21.00 estimate: $0 reserved, $18.50 spent, $131.50 available from $150.00.
- The temporary UI test event was removed by exact ID after verification; no user events were removed.
- Desktop and narrow/mobile layouts inspected in the browser, including the native date/time fields and two-stage navigation.
- Calendar and Canva displayed Not connected throughout. No bookings, account access, or editable Canva designs were created.
- Browser WebMCP support was unavailable in the testing browser. Optional feature-detected registration is present but could not be exercised here; normal UI and API flows were tested.
- Microphone capture was not exercised; dictation depends on user permission and browser recognition-service support. Typing and keyboard dictation remain available.

These are software test results, not an AI evaluation. The ten fictional prompts in data/sample/eval_ideas.json have not been run through a real model. No first-pass AI score or time-saving metric is claimed.
