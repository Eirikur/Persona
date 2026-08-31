#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = [
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
#    "webrtcvad",
#    "openwakeword",
#    "pvporcupine",
#    "RealtimeSTT",
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

import httpx
import torch
import uvicorn
import numpy as np
import soundfile as sf
from fastapi import FastAPI

torch.backends.nnpack.enabled = False  # silence unsupported-hardware NNPACK warnings
from RealtimeSTT import AudioToTextRecorder

# ─── Runtime State ───────────────────────────────────────────────────────────

recorder_instance = None
recorder_lock = threading.Lock()
force_typed = False

PORT = 8403
HUB_URL = "http://127.0.0.1:8400"

# ─── Test Configuration ───────────────────────────────────────────────────────

TEST_MODE = os.environ.get("PERSONA_TEST_MODE") == "1"
TEST_AUDIO_FILE = "tests/test_speech.wav"


def _detect_device():
    if torch.cuda.is_available():
        return "cuda", "float16"
    return "cpu", "int8"


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
    )
    
    with recorder_lock:
        recorder_instance = rec

    if TEST_MODE:
        if not os.path.exists(TEST_AUDIO_FILE):
            print(f"Error: Test audio file not found at {TEST_AUDIO_FILE}")
            return
        
        print(f"Test Mode: Feeding audio from {TEST_AUDIO_FILE}")
        data, samplerate = sf.read(TEST_AUDIO_FILE)
        if samplerate != 16000:
            print(f"Warning: Expected 16kHz audio, got {samplerate}Hz. Results may be poor.")
        
        data = data.astype(np.float32)
        if len(data.shape) > 1:
            data = np.mean(data, axis=1)
            
        rec.feed_audio(data)
        print("Audio fed. Waiting for transcription...")
    else:
        print("Listening — speak now")

    print("Entering STT transcription loop...")
    try:
        # Using the callback method as it's generally more stable in RealtimeSTT
        rec.text(on_text)
    except Exception as e:
        print(f"Error in STT loop: {e}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    t = threading.Thread(
        target=_recorder_loop,
        args=(HUB_URL, "small.en", 0.6),
        daemon=True,
    )
    t.start()
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
        r = httpx.post(f"{HUB_URL}/converse", json={"text": test_text, "typed": True}, timeout=120.0)
        r.raise_for_status()
        print(f"Hub responded: {r.status_code}")
        return {"status": "success", "text": test_text}
    except Exception as e:
        print(f"Hub error: {e}")
        return {"error": str(e)}, 500


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=PORT)
