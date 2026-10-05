#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11,<3.12"
# dependencies = [
#    "setuptools<81",
#    "fastapi",
#    "uvicorn",
#    "httpx",
#    "numpy",
#    "torch",
#    "sounddevice",
#    "pocket-tts",
# ]
# ///

"""Speech output service for Persona.

This service accepts text from the hub, renders it with PocketTTS in chunks,
and plays the result through the system's default audio output. While one chunk
plays, the next is rendering, so sound starts after the first chunk's render
instead of the whole reply's.
"""

import time

import httpx
import numpy as np
import sounddevice as sd
import uvicorn
from fastapi import FastAPI
from pocket_tts import TTSModel
from pydantic import BaseModel

from persona_text_chunks import split_into_chunks


# ─── Settings ────────────────────────────────────────────────────────────────

PORT                 = 8402
HUB_URL              = "http://127.0.0.1:8400"
DEFAULT_VOICE_PROMPT = "audio/bird-dream.wav"

# A reply is rendered and played in chunks of at least this many words. Lower
# starts sound sooner; higher means fewer, smoother-sounding pieces. Set it
# very high (1000) to render each reply whole. Chunking was turned off under
# Chatterbox (7eddf79) because it rendered slower than real time; PocketTTS
# renders several times faster than playback, so the next chunk is ready in time.
CHUNK_MIN_WORDS      = 4

# Seconds of silence added after every chunk except the last, so the break
# between sentences sounds like a breath. 0.0 means no added pause; PocketTTS
# ends each chunk with only a few frames of tail, which can sound too tight.
CHUNK_PAUSE          = 0.25

# Set by /stop so chunks that have not played yet are skipped. Cleared at the
# start of every reply.
stop_requested = False


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

    text = " ".join((text or "").split())

    if not text:
        return "You need to add some text for me to talk."

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


def start_playing(wav, pause: float = 0.0) -> None:
    """Begin playing rendered speech and return at once; play continues on its own. Adds pause seconds of silence at the end."""

    audio = np.asarray(wav, dtype=np.float32).reshape(-1)

    if pause > 0:
        audio = np.concatenate([audio, np.zeros(int(pause * MODEL.sample_rate), dtype=np.float32)])

    sd.play(audio, MODEL.sample_rate)


@app.post("/stop")
def stop():
    """Stop the audio that is currently playing, and skip any chunks still to come."""

    global stop_requested

    stop_requested = True
    sd.stop()

    return {"ok": True}


@app.post("/speak")
def speak(req: SpeakRequest):
    """Render and play one spoken response, chunk by chunk."""

    global stop_requested

    stop_requested = False

    text = normalize_punctuation(req.text)
    chunks = split_into_chunks(text, CHUNK_MIN_WORDS)
    started = time.time()
    first_sound = None

    for number, chunk in enumerate(chunks):
        wav = render_speech(chunk, req.voice_prompt)

        # sd.play replaces whatever is playing, so let the previous chunk finish.
        sd.wait()

        if stop_requested:
            break

        if number == 0:
            first_sound = time.time() - started
            try:
                httpx.post(f"{HUB_URL}/playback_start", timeout=1.0)
            except Exception:
                pass  # the hub being briefly unavailable shouldn't hold up playback

        is_last = number == len(chunks) - 1
        start_playing(wav, 0.0 if is_last else CHUNK_PAUSE)

    sd.wait()

    words = len(text.split())
    print(f"{words} words in {len(chunks)} chunks, first sound after "
          f"{first_sound if first_sound is not None else 0:.2f}s")

    return {"ok": True, "first_sound": first_sound, "words": words, "chunks": len(chunks)}


# ─── Main ────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=PORT)
