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

## Speech-out crash and hang, fixed (00:10, 2026-10-13)

- Cause: sounddevice's shared player was used from several request threads.
  sd.wait() closes the stream when it wakes; sd.play()/sd.stop() close it
  too. Two closes at once -> PortAudio assertion crash (23:45, three replies
  overlapping) or playback that never ends (a /speak hung forever after a
  /stop while another reply waited).
- 5bf7215: replies play one at a time (reply_lock); 63ce004: no sd.wait(),
  every player call under player_lock, waiting is a 20 ms poll.
- 514ff0e (hub): `speaking` is a count of replies in flight, so the first
  reply ending doesn't open the mic to the next one's voice.
- Stress test (scratchpad probe on port 8412): 3 overlapping replies with
  /stop at 2, 4, 6 s, then a full reply: no hang, no crash.
- Hub's /speak timeout is 120 s; a reply queued behind long ones could hit
  it. Watch for "speech output failed: ReadTimeout".

## Owner's notes at end of session (00:20, 2026-10-13)

Owner was tired; re-test these in the morning before trusting them.

1. **Queue seems to work.** Held input appears to get queued and played,
   but this was not tested carefully. Re-test in the morning.
2. **"Stop" did not stop a long reply.** Owner is fairly sure. They want
   "stop" to work as a safety valve, e.g. for a tool that returns many
   pages of text: an abort at the moment it hurts, instead of a length check
   that would always be a guess. Not investigated. Suspects:
   - The transcript may not *start* with "stop". dispatch() checks
     `normalized.startswith("stop")`, and a recording made while she talks
     can begin with her words ("...the lamp. Stop.").
   - /stop only stops speech-out's current reply. Since 5bf7215, replies
     waiting their turn (reply_lock) still play afterwards, and the hub
     side keeps going (other personas' replies, held-input replays).
3. **Named mode is still global.** Other personas hear input if the owner
   mis-clicks the roster, or forgets to click a persona off.
4. **Wanted:** when one persona hears its name in named mode, don't switch
   *everyone* to open mode, only that conversation. (Related to point 3, and
   to the open question in memory: should mode/state be per-persona?)

## 2026-10-15: stop investigated and fixed

Re-tested with Echo reciting pasted text (a valid test: same speak path).

Findings:
- Speech-out's /stop works: tested directly, a long reply went silent 20 ms
  after /stop.
- A bare "Stop." said as its own recording worked live (cut Echo off ~5 s in).
- Misses were all in the hub's dispatch():
  - "Echo, stop." / "Oh, and you know what? Uh... Stop." didn't *start*
    with "stop", so they were held as talk-over and replayed afterwards.
  - The mic merges Echo's words with the owner's ("the morning light crept
    across the table. stop"), which the first fix's echo check wrongly
    dropped as self-hear.
  - Fragments of Echo's voice recorded as she was stopped ("Rain tap.",
    "Brain tap.") were garbled enough to pass as the owner's, so were held
    and replayed after the stop; so was a held "Hmm.".
- Some early misses were simply the mic being muted.

What was built (persona_hub.py, tests in tests/test_self_hear.py):
- STOP_WORDS = stop, hush, be quiet. While a persona talks, one anywhere in
  a recording with at most STOP_MAX_WORDS (8) of the owner's own words
  (words not in recent replies) is a stop. When nobody talks, only input
  starting with "stop" is, so "how do I stop a process" still reaches the
  personas.
- Echo veto: a stop-containing recording that is mostly the persona's words
  is ignored, but only if a recent reply itself contains a stop word.
- "be quiet" stops speech *and* switches to named mode; stop/hush only stop.
- A stop clears held input and drops any recording that began before it
  ("ignored (recorded before stop)"). The clear happens *before* the /stop
  call, else the stopped reply's speech_finished() could replay one in the
  gap (race caught by the advisor).
- Stops now log `stop: '...'` in hub.log (they left no trace before).

Still open:
- A stop only ends the reply playing now. Replies waiting on speech-out's
  reply_lock, and hub-side replies still being generated, play afterwards.
  Matters with several personas loaded. Separate next step (speech-out).
- Owner's points 3 and 4 above (global named mode) untouched.
