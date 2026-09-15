"""Microphone proof-of-life indicator.

Adapted from the prototype at github.com/Eirikur/microphone-activity-indicator
(written by Perplexity from a spec). Runs its own audio input stream --
separate from RealtimeSTT's -- and posts a calm, smoothed 0..1 brightness
value to the hub, which relays it over SSE to drive the HEARING label's
flicker in the chat UI. If no input device is available, it just disables
itself; it never affects STT.
"""

import math
import threading
import time
from dataclasses import dataclass

import httpx
import numpy as np
import sounddevice as sd


EPSILON = 1e-12


# ─── Brightness Model ─────────────────────────────────────────────────────────

@dataclass
class IndicatorConfig:
    window_ms:        float = 100.0   # audio analysis window
    threshold_db:     float = -48.0   # RMS at/below this stays dark
    dynamic_range_db: float = 28.0    # dB above threshold that reaches full brightness
    gamma:            float = 1.8     # >1 makes room noise less visible, speech still registers
    attack_ms:        float = 65.0    # fast rise so speech visibly registers
    release_ms:       float = 450.0   # slow fall so it doesn't flicker between words
    post_hz:          float = 10.0    # how often to post an update to the hub


class CalmMicIndicator:
    """Smoothed 0..1 brightness from raw audio, calm enough not to flicker on room noise."""

    def __init__(self, config: IndicatorConfig) -> None:
        self.config     = config
        self.brightness = 0.0

    def update(self, samples: np.ndarray, dt_s: float) -> float:
        """Feed one block of audio samples, return the updated brightness."""
        x = np.asarray(samples, dtype=np.float32)
        if x.ndim > 1:
            x = np.mean(x, axis=1)

        rms  = float(np.sqrt(np.mean(np.square(x), dtype=np.float64)))
        dbfs = 20.0 * math.log10(max(rms, EPSILON))

        cfg    = self.config
        target = (dbfs - cfg.threshold_db) / cfg.dynamic_range_db
        target = float(np.clip(target, 0.0, 1.0)) ** cfg.gamma

        time_constant_ms = cfg.attack_ms if target > self.brightness else cfg.release_ms
        tau_s = max(time_constant_ms / 1000.0, 0.001)
        alpha = 1.0 - math.exp(-dt_s / tau_s)

        self.brightness += alpha * (target - self.brightness)
        self.brightness = float(np.clip(self.brightness, 0.0, 1.0))
        return self.brightness


# ─── Background Loop ──────────────────────────────────────────────────────────

def run_mic_indicator(hub_url: str) -> None:
    """
    Read the default microphone, compute a calm brightness value, and post it
    to the hub. Meant to run in its own daemon thread for the life of the
    speech-input service.
    """
    config    = IndicatorConfig()
    indicator = CalmMicIndicator(config)
    state     = {"brightness": 0.0}

    try:
        device_info = sd.query_devices(kind="input")
        sample_rate = int(device_info["default_samplerate"])
    except Exception as e:
        print(f"Mic indicator disabled (no input device): {e}")
        return

    blocksize       = max(1, round(sample_rate * config.window_ms / 1000.0))
    actual_window_s = blocksize / sample_rate

    def callback(indata, frames, time_info, status):
        # Keep this fast -- no network I/O here. The post loop below reads
        # the value on its own schedule.
        state["brightness"] = indicator.update(indata, actual_window_s)

    def post_loop():
        last_posted = None
        post_period = 1.0 / config.post_hz
        while True:
            time.sleep(post_period)
            rounded = round(state["brightness"], 2)
            if rounded == last_posted:
                continue
            last_posted = rounded
            try:
                httpx.post(f"{hub_url}/mic_level/{rounded}", timeout=1.0)
            except Exception:
                pass  # the hub being briefly unavailable shouldn't matter here

    threading.Thread(target=post_loop, daemon=True).start()

    try:
        with sd.InputStream(
            samplerate=sample_rate,
            blocksize=blocksize,
            channels=1,
            dtype="float32",
            callback=callback,
        ):
            while True:
                time.sleep(3600)
    except Exception as e:
        print(f"Mic indicator stopped: {e}")
