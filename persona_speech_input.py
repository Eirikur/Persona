#!/usr/bin/env -S uv run --script
"""requires-python = ">=3.11"
   Now pinned to 3.12.x because RealtimeSTT doesn't support 3.13 yet."""
# /// script
# requires-python = "==3.12.*"
# dependencies = [
#    "setuptools<81",
#    "fastapi",
#    "uvicorn",
#    "httpx",
#    "faster-whisper",
#    "torch",
#    "numpy",
#    "scipy",
#    "sounddevice",
#    "soundfile",
#    "torchaudio",
#    "pyaudio",
#    "openwakeword",
#    "pvporcupine",
#    "RealtimeSTT>=1.1.2",
#    "halo",
#    "nvidia-cublas-cu12",
#    "nvidia-cudnn-cu12",
# ]
# ///

import logging
import threading
import os
import time
from contextlib import asynccontextmanager

# ─── CPU Threads ──────────────────────────────────────────────────────────────

# CTranslate2 (faster-whisper) uses only 4 CPU threads unless told otherwise,
# and RealtimeSTT does not pass cpu_threads through. It does honor
# OMP_NUM_THREADS, but only if that is set before torch or ctranslate2 loads,
# so this must stay above the imports below. 16 is this machine's physical core
# count. Measured 2026-09-19 with large-v3-turbo on CPU: end of speech to text
# went from 5.5 s to 3.9 s, and Chatterbox rendering was not slowed. See
# notes/2026-09-19-realtimestt-servers-evaluation.md.
os.environ.setdefault("OMP_NUM_THREADS", "16")

import httpx
import torch
import uvicorn
import numpy as np
from fastapi import FastAPI

torch.backends.nnpack.enabled = False  # silence unsupported-hardware NNPACK warnings
from RealtimeSTT import AudioToTextRecorder

from persona_mic_indicator import run_mic_indicator

# ─── Runtime State ───────────────────────────────────────────────────────────

recorder_instance = None
recorder_lock = threading.Lock()
force_typed = False

PORT = 8403
HUB_URL = "http://127.0.0.1:8400"

# ─── STT Configuration ────────────────────────────────────────────────────────

# Whisper model size for RealtimeSTT. "small.en" is fast and English-only;
# "medium" is slower but noticeably more accurate. persona_schemas.py has an
# InputProfile.stt_model field meant to hold this once the editable-preferences
# system exists, but nothing wires it up to this service yet -- until then,
# this constant is the one place to change it.

# tiny.en, tiny, base.en, base, small.en, small, medium.en, medium,
# large-v1, large-v2, large-v3, large, distil-large-v2, distil-medium.en,
# distil-small.en, distil-large-v3, large-v3-turbo, turbo

STT_MODEL        = "large-v3-turbo"
SILENCE_DURATION = 0.6

# EXPERIMENT (2026-09-18): Whisper has no reason to guess "Salice" over
# "Alice"/"Solace" from audio alone, which is why MISHEARINGS has grown so
# long. faster-whisper's initial_prompt biases the transcription toward
# whatever text it's given, so feeding it the name -- spelled the way we
# want it recognized, in a natural sentence -- may cut mishearings off at
# the source instead of patching them after the fact. Fed to both the
# real-time and final passes below. If this doesn't measurably help after
# a few days of real use, revert it rather than tuning the wording forever.
WAKE_WORD_PROMPT = "Salice, pronounced sa-LEECE and often shortened to Sal, is a helpful voice assistant."

# ─── Test Configuration ───────────────────────────────────────────────────────

TEST_MODE = os.environ.get("PERSONA_TEST_MODE") == "1"
TEST_AUDIO_FILE = "tests/test_speech.wav"


def _detect_device():
    if torch.cuda.is_available():
        return "cuda", "float16"
    return "cpu", "int8"


def feed_test_audio(rec):
    """
    Play the test clip into the recorder at real-time speed, then three
    seconds of silence so the recorder can tell the utterance has ended.
    RealtimeSTT 1.1.x discards audio that arrives faster than real time, so
    the clip cannot be handed over in a single call.
    """
    rec.feed_audio_file(TEST_AUDIO_FILE)

    tenth_of_a_second = np.zeros(1600, dtype=np.float32)   # 16 kHz samples
    for step in range(30):
        rec.feed_audio(tenth_of_a_second)
        time.sleep(0.1)


def _recorder_loop(hub_url: str, stt_model: str, silence_duration: float):
    global recorder_instance
    device, compute_type = _detect_device()
    print(f"STT using {device} ({compute_type}), model={stt_model}")

    def on_text(text: str):
        global force_typed
        text = text.strip()
        if not text:
            return
        print(f"STT Callback received text: {text!r}")
        print(f"< {text}")
        
        is_typed = force_typed
        force_typed = False # Reset after use
        
        try:
            print(f"Sending to hub: {{'text': {text!r}, 'typed': {is_typed}}}")
            r = httpx.post(f"{hub_url}/converse", json={"text": text, "typed": is_typed}, timeout=120.0)
            r.raise_for_status()
            print(f"Hub responded: {r.status_code}")
        except Exception as e:
            print(f"Hub error: {e}")

    def on_recording_start():
        try:
            httpx.post(f"{hub_url}/recording_start", timeout=1.0)
        except Exception:
            pass  # the hub being briefly unavailable shouldn't matter here

    def on_recording_stop():
        try:
            httpx.post(f"{hub_url}/recording_stop", timeout=1.0)
        except Exception:
            pass  # the hub being briefly unavailable shouldn't matter here

    rec = AudioToTextRecorder(
        model=stt_model,
        device=device,
        compute_type=compute_type,
        spinner=False,
        level=logging.WARNING,
        no_log_file=True,
        post_speech_silence_duration=silence_duration if not TEST_MODE else 0.1,
        enable_realtime_transcription=True,
        use_microphone=not TEST_MODE,
        silero_sensitivity=0.1 if TEST_MODE else 0.4,
        initial_prompt=WAKE_WORD_PROMPT,
        initial_prompt_realtime=WAKE_WORD_PROMPT,
        on_recording_start=on_recording_start,
        on_recording_stop=on_recording_stop,
    )
    
    with recorder_lock:
        recorder_instance = rec

    if TEST_MODE:
        if not os.path.exists(TEST_AUDIO_FILE):
            print(f"Error: Test audio file not found at {TEST_AUDIO_FILE}")
            return
        
        print(f"Test Mode: Feeding audio from {TEST_AUDIO_FILE}")
        threading.Thread(target=feed_test_audio, args=(rec,), daemon=True).start()
        print("Audio feeding started. Waiting for transcription...")
    else:
        print("Listening — speak now")

    print("Entering STT transcription loop...")
    try:
        # rec.text() blocks for exactly one utterance and returns -- it is
        # not itself a loop. TEST_MODE feeds one fixed clip, so one call is
        # correct there. Live listening needs to keep calling it forever,
        # once per utterance, or the recorder goes silent after the first
        # thing anyone says.
        if TEST_MODE:
            rec.text(on_text)
        else:
            while True:
                rec.text(on_text)
    except Exception as e:
        print(f"Error in STT loop: {e}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    t = threading.Thread(
        target=_recorder_loop,
        args=(HUB_URL, STT_MODEL, SILENCE_DURATION),
        daemon=True,
    )
    t.start()

    threading.Thread(
        target=run_mic_indicator,
        args=(HUB_URL,),
        daemon=True,
    ).start()

    yield


app = FastAPI(lifespan=lifespan)


@app.get("/status")
def status():
    return {"listening": True}


@app.post("/test")
def trigger_test():
    """Bypass STT and send a test phrase directly to the hub to verify the pipeline."""
    print("Manual test triggered: Bypassing STT to verify Hub/LLM/Speech pipeline")
    
    test_text = "Sal, this is a system test. Do you hear me?"
    
    try:
        print(f"Sending test phrase to hub: {test_text!r}")
        r = httpx.post(f"{HUB_URL}/converse", json={"text": test_text, "typed": True, "speaker": "Test"}, timeout=120.0)
        r.raise_for_status()
        print(f"Hub responded: {r.status_code}")
        return {"status": "success", "text": test_text}
    except Exception as e:
        print(f"Hub error: {e}")
        return {"error": str(e)}, 500


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=PORT)
