# Latency ideas (owner, 2026-09-24) — not built

Two ideas the owner raised at the end of the 2026-09-24 session. Neither is
started; no code changed for them. Written down so they are not lost.

## 1. Let Chatterbox finish (CPU contention)

The owner's idea: instead of STT and Chatterbox competing for the same CPU
cores, just let Chatterbox finish its render first.

Background: `notes/2026-09-22-omp-threads-vs-chatterbox.md`. STT decodes
partials continuously while HEARING is on, so it is often decoding at the
exact moment Chatterbox renders a reply. Dropping `OMP_NUM_THREADS` from 16 to
8 helped (render ~0.95 -> ~0.79 s/word) but some contention remains.

Questions to settle before building (mine, not the owner's):

- What "finish" means in code: pause STT decoding while a reply renders, or
  only stop decoding Sal's own voice. The hub already sets `speaking = True`
  around the whole `speak()` call in `say()`, so the hub knows when a render is
  in flight; the STT service would need to be told.
- Cost: while paused, the owner cannot interrupt with "stop" by voice. That is
  already a known gap (see the self-hear guard in memory).
- Compare against the structural fix in `notes/2026-08-10-rocm-amd-port.md`
  (Whisper on the GPU), which removes the contention instead of scheduling
  around it.

## 2. Break big text into chunks for faster time-to-sound

The owner's idea: when a long reply is to be rendered, split it (at sentences,
or perhaps commas) and render/play the first piece while the rest is still
rendering, so sound starts sooner.

Background: `notes/2026-09-19-realtimestt-servers-evaluation.md` already noted
that sentence streaming would improve time-to-first-audio, but Chatterbox on
this CPU is slower than real time (~0.6-0.9 s/word), so it would not remove
gaps between chunks. Chunking gives faster start, not smoother playback.

Things to weigh:

- Where the split goes: sentence boundaries first; commas give an even faster
  start but risk choppy prosody.
- Voice: Sal's voice is a happy accident that the owner cannot attribute to any
  one ingredient. Rendering in pieces may change the prosody, so listen before
  and after, and flag it before changing the render path.
- Where it lives: `say()` in `persona_hub.py` sends the whole text to
  `speak()` in one call. The split could happen there, with one bubble still
  shown for the whole reply.
