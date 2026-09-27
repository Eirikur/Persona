We both missed something yesterday. My chunking-output latency fix is
wrong. We could have caught it, but we didn't.  Chunking correctly
reduces the time-to-first-audio. The rest of the latency still happens
and is very audible as "random" pauses betweeen chunks. I caught this
during more extended conversations last night.
Render chunk 1
playback chunk 1
Render chunk 2  <-- Needs to happen during playback of chunk 1
playback chunk 2
...

The general lesson is that we should look at numbers before declaring victory.

## Analysis (2026-09-27)

Checked the code: `speak()` in `persona_speech_output.py` (lines 189-215,
unchanged since `0d55696`) already does render N, wait for N-1's playback,
play N, loop — non-blocking `sd.play()` means render of chunk N+1 already
runs during playback of N. The diagram above assumes serialization that
isn't there; the overlap this note asks for already exists.

The gap is arithmetic, not structure. `notes/2026-09-24-latency-ideas.md`
(lines 75-84) already measured this on 2026-09-26: Chatterbox renders at
about 3 s fixed + 0.45 s/word, chunks play back at about 0.24 s/word. Render
is roughly 2x real time, so chunk N+1 is never ready when chunk N stops
playing, no matter how far ahead rendering starts. That note even names the
result explicitly ("about 10 s of silence after the 5-word opener") and
still concludes "Chunking stays on."

Silence is conserved either way: request-to-done was 35.8 s whole vs 37.2 s
chunked for the same reply; chunking only moves the wait from before first
sound to between chunks, it doesn't remove it.

Why the listening test didn't catch it: `tests/tts_bench_common.py`
(`render_mode`, line 105) writes `chunked.wav` as
`np.concatenate(pieces)` — the rendered chunks glued back-to-back, with no
silence inserted for the render lag. The owner's listening test compared
voice/prosody at the chunk joins, not the actual gap experience; the WAV
never contained the gap.

Options, honestly sized:

- Revert (`CHUNK_MIN_WORDS = 1000`): one line, back to a single ~24 s wait,
  zero gaps. Immediate mitigation, reversible.
- Reshuffle chunk sizes (small first chunk, then bigger ones): still doesn't
  fix the average deficit — e.g. a 5-word opener then one 44-word chunk
  gives one big mid-reply gap of roughly (3 + 0.45*44) - 0.24*5 ~= 22 s.
  Arguably worse than an upfront wait, not a fix.
- Buffer-then-play (start once buffered audio covers estimated remaining
  render): at ~2x real time you'd need to render ~65% of the reply before
  starting, so first sound only moves from ~24 s to ~20-23 s. Marginal at
  this render speed, likely not worth building.
- Real fix needs render faster than real time: (a) find where the ~3 s
  fixed cost per `generate()` call goes (unmeasured, see 09-24 note line
  87-88) — if it's avoidable, chunked total drops meaningfully; (b) PocketTTS
  benchmarked faster than real time (0.06 s/word) but voice cloning is
  gated/unheard for Sal's sample; Coqui XTTS-v2 is faster than Chatterbox but
  still 1.4x real time, so it still gaps.

