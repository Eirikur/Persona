"""Shared pieces for the TTS benchmark scripts (tts_bench_*.py).

Each engine script loads its model, prepares Sal's voice sample once, and
hands run_benchmark() a function that turns text into audio. This file renders
the same reply twice, whole and in chunks, times it, saves both as WAV files
for listening, and prints one summary per mode.

Nothing here touches the running Persona services.
"""

import sys
import time
from pathlib import Path

import numpy as np
import soundfile as sf

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from persona_text_chunks import split_into_chunks


# ─── Settings ────────────────────────────────────────────────────────────────

# The same 49-word reply used to measure the chunked speech service on
# 2026-09-26 (first sound 23.85 s whole, 5.45 s chunked).
TEXT = (
    "Sure, I can explain that. The hub receives your speech, decides where it "
    "should go, and hands the reply to the speech service. That service renders "
    "it with Chatterbox, which is slower than real time on this machine. So a "
    "long answer takes a while before you hear anything."
)

VOICE_SAMPLE = REPO / "audio" / "bird-dream.wav"
OUTPUT_DIR   = Path.home() / "tts-bench"

# Keep in step with CHUNK_MIN_WORDS in persona_speech_output.py.
CHUNK_MIN_WORDS = 4


# ─── Playback simulation ─────────────────────────────────────────────────────

def simulate_playback(render_seconds: list[float], audio_seconds: list[float]) -> tuple:
    """
    Work out when sound starts, how much silence follows, and when it ends.

    Chunks render one after another. A chunk plays as soon as it is rendered
    and the previous chunk has finished, which is how the speech service
    behaves. Returns (first_sound, silence_after_first_sound, finished).
    """

    rendered_at = 0.0
    play_ends   = 0.0
    silence     = 0.0
    first_sound = 0.0

    for number, (render, audio) in enumerate(zip(render_seconds, audio_seconds)):
        rendered_at = rendered_at + render

        if number == 0:
            first_sound = rendered_at
            play_start  = rendered_at
        else:
            play_start = max(rendered_at, play_ends)
            silence    = silence + (play_start - play_ends)

        play_ends = play_start + audio

    return first_sound, silence, play_ends


# ─── Benchmark ───────────────────────────────────────────────────────────────

def render_mode(engine_name: str, mode: str, chunks: list[str], render, sample_rate: int) -> None:
    """Render the chunks in order, print a summary, and save the joined audio."""

    render_seconds = []
    audio_seconds  = []
    pieces         = []

    for chunk in chunks:
        started = time.time()
        audio   = np.asarray(render(chunk), dtype=np.float32).reshape(-1)

        render_seconds.append(time.time() - started)
        audio_seconds.append(len(audio) / sample_rate)
        pieces.append(audio)

    first_sound, silence, finished = simulate_playback(render_seconds, audio_seconds)
    rendering = sum(render_seconds)
    speech    = sum(audio_seconds)
    words     = len(TEXT.split())

    print("  " + mode + ":  " + str(len(chunks)) + " chunk(s)")
    print("    first sound      " + f"{first_sound:6.2f} s")
    print("    silence after    " + f"{silence:6.2f} s   (gaps between chunks)")
    print("    request to done  " + f"{finished:6.2f} s")
    print("    render           " + f"{rendering:6.2f} s   ({rendering / words:.2f} s/word, "
          + f"{rendering / speech:.2f}x the speech length)")
    print("    speech length    " + f"{speech:6.2f} s")

    folder = OUTPUT_DIR / engine_name
    folder.mkdir(parents=True, exist_ok=True)
    sf.write(str(folder / (mode + ".wav")), np.concatenate(pieces), sample_rate)


def run_benchmark(engine_name: str, render, sample_rate: int) -> None:
    """
    Time one engine on the reply, whole and then chunked.

    render(text) must return the audio for that text as a float array. The
    voice sample must already be prepared by the caller. One short throwaway
    render comes first so first-call setup cost is not counted.
    """

    print("\n=== " + engine_name + " ===")

    started = time.time()
    render("Warming up.")
    print("  warm-up render (not counted): " + f"{time.time() - started:.2f} s")

    render_mode(engine_name, "whole",   [TEXT], render, sample_rate)
    render_mode(engine_name, "chunked", split_into_chunks(TEXT, CHUNK_MIN_WORDS), render, sample_rate)

    print("\n  WAVs to listen to: " + str(OUTPUT_DIR / engine_name) + "/")
