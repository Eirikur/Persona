# Speaker recognition as a crude auth gate — research

2026-09-26. Research only; nothing was installed, run, or changed. Question:
can Persona pick a "person recognition" package so that guests and media
playing in the room are never transcribed? Accuracy and integration claims
below come from docs and the RealtimeSTT source, not from a test on this box.

## Pick

**SpeechBrain `spkrec-ecapa-voxceleb`** (ECAPA-TDNN).

- 0.80% EER on VoxCeleb1-test (cleaned), per the model card. Far better than
  Resemblyzer's older GE2E encoder.
- Apache 2.0.
- API: `EncoderClassifier.from_hparams(source="speechbrain/spkrec-ecapa-voxceleb")`
  then `.encode_batch(signal)`; compare two embeddings by cosine similarity.
  Input is 16 kHz mono, which is what RealtimeSTT already produces.
- Small network: should run on CPU in tens of milliseconds per utterance.
  Keep it on CPU (leaves the GPU for Whisper and the LLM, per
  `2026-08-10-rocm-amd-port.md`) and cap its torch threads so it does not
  compete with Chatterbox (see `2026-09-22-omp-threads-vs-chatterbox.md`).
- Model card: https://huggingface.co/speechbrain/spkrec-ecapa-voxceleb

## Runner-ups

- **WeSpeaker** (https://github.com/wenet-e2e/wespeaker) — Apache 2.0,
  actively maintained (updated 2026-09-22), ECAPA / ResNet / CAM++ models,
  `wespeaker.load_model()` API. Installs from git, not PyPI; more
  research-shaped. Fallback if SpeechBrain's torch/torchaudio pins fight the
  ROCm setup.
- **Resemblyzer** (https://github.com/resemble-ai/Resemblyzer) — Apache 2.0,
  simplest, 256-dim embeddings. Side project, little recent activity, README
  only demos 10 speakers. Weakest at guest-vs-owner.
- **pyannote** — diarization-focused, models gated behind a Hugging Face
  login. Overkill here.
- Chatterbox bundles a Resemblyzer-derived voice encoder, but it lives in the
  speech-output environment and is the weaker model; not worth reusing.

## Where it fits

In `persona_speech_input.py`, the live loop calls `rec.text(on_text)`. In the
installed RealtimeSTT, `text()` is just `wait_audio()` then `transcribe()`,
and `wait_audio()` leaves the finished utterance in `rec.audio` as a float32
16 kHz array (`RealtimeSTT/audio_recorder.py:490`). So the gate slots between
the two:

1. `rec.wait_audio()`
2. Embed `rec.audio`, compare with the enrolled voiceprint.
3. `rec.transcribe()` only on a match; otherwise drop the utterance.

Enrollment would be a one-time script that records a few sentences and saves
the averaged embedding, probably under `~/.config/persona/`.

## Limits to expect

- **Crude, not security.** A recording of the owner's voice would pass, and
  TV dialogue that sounds like the owner could too. It mostly filters guests
  and media.
- **Short utterances are the weak spot.** "Stop" or "Sal" alone (under about
  1.5 s) gives noisy embeddings. The model card gives no guarantee outside
  VoxCeleb's data. Needs a threshold tuned on this mic and room, plus a
  decision on how to treat very short clips.
- **Realtime partials still cost CPU.** `enable_realtime_transcription=True`
  runs Whisper on audio as it arrives, before the gate. Nothing consumes the
  partials today, so nothing leaks, but the CPU is spent on guests too. A
  stricter version would turn realtime transcription off.
- **Recording events still fire for everyone.** `/recording_start` posts, the
  LED ring and the HEARING brightness would still react to a guest's voice.
- **The voiceprint file is sensitive.** Treat it like the voice sample in
  `2026-09-23-voice-sample-legal.md`; keep it out of git.

## Suggested first step

A standalone script in `tests/`, in the style of the TTS benchmarks: enroll
the owner, then score a few owner utterances against a guest's voice and a
YouTube clip, to see the threshold gap before touching the STT service. Do
this before any change to `persona_speech_input.py`.
