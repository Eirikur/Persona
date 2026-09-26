#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11,<3.12"
# dependencies = [
#    "setuptools<81",
#    "numpy",
#    "soundfile",
#    "torch",
#    "pocket-tts",
# ]
# ///

"""Benchmark Kyutai's PocketTTS (small English model, CPU) cloning Sal's sample.

Voice cloning needs Kyutai's gated weights on Hugging Face. If cloning is not
available yet, this script says so and measures speed with the built-in
"alba" voice instead, which does not tell you anything about the sound of
Sal's voice.
"""

import time

from tts_bench_common import VOICE_SAMPLE, run_benchmark


# ─── Load and prepare ────────────────────────────────────────────────────────

from pocket_tts import TTSModel

print("Loading PocketTTS on CPU...")
model = TTSModel.load_model()

started = time.time()

try:
    voice_state = model.get_state_for_audio_prompt(str(VOICE_SAMPLE))
    print("Voice sample prepared once in " + f"{time.time() - started:.2f} s")
except Exception as problem:
    print("!! CLONING NOT AVAILABLE: " + str(problem))
    print("!! Falling back to the built-in 'alba' voice. Speed only, not Sal's sound.")
    voice_state = model.get_state_for_audio_prompt("alba")


def render(text: str):
    """Render text in the prepared voice."""

    return model.generate_audio(voice_state, text).numpy()


# ─── Run ─────────────────────────────────────────────────────────────────────

run_benchmark("pocket-tts", render, model.sample_rate)
