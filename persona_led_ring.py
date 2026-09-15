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
EFFECT_DOA    = 4

# One look per pipeline state -- a rough first pass, easy to retune later.
STATE_LOOKS = {
    "listening":    {"effect": EFFECT_DOA},                       # idle: normal DOA tracking
    "transcribing": {"effect": EFFECT_SINGLE, "color": 0x3050FF}, # blue
    "inference":    {"effect": EFFECT_SINGLE, "color": 0xFFA000}, # amber
    "speaking":     {"effect": EFFECT_SINGLE, "color": 0x30C060}, # green
}

# Mirrors persona_chat.html's setLive() event -> state mapping, so the LED
# ring and the chat UI agree on what each SSE event means.
EVENT_TO_STATE = {
    "heard":      "transcribing",
    "user_turn":  "inference",
    "sal_turn":   "speaking",
    "speak_done": "listening",
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
    dev  = connect()
    ring = LedRing(dev)
    ring.show(STATE_LOOKS["listening"])

    while True:
        try:
            with httpx.stream("GET", f"{HUB_URL}/events", timeout=None) as response:
                for line in response.iter_lines():
                    if not line.startswith("data: "):
                        continue
                    data  = json.loads(line[len("data: "):])
                    state = EVENT_TO_STATE.get(data.get("type"))
                    if state:
                        ring.show(STATE_LOOKS[state])
        except Exception as e:
            print(f"Lost connection to hub ({e}) -- retrying in 3s")
            time.sleep(3)


if __name__ == "__main__":
    run()
