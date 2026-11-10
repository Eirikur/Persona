"""Persona Backstage — everything behind one reply.

At the end of every reply, persona_llm.py sends the hub the whole turn as
a list of steps: the system prompt, the replayed history, the new input,
each round's reasoning and token counts, every tool call and its result,
and the final reply. This file keeps the most recent turns in memory for
the Backstage window. They are lost when the hub restarts.

As with the data window, the hub only sends a short notice over its event
stream; the window fetches the full turn over HTTP. A turn carries the
whole replayed history, far too much to push to every listening page.
"""

import threading
import time

from persona_prices import cost_text
from persona_side_window import show_window as show_side_window


# ─── Configuration ────────────────────────────────────────────────────────────

TURNS_KEPT = 20   # oldest turns are forgotten beyond this many

BACKSTAGE_WINDOW_TITLE = "Persona Backstage"   # must match <title> in persona_backstage.html
BACKSTAGE_WINDOW_WIDTH = 1000
BACKSTAGE_WINDOW_URL   = "http://localhost:8400/ui/persona_backstage.html"


# ─── Stored Turns ─────────────────────────────────────────────────────────────

turns      = []   # oldest first; each one a dict, see add_turn()
turns_lock = threading.Lock()
next_id    = 1


def add_turn(persona: str, provider: str, model: str, steps: list[dict], cost: float | None) -> dict:
    """Keep one turn and what it cost, give it an id and a time, and return it."""
    global next_id

    with turns_lock:
        turn = {
            "id":       next_id,
            "time":     time.strftime("%H:%M:%S"),
            "persona":  persona,
            "provider": provider,
            "model":    model,
            "steps":    steps,
            "cost":     cost,
        }
        next_id += 1

        turns.append(turn)
        if len(turns) > TURNS_KEPT:
            turns.pop(0)

    return turn


def recent_turns() -> list[dict]:
    """Every kept turn, newest first."""
    with turns_lock:
        return list(reversed(turns))


def find_turn(turn_id: int) -> dict | None:
    """The kept turn with this id, or None if it was never kept or has been forgotten."""
    with turns_lock:
        for turn in turns:
            if turn["id"] == turn_id:
                return turn

    return None


def total_tokens(steps: list[dict]) -> dict:
    """
    A turn's token counts, added up over all its rounds, plus how many
    rounds there were. Also used by persona_llm.py for the turns tally.
    """
    total = {"in": 0, "cached": 0, "out": 0, "reasoning": 0, "rounds": 0}

    for step in steps:
        if step["kind"] == "tokens":
            for name in step["counts"]:
                total[name] += step["counts"][name]

            total["rounds"] += 1

    return total


def notice_text(turn: dict) -> str:
    """The one-line summary sent over the event stream (and shown in Trace)."""
    total = total_tokens(turn["steps"])
    return (turn["persona"] + " via " + turn["model"] + ": "
            + str(total["in"]) + " tokens in, " + str(total["out"]) + " out, model "
            + cost_text(turn["cost"]))


# ─── Opening the Window ───────────────────────────────────────────────────────

def show_window(chat_title: str) -> None:
    """Bring the Backstage window to the front, opening it beside the chat window first if it isn't open."""
    show_side_window(BACKSTAGE_WINDOW_TITLE, BACKSTAGE_WINDOW_URL, BACKSTAGE_WINDOW_WIDTH, chat_title)
