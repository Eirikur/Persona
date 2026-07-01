#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11,<3.12"
# dependencies = [
#    "fastapi",
#    "uvicorn",
#    "numpy",
#    "torch",
#    "torchaudio",
#    "sounddevice",
#    "chatterbox-tts>=0.1.5",
#    "resemble-perth",
# ]
#
# [tool.uv.sources]
# resemble-perth = { path = "../Perth" }
#
# [tool.uv.extra-build-dependencies]
# pkuseg = ["numpy"]
# ///

import io
import time
import warnings
from contextlib import redirect_stderr, redirect_stdout

import uvicorn
import sounddevice as sd
from fastapi import FastAPI
from pydantic import BaseModel

warnings.filterwarnings("ignore", category=UserWarning, module="perth")

import torch

PORT = 8402
DEVICE = 'cuda' if torch.cuda.is_available() else 'cpu'
DEFAULT_VOICE_PROMPT = 'audio/bird-dream.wav'

print(f"Loading Chatterbox Turbo on {DEVICE.upper()}...")
_t = time.time()
from chatterbox.tts_turbo import ChatterboxTurboTTS
MODEL = ChatterboxTurboTTS.from_pretrained(device=DEVICE)
print(f"Model loaded in {time.time() - _t:.2f}s")

app = FastAPI()


class SpeakRequest(BaseModel):
    text: str
    voice_prompt: str = DEFAULT_VOICE_PROMPT


def punc_norm(text: str) -> str:
    if not text:
        return "You need to add some text for me to talk."
    if text[0].islower():
        text = text[0].upper() + text[1:]
    text = " ".join(text.split())
    for old, new in [
        ("...", ", "), ("…", ", "), (":", ","), (" - ", ", "), (";", ", "),
        ("—", "-"), ("–", "-"), (" ,", ","),
        ("“", '"'), ("”", '"'), ("‘", "'"), ("’", "'"),
    ]:
        text = text.replace(old, new)
    text = text.rstrip()
    if not any(text.endswith(p) for p in {".", "!", "?", "-", ","}):
        text += "."
    return text


@app.post("/stop")
def stop():
    sd.stop()
    return {"ok": True}

@app.post("/speak")
def speak(req: SpeakRequest):
    text = punc_norm(req.text)
    start = time.time()
    sink = io.StringIO()
    with redirect_stderr(sink), redirect_stdout(sink):
        wav = MODEL.generate(text, audio_prompt_path=req.voice_prompt)
    elapsed = time.time() - start
    words = len(text.split())
    print(f"{words} words, {elapsed:.2f}s render, {elapsed/words:.2f}s/word")
    audio = wav.squeeze().cpu().numpy()
    sd.play(audio, MODEL.sr)
    sd.wait()
    return {"ok": True, "elapsed": elapsed, "words": words}


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=PORT)
