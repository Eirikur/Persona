#!/usr/bin/env -S uv run --script
"""Speech-to-text comparison: run every clip of the recorded test set through
one or more Whisper models and report word errors and delays for each.

The clips are real sentences in the owner's voice and room, recorded with
tests/stt_corpus_record.py, each with a .txt file of what it should say.
Clips with an empty .txt are room noise only: the right result is no words,
and any words heard there are counted as invented.

Runs its own recorder (no microphone, no hub), with production's settings
except for the model, so it is safe to run while the live services are up.
The live speech-input service shares the CPU, so delays are a little slower
while it is busy.

Usage:
  ./persona_stt_compare.py [model ...]

With no models named, compares large-v3-turbo, medium.en and small.en.
Results are printed and saved to tests/stt_corpus_results/<timestamp>.json.

The model files must already be downloaded. Most are under
~/.cache/huggingface, so run it as:
  HF_HOME=~/.cache/huggingface HF_HUB_OFFLINE=1 ./persona_stt_compare.py
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

import json
import logging
import statistics
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

# Importing the check first is deliberate: through persona_speech_input it
# sets OMP_NUM_THREADS before torch loads, and it brings production's
# settings and the word-comparison code, so this file keeps no copy of them.
import persona_stt_check as check
from persona_speech_input import (
    SILENCE_DURATION, SILERO_SENSITIVITY, WAKE_WORD_PROMPT, _detect_device,
)

import numpy as np
import soundfile as sf
from RealtimeSTT import AudioToTextRecorder


# ─── Configuration ────────────────────────────────────────────────────────────

REPO_DIR    = Path(__file__).parent
CORPUS_DIR  = REPO_DIR / "tests" / "stt_corpus"
RESULTS_DIR = REPO_DIR / "tests" / "stt_corpus_results"

DEFAULT_MODELS = ("large-v3-turbo", "medium.en", "small.en")

# How long to wait for text after a clip has finished playing. Room-noise
# clips often never open a recording at all, so without a limit the wait
# would last forever. Real speech returns well inside this.
GIVE_UP_AFTER = 10.0   # seconds


# ─── Clips ────────────────────────────────────────────────────────────────────

def load_corpus():
    """
    Every recorded clip, in order, as a list of (name, samples, reference text).
    Samples are 16 kHz mono 16-bit, the way the recognizer wants them.
    """
    clips = []

    for wav_path in sorted(CORPUS_DIR.glob("*.wav")):
        text_path = wav_path.with_suffix(".txt")
        if not text_path.exists():
            continue

        data, rate = sf.read(wav_path, dtype="float32")
        if rate != check.SAMPLE_RATE:
            sys.exit(f"{wav_path.name} is {rate} Hz; expected {check.SAMPLE_RATE} Hz")

        if data.ndim > 1:
            data = data.mean(axis=1)

        samples = (np.clip(data, -1, 1) * 32767).astype(np.int16)
        clips.append((wav_path.stem, samples, text_path.read_text().strip()))

    return clips


# ─── One Clip ─────────────────────────────────────────────────────────────────

def run_clip(rec, samples):
    """
    Play one clip into the recorder. Returns (what was heard, how many pieces
    it came back in, endpoint seconds, decode seconds).

    A long pause inside a sentence can make the recorder decide the speaker
    has finished, so one clip may come back as several pieces -- live, each
    piece would be a separate turn. The pieces are joined and counted.

    If nothing comes back within GIVE_UP_AFTER seconds of the clip ending,
    the recorder is told to stop waiting: no recording, no delays.
    """
    check.marks.clear()
    stop = threading.Event()

    threading.Thread(target=check.feed_clip, args=(rec, samples, check.marks, stop),
                     daemon=True).start()

    clip_seconds = len(samples) / check.SAMPLE_RATE
    gave_up      = threading.Event()

    def give_up():
        """Watchdog: if text() is still waiting long after the clip, abort it."""
        gave_up.set()
        rec.abort()

    watchdog = threading.Timer(clip_seconds + GIVE_UP_AFTER, give_up)
    watchdog.start()

    # Keep asking for text until a piece arrives after the clip has finished
    # playing (or the watchdog gives up). Usually that is the first piece.
    pieces = []

    while True:
        piece    = rec.text() or ""
        returned = time.monotonic()

        if piece:
            pieces.append(piece)

        if gave_up.is_set() or "speech_end" in check.marks:
            break

    watchdog.cancel()
    stop.set()

    heard = " ".join(pieces)

    if gave_up.is_set() or "recording_stop" not in check.marks:
        return heard, len(pieces), None, None

    endpoint = check.marks["recording_stop"] - check.marks["speech_end"]
    decode   = returned - check.marks["recording_stop"]

    return heard, len(pieces), endpoint, decode


# ─── One Model ────────────────────────────────────────────────────────────────

def run_model(model, clips):
    """Load one model, play every clip through it, print a line per clip. Returns the results."""
    device, compute_type = _detect_device()
    print(f"\n── {model} ({device}, {compute_type}) " + "─" * 40, flush=True)

    rec = AudioToTextRecorder(
        model=model,
        device=device,
        compute_type=compute_type,
        spinner=False,
        level=logging.WARNING,
        no_log_file=True,
        post_speech_silence_duration=SILENCE_DURATION,
        enable_realtime_transcription=True,
        use_microphone=False,
        silero_sensitivity=SILERO_SENSITIVITY,
        initial_prompt=WAKE_WORD_PROMPT,
        initial_prompt_realtime=WAKE_WORD_PROMPT,
        on_recording_stop=check.note_recording_stop,
    )

    results = []

    for name, samples, reference in clips:
        heard, pieces, endpoint, decode = run_clip(rec, samples)

        reference_words = len(check.normalize_words(reference))
        heard_words     = len(check.normalize_words(heard))

        if reference:
            errors = round(check.word_error_rate(reference, heard) * reference_words)
        else:
            errors = heard_words   # room noise: every word heard was invented

        if decode is None:
            timing = "no recording"
        else:
            timing = f"decode {decode:4.2f}s"

        if pieces > 1:
            timing = timing + f", SPLIT IN {pieces}"

        print(f"  {name:<38} {errors:2d} wrong   {timing:<14} heard {heard!r}", flush=True)

        results.append({
            "clip":            name,
            "reference":       reference,
            "heard":           heard,
            "pieces":          pieces,
            "reference_words": reference_words,
            "errors":          errors,
            "endpoint":        endpoint,
            "decode":          decode,
        })

        time.sleep(1.0)

    # RealtimeSTT logs harmless tracebacks while closing down; see persona_stt_check.py.
    logging.disable(logging.CRITICAL)
    rec.shutdown()
    logging.disable(logging.NOTSET)

    return results


# ─── Summary ──────────────────────────────────────────────────────────────────

def summarize(model, results):
    """One line for one model: word errors on speech, words invented on noise, typical decode."""
    speech = [r for r in results if r["reference"]]
    noise  = [r for r in results if not r["reference"]]

    wrong    = sum(r["errors"] for r in speech)
    total    = sum(r["reference_words"] for r in speech)
    invented = sum(r["errors"] for r in noise)

    decodes = [r["decode"] for r in speech if r["decode"] is not None]
    if decodes:
        decode_text = f"median decode {statistics.median(decodes):.2f}s, worst {max(decodes):.2f}s"
    else:
        decode_text = "no decodes"

    return (f"  {model:<16} {wrong:3d} of {total} words wrong   "
            f"{invented:2d} invented on noise   {decode_text}")


# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    """Compare the named models (or the defaults) over the whole recorded test set."""
    models = sys.argv[1:] or list(DEFAULT_MODELS)
    clips  = load_corpus()

    if not clips:
        sys.exit(f"No clips in {CORPUS_DIR}. Record some with tests/stt_corpus_record.py")

    print(f"{len(clips)} clips, models: {', '.join(models)}", flush=True)

    all_results = {}
    for model in models:
        all_results[model] = run_model(model, clips)

    print("\nSummary")
    for model in models:
        print(summarize(model, all_results[model]))

    RESULTS_DIR.mkdir(exist_ok=True)
    stamp    = datetime.now().strftime("%Y-%m-%d-%H%M%S")
    out_path = RESULTS_DIR / (stamp + ".json")
    out_path.write_text(json.dumps(all_results, indent=2))
    print(f"\nSaved {out_path}")


if __name__ == "__main__":
    main()
