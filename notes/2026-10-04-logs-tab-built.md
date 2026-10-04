# 2026-10-04 handoff: Logs tab built, pre-Trace items closed

State at the end of the session: everything below is committed on `main`
(last commit d15eedb). The stack was left running. Untracked and not mine:
`audio/dropped/`, `fonts/dropped/`, `notes/Sal-hears-the-birds.txt`.
Untracked and from the Tutor (Letta) session: `COORDINATION.md`,
`TUTOR_FINDINGS.md`.

## Done

- **Items from the 2026-10-02 handoff**
  - Per-tab window resize works live (Chromium honours `window.resizeTo`
    on X11; no wmctrl fallback needed).
  - Missing chat input box: not reproduced at heights 250..900 or at 500
    wide, and the owner sees it now. Probably a one-off repaint glitch.
    CSS left alone.
  - Leftover old window: gone.
  - Hal/Echo voices: still the owner's. The installed PocketTTS accepts a
    `.safetensors` voice file in `get_state_for_audio_prompt`, and
    `persona_speech_output.py` passes the path straight through. Not
    loaded for real yet.
- **Logs tab** (new, wide 1800x1600, between Trace and Settings)
  - 1731629 tailer: `persona_log_tailer.py` follows `logs/*.log` read-only
    (never truncates, renames or creates), replays 50 lines per file via
    `/logs/recent`, pushes new lines as SSE `service_log` events.
  - 0b1e172 line spacing 1.2.
  - 10c5813 rows: coloured stripe, fixed time and source columns, message
    on one line with "...", click a row to show the full text. Access-log
    lines shortened to `POST /converse 200`. Palette `LOG_COLORS` in
    `persona_schemas.py`, no reds or pinks.
  - 60a3453 bug I caused and fixed: the tailer first used SSE type `log`,
    which the hub already uses for its own Trace events.
  - 0c0d8a7, 8f70545 errors: red band, "!" in the gutter, hidden tab turns
    red and breathes, an error always scrolls into view, normal lines
    only follow when already at the bottom. Same rule in Trace, except for
    speech events (`SPEECH_EVENT_TYPES`). Tested live with TEST lines.
  - 4944bc8 sixth source `systemd`: `journalctl --user --unit persona-*`.
    Shows started, stopped, killed and OOM lines. Silver stripe.
  - d15eedb a reload keeps the current tab (`#logs` in the URL).

## Where the error rules live

`persona_schemas.py`: `ERROR_WORDS` (what counts), `ERROR_IGNORE_WORDS`
(known harmless lines), `LOG_NOISE_WORDS` (dropped entirely: mic_level,
recording_*, LED ring WriteCMD). Matching is plain substring.

Currently ignored as errors, with reasons:
- `timeout graceful shutdown exceeded` -- uvicorn, every hub stop with the
  chat page open (it cancels the open `/events` streams after 3 s).
- `Frame latency is negative` -- Chromium rendering noise.

Known and still shown red: `led-ring` "Lost connection to hub ... Errno" after
every hub restart. Real, but expected on a restart. Add an ignore entry if
it gets annoying.

## Tutor (Letta agent)

Tutor watched `logs/` this session. Its finding (TUTOR_FINDINGS.md) that
the shutdown error means a hang was checked and is wrong: the 4 occurrences
lined up with 4 of my `systemctl --user restart persona-hub` calls.
Answer recorded in COORDINATION.md. "Confusion lags" and "ignored
utterance" are not explained and remain open. Late in the session Tutor
reported "a loop"; the logs showed none (no reconnects, no repeated
lines). Its actual message was never seen.

## Left in the logs

Two harmless lines I appended to `logs/hub.log` for the error-band test:
`ERROR: TEST line from Claude ...` and `ERROR: TEST line 2 from Claude ...`.

## Open

1. Hal/Echo production voices, and try exporting to `.safetensors`.
2. Traceback continuation lines are not grouped under their first line
   (planned in the 2026-10-02 design; the owner said not needed).
3. Bookmarked: persona names in the roster in each persona's own font (see
   memory `roster-names-in-persona-font`).

## Cautions

- Hub restarts print the graceful-shutdown error. Not a fault.
- Propose before restarts; the owner's energy varies.
- A Logs tab restart-only change needs just the hub:
  `systemctl --user restart persona-hub`.
