#!/usr/bin/env -S uv run --script
"""Drives the ReSpeaker XVF3800's LED ring from the hub's SSE event stream.

Just another client of the hub's /events stream, the same one the chat UI
uses -- no new plumbing needed on the hub side. Needs raw USB access to the
ReSpeaker (vendor:product 2886:001a), which currently requires sudo. Vendor
protocol details live in xvf_host.py (vendored, untouched); nothing here
reimplements them.

Running: sudo uv run persona_led_ring.py
"""
# /// script
# requires-python = ">=3.9"
# dependencies = [
#    "pyusb",
#    "libusb_package",
#    "httpx",
# ]
# ///

import json
import time

import httpx

from xvf_host import find


HUB_URL = "http://127.0.0.1:8400"


# ─── State → Look ─────────────────────────────────────────────────────────────

# Effect codes, from xvf_host.py's PARAMETERS table:
#   0=off  1=breath  2=rainbow  3=single color  4=doa  5=ring
EFFECT_SINGLE = 3
EFFECT_BREATH = 1
EFFECT_DOA    = 4

# One look per pipeline state, colors and effects carried over from the
# hand-tuned trials in p.sh. LISTENING and TRANSCRIBING are static solid
# colors -- see BLINK_STATES below, which reissues them on mic activity.
# RESTING isn't a pipeline stage, just "nothing worth naming is happening" --
# it's what shows between turns, and again if a VAD-detected recording never
# turns into a transcript.
STATE_LOOKS = {
    "resting":      {"effect": EFFECT_DOA},                                     # idle: DOA hunting
    "listening":    {"effect": EFFECT_SINGLE, "color": 0x880000},               # red, recording
    "transcribing": {"effect": EFFECT_SINGLE, "color": 0x0000CD},               # blue
    "inference":    {"effect": EFFECT_BREATH, "color": 0xFFFFFF, "speed": 3},   # white, breathing
    "speaking":     {"effect": EFFECT_SINGLE, "color": 0x00AA00},               # green
}

# Static-color states that should blink -- reissue their own look's command --
# each time a mic_level (HEARING) event comes in, so the ring visibly pulses
# along with live mic activity the same way the chat UI's HEARING label does.
BLINK_STATES = ("listening", "transcribing")

# Mirrors persona_chat.html's setLive() event -> state mapping, so the LED
# ring and the chat UI agree on what each SSE event means. recording_start/
# recording_stop come straight from RealtimeSTT's VAD, via the hub -- see
# persona_speech_input.py's on_recording_start/on_recording_stop callbacks.
EVENT_TO_STATE = {
    "recording_start": "listening",
    "recording_stop":  "resting",
    "heard":           "transcribing",
    "user_turn":       "inference",
    "sal_turn":        "speaking",
    "speak_done":      "resting",
}


# ─── LED Ring ─────────────────────────────────────────────────────────────────

class LedRing:
    """Thin wrapper that only ever sets a whole "look" (effect + color) at once."""

    def __init__(self, dev):
        self.dev          = dev
        self.current_look = None

    def show(self, look: dict) -> None:
        if look == self.current_look:
            return
        self.apply(look)

    def apply(self, look: dict) -> None:
        """Write a look to the hardware unconditionally, even if it matches
        what's already showing. Used for the mic-activity blink, where
        reissuing the same solid color is what makes it visibly pulse."""
        if "speed" in look:
            self.dev.write("LED_SPEED", [look["speed"]])
        self.dev.write("LED_EFFECT", [look["effect"]])
        if "color" in look:
            self.dev.write("LED_COLOR", [look["color"]])
        self.current_look = look


def connect(vid=0x2886, pid=0x001A):
    """Keep retrying until the ReSpeaker shows up, so a service restart or a
    reconnected cable recovers on its own."""
    while True:
        dev = find(vid=vid, pid=pid)
        if dev:
            return dev
        print("ReSpeaker not found -- retrying in 5s")
        time.sleep(5)


# ─── Event Loop ───────────────────────────────────────────────────────────────

def run() -> None:
    dev           = connect()
    ring          = LedRing(dev)
    current_state = "resting"
    ring.show(STATE_LOOKS[current_state])

    while True:
        try:
            with httpx.stream("GET", f"{HUB_URL}/events", timeout=None) as response:
                for line in response.iter_lines():
                    if not line.startswith("data: "):
                        continue
                    data      = json.loads(line[len("data: "):])
                    event     = data.get("type")

                    if event == "mic_level":
                        if current_state in BLINK_STATES:
                            ring.apply(STATE_LOOKS[current_state])
                        continue

                    state = EVENT_TO_STATE.get(event)
                    if state:
                        current_state = state
                        ring.show(STATE_LOOKS[current_state])
        except Exception as e:
            print(f"Lost connection to hub ({e}) -- retrying in 3s")
            time.sleep(3)


if __name__ == "__main__":
    run()
