#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11,<3.12"
# dependencies = [
#    "setuptools<81",
#    "numpy",
#    "sounddevice",
#    "soundfile",
#    "torch",
#    "torchaudio",
#    "coqui-tts[codec]",
#    "transformers>=4.57,<5",
# ]
# ///

"""Audition Coqui XTTS-v2 voices through the default audio output.

    tests/tts_audition_coqui.py                          type voices at a prompt
    tests/tts_audition_coqui.py --all                    every built-in speaker, in order
    tests/tts_audition_coqui.py "Claribel Dervla" "Andrew Chipper"    only these
    tests/tts_audition_coqui.py "Claribel Dervla=0.6,Andrew Chipper=0.4"    a blend
    tests/tts_audition_coqui.py audio/dropped/echo.wav   clone from a sample

At the prompt, type a speaker, a blend or a .wav path and press Enter to hear
it; an empty line quits. "list" shows the speaker names. The "coqui:" prefix is
optional. Each voice says its own name, then a sentence. Assign what you like
with "system voice <persona> coqui:<speaker>".

XTTS renders on the CPU, slower than real time, so expect a wait before each
voice. Runs on its own and does not touch the Persona services.
"""

import sys
import time
from pathlib import Path

import sounddevice as sd

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

import persona_coqui


# ─── Settings ────────────────────────────────────────────────────────────────

SENTENCE      = "I can be one of the voices in your room. How does this sound?"
PAUSE_BETWEEN = 0.8     # seconds of quiet after each voice


# ─── Play ────────────────────────────────────────────────────────────────────

def spoken_name(voice_prompt: str) -> str:
    """How a voice introduces itself: speaker names joined with "and", or "a cloned voice" for a sample file."""

    if voice_prompt.endswith(".wav"):
        return "a cloned voice"

    return " and ".join(name for name, weight in persona_coqui.parse_voice(voice_prompt))


def say_in_voice(entry: str) -> None:
    """Render the voice's name and the test sentence, then play and wait."""

    voice_prompt = entry if entry.startswith(persona_coqui.PREFIX) else persona_coqui.PREFIX + entry
    text         = "This is " + spoken_name(voice_prompt) + ". " + SENTENCE

    audio = persona_coqui.render(text, voice_prompt)

    sd.play(audio, persona_coqui.SAMPLE_RATE)
    sd.wait()


def play_each(entries: list) -> None:
    """Play every entry in order, with a pause between."""

    for number, entry in enumerate(entries, start=1):
        print(f"{number}/{len(entries)}  {entry}")
        say_in_voice(entry)
        time.sleep(PAUSE_BETWEEN)


def prompt_loop() -> None:
    """Ask for voices one at a time and play each until an empty line."""

    print('Type a speaker, blend or .wav path. "list" shows names; empty line quits.')

    while True:
        entry = input("voice> ").strip()

        if not entry:
            return

        if entry == "list":
            print(", ".join(persona_coqui.speaker_names()))
            continue

        try:
            say_in_voice(entry)
        except Exception as problem:
            print("Could not play that: " + str(problem))


# ─── Main ────────────────────────────────────────────────────────────────────

arguments = sys.argv[1:]

try:
    if arguments == ["--all"]:
        play_each(persona_coqui.speaker_names())
    elif arguments:
        play_each(arguments)
    else:
        prompt_loop()
except (KeyboardInterrupt, EOFError):
    sd.stop()
    print("Stopped.")
