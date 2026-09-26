#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11,<3.12"
# dependencies = [
#    "setuptools<81",
#    "numpy",
#    "soundfile",
#    "torch",
#    "torchaudio",
#    "coqui-tts[codec]",
#    "transformers>=4.57,<5",
# ]
# ///

"""Benchmark Coqui XTTS-v2 (Idiap's maintained fork, CPU) cloning Sal's sample.

The first run downloads the model and asks you to accept Coqui's license
(CPML, non-commercial use only). Run it yourself so the question can reach
you: `! ./tests/tts_bench_coqui.py`. This script does not accept it for you.
"""

import time

from tts_bench_common import VOICE_SAMPLE, run_benchmark


# ─── Load and prepare ────────────────────────────────────────────────────────

from TTS.api import TTS

print("Loading XTTS-v2 on CPU...")
api = TTS("tts_models/multilingual/multi-dataset/xtts_v2").to("cpu")
xtts = api.synthesizer.tts_model

started = time.time()
gpt_cond_latent, speaker_embedding = xtts.get_conditioning_latents(audio_path=[str(VOICE_SAMPLE)])
print("Voice sample prepared once in " + f"{time.time() - started:.2f} s")


def render(text: str):
    """Render text in the prepared voice."""

    result = xtts.inference(text, "en", gpt_cond_latent, speaker_embedding)

    return result["wav"]


# ─── Run ─────────────────────────────────────────────────────────────────────

run_benchmark("coqui-xtts", render, 24000)
