#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11,<3.12"
# dependencies = [
#    "setuptools<81",
#    "numpy",
#    "sounddevice",
#    "torch",
#    "kokoro>=0.9.4",
#    "transformers>=4.40",
# ]
# ///

"""Audition Kokoro voices and blends through the default audio output.

    tests/tts_audition_kokoro.py                       type voices at a prompt
    tests/tts_audition_kokoro.py --all                 every English voice, in order
    tests/tts_audition_kokoro.py af_bella am_adam      only these, in this order
    tests/tts_audition_kokoro.py af_bella=0.6,am_adam=0.4    a blend

At the prompt, type a voice or a blend and press Enter to hear it; an empty
line quits. "list" shows the voice names. The "kokoro:" prefix is optional.
Each voice says its own name, then a sentence. Assign what you like with
"system voice <persona> kokoro:<voice or blend>".

Voice names start with a language letter and a gender letter: af_ and am_ are
American female and male, bf_ and bm_ are British. Runs on its own and does not
touch the Persona services.
"""

import sys
import time
from pathlib import Path

import numpy as np
import sounddevice as sd

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

import persona_kokoro
from huggingface_hub import list_repo_files


# ─── Settings ────────────────────────────────────────────────────────────────

SENTENCE      = "I can be one of the voices in your room. How does this sound?"
PAUSE_BETWEEN = 0.8     # seconds of quiet after each voice
ENGLISH_STARTS = ("af_", "am_", "bf_", "bm_")


# ─── Voice names ─────────────────────────────────────────────────────────────

def english_voice_names() -> list:
    """The English voice names Kokoro offers, found by listing its model repository."""

    names = []

    for path in list_repo_files(persona_kokoro.REPO_ID):
        if path.startswith("voices/") and path.endswith(".pt"):
            name = path[len("voices/"):-len(".pt")]
            if name.startswith(ENGLISH_STARTS):
                names.append(name)

    return sorted(names)


def check_names(voice_prompt: str) -> None:
    """Raise ValueError naming any voice in the string that Kokoro does not offer."""

    known   = english_voice_names()
    unknown = [name for name, weight in persona_kokoro.parse_voice(voice_prompt) if name not in known]

    if unknown:
        raise ValueError("unknown voice " + ", ".join(unknown) + ' (type "list" to see names)')


def spoken_name(voice_prompt: str) -> str:
    """How a voice introduces itself: "af_bella=0.6,am_adam=0.4" becomes "af bella and am adam"."""

    names = [name.replace("_", " ") for name, weight in persona_kokoro.parse_voice(voice_prompt)]

    return " and ".join(names)


# ─── Play ────────────────────────────────────────────────────────────────────

def say_in_voice(entry: str) -> None:
    """Render the voice's name and the test sentence, then play and wait."""

    voice_prompt = entry if entry.startswith(persona_kokoro.PREFIX) else persona_kokoro.PREFIX + entry
    check_names(voice_prompt)

    text = "This is " + spoken_name(voice_prompt) + ". " + SENTENCE

    audio = persona_kokoro.render(text, voice_prompt)

    sd.play(audio, persona_kokoro.SAMPLE_RATE)
    sd.wait()


def play_each(entries: list) -> None:
    """Play every entry in order, with a pause between."""

    for number, entry in enumerate(entries, start=1):
        print(f"{number}/{len(entries)}  {entry}")
        say_in_voice(entry)
        time.sleep(PAUSE_BETWEEN)


def prompt_loop() -> None:
    """Ask for voices one at a time and play each until an empty line."""

    print('Type a voice or blend, e.g. af_bella=0.6,am_adam=0.4. "list" shows names; empty line quits.')

    while True:
        entry = input("voice> ").strip()

        if not entry:
            return

        if entry == "list":
            print(", ".join(english_voice_names()))
            continue

        try:
            say_in_voice(entry)
        except Exception as problem:
            print("Could not play that: " + str(problem))


# ─── Main ────────────────────────────────────────────────────────────────────

arguments = sys.argv[1:]

try:
    if arguments == ["--all"]:
        play_each(english_voice_names())
    elif arguments:
        play_each(arguments)
    else:
        prompt_loop()
except (KeyboardInterrupt, EOFError):
    sd.stop()
    print("Stopped.")
