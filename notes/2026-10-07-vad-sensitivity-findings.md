# 2026-10-07 — VAD sensitivity trial, first data (and a speech-out crash)

Branch: tts-backends. Source: Logs tab (`/logs/recent`, 21:59–22:37).

## What was changed

- `d5d3d78`: `persona_speech_input.py` now has `SILERO_SENSITIVITY = 0.25`
  (was a literal 0.4). Direction is inverted: speech counts when Silero's
  probability exceeds `1 - sensitivity`, so lower = stricter (0.6 -> 0.75).
- speech-in restarted 22:32:23, listening again 22:32:27.
- Owner also planned to move the ReSpeaker array off the cluttered desk
  (exact time not recorded) — so the two changes are confounded.

## Findings

Before the change (21:59–22:32, ~33 min), speech-in sent roughly a dozen
stray short transcripts to the hub: "Thank you." x9, "Thanks." x2, "Yep.",
"Thank you, Bruce Michael." Some may have been real, but most arrived with
no one addressing the machine.

After the change (22:32:27–22:37, ~5 min, mostly active testing): no stray
"Thank you."-type lines. Every transcript was real speech. The one
"Thank you very much." at 22:35:15 was caught by the self-hear guard
(Sal's own voice), as designed.

Real speech was still picked up fine, including a quiet-ish sentence at
22:35:07 and the typed-style requests ("Sal, what's the weather for
tonight?"). No sign of missed speech yet.

Caveat: five minutes is far too little to call it a win. Needs a long
stretch of idle room time, which is where the hallucinations used to happen.

Unrelated to VAD, but seen in the same window: the 22:02:53 red error band
was the word "killed" in a background-chatter transcript tripping
`ERROR_WORDS`. Background speech from other people is real speech, which
no VAD setting removes (diarization is the eventual answer).

Also: HEARING was muted until 22:34:34 (`muted -> False`). Muted voice input
is dropped silently by the hub (`converse()`), with no log line.

## Separate problem: speech-out crashed at 22:35:22

- `double free or corruption (out)`, core dumped, exit 134. systemd restarted
  it within about a second (restart counter 1) and it came back healthy.
- Backtrace ends in `snd_pcm_close` -> `libasound_module_pcm_pipewire.so` ->
  `libportaudio.so.2`, i.e. closing an audio output stream, in the
  PocketTTS environment (python3.11). Not in Persona's own code.
- It hit during back-to-back replies (22:35:10, 22:35:17); the hub logged
  `speech output failed: RemoteProtocolError` for the two replies in flight,
  so those were not spoken. Not reproduced yet; cause unknown. Possibly
  related to overlapping playback or stream teardown, but that is a guess.

## Open items

1. Let `0.25` run through a long idle stretch; compare stray transcripts per
   hour against the 0.4 baseline above. If quiet speech is missed, try 0.3.
2. To separate mic position from VAD: temporarily set back to 0.4 later and
   see whether strays return.
3. Speech-out crash: watch for recurrence (`journalctl --user -u
   persona-speech-out`, `coredumpctl`). Not investigated further.
4. Candidate fixes, not built: log a line when muted drops voice input;
   don't flag speech-in transcript lines as errors in the Logs tab.
5. `WAKE_WORD_PROMPT` remains an unproven experiment (2026-09-18) and a
   possible hallucination contributor.
