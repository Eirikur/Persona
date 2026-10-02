# 2026-10-02 handoff: logs tab plan, window size, drop features

State at the end of the session: everything below is committed on `main`
(last commit b487d6e). Nothing is half-edited. Untracked and not mine:
`audio/dropped/`, `fonts/dropped/`, `notes/Sal-hears-the-birds.txt`.

## Done today

- **system persist** (35e7bf2) -- saves in-memory state to state.json.
  Dropped fonts are stored in `Persona.font`. Voice drops already saved.
- **Drop feedback** -- green/red bubble flash for every file drop, and the
  persona answers "I received <file>." with the file name on its info line.
- **Speech failure no longer hangs a turn** (f6b7042): `speak()` catches any
  HTTP error, logs it, and the turn finishes. Voice drops over 12 MB are
  refused (413).
- **Why speech died:** 3-minute (35 MB) voice samples made PocketTTS use
  ~16 GB and the OOM killer took persona-speech-out. Hal and Echo were
  given such samples; the owner re-dropped Bird-Dream on both.
- **Echo labels:** model slot says "just an echo", provider shows "local".
- **Hub stops in 3 s** with the chat page open (c2dc2a3,
  `timeout_graceful_shutdown=3`).
- **Chat window is 1200x1600** (fb8a271 + a309704). It needed its own
  Chromium profile (`~/.config/persona/chromium`); with the everyday
  profile the window was handed to the running browser, which restored
  its own remembered size.
- **Logs tab renamed Trace** (f9a5eb3): one block per entry, hanging
  indent, brighter text, 2000-line cap.
- **Per-tab window size** (b487d6e): `TAB_WINDOW_SIZES` in
  persona_chat.html; Trace is 1800x1600 and uses the full width.
  UNTESTED in the live window -- see below.

## Open

1. **Test the per-tab resize live.** Reload the page, click Trace (window
   should grow to ~1800 wide), click Chat (back to 1200). If the browser
   ignores `window.resizeTo`, fall back to the hub calling `wmctrl`.
2. **Chat input box may have been missing** in the live window ("type here"
   not displayed). A headless screenshot at 1200x1600 shows it fine, so
   it was not reproduced. Check again after a fresh start.
3. **Leftover old "Persona Chat" window** (1829x2124) from before the
   profile change. Closing it while the stack is up shuts everything down.
   Stop first (`systemctl --user stop persona.target`), close it, restart.
4. **Hal/Echo voices** are placeholders (Bird-Dream) until the owner has
   cleaned, short production voices. PocketTTS README: clean the sample,
   and export to .safetensors for fast low-memory loading (untested here
   whether our speech service accepts that path).

## Next: the new Logs tab (design agreed, mockup at /tmp/persona_logs_mock.png)

Steps, one commit each:

1. Tailer thread in the hub follows `logs/*.log` and sends each new line
   to the page over SSE; new "Logs" tab, wide. Start at the end of each
   file (hub.log is 400k+ lines). Drop noise (`mic_level`, `recording_*`).
   Replay the last ~50 lines per file on hub start.
2. Row layout: coloured stripe, time, service name (full length, fixed
   column), message on ONE line, elided with "..."; click a row to expand.
   Shorten access-log lines (`POST /converse 200`). Palette in
   persona_schemas.py, no red or pink hues.
3. Errors (list of keywords: Error, Traceback, Exception, failed, killed,
   OOM): separate red band + "!" in the gutter; message text stays neutral
   so error colour is never confused with a source colour. Always scroll
   to the error line; light the tab red. Same rule in Trace.
4. Add `journalctl --user` as a sixth source "systemd" (the OOM kill and
   restart lines only exist there). The owner confirmed this.

Group traceback continuation lines under their first line with a lighter
stripe.

## Cautions for next time

- The owner wants to hand-edit nothing in state.json; use the drop
  features and `system persist`.
- Propose before restarts; the owner's energy varies.
- Check `git status --short` first: persona_chat.html once had 257 lines
  of CSS deleted by an unsaved/accidental editor change (restored from git).
