#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11,<3.12"
# dependencies = [
#    "setuptools<81",
#    "numpy",
#    "sounddevice",
#    "torch",
#    "pocket-tts",
# ]
# ///

"""Audition PocketTTS's built-in voices through the default audio output.

    tests/tts_audition_presets.py                 every preset, in order
    tests/tts_audition_presets.py george alba     only these, in this order

Each voice says its own name, then a sentence, so you can tell which one you
are hearing. Press Ctrl-C to stop. Names are the ones PRESET_VOICES lists in
persona_schemas.py; assign one with "system voice <persona> <name>".

Runs on its own and does not touch the Persona services, but it does use the
CPU, so expect the first voice to take a moment while the model loads.
"""

import sys
import time
from pathlib import Path

import numpy as np
import sounddevice as sd

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from persona_schemas import PRESET_VOICES
from pocket_tts import TTSModel


# ─── Settings ────────────────────────────────────────────────────────────────

SENTENCE      = "I can be one of the voices in your room. How does this sound?"
PAUSE_BETWEEN = 0.8     # seconds of quiet after each voice


# ─── Choose voices ───────────────────────────────────────────────────────────

names = sys.argv[1:] or list(PRESET_VOICES)

unknown = [name for name in names if name not in PRESET_VOICES]
if unknown:
    print("Unknown preset: " + ", ".join(unknown))
    print("Choices: " + ", ".join(PRESET_VOICES))
    sys.exit(1)


# ─── Load ────────────────────────────────────────────────────────────────────

print("Loading PocketTTS on CPU...")
model = TTSModel.load_model()


# ─── Play ────────────────────────────────────────────────────────────────────

def say_in_voice(name: str) -> None:
    """Render the voice's name and the test sentence, then play and wait."""

    state = model.get_state_for_audio_prompt(name)
    spoken_name = name.replace("_", " ")
    text = "This is " + spoken_name + ". " + SENTENCE

    wav = model.generate_audio(state, text)
    audio = np.asarray(wav, dtype=np.float32).reshape(-1)

    sd.play(audio, model.sample_rate)
    sd.wait()


try:
    for number, name in enumerate(names, start=1):
        print(f"{number}/{len(names)}  {name}")
        say_in_voice(name)
        time.sleep(PAUSE_BETWEEN)
except KeyboardInterrupt:
    sd.stop()
    print("Stopped.")
