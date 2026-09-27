#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11,<3.12"
# dependencies = [
#    "setuptools<81",
#    "fastapi",
#    "uvicorn",
#    "numpy",
#    "torch",
#    "sounddevice",
#    "pocket-tts",
# ]
# ///

"""Speech output service for Persona.

This service accepts text from the hub, renders it whole with PocketTTS, and
plays the result through the system's default audio output.
"""

import time

import numpy as np
import sounddevice as sd
import uvicorn
from fastapi import FastAPI
from pocket_tts import TTSModel
from pydantic import BaseModel


# ─── Settings ────────────────────────────────────────────────────────────────

PORT                 = 8402
DEFAULT_VOICE_PROMPT = "audio/bird-dream.wav"


# ─── Model Loading ───────────────────────────────────────────────────────────

print("Loading PocketTTS...")
load_started = time.time()

MODEL = TTSModel.load_model()

print(f"Model loaded in {time.time() - load_started:.2f}s")

# One prepared voice state per sample file. PocketTTS's cloning setup step
# (get_state_for_audio_prompt) costs about a second, so each voice prompt is
# only prepared once and reused after that.
VOICE_STATES = {}


def voice_state_for(voice_prompt: str):
    """Return the prepared PocketTTS state for a voice sample, preparing it once."""

    if voice_prompt not in VOICE_STATES:
        VOICE_STATES[voice_prompt] = MODEL.get_state_for_audio_prompt(voice_prompt)

    return VOICE_STATES[voice_prompt]


# ─── Web Service ─────────────────────────────────────────────────────────────

app = FastAPI()


class SpeakRequest(BaseModel):
    """Text and voice information for one speech request."""

    text: str
    voice_prompt: str = DEFAULT_VOICE_PROMPT


def normalize_punctuation(text: str) -> str:
    """Make generated text a little easier for the model to speak."""

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
    """Render speech audio for the whole reply with PocketTTS."""

    state = voice_state_for(voice_prompt)

    return MODEL.generate_audio(state, text)


def play_speech(wav) -> None:
    """Play rendered speech through the default sounddevice output."""

    audio = np.asarray(wav, dtype=np.float32).reshape(-1)

    sd.play(audio, MODEL.sample_rate)
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
