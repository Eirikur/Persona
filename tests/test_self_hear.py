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
And of those, does it hold (not drop) the ones that aren't the persona's own
words, then replay them one at a time once speech is done?

Fast and service-free: imports persona_hub without starting its server, so no
window, no sound, and the live hub is never touched. The hub's emit() is
replaced with one that just remembers events, which is how each test sees
whether a transcript was ignored.

Usage: tests/test_self_hear.py      (exit code 0 = every test passed)
"""

import sys
import threading
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
    hub.recent_replies          = ["Hello there, the persona words are these."]
    hub.held_inputs.clear()


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


def transcript_was_held(text):
    """Send a voice transcript through dispatch() and report whether it was held for later."""
    events.clear()
    hub.dispatch(text)

    return any(event_type == "held" for event_type, _ in events)


def replay_and_catch(action=None):
    """
    Run action (replay_held_input() if none is given) with converse()
    swapped for a stand-in, and return the request that would have been
    replayed (or None if nothing was).
    """
    if action is None:
        action = hub.replay_held_input
    caught = []
    done   = threading.Event()

    def pretend_converse(request):
        """Stand-in for hub.converse(): note the request instead of answering it."""
        caught.append(request)
        done.set()

    real_converse = hub.converse
    hub.converse  = pretend_converse

    try:
        action()
        done.wait(timeout=2.0)
    finally:
        hub.converse = real_converse

    if caught:
        return caught[0]
    return None


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


def test_owner_talking_over_persona_is_held():
    """Words that aren't the persona's reply are the owner talking over it: held, not dropped."""
    fresh_start()
    hub.speaking = True

    assert transcript_was_held("oh I actually meant a font")
    assert hub.held_inputs == ["oh I actually meant a font"]


def test_echo_is_dropped_not_held():
    """The persona's own words coming back through the mic are dropped, never queued."""
    fresh_start()
    hub.speaking = True

    assert transcript_was_ignored("the persona words are these")
    assert hub.held_inputs == []


def test_held_input_is_replayed_oldest_first_one_at_a_time():
    """Each finished round of speech replays one held input, the oldest."""
    fresh_start()
    hub.held_inputs.extend(["first thing", "second thing"])

    request = replay_and_catch()

    assert request.text == "first thing"
    assert request.replayed
    assert hub.held_inputs == ["second thing"]


def test_held_after_persona_finished_is_replayed_at_once():
    """
    The "I'm really into it." case: the recording began while the persona
    talked, but its text arrived after she finished. Nothing else will
    speak to trigger a replay, so it must be replayed right away.
    """
    fresh_start()
    hub.speaking = True
    hub.recording_start()
    hub.recording_stop()
    persona_stopped(seconds_ago=1.0)

    request = replay_and_catch(lambda: hub.dispatch("I'm really into it."))

    assert request.text == "I'm really into it."
    assert hub.held_inputs == []


def test_nothing_held_nothing_replayed():
    """With nothing held, finishing a round of speech replays nothing."""
    fresh_start()

    assert replay_and_catch() is None


def test_replayed_input_passes_the_guard():
    """A replayed input already passed the guard once; a persona talking now mustn't hold it again."""
    fresh_start()
    hub.speaking = True
    events.clear()
    hub.dispatch("oh I actually meant a font", replayed=True)

    assert hub.held_inputs == []
    assert ("heard", "oh i actually meant a font") in events


def test_reply_to_replayed_input_does_not_loop():
    """The reply to a replayed input, heard by the mic, is echo: dropped, not held again."""
    fresh_start()
    hub.recent_replies.append("A font, of course. Which one would you like?")
    hub.speaking = True

    assert transcript_was_ignored("a font of course which one would you like")
    assert hub.held_inputs == []


def test_speaking_lasts_until_the_last_overlapping_reply_ends():
    """
    Two replies on their way to speech output at once (speech output plays
    them one after another): the first one ending must not clear `speaking`
    while the second is still to be heard.
    """
    fresh_start()
    hub.replies_in_flight = 0

    first_may_end  = threading.Event()
    second_may_end = threading.Event()

    def pretend_speak(text, voice_prompt):
        """Stand-in for hub.speak(): 'play' until the test says this reply may end."""
        if text == "first reply":
            first_may_end.wait(timeout=2.0)
        else:
            second_may_end.wait(timeout=2.0)

    real_speak, real_turn = hub.speak, hub.emit_persona_turn
    hub.speak             = pretend_speak
    hub.emit_persona_turn = lambda *args: None

    try:
        first  = threading.Thread(target=hub.say, args=("echo", "first reply"))
        second = threading.Thread(target=hub.say, args=("echo", "second reply"))
        first.start()
        second.start()
        time.sleep(0.2)

        first_may_end.set()
        first.join(timeout=2.0)
        still_speaking = hub.speaking

        second_may_end.set()
        second.join(timeout=2.0)
    finally:
        hub.speak             = real_speak
        hub.emit_persona_turn = real_turn

    assert still_speaking
    assert not hub.speaking


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
