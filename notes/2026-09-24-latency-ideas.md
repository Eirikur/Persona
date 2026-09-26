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

## Idea 2 built (2026-09-26, branch `stt-engine-experiment`)

Chunking lives in the speech service, not the hub's `say()`. Doing it in the
hub would render and play each chunk in turn, so the next render could not
start until the last chunk finished playing. In the service, `sd.play()` does
not block, so the next chunk renders while the current one plays.

- `persona_text_chunks.py` (new, no model or audio code) splits normalized text
  at sentence ends and merges sentences until a chunk has `CHUNK_MIN_WORDS`
  words (setting in `persona_speech_output.py`, now 4). Set it to 1000 to
  render replies whole, as before.
- `persona_speech_output.py`: renders chunk, waits for the previous chunk to
  finish, plays. `/playback_start` is posted once, before the first chunk
  plays. `/stop` sets a flag so unplayed chunks are skipped (a render already
  in flight still finishes, as before). The voice sample is passed only with
  the first chunk; Chatterbox re-reads it on every call that is given one.

Measured directly (services stopped, one 49-word reply, no STT running):

| | before | chunked (min 4) |
|---|---|---|
| first sound | 23.85 s | 5.45 s |
| request to done | 35.8 s | 37.2 s |
| render s/word | 0.49 | 0.69 |

Each `generate()` call costs about 3 s fixed plus about 0.45 s/word (fit from
the four chunks: 5 words 5.45 s, 18 words 11.51 s, 15 words 9.21 s, 11 words
7.53 s). So chunking buys a faster start and pays for it in total time. It does
not remove gaps: a chunk plays about 0.24 s/word but renders slower, so the
next chunk is late (about 10 s of silence after the 5-word opener here).

Not yet listened to for prosody at chunk joins. Not run through the full stack.

Possible next tweak (not built): a small first chunk and larger later ones, to
keep the fast start while paying the 3 s fixed cost fewer times. Where the 3 s
goes inside `generate()` (perth watermark? s3gen setup?) is unmeasured.
