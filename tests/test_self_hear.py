#!/usr/bin/env -S uv run --no-project --script
# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "fastapi",
#     "uvicorn",
#     "httpx",
# ]
# ///

"""Self-hear guard tests: does the hub ignore exactly the transcripts whose
recording began while a persona was talking (or just after), and nothing else?

Fast and service-free: imports persona_hub without starting its server, so no
window, no sound, and the live hub is never touched. The hub's emit() is
replaced with one that just remembers events, which is how each test sees
whether a transcript was ignored.

Usage: tests/test_self_hear.py      (exit code 0 = every test passed)
"""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import persona_hub as hub


# ─── Helpers ──────────────────────────────────────────────────────────────────

# Every event the hub emitted during the current test, as (type, text).
events = []


def remember_event(event_type, text, **extra):
    """Stand-in for hub.emit(): keep the event instead of sending it to the UI."""
    events.append((event_type, text))


def fresh_start():
    """Put the hub's self-hear state back to "nobody has spoken for a long time"."""
    events.clear()

    hub.emit                    = remember_event
    hub.speaking                = False
    hub.playing                 = False
    hub.last_spoke              = 0.0
    hub.last_speaker            = "Echo"
    hub.recording_heard_persona = False
    hub.finished_heard_persona  = False


def persona_stopped(seconds_ago):
    """Pretend a persona finished talking this many seconds ago."""
    hub.speaking   = False
    hub.playing    = False
    hub.last_spoke = time.time() - seconds_ago


def transcript_was_ignored(text, typed=False):
    """Send a transcript through dispatch() and report whether it was ignored as self-hear."""
    events.clear()
    hub.dispatch(text, typed)

    return any(event_type == "ignored" for event_type, _ in events)


# ─── Tests ────────────────────────────────────────────────────────────────────

def test_recording_during_speech_is_ignored():
    """Recording began while the persona talked; text arrives after it stopped."""
    fresh_start()
    hub.speaking = True
    hub.playing  = True
    hub.recording_start()
    hub.recording_stop()
    persona_stopped(seconds_ago=1.0)

    assert transcript_was_ignored("hello there")


def test_recording_just_after_speech_is_ignored():
    """Recording began inside SELF_HEAR_MARGIN after the persona stopped (its last word)."""
    fresh_start()
    persona_stopped(seconds_ago=hub.SELF_HEAR_MARGIN / 2)
    hub.recording_start()
    hub.recording_stop()

    assert transcript_was_ignored("hello there")


def test_recording_well_after_speech_is_accepted():
    """The 11:50:55 case: the owner said "ok" 7.5 s after Echo stopped. Must go through."""
    fresh_start()
    persona_stopped(seconds_ago=7.5)
    hub.recording_start()
    hub.recording_stop()

    assert not transcript_was_ignored("ok")


def test_verdict_follows_its_own_recording():
    """
    Recording A caught the persona; recording B starts (owner talking) before
    A's text arrives. A must still be ignored, and B accepted afterwards.
    """
    fresh_start()
    hub.speaking = True
    hub.recording_start()          # A begins while the persona talks
    hub.recording_stop()           # A ends
    persona_stopped(seconds_ago=2.0)
    hub.recording_start()          # B begins, persona long finished

    assert transcript_was_ignored("persona words")     # A's text

    hub.recording_stop()           # B ends
    assert not transcript_was_ignored("owner words")   # B's text


def test_persona_talking_when_text_arrives_is_ignored():
    """Even a recording that began in silence may have caught a persona who started since."""
    fresh_start()
    hub.recording_start()
    hub.recording_stop()
    hub.speaking = True

    assert transcript_was_ignored("hello there")


def test_typed_input_is_never_ignored():
    """Typed input can't be the persona's voice, so the guard never applies to it."""
    fresh_start()
    hub.speaking = True
    hub.recording_start()
    hub.recording_stop()

    assert not transcript_was_ignored("hello there", typed=True)


def test_ignored_message_names_the_persona():
    """The Trace line should name whoever was talking, not always "Sal"."""
    fresh_start()
    hub.last_speaker = "Echo"
    hub.speaking     = True
    hub.playing      = True

    assert "Echo" in hub.ignored_reason()
    assert "Sal" not in hub.ignored_reason()


def test_display_names():
    """The internal key "default" is Sal; other keys just get a capital letter."""
    assert hub.display_name("default") == "Sal"
    assert hub.display_name("echo")    == "Echo"


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
