#!/usr/bin/env -S uv run --script
"""Speech-to-text check: play a known clip into the recognizer, compare what
it heard with what the clip says, and time how long it took after the speech
ended.

Runs its own recorder (no microphone, no hub), so it is safe to run while the
live services are up. Timings will be a little slower if they are busy at the
same moment.

Usage: ./persona_stt_check.py [rounds]

Exit code: 0 = every round matched, 1 = a round misheard, 2 = no reference text.

The last line, "SAY: ...", is a short spoken version of the result. When this runs
from the hub's script runner (persona_scripts.py), the persona says it aloud.
"""
# /// script
# requires-python = "==3.12.*"
# dependencies = [
#    "setuptools<81",
#    "fastapi",
#    "uvicorn",
#    "httpx",
#    "faster-whisper",
#    "torch",
#    "numpy",
#    "scipy",
#    "sounddevice",
#    "soundfile",
#    "torchaudio",
#    "pyaudio",
#    "openwakeword",
#    "pvporcupine",
#    "RealtimeSTT>=1.1.2",
#    "halo",
#    "nvidia-cublas-cu12",
#    "nvidia-cudnn-cu12",
# ]
# ///

import logging
import os
import re
import statistics
import sys
import threading
import time

# Importing the service first is deliberate: it sets OMP_NUM_THREADS before
# torch and ctranslate2 load, so this check runs with production's thread
# count. It also gives us the production model, silence and prompt settings,
# so this file never keeps its own copy of them.
from persona_speech_input import STT_MODEL, SILENCE_DURATION, WAKE_WORD_PROMPT, _detect_device

import numpy as np
import soundfile as sf
from RealtimeSTT import AudioToTextRecorder


# ─── Configuration ────────────────────────────────────────────────────────────

REPO_DIR       = os.path.dirname(os.path.abspath(__file__))
CLIP_FILE      = os.path.join(REPO_DIR, "tests", "test_speech.wav")
REFERENCE_FILE = os.path.join(REPO_DIR, "tests", "test_speech.txt")

SAMPLE_RATE = 16000
CHUNK       = 512    # samples per feed, 32 ms at 16 kHz

# Fraction of reference words that may be wrong, missing or extra.
# 0.2 tolerates one slip in a five-word clip.
MAX_WORD_ERROR_RATE = 0.2


# ─── Comparing Text ───────────────────────────────────────────────────────────

def normalize_words(text):
    """Lower-case the text, drop punctuation, and split it into words."""
    not_a_word = r"[^a-z0-9' ]+"
    cleaned    = re.sub(not_a_word, " ", text.lower())

    return cleaned.split()


def word_error_rate(reference, heard):
    """
    Word-level edit distance between the two texts, divided by the number of
    words in the reference. 0.0 is a perfect match; 0.2 is one wrong word in
    five. Case and punctuation are ignored.
    """
    reference_words = normalize_words(reference)
    heard_words     = normalize_words(heard)

    # previous[j] = edits needed to turn the reference words seen so far
    # into the first j heard words.
    previous = list(range(len(heard_words) + 1))

    for i, reference_word in enumerate(reference_words, start=1):
        current = [i]

        for j, heard_word in enumerate(heard_words, start=1):
            if reference_word == heard_word:
                swap_cost = 0
            else:
                swap_cost = 1

            current.append(min(
                previous[j] + 1,              # reference word missing from heard
                current[j - 1] + 1,           # extra word heard
                previous[j - 1] + swap_cost,  # same word, or a wrong one
            ))

        previous = current

    return previous[len(heard_words)] / max(len(reference_words), 1)


def spoken_summary(passed, median):
    """The short result the persona says aloud after the run. Kept brief: every word costs render time."""
    if passed:
        return f"Recognition check passed. Median delay {median:.1f} seconds."

    return "Recognition check failed. The words heard did not match."


# ─── Feeding the Clip ─────────────────────────────────────────────────────────

def load_clip():
    """Read the test clip as 16 kHz mono 16-bit samples, the way the recognizer wants them."""
    data, rate = sf.read(CLIP_FILE, dtype="float32")

    if rate != SAMPLE_RATE:
        sys.exit(f"{CLIP_FILE} is {rate} Hz; this check expects {SAMPLE_RATE} Hz")

    if data.ndim > 1:
        data = data.mean(axis=1)

    return (np.clip(data, -1, 1) * 32767).astype(np.int16)


def feed_clip(rec, pcm, marks, stop):
    """
    Feed the clip in real time, note when the speech ended, then keep feeding
    silence until told to stop. RealtimeSTT 1.1.x discards audio that arrives
    faster than real time, so every chunk waits for its moment.
    """
    silence = np.zeros(CHUNK, dtype=np.int16)
    started = time.monotonic()
    fed     = 0

    for i in range(0, len(pcm), CHUNK):
        chunk = pcm[i:i + CHUNK]

        if len(chunk) < CHUNK:
            chunk = np.concatenate([chunk, np.zeros(CHUNK - len(chunk), dtype=np.int16)])

        rec.feed_audio(chunk.tobytes())
        fed += CHUNK

        wait = started + fed / SAMPLE_RATE - time.monotonic()
        if wait > 0:
            time.sleep(wait)

    marks["speech_end"] = time.monotonic()

    while not stop.is_set():
        rec.feed_audio(silence.tobytes())
        fed += CHUNK

        wait = started + fed / SAMPLE_RATE - time.monotonic()
        if wait > 0:
            time.sleep(wait)


# ─── One Round ────────────────────────────────────────────────────────────────

def run_round(rec, pcm):
    """Play the clip once. Returns (what was heard, seconds from end of speech to text)."""
    marks = {}
    stop  = threading.Event()

    threading.Thread(target=feed_clip, args=(rec, pcm, marks, stop), daemon=True).start()

    heard    = rec.text()
    returned = time.monotonic()
    stop.set()

    return heard, returned - marks["speech_end"]


# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    """Load the recognizer, run the rounds, print one line per round and a verdict."""
    rounds = int(sys.argv[1]) if len(sys.argv) > 1 else 3
    pcm    = load_clip()

    reference = None
    if os.path.exists(REFERENCE_FILE):
        with open(REFERENCE_FILE) as f:
            reference = f.read().strip()

    device, compute_type = _detect_device()
    print(f"STT check: model={STT_MODEL} device={device} ({compute_type}) "
          f"threads={os.environ['OMP_NUM_THREADS']}", flush=True)

    loading_started = time.monotonic()
    rec = AudioToTextRecorder(
        model=STT_MODEL,
        device=device,
        compute_type=compute_type,
        spinner=False,
        level=logging.WARNING,
        no_log_file=True,
        post_speech_silence_duration=SILENCE_DURATION,
        enable_realtime_transcription=True,
        use_microphone=False,
        silero_sensitivity=0.4,
        initial_prompt=WAKE_WORD_PROMPT,
        initial_prompt_realtime=WAKE_WORD_PROMPT,
    )
    print(f"model load {time.monotonic() - loading_started:.1f}s", flush=True)

    error_rates = []
    latencies   = []

    for n in range(1, rounds + 1):
        heard, latency = run_round(rec, pcm)
        latencies.append(latency)

        if reference is None:
            print(f"round {n}: latency {latency:.2f}s  heard {heard!r}", flush=True)
        else:
            error_rate = word_error_rate(reference, heard)
            error_rates.append(error_rate)
            print(f"round {n}: latency {latency:.2f}s  word errors {error_rate:.2f}  "
                  f"heard {heard!r}", flush=True)

        time.sleep(1.0)

    # RealtimeSTT 1.1.2 logs harmless tracebacks while closing down (the
    # Whisper engine has no close method, and a pipe is read after it closes).
    # This script reports with print, so switching logging off hides only them.
    logging.disable(logging.CRITICAL)
    rec.shutdown()

    if reference is None:
        print(f"No reference text. Put what the clip says in {REFERENCE_FILE}")
        sys.exit(2)

    worst  = max(error_rates)
    median = statistics.median(latencies)

    if worst <= MAX_WORD_ERROR_RATE:
        verdict = "PASS"
    else:
        verdict = "FAIL"

    print(f"{verdict}: worst word errors {worst:.2f} (limit {MAX_WORD_ERROR_RATE}), "
          f"median latency {median:.2f}s")

    # The hub's script runner speaks this line once the script has exited.
    print("SAY: " + spoken_summary(verdict == "PASS", median))

    sys.exit(0 if verdict == "PASS" else 1)


if __name__ == "__main__":
    main()
