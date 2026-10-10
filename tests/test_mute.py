#!/usr/bin/env -S uv run --no-project --script
# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "fastapi",
#     "uvicorn",
#     "httpx",
# ]
# ///

"""Mute tests: does the hub announce every mute change, and drop voice input
(but not typed input) while muted?

Fast and service-free, like tests/test_self_hear.py: imports persona_hub
without starting its server and replaces emit() with one that remembers
events, so the live hub is never touched.

Usage: tests/test_mute.py      (exit code 0 = every test passed)
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import persona_hub as hub


# ─── Helpers ──────────────────────────────────────────────────────────────────

# Every event the hub emitted during the current test, as (type, text).
events = []


def remember_event(event_type, text, **extra):
    """Stand-in for hub.emit(): keep the event instead of sending it to the UI."""
    events.append((event_type, text))


def do_nothing(*arguments):
    """Stand-in for hub.announce_bubble(), which would raise the real chat window and notify."""


def fresh_start():
    """Unmuted, nobody talking, no events yet."""
    events.clear()

    hub.emit                   = remember_event
    hub.announce_bubble        = do_nothing
    hub.MUTED                  = False
    hub.speaking               = False
    hub.last_spoke             = 0.0
    hub.finished_heard_persona = False


# ─── Tests ────────────────────────────────────────────────────────────────────

def test_mute_on_is_announced():
    """Muting sets the hub's flag and sends a "mute" event saying "on"."""
    fresh_start()
    answer = hub.set_mute("on")

    assert hub.MUTED is True
    assert answer == {"muted": True}
    assert ("mute", "on") in events


def test_mute_off_is_announced():
    """Unmuting clears the flag and sends a "mute" event saying "off"."""
    fresh_start()
    hub.set_mute("on")
    events.clear()
    answer = hub.set_mute("off")

    assert hub.MUTED is False
    assert answer == {"muted": False}
    assert ("mute", "off") in events


def test_unknown_setting_changes_nothing():
    """A bad setting is refused: no change, no event."""
    fresh_start()
    answer = hub.set_mute("maybe")

    assert "error" in answer
    assert hub.MUTED is False
    assert events == []


def test_state_reports_mute():
    """/state carries the setting, which is how the page and ring catch up after a reconnect."""
    fresh_start()
    hub.set_mute("on")

    assert hub.get_state()["muted"] is True


def test_voice_input_dropped_while_muted():
    """Muted voice input never reaches dispatch: no bubble, no reply."""
    fresh_start()
    hub.set_mute("on")
    events.clear()
    hub.converse(hub.ThinkRequest(text="echo, hello there", typed=False))

    assert events == []


def test_typed_input_goes_through_while_muted():
    """Typed input isn't affected by mute: it still shows up as the owner's turn."""
    fresh_start()
    hub.set_mute("on")
    events.clear()
    hub.MODE = "named"   # nobody named, so no persona answers and nothing is spoken
    hub.converse(hub.ThinkRequest(text="hello there", typed=True))

    assert any(event_type == "user_turn" for event_type, _ in events)


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
