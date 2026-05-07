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
#    "halo",
#    "nvidia-cublas-cu12",
#    "nvidia-cudnn-cu12",
# ]
# ///

import logging
import threading
from contextlib import asynccontextmanager

import httpx
import uvicorn
from fastapi import FastAPI

from persona_audio_recorder import AudioToTextRecorder

PORT = 8403
HUB_URL = "http://127.0.0.1:8400"


def _detect_device():
    try:
        import ctranslate2
        if 'float16' in ctranslate2.get_supported_compute_types('cuda'):
            return 'cuda', 'float16'
    except (RuntimeError, ImportError):
        pass
    return 'cpu', 'int8'


def _recorder_loop(hub_url: str, stt_model: str, silence_duration: float):
    device, compute_type = _detect_device()
    print(f"STT using {device} ({compute_type}), model={stt_model}")

    def on_text(text: str):
        text = text.strip()
        if not text:
            return
        print(f"< {text}")
        try:
            r = httpx.post(f"{hub_url}/converse", json={"text": text}, timeout=120.0)
            r.raise_for_status()
        except Exception as e:
            print(f"Hub error: {e}")

    recorder = AudioToTextRecorder(
        model=stt_model,
        device=device,
        compute_type=compute_type,
        spinner=False,
        level=logging.WARNING,
        no_log_file=True,
        post_speech_silence_duration=silence_duration,
        enable_realtime_transcription=True,
    )
    print("Listening — speak now")
    while True:
        recorder.text(on_text)


@asynccontextmanager
async def lifespan(app: FastAPI):
    t = threading.Thread(
        target=_recorder_loop,
        args=(HUB_URL, "base.en", 0.6),
        daemon=True,
    )
    t.start()
    yield


app = FastAPI(lifespan=lifespan)


@app.get("/status")
def status():
    return {"listening": True}


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=PORT)
