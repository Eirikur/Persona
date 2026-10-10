#!/usr/bin/env -S uv run --no-project --script
# /// script
# requires-python = ">=3.9"
# dependencies = [
#    "pyusb",
#    "libusb_package",
#    "httpx",
# ]
# ///

"""LED ring tests: does mute win over every other look, and is it unmistakable?

Fast and hardware-free: imports persona_led_ring without connecting to the
ReSpeaker or the hub, and only checks which look would be chosen.

Usage: tests/test_led_ring.py      (exit code 0 = every test passed)
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import persona_led_ring as led


# ─── Tests ────────────────────────────────────────────────────────────────────

def test_muted_is_red_in_every_state():
    """While muted, every pipeline state shows the mute look."""
    for state in led.STATE_LOOKS:
        assert led.look_for(state, muted=True) == led.MUTED_LOOK


def test_unmuted_shows_the_state():
    """Without mute, each state shows its own look."""
    for state, look in led.STATE_LOOKS.items():
        assert led.look_for(state, muted=False) == look


def test_mute_look_is_solid_full_red():
    """Mute is a solid (not breathing, not hunting) full-brightness red."""
    assert led.MUTED_LOOK["effect"] == led.EFFECT_SINGLE
    assert led.MUTED_LOOK["color"]  == 0xFF0000


def test_mute_look_is_unlike_any_state():
    """No pipeline state may look the same as mute, or mute could be mistaken for it."""
    for look in led.STATE_LOOKS.values():
        assert look != led.MUTED_LOOK


# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    """Run every test_ function in this file, print PASS or FAIL for each, exit 1 on any failure."""
    tests = []
    for name, value in list(globals().items()):
        if name.startswith("test_") and callable(value):
            tests.append(value)

    failures = 0

    for test in tests:
        try:
            test()
            print(f"PASS  {test.__name__}")
        except AssertionError:
            failures += 1
            print(f"FAIL  {test.__name__}  -- {test.__doc__.strip().splitlines()[0]}")

    print(f"\n{len(tests) - failures} of {len(tests)} passed")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
