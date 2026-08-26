# Voice Port Handoff

Date: 2026-08-26

This note summarizes the current voice-port state after restoring the repo to a
clean baseline and making the first known-good speech-output change.


# Process State

The repo had uncommitted and untracked work. That work was saved outside the repo
before cleanup:

- `../Persona-drafts/2026-08-26-013303/`

The repo was then reset to HEAD and cleaned. After that, one focused change was
made and committed.

Latest relevant commit:

- `9eaeac5 Restore AMD notes and simplify speech output`

That commit added:

- `notes/2026-08-10-rocm-amd-port.md`
- CPU-first `persona_speech_output.py`
- `speak-test.sh`


# Speech Output State

`persona_speech_output.py` now runs Chatterbox on CPU by default.

Important settings at the top of the file:

```python
PORT                 = 8402
DEVICE               = "cpu"
CHATTERBOX_MODEL     = "standard"
DEFAULT_VOICE_PROMPT = "audio/bird-dream.wav"
```

`CHATTERBOX_MODEL` can be changed to:

- `"standard"`
- `"turbo"`

The vendored Perth path override was removed because `../Perth` was not present.
The script now depends on normal `resemble-perth` resolution and pins
`setuptools<81`, because Perth still needs `pkg_resources`.


# Speech Output Test Result

The speech-output service started successfully:

```text
Loading Chatterbox standard on CPU...
loaded PerthNet (Implicit) at step 250,000
Model loaded in ...
Uvicorn running on http://127.0.0.1:8402
```

A direct speech request worked through:

```bash
./speak-test.sh
```

The system first played through the Strix's small built-in speakers. After the
owner switched the desktop default output to the USB DAC, `sounddevice` followed
the new default output as expected.

Conclusion: speech output works end-to-end by itself.


# Next Recommended Step

Do not start by testing the full voice loop.

The next focused task should be speech input:

1. Inspect `persona_speech_input.py` from the clean committed state.
2. Compare it with `notes/2026-08-10-rocm-amd-port.md`.
3. Port Whisper/STT separately from speech output.
4. Test speech input by itself before involving the hub, LLM, or speech output.
5. Commit the known-good speech-input step before full-stack testing.


# Cautions

- This machine is AMD/ROCm, not NVIDIA/CUDA.
- Chatterbox TTS should remain CPU-first on this host unless new benchmarks show
  otherwise.
- Whisper is the likely GPU beneficiary.
- Keep dependency experiments small and committed separately.
- Keep using `git status --short` before and after changes.
