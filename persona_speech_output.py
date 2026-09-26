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

import httpx
import sounddevice as sd
import uvicorn
from fastapi import FastAPI
from pydantic import BaseModel

from persona_text_chunks import split_into_chunks

warnings.filterwarnings("ignore", category=UserWarning, module="perth")


# ─── Settings ────────────────────────────────────────────────────────────────

PORT                 = 8402
HUB_URL              = "http://127.0.0.1:8400"
DEVICE               = "cpu"
CHATTERBOX_MODEL     = "standard"
DEFAULT_VOICE_PROMPT = "audio/bird-dream.wav"

# A reply is rendered and played in chunks of at least this many words. Lower
# starts sound sooner; higher means fewer, smoother-sounding pieces. Set it
# very high (1000) to render each reply whole, as before chunking.
CHUNK_MIN_WORDS      = 4


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

stop_requested = False


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


def render_speech(text: str, voice_prompt: str | None):
    """
    Render speech audio with Chatterbox while hiding noisy model output.

    Chatterbox re-reads the voice sample every time it is given one. Passing
    None reuses the sample from the previous call, so only a reply's first
    chunk needs to pass it.
    """

    sink = io.StringIO()

    with redirect_stderr(sink), redirect_stdout(sink):
        wav = MODEL.generate(text, audio_prompt_path=voice_prompt)

    return wav


def start_playing(wav) -> None:
    """Begin playing rendered speech and return at once; play continues on its own."""

    audio = wav.squeeze().cpu().numpy()

    sd.play(audio, MODEL.sr)


@app.post("/stop")
def stop():
    """Stop the audio that is playing, and skip the chunks not yet played."""

    global stop_requested

    stop_requested = True
    sd.stop()

    return {"ok": True}


@app.post("/speak")
def speak(req: SpeakRequest):
    """
    Render and play one spoken response, one chunk at a time.

    While a chunk plays, the next one renders. Playback of a chunk is waited
    on only when the next chunk is ready to take its place.
    """

    global stop_requested

    stop_requested = False

    text = normalize_punctuation(req.text)
    chunks = split_into_chunks(text, CHUNK_MIN_WORDS)
    started = time.time()
    render_total = 0.0

    for number, chunk in enumerate(chunks, start=1):
        if stop_requested:
            break

        render_started = time.time()
        wav = render_speech(chunk, req.voice_prompt if number == 1 else None)
        render_seconds = time.time() - render_started
        render_total += render_seconds

        words = len(chunk.split())
        print(f"chunk {number}/{len(chunks)}: {words} words, "
              f"{render_seconds:.2f}s render, {render_seconds / words:.2f}s/word")

        sd.wait()  # the previous chunk finishes before this one starts

        if stop_requested:
            break

        if number == 1:
            print(f"first sound after {time.time() - started:.2f}s")

            try:
                httpx.post(f"{HUB_URL}/playback_start", timeout=1.0)
            except Exception:
                pass  # the hub being briefly unavailable shouldn't hold up playback

        start_playing(wav)

    sd.wait()

    words = len(text.split())
    print(f"{words} words, {render_total:.2f}s render, {render_total / words:.2f}s/word")

    return {"ok": True, "elapsed": render_total, "words": words}


# ─── Main ────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=PORT)
