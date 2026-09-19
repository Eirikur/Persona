# Biasing Whisper toward "Salice"/"Sal" with initial_prompt

2026-09-18. `MISHEARINGS` (in `persona_hub.py`) kept growing --
"solace," "alice," "sal ease," "salish," "ciao" -- because a general
Whisper model has no reason to guess "Salice" over any of those from audio
alone. The owner didn't want to keep hand-maintaining that list.

## The fix

`faster-whisper` (via RealtimeSTT's `AudioToTextRecorder`) accepts
`initial_prompt` (biases the final transcription pass) and
`initial_prompt_realtime` (biases the live partial one). Neither was set.
This is the standard Whisper technique for nudging recognition toward
specific vocabulary *before* transcription happens, instead of
string-replacing wrong guesses after the fact.

`persona_speech_input.py` now sets both to:

```
"Salice, pronounced sa-LEECE and often shortened to Sal, is a helpful voice assistant."
```

A natural sentence, not a bare word list -- that's what Whisper's prompt
conditioning responds best to. Fed to both the real-time and final
transcription passes in `_recorder_loop()`.

## Marked explicitly as an experiment

The code comment says so directly: if it doesn't measurably help after a
few days of real use, revert it rather than tuning the wording forever.
`MISHEARINGS` stays in place as a fallback for whatever still slips
through -- this is meant to shrink that list over time, not replace it
outright.

## Confirmed working

Tried live, immediately after deploying -- the owner confirmed improved
recognition on both "Sal" and "Salice." Keeping it.

## Files

`persona_speech_input.py`.

Commit: `76d7b80`.
