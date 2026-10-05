#!/usr/bin/env -S uv run --no-project --script
# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "httpx",
# ]
# ///

"""Latency bench: run the pipeline check several times and report the spread.

One pipeline check gives one sample, and a single sample can't tell a real
improvement from luck. This sends a few typed messages of different lengths,
several rounds each, and prints the median and worst time for every stage.
The numbers are saved as JSON so a later run can be compared against them.

Typed messages skip speech input, so this measures what happens after the hub
has the text: routing, inference, render and playback. Like the pipeline check,
it makes the persona speak every reply aloud.

Usage:
  ./persona_latency_bench.py [--rounds N] [--label NAME] [--baseline FILE]

Results go to tests/latency_results/<timestamp>-<label>.json. Pass an earlier
file as --baseline to print its medians next to this run's.
"""

import argparse
import json
import statistics
import time
from datetime import datetime
from pathlib import Path

import httpx

import persona_pipeline_check as check


# ─── Configuration ────────────────────────────────────────────────────────────

HUB_URL     = "http://127.0.0.1:8400"
SPEAKER     = "Latency bench"
RESULTS_DIR = Path(__file__).parent / "tests" / "latency_results"
STATE_FILE  = Path.home() / ".config" / "persona" / "state.json"
PAUSE       = 2.0   # seconds between rounds, so one reply's tail can't leak into the next

# Short, medium and long prompts. Reply length drives render time, so the
# three sizes show whether lag comes from inference or from rendering.
# NAME stands for a wake word of the loaded persona, filled in at run time.
PROMPTS = (
    ("short",  "NAME, say hello in three words."),
    ("medium", "NAME, this is a system test. Do you hear me?"),
    ("long",   "NAME, tell me about the weather on Mars in about five sentences."),
)

# Stage names in the order they are printed, then the total.
COLUMNS = tuple(stage[0] for stage in check.STAGES) + ("total",)


# ─── Finding Who Will Answer ──────────────────────────────────────────────────

def loaded_persona():
    """
    Ask the hub who is loaded. Returns (name, wake word, provider) of the first
    loaded persona, or None. The hub's /state lists only names, so the wake word
    and provider come from the saved state file (the hub saves it on "persist").
    """
    state = httpx.get(HUB_URL + "/state", timeout=5.0).json()

    if not state["loaded_personas"]:
        return None

    name = state["loaded_personas"][0]
    saved = json.loads(STATE_FILE.read_text())["personas"].get(name, {})

    wake_words = saved.get("wake_words") or [name]

    return name, wake_words[0], saved.get("provider", "unknown")


# ─── Running One Sample ───────────────────────────────────────────────────────

def run_once(text):
    """Send one typed message and return (seconds per stage, missing stages, reply words)."""
    check.first_seen.clear()
    check.replies.clear()

    check.first_seen["sent"] = time.monotonic()

    try:
        httpx.post(HUB_URL + "/converse", timeout=180.0,
                   json={"text": text, "typed": True, "speaker": SPEAKER})
    except httpx.HTTPError as e:
        print(f"    hub error: {e}")

    deadline = time.monotonic() + check.FINISH_WAIT
    while "speak_done" not in check.first_seen and time.monotonic() < deadline:
        time.sleep(0.05)

    seconds, missing = check.measure()
    words = len(check.replies[0].split()) if check.replies else 0

    return seconds, missing, words


# ─── Summarising ──────────────────────────────────────────────────────────────

def median_of(samples, column):
    """Median of one column across the samples that have it, or None if none do."""
    values = [s["seconds"][column] for s in samples if column in s["seconds"]]
    return statistics.median(values) if values else None


def worst_of(samples, column):
    """Largest value of one column across the samples that have it, or None."""
    values = [s["seconds"][column] for s in samples if column in s["seconds"]]
    return max(values) if values else None


def cell(value):
    """A number formatted for the table, or a dash when there was no sample."""
    return "    -" if value is None else f"{value:5.2f}"


def print_table(title, samples, baseline_samples=None):
    """Print median (and worst) seconds for each stage; add the baseline median if given."""
    print(f"\n{title}  ({len(samples)} samples)")
    print("  " + " " * 12 + "".join(f"{name:>10}" for name in COLUMNS))

    print("  " + f"{'median':<12}" + "".join(f"{cell(median_of(samples, c)):>10}" for c in COLUMNS))
    print("  " + f"{'worst':<12}" + "".join(f"{cell(worst_of(samples, c)):>10}" for c in COLUMNS))

    if baseline_samples:
        print("  " + f"{'baseline':<12}"
              + "".join(f"{cell(median_of(baseline_samples, c)):>10}" for c in COLUMNS))


# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    """Run every prompt for the requested rounds, print the tables, and save the numbers."""
    parser = argparse.ArgumentParser(description="Repeat the pipeline check and report the spread.")
    parser.add_argument("--rounds",   type=int, default=3,  help="samples per prompt (default 3)")
    parser.add_argument("--label",    default="run",        help="name used in the results file")
    parser.add_argument("--baseline", default=None,         help="earlier results file to compare against")
    args = parser.parse_args()

    baseline = json.loads(Path(args.baseline).read_text()) if args.baseline else None

    threading_ok = start_listener()
    if not threading_ok:
        return 1

    who = loaded_persona()
    if who is None:
        print("No persona is loaded, so nobody can answer.")
        return 1

    name, wake_word, provider = who
    print(f"Addressing {name!r} as {wake_word!r}, provider {provider!r}")
    if provider == "echo":
        print("Note: the echo provider makes no LLM call, so inference time here means nothing.")

    samples = []

    for size, template in PROMPTS:
        text = template.replace("NAME", wake_word.capitalize())

        for round_number in range(1, args.rounds + 1):
            seconds, missing, words = run_once(text)

            total = seconds.get("total")
            note  = "" if not missing else "   MISSING: " + ", ".join(missing)
            print(f"  {size:<7} round {round_number}: "
                  + ("total " + f"{total:.2f}s" if total is not None else "no total")
                  + f", {words} words{note}", flush=True)

            samples.append({"size": size, "seconds": seconds, "missing": missing, "words": words})
            time.sleep(PAUSE)

    for size, text in PROMPTS:
        mine     = [s for s in samples if s["size"] == size]
        previous = [s for s in baseline["samples"] if s["size"] == size] if baseline else None
        print_table(size, mine, previous)

    stamp = datetime.now().strftime("%Y-%m-%d-%H%M%S")
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    path = RESULTS_DIR / (stamp + "-" + args.label + ".json")
    path.write_text(json.dumps({"label": args.label, "stamp": stamp, "persona": name, "provider": provider, "samples": samples}, indent=2))
    print(f"\nSaved {path}")

    failed = [s for s in samples if s["missing"]]
    return 1 if failed else 0


def start_listener():
    """Start the pipeline check's event listener against the hub. False if the hub can't be reached."""
    import threading

    threading.Thread(target=check.listen_for_events, args=(HUB_URL,), daemon=True).start()
    check.listening.wait(timeout=5.0)

    if check.listen_errors or not check.listening.is_set():
        reason = check.listen_errors[0] if check.listen_errors else "no answer"
        print(f"Could not connect to the hub at {HUB_URL}: {reason}")
        return False

    return True


if __name__ == "__main__":
    raise SystemExit(main())
