#!/usr/bin/env -S uv run --no-project --script
# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "httpx",
# ]
# ///

"""Pipeline check: send one typed message through the hub and time each stage.

The hub announces every stage of a reply as an event on /events. This script
listens to that stream, sends the test message to /converse, and notes when
each event arrives. Nothing in the hub is touched, so the check cannot disturb
the thing it measures. Like the "Run test" button, it makes the persona speak
its reply aloud.

Stages, in order:
  hub routing  message sent           -> inference began
  inference    inference began        -> reply text ready
  render       reply text ready       -> audio starts playing
  playback     audio starts playing   -> reply finished

Usage: ./persona_pipeline_check.py [hub_url]

Exit code: 0 = every stage happened, 1 = a stage was missing or the hub failed.
"""

import json
import sys
import threading
import time

import httpx


# ─── Configuration ────────────────────────────────────────────────────────────

HUB_URL     = "http://127.0.0.1:8400"
TEST_TEXT   = "Sal, this is a system test. Do you hear me?"
SPEAKER     = "Pipeline check"   # chat-bubble label for the test message
FINISH_WAIT = 5.0                # seconds to wait for the last event after the hub answers

# Hub event names this check cares about. Others (mic levels and so on) are ignored.
STAGE_EVENTS = ("inference", "sal_turn", "playback_start", "speak_done")

# Stage name, event that starts it, event that ends it. "sent" is our own moment of sending.
STAGES = (
    ("hub routing", "sent",           "inference"),
    ("inference",   "inference",      "sal_turn"),
    ("render",      "sal_turn",       "playback_start"),
    ("playback",    "playback_start", "speak_done"),
)


# ─── Runtime State ────────────────────────────────────────────────────────────

# Event name -> when its first occurrence arrived (time.monotonic seconds).
first_seen = {}

# Text of every reply the hub announced. More than one means several personas answered.
replies = []

listening = threading.Event()

# Why the event stream could not be opened or was lost, if it was.
listen_errors = []


# ─── Listening to the Hub ─────────────────────────────────────────────────────

def listen_for_events(hub_url):
    """Record the arrival time of each stage event the hub announces. Runs in its own thread."""
    try:
        with httpx.stream("GET", hub_url + "/events", timeout=None) as response:
            listening.set()

            for line in response.iter_lines():
                if not line.startswith("data: "):
                    continue   # keepalive comments between events

                event = json.loads(line[len("data: "):])
                kind  = event["type"]

                if kind not in STAGE_EVENTS:
                    continue

                first_seen.setdefault(kind, time.monotonic())

                if kind == "sal_turn":
                    replies.append(event["text"])

    except httpx.HTTPError as e:
        listen_errors.append(str(e))
        listening.set()   # so main stops waiting and reports it


# ─── Reporting ────────────────────────────────────────────────────────────────

def print_report():
    """Print the time each stage took, the reply, and a total. Returns the stages that never happened."""
    missing = []

    for name, begins, ends in STAGES:
        if begins not in first_seen or ends not in first_seen:
            print(f"  {name:<12} not seen")
            missing.append(name)
            continue

        seconds = first_seen[ends] - first_seen[begins]
        detail  = ""

        if name == "render" and replies:
            words  = len(replies[0].split())
            detail = f"   {words} words, {seconds / max(words, 1):.2f}s per word"

        print(f"  {name:<12} {seconds:6.2f}s{detail}")

    if "sent" in first_seen and "speak_done" in first_seen:
        print(f"  {'total':<12} {first_seen['speak_done'] - first_seen['sent']:6.2f}s")

    if replies:
        print(f"Reply: {replies[0]!r}")

    if len(replies) > 1:
        print(f"Note: {len(replies)} personas replied. Stage times cover the first reply only.")

    return missing


# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    """Send the test message, wait for the reply to finish, and print the stage times."""
    hub_url = sys.argv[1] if len(sys.argv) > 1 else HUB_URL

    threading.Thread(target=listen_for_events, args=(hub_url,), daemon=True).start()

    listening.wait(timeout=5.0)

    if listen_errors or not listening.is_set():
        reason = listen_errors[0] if listen_errors else "no answer"
        print(f"Could not connect to the hub at {hub_url}: {reason}")
        sys.exit(1)

    print(f"Pipeline check: sending {TEST_TEXT!r}", flush=True)
    first_seen["sent"] = time.monotonic()

    try:
        response = httpx.post(hub_url + "/converse", timeout=180.0,
                              json={"text": TEST_TEXT, "typed": True, "speaker": SPEAKER})
        response.raise_for_status()
    except httpx.HTTPError as e:
        print(f"The hub did not complete the request: {e}")

    # The hub answers just after it announces speak_done; give the event a moment to arrive.
    deadline = time.monotonic() + FINISH_WAIT
    while "speak_done" not in first_seen and time.monotonic() < deadline:
        time.sleep(0.05)

    missing = print_report()

    if missing:
        print("FAIL: these stages did not happen: " + ", ".join(missing))
        sys.exit(1)

    print("PASS: every stage happened")


if __name__ == "__main__":
    main()
