"""Persona Data Window — what the personas' tools returned.

Every tool call a persona makes (news_read, web_search, ...) is reported to
the hub by persona_llm.py: who asked, what they were answering, the exact
arguments the model sent, and the exact result it got back. This file keeps
the most recent of those in memory, so the data window can show them even
if it was opened after the fact. The list is lost when the hub restarts.

The hub only sends a short notice over its event stream; the data window
fetches the full records from the hub over HTTP. Tool results can be long
(a fetched page), and every page listening to the stream would otherwise
receive them.
"""

import threading
import time


# ─── Configuration ────────────────────────────────────────────────────────────

RECORDS_KEPT = 50   # oldest tool results are forgotten beyond this many


# ─── Stored Tool Results ──────────────────────────────────────────────────────

records      = []   # oldest first; each one a dict, see add_record()
records_lock = threading.Lock()
next_id      = 1


def add_record(persona: str, question: str, tool: str, arguments: str, result: str) -> dict:
    """Keep one tool result, give it an id and a time, and return it."""
    global next_id

    with records_lock:
        record = {
            "id":        next_id,
            "time":      time.strftime("%H:%M:%S"),
            "persona":   persona,
            "question":  question,
            "tool":      tool,
            "arguments": arguments,
            "result":    result,
        }
        next_id += 1

        records.append(record)
        if len(records) > RECORDS_KEPT:
            records.pop(0)

    return record


def recent_records() -> list[dict]:
    """Every kept tool result, newest first."""
    with records_lock:
        return list(reversed(records))


def find_record(record_id: int) -> dict | None:
    """The kept tool result with this id, or None if it was never kept or has been forgotten."""
    with records_lock:
        for record in records:
            if record["id"] == record_id:
                return record

    return None


def notice_text(record: dict) -> str:
    """The one-line summary sent over the event stream (and shown in Trace)."""
    size = len(record["result"])
    return record["tool"] + " for " + record["persona"] + ": " + str(size) + " characters"
