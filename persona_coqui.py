"""Coqui XTTS-v2 voices for the speech output service.

A Coqui voice is written as a plain string starting with "coqui:". After the
prefix comes one of:

    coqui:Claribel Dervla                    a built-in speaker
    coqui:Claribel Dervla=0.6,Andrew Chipper=0.4    a weighted blend of speakers
    coqui:audio/dropped/echo.wav             clone a voice from a sample file

A string ending in ".wav" is a sample file; anything else is speaker names,
each with an optional weight. Weights need not add up to 1. Rendering runs on
the CPU and is slower than PocketTTS or Kokoro.
"""

import numpy as np
from TTS.api import TTS


# ─── Settings ────────────────────────────────────────────────────────────────

PREFIX      = "coqui:"
SAMPLE_RATE = 24000
MODEL_NAME  = "tts_models/multilingual/multi-dataset/xtts_v2"
LANGUAGE    = "en"

# The XTTS model, loaded the first time a Coqui voice is spoken.
MODEL = None

# One prepared (latent, embedding) pair per voice string, made only once.
CONDITIONING = {}


# ─── Voice Strings ───────────────────────────────────────────────────────────

def is_coqui(voice_prompt: str) -> bool:
    """True if a voice string names a Coqui voice."""

    return voice_prompt.startswith(PREFIX)


def parse_voice(voice_prompt: str) -> list:
    """Turn "coqui:Claribel Dervla=0.6,Andrew Chipper=0.4" into [("Claribel Dervla", 0.6), ("Andrew Chipper", 0.4)]."""

    spec  = voice_prompt[len(PREFIX):]
    parts = []

    for piece in spec.split(","):
        piece = piece.strip()

        if not piece:
            continue

        if "=" in piece:
            name, weight = piece.rsplit("=", 1)
            parts.append((name.strip(), float(weight)))
        else:
            parts.append((piece, 1.0))

    if not parts:
        raise ValueError("Coqui voice has no speaker names: " + voice_prompt)

    return parts


# ─── Rendering ───────────────────────────────────────────────────────────────

def load_model():
    """Return the XTTS model, loading it on first use."""

    global MODEL

    if MODEL is None:
        MODEL = TTS(MODEL_NAME).to("cpu").synthesizer.tts_model

    return MODEL


def speaker_names() -> list:
    """The names of XTTS's built-in speakers."""

    return list(load_model().speaker_manager.speakers)


def conditioning_for(voice_prompt: str):
    """Return the (gpt_cond_latent, speaker_embedding) pair for a voice string."""

    if voice_prompt in CONDITIONING:
        return CONDITIONING[voice_prompt]

    model = load_model()
    spec  = voice_prompt[len(PREFIX):].strip()

    if spec.endswith(".wav"):
        latent, embedding = model.get_conditioning_latents(audio_path=[spec])
    else:
        parts        = parse_voice(voice_prompt)
        total_weight = sum(weight for name, weight in parts)
        latent       = None
        embedding    = None

        for name, weight in parts:
            if name not in model.speaker_manager.speakers:
                raise ValueError("Unknown Coqui speaker: " + name)

            speaker = model.speaker_manager.speakers[name]
            scale   = weight / total_weight

            if latent is None:
                latent    = speaker["gpt_cond_latent"] * scale
                embedding = speaker["speaker_embedding"] * scale
            else:
                latent    = latent + speaker["gpt_cond_latent"] * scale
                embedding = embedding + speaker["speaker_embedding"] * scale

    CONDITIONING[voice_prompt] = (latent, embedding)

    return CONDITIONING[voice_prompt]


def render(text: str, voice_prompt: str):
    """Render text in a Coqui voice and return the audio as one float array."""

    latent, embedding = conditioning_for(voice_prompt)
    result            = load_model().inference(text, LANGUAGE, latent, embedding)

    return np.asarray(result["wav"], dtype=np.float32)
