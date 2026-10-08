# 2026-10-08 — roster restyle, click behavior, and setups

Companion to `2026-10-08-news-tool-and-x-cli.md` (the news_read tool).

## Roster strip (persona_chat.html)

- Names are 11px, two steps above the tab bar (9px). The first letter of each
  name is 1.5x larger (`.roster-name::first-letter`).
- Each name is drawn in its persona's own font. Fonts load after the roster is
  first drawn, so `useFont` also restyles the roster entries.
- Click toggles the persona in or out of the chat. Double-click scrolls to
  their last bubble and flashes it (does nothing if they have not spoken on
  this page). A click waits `CLICK_WAIT_MS` (250 ms) before toggling so a
  double-click can cancel it. Shift+click was removed (plain click does it).
- Right-click "Remove from chat" menu kept on purpose; the owner expects to
  use it.

## Setups (persona_schemas.py, persona_hub.py, persona_start.sh)

A setup is a named copy of the whole system state, same format as
`state.json`, stored in `~/.config/persona/setups/<name>.json`. Called "setup"
in code because "preset" already means voices here (`PRESET_VOICES`).

- Save: `system persist <name>` (the word "as" is optional; speech
  recognition drops it). Names are lowercased, words joined with a hyphen,
  anything unsafe stripped (`clean_setup_name`). Bare `system persist` still
  just saves `state.json`.
- Feedback: a Trace log line and a spoken "Saved setup <name>" in the system
  voice. No chat bubble, on purpose: it would eat chat space.
- Start from one: `./persona_start.sh --setup <name>` (combine with
  `--no-voice`). An unknown name lists the saved ones and exits before
  stopping anything. The current `state.json` is kept as
  `state-before-setup.json` (overwritten each time).
- A setup holds configuration only (personas, prompts, providers, tools,
  voices, fonts, who is loaded), never chat history.

## Notes from testing

- The hub does not pick up code changes until restarted; the first test hit
  old code.
- In named mode, say "System" to wake it, then "persist test". Traffic noise
  makes recognition unreliable; the owner chose not to tweak this yet.
- Open idea: `--list-setups` on the start script.
