# "Sal is unresponsive" — what it was, and four fixes (2026-11-11)

## What happened

Sal didn't answer in a freshly launched Persona. No errors anywhere.
Suspected cause: last night's headphone-surround work. Not the cause.

- Every hub start reset the room to Echo alone, so Sal was never in it.
- Named mode fails silently: "Sal, are you there?" arrived three times,
  matched nobody present, and was dropped. No reply, no log line.
- Roster names: present ones were grey (--text-info), absent ones darker
  grey (--text-dim). In Sal's thin font the two look alike, so Sal looked
  present.
- After Sal was loaded by curl, clicks in the window muted HEARING and
  removed Sal and Echo (a single click on a roster name toggles). The
  room was then empty and the mic muted.
- Two hub exits with code 137 at 16:37 were outside kills during launch,
  not crashes. No OOM kill logged.

Cleared: the surround output. Sal is audible through
`headphone_surround_music`. The default mic is the POROSVOC array, as
chosen for Sal mode on 2026-11-09.

## Fixes (one commit each, on main)

1. **e2ba7c9 — present names in white.** New token `--roster-here`
   (#FFFFFF) in persona_chat.html. Owner's idea. Also corrected the roster
   comment: click toggles, double-click finds the last bubble, right-click
   opens the Remove popup.

2. **159c3a1 — named miss is announced.** In named mode, if the first
   word names a persona who is out of the room, System says "Nobody named
   X is in the room." (`absent_persona_named()` in persona_hub.py.)
   - Whole first word, no comma needed (owner's choice). The in-room match
     still uses `startswith`, so "salad" counts as Sal there but won't
     trigger the miss.
   - System is skipped: its name starts commands.
   - The sentence doesn't start with a name, so if the mic hears it, it
     doesn't address anyone again.

3. **5353f43 — the room comes back as it was left.** Joining or leaving
   saves only `loaded_personas` into state.json (`save_roster()` in
   persona_schemas.py). Fonts, voices and the rest still need
   "system persist". At start, unknown names are dropped; Echo starts
   alone only if nobody is left. Replaces the old "every start begins with
   Echo alone" rule (owner chose auto-save over persist-only).

4. **42c8645 (committed 2026-11-20) — roster re-read on reconnect.** The page re-read mute
   but not the roster when its event stream reconnected after a hub
   restart, so a change during the restart left a stale white name (Echo,
   seen live). Now `es.onopen` also calls `loadRoster()`. Owner approved
   and confirmed it works.

## Behavior changes to know

- `active_persona` at start is now the first persona in the saved room
  (Sal), not always Echo. Settings tab provider/model edits apply to it.
- `persona_sal.sh --restore` only restores the mic, so the Sal-only room
  now sticks across restarts until Echo is clicked back in.
- `persona_start.sh --setup NAME` now also brings back the setup's room.
- Testing joins/leaves now changes the saved room. Undo test changes.

## Tests run

- Typed "Sal, are you there?" with Sal absent: `named miss: default`,
  System spoke. Owner heard "Nobody named Major is in the room."
- "hello there": no announcement.
- Echo added → hub restart → `['default', 'echo']`; removed → restart →
  `['default']`. The rest of state.json was unchanged (diffed against a
  backup).

## Open

- Commit fix 4 after the owner's testing.
- Owner will define an "addressed mode" (stricter addressing, e.g. name
  plus comma) for Claude to implement.
- Not pushed: e2ba7c9, 159c3a1, 5353f43 (and fix 4 once committed).
