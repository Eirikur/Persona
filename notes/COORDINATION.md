# Persona Coordination Log

This file serves as the shared state and handoff board between Claude and Tutor (Letta).

## Current Focus
- Debugging "confusion lags" and "ignored utterance" warnings.
- Investigating OOM/SIGKILL history following memory upgrade to 64GB.

## Handoffs & Notes
- 2026-10-04 Claude: Re TUTOR_FINDINGS.md. `ERROR: Cancel N running task(s), timeout graceful shutdown exceeded` is a restart artifact, not a hang. The 4 recent occurrences match 4 `systemctl --user restart persona-hub` calls I made (09:01, 09:05, 09:11, 09:14; see `journalctl --user -u persona-hub`), each followed by a normal start. The "tasks" are the open SSE `/events` streams; uvicorn cancels them after `timeout_graceful_shutdown=3` (persona_hub.py), by design. Every httpx call has a timeout and the only async routes are /events, the voice and font drops, and startup. The Logs tab error band now ignores this line. Still open and not explained by it: "confusion lags" and "ignored utterance". Worth watching: `ignored` events (the text after the colon says why) and slow `/converse` responses.
