Merging pocket-tts-experiment into stt-engine-experiment
==========================================================

Goal: bring the PocketTTS switch into the roster/tool-calling/drop-voice
branch so it can be tested in that more-featured chat room.

Branch shape (checked 2026-09-27)
----------------------------------

- `stt-engine-experiment` is a strict superset of `led-ring-vad-states` --
  ignore the latter, it has nothing stt-engine-experiment lacks.
- `pocket-tts-experiment` branches off `main` at 226ddae ("Ignore .env").
- `stt-engine-experiment` and `pocket-tts-experiment` share an earlier
  common ancestor, 8e45127, then diverge for a long way. `stt-engine`
  carries the roster, echo persona, tool calling, drop-a-.wav-to-swap-voice,
  raise/notify alerts, and the chunked-playback/LED-ring work.
  `pocket-tts-experiment` carries only the TTS engine swap plus the
  `tools`/`label` schema fields (which stt-engine already has, identically
  -- that hunk merges clean).
- `git merge-tree` confirms exactly one real conflict: `persona_speech_output.py`.
  Both branches rewrote it independently.

The conflict, and how to resolve it
------------------------------------

`stt-engine-experiment`'s version (built across 0d55696 / f06d0ef /
5d59a88, chunking then reverted in 7eddf79) still runs Chatterbox, and adds:
- non-blocking `start_playing()` + a `stop_requested` flag so `/stop` can
  cut audio off mid-reply
- an `httpx.post(HUB_URL + "/playback_start")` call the hub relays as an
  SSE event (`persona_hub.py:playback_start`), which the LED ring and chat
  state strip use to distinguish "rendering" (amber -- text is ready, audio
  isn't) from "speaking". This is a real, load-bearing UI signal, unrelated
  to chunking.
- a chunk-splitting loop (`split_into_chunks`, `CHUNK_MIN_WORDS`) that is
  now permanently inert: `notes/2026-09-27-chunking-output-fix.md` (on this
  branch) found Chatterbox renders slower than real time, so chunking only
  moved the wait around rather than removing it, and set
  `CHUNK_MIN_WORDS = 1000` to turn it off for good. Nothing currently
  un-inerts it.

`pocket-tts-experiment`'s version swaps the engine: `TTSModel.load_model()`,
a `VOICE_STATES` cache (`voice_state_for`), `generate_audio`, and a numpy
(not torch) playback path. No chunking, no stop-mid-reply, no
`playback_start` ping -- none of that existed on this branch.

Owner's call (2026-09-27): don't resurrect chunking in the merge -- it
isn't part of what's actually running, and per the code-style rule ("delete
unused code and empty stubs"), inert scaffolding shouldn't be carried
forward just because it's technically mergeable.

Resolution plan for `persona_speech_output.py`:
- Engine: take pocket-tts-experiment's model loading, `VOICE_STATES` /
  `voice_state_for`, `render_speech`, and the numpy conversion +
  `MODEL.sample_rate`.
- Keep from stt-engine: `import httpx`, `HUB_URL`, non-blocking
  `start_playing()`, `stop()` (simplified -- no `stop_requested` flag needed
  without a chunk loop to interrupt; `sd.stop()` alone is enough for a
  single-shot render), and the `httpx.post(.../playback_start)` call right
  before playback starts.
- Drop entirely: `from persona_text_chunks import split_into_chunks`,
  `CHUNK_MIN_WORDS`, the chunk-numbering loop, `stop_requested`.
- `speak()` becomes: normalize text -> render once -> POST
  `/playback_start` -> `start_playing()` (non-blocking) -> `sd.wait()` ->
  return timing, same shape as pocket-tts-experiment's version but with the
  hub ping added back in.
- Drop the "Passing None reuses the sample" docstring paragraph on
  `render_speech` -- that was a Chatterbox-specific optimization
  (`voice_state_for(None)` would break PocketTTS's cache lookup); every call
  passes `req.voice_prompt`.

Everything else merges clean (`persona_schemas.py` auto-merges; the
benchmark-script and `persona_text_chunks.py` commits exist on both
branches with identical content).

Post-merge checks (not yet done)
----------------------------------

- `grep -n playback_start persona_hub.py` on the merged tree, to confirm
  the endpoint is still there and wired to `emit`.
- Start `persona_speech_output.py` directly (not the full stack) and hit
  `/speak` with curl before touching the live systemd unit.
- pocket-tts-experiment's last commit (7bd589a) added `HF_HOME` to the
  speech-out systemd unit -- if the installed unit predates it, re-run
  `persona_install.sh` and `systemctl --user daemon-reload` before
  restarting the live service.
- Don't restart the live speech-out service without asking first.
- Don't push.

Not yet done: the actual `git checkout stt-engine-experiment && git merge
pocket-tts-experiment`, or the hand-resolution above.
