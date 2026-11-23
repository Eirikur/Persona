"""Persona Memory window — what the memory system looks up and keeps.

Every mem0 search (before a reply) and every mem0 save (after a reply)
becomes a record here, for the Memory window to show. A search record
holds the text searched for and each memory found, with its score. A save
record holds the exchange sent to mem0 and, once mem0 has made up its
mind a few seconds later, what it decided: memories added, changed or
deleted, or nothing kept.

Each record names its memory system ("mem0" for now), so another one
could share the window later. Records live in memory only and are lost
when the hub restarts.

As with Backstage, the hub sends only a short notice over its event
stream; the window fetches the full record over HTTP.
"""

import threading
import time

from persona_side_window import show_window as show_side_window


# ─── Configuration ────────────────────────────────────────────────────────────

RECORDS_KEPT = 50   # oldest records are forgotten beyond this many

MEMORY_WINDOW_TITLE = "Persona Memory"   # must match <title> in persona_memory.html
MEMORY_WINDOW_WIDTH = 900
MEMORY_WINDOW_URL   = "http://localhost:8400/ui/persona_memory.html"


# ─── Stored Records ───────────────────────────────────────────────────────────

records      = []   # oldest first; each one a dict, see add_record()
records_lock = threading.Lock()
next_id      = 1


def add_record(system: str, kind: str, persona: str, details: dict) -> dict:
    """
    Keep one record, give it an id and a time, and return a copy of it.

    kind is "search" or "save". details holds the rest: for a search, what
    mem0_search() returned; for a save, the exchange and the save's status.
    """
    global next_id

    with records_lock:
        record = {
            "id":      next_id,
            "time":    time.strftime("%H:%M:%S"),
            "system":  system,
            "kind":    kind,
            "persona": persona,
        }
        record.update(details)
        next_id += 1

        records.append(record)
        if len(records) > RECORDS_KEPT:
            records.pop(0)

        return dict(record)


def update_record(record_id: int, changes: dict) -> dict | None:
    """
    Add changes to a kept record (a save that mem0 has now decided on) and
    return a copy of it, or None if it has been forgotten meanwhile.
    """
    with records_lock:
        for record in records:
            if record["id"] == record_id:
                record.update(changes)
                return dict(record)

    return None


def recent_records() -> list[dict]:
    """Every kept record, newest first."""
    with records_lock:
        return list(reversed(records))


def find_record(record_id: int) -> dict | None:
    """The kept record with this id, or None if it was never kept or has been forgotten."""
    with records_lock:
        for record in records:
            if record["id"] == record_id:
                return dict(record)

    return None


def notice_text(record: dict) -> str:
    """The one-line summary sent over the event stream (and shown in Trace)."""
    start = record["system"] + " " + record["kind"] + " for " + record["persona"] + ": "

    if record.get("error"):
        return start + record["error"]

    if record["kind"] == "search":
        used = 0
        for hit in record["hits"]:
            if hit["used"]:
                used += 1

        return (start + str(len(record["hits"])) + " memories found, " + str(used)
                + " used, in " + str(record["seconds"]) + " s")

    if record["status"] != "SUCCEEDED":
        return start + record["status"].lower()

    decisions = record["decisions"]
    if not decisions:
        return start + "nothing kept"

    return start + str(len(decisions)) + " memories decided"


# ─── Opening the Window ───────────────────────────────────────────────────────

def show_window(chat_title: str) -> None:
    """Bring the Memory window to the front, opening it beside the chat window first if it isn't open."""
    show_side_window(MEMORY_WINDOW_TITLE, MEMORY_WINDOW_URL, MEMORY_WINDOW_WIDTH, chat_title)
