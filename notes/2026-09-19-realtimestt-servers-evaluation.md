# Should Persona adopt the RealtimeSTT / RealtimeTTS servers?

2026-09-19. Research pass, no code changed. The owner had cloned
`RealtimeSTT/` and `RealtimeTTS/` (Kolja Beigel's projects) into the repo and
asked whether Persona could delete its own speech services and run the
upstream servers instead, mainly to reach the non-Whisper STT engines.

**Decision: no to both servers. Use the RealtimeSTT library in-process and
select a different engine by keyword argument.**

## STT: why not the server

There are two servers in `RealtimeSTT/RealtimeSTT_server/`.

- `stt_server.py` (921 lines, entry point `stt-server`) is the legacy
  recorder-backed server. It has no engine option at all -- faster-whisper
  only. The owner's first reading was correct for this one.
- `production_server.py` (5321 lines, `stt-server-production`) does support
  the other engines (`--engine sherpa_onnx_parakeet`, and so on). But it is a
  WebSocket/HTTP ingest server for remote and browser clients. It has no
  microphone capture and, per its own docs, no recorder or VAD deciding turn
  boundaries -- the client decides. Adopting it would mean writing a
  mic-to-WebSocket client with our own VAD/endpointing to replace the
  ~230-line `persona_speech_input.py`: more code, plus two more ports.

Persona's glue (the hub POSTs on `on_recording_start` / `on_recording_stop`
that drive the LED ring and the state strip, the HEARING mute, the mic
indicator, `/test`) would all have to move into that client anyway.

## STT: what to do instead

`AudioToTextRecorder` already takes `transcription_engine=` and
`realtime_transcription_engine=` (see `RealtimeSTT/docs/transcription-engines.md`).
Every keyword Persona passes today, and the methods it calls (`text`,
`feed_audio`, `abort`, `shutdown`), exist in 1.1.2. No server is needed to try
other engines.

Upstream's recommended CPU profile is `sherpa_onnx_nemotron` (live partials)
plus `sherpa_onnx_parakeet` (authoritative final). Both are INT8 ONNX through
onnxruntime: no torch GPU, no CTranslate2, so the ROCm wheel problem does not
arise. Model bundles are installed once with
`stt-install-sherpa-models --root <dir> --model all` (about 475 MB and
487 MB); engine init never downloads.

## Findings that matter more than the server question

1. **Persona's STT runs on the CPU.** The uv env
   `persona-speech-input-cbf370596f93db50` has torch `2.13.0+cu130` (a CUDA
   build, `torch.version.hip` is None) on an AMD machine, so
   `torch.cuda.is_available()` is False and `_detect_device()` picks CPU int8.
   `logs/speech-in.log` confirms it. CLAUDE.md says Whisper is "expected to
   benefit from the GPU"; it currently does not. Typist solved this with a
   vendored ROCm CTranslate2 wheel and pyproject extras
   (`~/Proj/Typist/components/pyproject.toml`, `wheels/rocm/`), following
   `notes/2026-08-10-rocm-amd-port.md`. That port is still open and is
   independent of the engine experiment.
2. **Persona is running an old RealtimeSTT.** The same env has RealtimeSTT
   **0.3.94** with faster-whisper 1.1.1, because the script's dependency is
   unpinned and uv cached the environment on 2026-08-24. The engine system
   arrived in the 1.x line. Typist runs 1.1.2 on this machine.
3. **Whisper hallucination signature in the log.** 2723 callbacks, of which
   372 are `'Thank you.'`, 142 `'Okay.'`, 101 `'Yeah.'`, 55
   `'Thank you very much.'`. That is Whisper's known silence/noise artifact.
   The log cannot say which of those were real speech. The owner had not
   noticed them because, before 2026-09-18, unaddressed speech produced no chat
   bubble (see `progress/2026-09-18-always-show-heard-input.md`); named mode
   discarded them invisibly. They may now show up as bubbles. VAD and
   `min_length_of_recording` tuning is worth doing whatever the engine.
4. Log history shows the deployed model moved small.en -> medium ->
   large-v3-turbo. Nothing in the log shows GPU use at any point.

## TTS: why not the server

- The pasted endpoints (`/tts`, `/engines`, `/set_engine`, `/voices`,
  `/setvoice`) are `RealtimeTTS/example_fast_api/server.py`, an example app,
  not a packaged service. `/tts` runs `stream.play(on_audio_chunk=...,
  muted=True)` and streams chunks back over HTTP. The *client* plays them.
  Persona would still need a player, so `persona_speech_output.py` (180 lines)
  would not go away.
- Persona's contract is `POST /speak` (render, then play on the server, and
  post `/playback_start` to the hub between the two) plus `POST /stop`. The
  example server has neither, and keeps global "current engine" state.
- `RealtimeTTS/engines/chatterbox_engine.py` wraps `chatterbox.tts_turbo`
  only and defaults to `device="cuda"`. Persona's benchmarked decision is the
  *standard* Chatterbox model on CPU.

## TTS: where RealtimeTTS could still pay off (not now)

The in-process library, not the server: `TextToAudioStream.play_async`,
`fast_sentence_fragment`, `on_audio_stream_start` / `on_audio_stream_stop`,
`stop()`. That matches `goals/listen-while-speaking--allow-interruptions.txt`
and hides some of the latency measured in
`progress/2026-09-18-tool-call-and-playback-signals.md` (about 20 s to render
a 34-word reply before 11 s of playback). Caveat: Chatterbox renders slower
than real time on this CPU, so sentence streaming improves time-to-first-audio
but will not remove gaps between sentences. Revisit when that goal is taken up.

## Plan for the STT experiment (one small change at a time)

Work on a branch off `led-ring-vad-states`. Speech services are currently
stopped, so test the one service directly with `PERSONA_TEST_MODE=1`
(feeds `tests/test_speech.wav`, hub POSTs fail harmlessly) before touching the
full stack.

1. Bump `RealtimeSTT` to 1.1.2 in the script's dependency block, still on
   faster-whisper. Confirm the existing behaviour is unchanged. Commit.
2. Add `TRANSCRIPTION_ENGINE` and `REALTIME_TRANSCRIPTION_ENGINE` constants
   next to `STT_MODEL`; default them to faster_whisper so nothing changes.
   Commit.
3. Install the sherpa-onnx models onto a persistent path, then switch the
   constants to Nemotron (live) and Parakeet (final). Compare against Whisper
   by ear, watching for the "Thank you." pattern. Note that `initial_prompt`
   is a Whisper feature: the "Salice" bias will not carry over, so
   `MISHEARINGS` matters again with these engines.

Rollback at every step is `git revert`. Caveat: uv rebuilt the speech-input
env in place (same cache directory), so the old 0.3.94 environment is gone; a
revert re-resolves and will land on 1.1.2 unless the script pins
`RealtimeSTT==0.3.94`.

## Step 1 result (2026-09-19, branch `stt-engine-experiment`)

Direct test with `PERSONA_TEST_MODE=1` passes on RealtimeSTT 1.1.2 with
faster-whisper large-v3-turbo: the clip transcribes as "Sal, do you know what
time it is?" (the `initial_prompt` "Sal" bias still works). Getting there took
four fixes, all now in `persona_speech_input.py`:

1. `requires-python = "~=3.12"` means "3.12 or newer", not "3.12 only", so uv
   had built the env on Python 3.13, which RealtimeSTT 1.1.2 does not support.
   Now `==3.12.*`.
2. `webrtcvad` imports `pkg_resources`, which setuptools 81+ removed (same trap
   as the ROCm note). Added `"setuptools<81"`, as `persona_speech_output.py`
   already does. Removed the script's own redundant `webrtcvad` line;
   RealtimeSTT 1.1.2 depends on `webrtcvad-wheels`.
3. 1.1.x drops audio that arrives faster than real time ("Audio queue size
   exceeds latency limit"), so test mode's single `feed_audio(whole_clip)` was
   silently discarded. Test mode now feeds the clip with the library's paced
   `feed_audio_file()` plus three seconds of silence, in a background thread
   (new function `feed_test_audio`).
4. Removed the now-unused `soundfile` import.

Not yet verified: live microphone use through the full stack. Do that before
step 2.

## Gotcha: do not keep upstream clones inside the repo

The `RealtimeSTT` repo has an `__init__.py` at its root, so a clone sitting in
`~/Proj/Persona/RealtimeSTT/` is importable as a package named `RealtimeSTT`.
`persona_speech_input.py` runs with the repo as its script directory, so that
folder shadowed the installed library and the service died at import with
`ImportError: cannot import name 'AudioToTextRecorder'`. Ignoring the clones in
`.gitignore` is not enough. They now live at `~/Proj/RealtimeSTT` and
`~/Proj/RealtimeTTS`, outside the repo.

## Open items

- Untracked owner files awaiting a decision on where they live:
  `Friday9-18-notes.txt`, `goals/`, `p.sh` (LED-ring colour test script).
- `led-ring-vad-states` is 11 commits ahead of `main` and behind nothing.
  Merging it is the owner's call.
- Direction, weeks out: modularize so code is written once and shared between
  Persona and the standalone utilities (Typist and others). The ROCm/torch
  device-selection logic is the obvious first candidate, since Typist and
  Persona both need it. `~/Proj/claude-tools` holds cross-project tools; move
  things there only once they are reused for real.
