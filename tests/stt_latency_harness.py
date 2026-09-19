"""A/B latency harness: same clip, production settings, prints per-round latency.

Feeds the clip at real-time pace (works on 0.3.94 and 1.1.2 alike), then keeps
feeding silence until text() returns. Latency = last-speech-chunk fed ->
text() returned.
"""
import sys
import threading
import time
import logging
import importlib.metadata as md

import numpy as np
import soundfile as sf
from RealtimeSTT import AudioToTextRecorder

CLIP = "/home/eh/Proj/Persona/tests/test_speech.wav"
PROMPT = "Salice, pronounced sa-LEECE and often shortened to Sal, is a helpful voice assistant."
CHUNK = 512  # samples, 32 ms at 16 kHz


def feeder(rec, pcm, marks, stop):
    """Feed the clip in real time, note when speech ended, then feed silence."""
    silence = np.zeros(CHUNK, dtype=np.int16).tobytes()
    started = time.monotonic()
    fed = 0
    for i in range(0, len(pcm), CHUNK):
        chunk = pcm[i:i + CHUNK]
        if len(chunk) < CHUNK:
            chunk = np.concatenate([chunk, np.zeros(CHUNK - len(chunk), dtype=np.int16)])
        rec.feed_audio(chunk.tobytes())
        fed += CHUNK
        wait = started + fed / 16000.0 - time.monotonic()
        if wait > 0:
            time.sleep(wait)
    marks["speech_end"] = time.monotonic()
    while not stop.is_set():
        rec.feed_audio(silence)
        fed += CHUNK
        wait = started + fed / 16000.0 - time.monotonic()
        if wait > 0:
            time.sleep(wait)


if __name__ == "__main__":
    label = sys.argv[1]
    rounds = int(sys.argv[2]) if len(sys.argv) > 2 else 3

    data, rate = sf.read(CLIP, dtype="float32")
    if data.ndim > 1:
        data = data.mean(axis=1)
    pcm = (np.clip(data, -1, 1) * 32767).astype(np.int16)

    print(f"[{label}] RealtimeSTT={md.version('realtimestt')} faster-whisper={md.version('faster-whisper')} "
          f"ctranslate2={md.version('ctranslate2')} python={sys.version.split()[0]}", flush=True)

    t0 = time.monotonic()
    rec = AudioToTextRecorder(
        model="large-v3-turbo", device="cpu", compute_type="int8",
        spinner=False, level=logging.WARNING, no_log_file=True,
        post_speech_silence_duration=0.6, enable_realtime_transcription=True,
        use_microphone=False, silero_sensitivity=0.4,
        initial_prompt=PROMPT, initial_prompt_realtime=PROMPT,
    )
    print(f"[{label}] model load {time.monotonic() - t0:.1f}s", flush=True)

    for n in range(1, rounds + 1):
        marks, stop = {}, threading.Event()
        threading.Thread(target=feeder, args=(rec, pcm, marks, stop), daemon=True).start()
        text = rec.text()
        returned = time.monotonic()
        stop.set()
        latency = returned - marks["speech_end"]
        print(f"[{label}] round {n}: latency after end of speech = {latency:.2f}s  text={text!r}", flush=True)
        time.sleep(1.0)

    rec.shutdown()
