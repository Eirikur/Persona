# Talking over a persona: hold and replay (2026-10-12)

## State

- `tts-backends` fast-forward merged into `main` (34 commits; `main` hadn't
  moved since the branch started).
- New branch `speak-over-queue`, two commits on top of `main`:
  - 2ea4acc  Echo's provider label `local` -> `internal`.
  - 207e6c7  Hold voice input spoken over a persona, replay it after.
- Unit tests pass (`tests/run_all.sh`; 14 cases in test_self_hear.py).
  **Not yet tried live.** It needs a hub-only restart (not `--no-voice`,
  which stops live speech) and a Ctrl+R on the chat page.

## Owner's decision

Queue, don't "wait for all of them" (that would need a new timeout). The
owner rarely says more than two lines over a persona, and small gaps in
timing don't matter.

## How it works (persona_hub.py)

1. `say()` keeps the text of the last `REPLIES_KEPT` (3) replies in
   `recent_replies`.
2. In `dispatch()`, the self-hear guard still catches voice input heard
   while a persona talks (or just after). It then checks `sounds_like_echo()`:
   - If at least `ECHO_OVERLAP` (0.6) of the transcript's words are in a
     recent reply, it's the persona's own voice. It's dropped as before, with
     an "ignored" trace line.
   - Otherwise it's the owner talking. `hold_input()` adds it to
     `held_inputs`, with a "held" trace line.
3. Every round of speech now ends in `speech_finished()`, which emits
   `speak_done` and then `replay_held_input()`. That function pops the
   **oldest** held input and runs it through `converse()` in a thread, with
   `replayed=True`. Only one is replayed per round; its own reply ends in
   `speech_finished()`, which replays the next one.
4. Replayed input skips the self-hear check only. Mute and named mode
   (the wake word) still apply.
5. Page: a "held" event resets TRANSCRIBING the same way "ignored" does.

## Known gaps / things to watch

- **Mixed recordings.** If owner and persona talk at once, the transcript
  holds both. It's held or dropped depending on which side of 0.6 it falls.
  Tune `ECHO_OVERLAP` once live examples show up in Trace.
- **Short answers.** A short answer ("yes") counts as echo if the reply also
  said "yes".
- **Muted at replay time.** If the hub is muted when an item is replayed,
  that item is dropped silently. Anything still held waits for the next
  round of speech.
- **No pending bubble.** The bubble appears only when the input is
  replayed. Before that, the only sign is the "held" line in Trace.

## Live findings (23:40)

- Echo check worked before the last restart: her own lines were marked
  "ignored", and the owner's "Challo." was held and then replayed.
- Bug, fixed in 9a50b43: a recording can start while the persona talks
  but deliver its text after she's done. Then nothing replayed it
  ("I'm really into it." waited until a restart lost it). Now, if nobody
  is speaking when something is held, it's replayed right away.
- The "let her finish" test ran while the hub was muted, so mute swallowed
  every transcript before the echo check. Re-run it unmuted.
