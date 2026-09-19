# Signaling tool-calls and render-vs-playback, on the LED ring and on screen

2026-09-18. After tool-calling landed, the owner noticed real lag with no
visible explanation -- "I don't think I ever seen the INFERENCE light, so
I don't know what we're waiting for." Investigated with precise SSE
timing rather than guessing.

## What was actually happening

Two requests, measured with per-event timestamps against the live hub:

- A weather query (tool call, one round): `inference` -> `tool_call` ->
  `sal_turn` in under a second -- fast. But `sal_turn` to `speak_done` was
  **31 seconds**, entirely inside `speak()` on the speech-output service.
  `logs/speech-out.log` confirmed the split: ~20s Chatterbox rendering,
  ~11s actual playback, for a 34-word reply.
- A SpaceX query (tool call, more reasoning) took 50s total end to end.

So the INFERENCE/SPEAKING pipeline wasn't broken -- both states were
firing correctly -- but neither the LED ring nor the chat window
distinguished "the model is calling a tool" from "the model is just
thinking," or "Chatterbox is still rendering audio" from "audio is
actually playing." A 20-second silent wait with a static, unchanging
label reads exactly like frozen.

## Design (talked through before building)

Grounded in the project's own earlier LED color research
(`notes/LED-Light-Ring-Sequence-Research.md`): amber was flagged there as
the "in-progress/caution" color, before `inference` moved to white -- that
slot was sitting unused. Reused it:

- **INFERENCE**: white while thinking (unchanged), switches to amber the
  moment a tool call starts. No "stop being amber" signal needed -- it
  rides through to the final reply.
- **SPEAKING**: split into two sub-phases that didn't have separate
  signals before -- amber while Chatterbox renders (reply text is ready,
  no audio yet), green once playback actually starts.
- Breathing (not solid) on both, so a long wait still reads as "alive,"
  not stuck. Explicitly decided *not* to try to sync state changes to the
  breath cycle's phase -- the ring's breathing runs entirely in hardware
  once the effect is set, there's no phase to read back, so a clean cut
  was chosen over guessing at timing.
- Both the LED ring and the on-screen state strip render the same two new
  signals -- one hub event each, two renderers, not two designs.

## New signals

- `persona_llm.py` posts to a new hub route (`/tool_call/{name}`) right
  before running a tool call. Fire-and-forget, same pattern
  `persona_speech_input.py` already uses for recording start/stop.
- `persona_speech_output.py` posts to `/playback_start`, inserted between
  its existing `render_speech()` and `play_speech()` calls -- that
  boundary already existed in the code, just wasn't signaled anywhere.
- Hub relays both as SSE events: `tool_call` (carries the tool name) and
  `playback_start`.

## Renderers

**LED ring** (`persona_led_ring.py`): `sal_turn` now maps to a new
`rendering` state (amber breath) instead of directly to `speaking`;
`playback_start` maps to `speaking` (green breath, changed from a solid
color). `tool_call` maps to its own `tool_call` state, sharing the same
amber-breath look object as `rendering` (same appearance, so no wasted
hardware writes switching between them).

**Chat UI** (`persona_chat.html`): kept the existing four-label state
strip as-is and layered modifier classes on top --  `.tool` on INFERENCE,
`.rendering`/`.playing` on SPEAKING -- rather than inventing new labels or
widgets. A `@keyframes breathe` opacity pulse is scoped to exactly
`#state-inference.live` and `#state-speaking.live`, so it can't fight the
mic_level handler's inline `opacity` writes on `#state-hearing` (a
pre-existing pattern flagged as a recurring gotcha in this codebase).
Modifier classes are toggled explicitly in each SSE handler rather than
folded into `setLive()`'s async transition queue, to avoid a race where a
`tool_call` event arrives mid-transition.

## Verified

Full chain confirmed three times against the live stack with real
Cerebras + Brave calls: `inference -> tool_call -> sal_turn ->
playback_start -> speak_done`, correct order, plausible timing each time.
Not verified: the actual physical LED ring or the live browser window's
animation -- no way to observe hardware state or interact with the live
window without risk (see `feedback_no_reload_live_ui` in the assistant's
memory), so that half is the owner's to eyeball.

## Files

`persona_hub.py`, `persona_llm.py`, `persona_speech_output.py`,
`persona_led_ring.py`, `persona_chat.html`.

Commits: `f06d0ef` (signals + LED ring), `5d59a88` (chat UI).
