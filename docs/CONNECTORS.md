# Integration handoff

The local UI includes Google Calendar OAuth for read-only free/busy checks on the connected primary calendar. It does not create events, reserve rooms, or send invitations. P-card and room calendar checks still need additional calendar IDs and permission grants. `connectors/contracts.py` defines the future connector boundaries.

## Structured drafting provider

`/api/draft` now uses OpenAI Structured Outputs through `agents/openai_drafting.py` and returns the `EventDraft` Pydantic schema. Keep deterministic validators and the editable review step. The model has no authority to write to Google Calendar; the UI offers a prefilled calendar link that the user must save. Add credentials only on the server and never return them to the browser. Do not silently fall back to the legacy local parser after a model failure.

## Google Calendar

Use an OAuth flow appropriate to deployment: a desktop client and loopback callback for a local app, or a web client with a registered callback for hosted use. Query free/busy for the user's, P-card, and space calendars only when access is actually granted. Per-calendar errors mean availability is unknown, never free. Use the configured IANA timezone and check every date in the intended weekly series, including Hall Council overlap and daylight-saving transitions.

Present specific calendar targets, dates, recurrence, timezone, and P-card window for approval. Recheck availability immediately before writing. Use a stored deterministic event ID per approved operation for retry safety, show partial failures explicitly, and do not promise that a free/busy check creates an atomic reservation. Do not invite guests or send notices without an explicit approval covering that action.

Official references:
- https://developers.google.com/workspace/calendar/api/quickstart/python
- https://developers.google.com/workspace/calendar/api/v3/reference/freebusy/query
- https://developers.google.com/workspace/calendar/api/v3/reference/events/insert

## Canva

Use server-side OAuth authorization code + PKCE with verified state, secure refresh-token storage, and the minimum required scopes. Check account capabilities. Map title, date, time, venue, and invitation copy onto three approved templates. Read each template's current field dataset before creating jobs; missing fields can otherwise be silently skipped by Canva.

Creating a draft in Canva is an external write. Add a separate “Create three drafts in Canva” approval after the event details have been reviewed. Poll jobs and show actual editable design links only on success. Do not overwrite source templates. Preview generation, calendar booking, and exporting should have distinct approval intents so choosing a flyer does not authorize reservations.

Official references:
- https://www.canva.dev/docs/apps/rest-apis/authentication/
- https://www.canva.dev/docs/apps/rest-apis/autofill-guide/
- https://www.canva.dev/docs/apps/rest-apis/reference/autofills/create-design-autofill-job/

## Approval and storage

The local app uses an HMAC of the event, configuration and budget snapshot and recomputes it inside a SQLite write transaction. It intentionally invalidates approvals after changes or server restarts. For integrations, add a durable operation ledger, explicit action type and destination, content hash, status, and connector response IDs. A local proposal approval must never be reused as implicit authority for a new external write. Encrypt credentials at rest for any multi-user deployment.
