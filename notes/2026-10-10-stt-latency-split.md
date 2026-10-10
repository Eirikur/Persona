# 2026-10-10 — where the "after I stop talking" wait goes

Branch: tts-backends. Stack was down during all runs (quiet CPU).

## The complaint

The owner feels the lag right after they stop talking: the HEARING ->
TRANSCRIBING change "seems too slow, almost as if the display is laggy".

## Finding 1: the display really is late

`persona_chat.html` lights TRANSCRIBING on the `heard` event, which arrives
only after Whisper has finished. The hub already emits `recording_stop` (the
moment transcription begins) but the state strip ignores it. So HEARING stays
lit through the whole endpoint + decode wait, then TRANSCRIBING flashes with
the text already in hand and is held for a 2-second minimum (`minEndTime`),
which can also hold back INFERENCE and SPEAKING. Not fixed yet.

## Finding 2: measured split (persona_stt_check.py, 5 rounds each)

`persona_stt_check.py` now reports endpoint (end of speech -> recorder's
`recording_stop`) and decode (`recording_stop` -> text) separately, and uses
production's `SILERO_SENSITIVITY` (it had a hard-coded 0.4). Clip:
`tests/test_speech.wav`, 1.8 s, "Sal, do you know what time it is?".
Every run below heard it perfectly.

| Configuration                            | Endpoint | Decode | Total  |
|------------------------------------------|----------|--------|--------|
| production: large-v3-turbo, 8 threads    | 1.03 s   | 2.58 s | 3.64 s |
| large-v3-turbo, OMP_NUM_THREADS=16       | 1.03 s   | 2.78 s | 3.84 s |
| large-v3-turbo, realtime partials off    | 1.06 s   | 2.78 s | 3.83 s |
| medium.en                                | 1.03 s   | 0.99 s | 2.01 s |
| small.en                                 | 1.03 s   | 0.37 s | 1.41 s |

Device is CPU (int8); CTranslate2 does not see the ROCm GPU here.

- Thread count and realtime partials: no gain. Both ruled out.
- Endpoint ~1.0 s = `SILENCE_DURATION` 0.6 + RealtimeSTT's 0.16 confirmation
  + VAD lag. Tunable, but too short cuts people off mid-pause.
- Model size is the lever: small.en decodes 7x faster than large-v3-turbo.

The non-production rows were throwaway copies of the check script (in the
Claude job's tmp dir), not committed. small.en / medium.en came from
`~/.cache/huggingface` (HF_HOME points at ~/AImodels, which only has
large-v3-turbo and tiny), run with `HF_HUB_OFFLINE=1`.

## Caveat before switching models

One clean clip proves speed, not accuracy. large-v3-turbo was chosen for
accuracy, and "Sal"/"Salice" recognition is why MISHEARINGS exists. Before
switching, build a small accuracy corpus: a dozen or so real utterances in the
owner's voice and room (names, commands, quiet speech), each with reference
text, and compare models on word errors as well as time.

## Next steps (proposed, not started)

1. UI: light TRANSCRIBING on `recording_stop`; reconsider the 2 s hold.
2. Accuracy corpus + make the check take a model name and several clips.
3. Decide model (small.en / medium.en / distil) from corpus numbers.
4. Voice-path bench through the live stack (stop talking -> first sound).
5. Later: Whisper on the GPU (needs a ROCm-capable backend), endpoint tuning.
