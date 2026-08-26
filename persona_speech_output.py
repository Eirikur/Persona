#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11,<3.12"
# dependencies = [
#    "setuptools<81",
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
# [tool.uv.extra-build-dependencies]
# pkuseg = ["numpy"]
# ///

"""Speech output service for Persona.

This service accepts text from the hub, renders it with Chatterbox, and plays the
result through the system's default audio output.
"""

import io
import time
import warnings
from contextlib import redirect_stderr, redirect_stdout

import sounddevice as sd
import uvicorn
from fastapi import FastAPI
from pydantic import BaseModel

warnings.filterwarnings("ignore", category=UserWarning, module="perth")


# ─── Settings ────────────────────────────────────────────────────────────────

PORT                 = 8402
DEVICE               = "cpu"
CHATTERBOX_MODEL     = "standard"
DEFAULT_VOICE_PROMPT = "audio/bird-dream.wav"


# ─── Model Loading ───────────────────────────────────────────────────────────

def load_model():
    """Load the configured Chatterbox model."""

    if CHATTERBOX_MODEL == "standard":
        from chatterbox.tts import ChatterboxTTS

        return ChatterboxTTS.from_pretrained(device=DEVICE)

    if CHATTERBOX_MODEL == "turbo":
        from chatterbox.tts_turbo import ChatterboxTurboTTS

        return ChatterboxTurboTTS.from_pretrained(device=DEVICE)

    raise ValueError("CHATTERBOX_MODEL must be 'standard' or 'turbo'")


print(f"Loading Chatterbox {CHATTERBOX_MODEL} on {DEVICE.upper()}...")
load_started = time.time()

MODEL = load_model()

print(f"Model loaded in {time.time() - load_started:.2f}s")


# ─── Web Service ─────────────────────────────────────────────────────────────

app = FastAPI()


class SpeakRequest(BaseModel):
    """Text and voice information for one speech request."""

    text: str
    voice_prompt: str = DEFAULT_VOICE_PROMPT


def normalize_punctuation(text: str) -> str:
    """Make generated text a little easier for Chatterbox to speak."""

    if not text:
        return "You need to add some text for me to talk."

    text = " ".join(text.split())

    if text[0].islower():
        text = text[0].upper() + text[1:]

    replacements = [
        ("...", ", "),
        ("…",   ", "),
        (":",   ","),
        (" - ", ", "),
        (";",   ", "),
        ("—",   "-"),
        ("–",   "-"),
        (" ,",  ","),
        ("“",   '"'),
        ("”",   '"'),
        ("‘",   "'"),
        ("’",   "'"),
    ]

    for old, new in replacements:
        text = text.replace(old, new)

    text = text.rstrip()

    if not any(text.endswith(mark) for mark in [".", "!", "?", "-", ","]):
        text += "."

    return text


def render_speech(text: str, voice_prompt: str):
    """Render speech audio with Chatterbox while hiding noisy model output."""

    sink = io.StringIO()

    with redirect_stderr(sink), redirect_stdout(sink):
        wav = MODEL.generate(text, audio_prompt_path=voice_prompt)

    return wav


def play_speech(wav) -> None:
    """Play rendered speech through the default sounddevice output."""

    audio = wav.squeeze().cpu().numpy()

    sd.play(audio, MODEL.sr)
    sd.wait()


@app.post("/stop")
def stop():
    """Stop any audio that is currently playing."""

    sd.stop()

    return {"ok": True}


@app.post("/speak")
def speak(req: SpeakRequest):
    """Render and play one spoken response."""

    text = normalize_punctuation(req.text)
    words = len(text.split())
    started = time.time()

    wav = render_speech(text, req.voice_prompt)
    elapsed = time.time() - started

    print(f"{words} words, {elapsed:.2f}s render, {elapsed / words:.2f}s/word")

    play_speech(wav)

    return {"ok": True, "elapsed": elapsed, "words": words}


# ─── Main ────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=PORT)
