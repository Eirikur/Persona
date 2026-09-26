#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11,<3.12"
# dependencies = [
#    "setuptools<81",
#    "numpy",
#    "soundfile",
#    "torch",
#    "torchaudio",
#    "chatterbox-tts>=0.1.5",
#    "resemble-perth",
# ]
#
# [tool.uv.extra-build-dependencies]
# pkuseg = ["numpy"]
# ///

"""Benchmark Chatterbox (standard model, CPU) as the baseline for the others.

Same settings as persona_speech_output.py. Stop the Persona speech services
first (systemctl --user stop persona-speech-out persona-speech-in) so they do
not compete for the CPU cores.
"""

import io
import time
import warnings
from contextlib import redirect_stderr, redirect_stdout

from tts_bench_common import VOICE_SAMPLE, run_benchmark

warnings.filterwarnings("ignore", category=UserWarning, module="perth")


# ─── Load and prepare ────────────────────────────────────────────────────────

from chatterbox.tts import ChatterboxTTS

print("Loading Chatterbox standard on CPU...")
model = ChatterboxTTS.from_pretrained(device="cpu")

started = time.time()
model.prepare_conditionals(str(VOICE_SAMPLE))
print("Voice sample prepared once in " + f"{time.time() - started:.2f} s")


def render(text: str):
    """Render text in the prepared voice, hiding the model's console noise."""

    sink = io.StringIO()

    with redirect_stderr(sink), redirect_stdout(sink):
        wav = model.generate(text)

    return wav.squeeze().cpu().numpy()


# ─── Run ─────────────────────────────────────────────────────────────────────

run_benchmark("chatterbox", render, model.sr)
