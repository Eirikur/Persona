"""Kokoro voices for the speech output service.

A Kokoro voice is written as a plain string starting with "kokoro:".
After the prefix come one or more voice names, each with an optional weight:

    kokoro:af_bella
    kokoro:af_bella=0.6,am_adam=0.4

Several voices are blended into one by a weighted average of their voice
tensors. Weights need not add up to 1; they are scaled to do so.
Voice names start with a language letter: a is American English,
b is British English (af_ / am_ are American female / male, bf_ / bm_ British).
"""

import numpy as np
from kokoro import KPipeline


# ─── Settings ────────────────────────────────────────────────────────────────

PREFIX      = "kokoro:"
SAMPLE_RATE = 24000
REPO_ID     = "hexgrad/Kokoro-82M"

# One loaded pipeline per language letter, filled in as voices need them.
PIPELINES = {}

# One blended voice tensor per voice string, so each blend is made only once.
BLENDS = {}


# ─── Voice Strings ───────────────────────────────────────────────────────────

def is_kokoro(voice_prompt: str) -> bool:
    """True if a voice string names a Kokoro voice rather than a PocketTTS one."""

    return voice_prompt.startswith(PREFIX)


def parse_voice(voice_prompt: str) -> list:
    """Turn "kokoro:af_bella=0.6,am_adam=0.4" into [("af_bella", 0.6), ("am_adam", 0.4)]."""

    spec  = voice_prompt[len(PREFIX):]
    parts = []

    for piece in spec.split(","):
        piece = piece.strip()

        if not piece:
            continue

        if "=" in piece:
            name, weight = piece.split("=", 1)
            parts.append((name.strip(), float(weight)))
        else:
            parts.append((piece, 1.0))

    if not parts:
        raise ValueError("Kokoro voice has no voice names: " + voice_prompt)

    return parts


# ─── Rendering ───────────────────────────────────────────────────────────────

def pipeline_for(language: str):
    """Return the Kokoro pipeline for a language letter, loading it once."""

    if language not in PIPELINES:
        PIPELINES[language] = KPipeline(lang_code=language, repo_id=REPO_ID)

    return PIPELINES[language]


def blend_for(voice_prompt: str, pipeline):
    """Return the voice tensor for a voice string, blending several voices if asked."""

    if voice_prompt not in BLENDS:
        parts        = parse_voice(voice_prompt)
        total_weight = sum(weight for name, weight in parts)
        blend        = None

        for name, weight in parts:
            tensor = pipeline.load_voice(name) * (weight / total_weight)
            blend  = tensor if blend is None else blend + tensor

        BLENDS[voice_prompt] = blend

    return BLENDS[voice_prompt]


def render(text: str, voice_prompt: str):
    """Render text in a Kokoro voice and return the audio as one float array."""

    parts    = parse_voice(voice_prompt)
    language = parts[0][0][0]
    pipeline = pipeline_for(language)
    voice    = blend_for(voice_prompt, pipeline)

    pieces = []
    for graphemes, phonemes, audio in pipeline(text, voice=voice):
        pieces.append(audio.numpy())

    return np.concatenate(pieces)
