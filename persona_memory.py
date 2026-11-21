"""Persona Memory — what a persona remembers between turns.

Replay: every persona keeps its last few exchanges with the owner (what the
owner said, what the persona answered) and they are sent along with each
new message. That is what lets a follow-up question like "and what about
the second one?" make sense. The number kept is REPLAY_EXCHANGES in
persona_schemas.py.

The history lives in memory only. A hub restart starts every persona fresh.

mem0 (optional, the "mem0" box on the Settings tab): after each exchange,
mem0's hosted service reads it and its own LLM decides what is worth
keeping ("User has a dog named Rufus"). Before each reply, the memories
closest to the new message are added to the end of the system prompt
under "Memories:", the way mem0's companion example does it. Saving takes
mem0 a few seconds; replay covers the gap. mem0 is called over its plain
REST API with httpx, so what is sent and received is exactly what the hub
log shows. Searches and saves also return what happened, and the hub
keeps that for the Memory window (persona_memory_window.py).

The prompt that goes to the LLM is a list of messages, each a role and some
text, in this order:

    system     the persona's system prompt (sent separately, see llm())
    user       an earlier message from the owner
    assistant  the persona's reply to it
    ...        more earlier exchanges, oldest first
    user       the new message -- always last

persona_hub.py only calls into this file; it never handles the history itself.
"""

import os
import threading
import time

import httpx

from persona_schemas import (
    MEM0_ADD_TIMEOUT, MEM0_EVENT_POLL, MEM0_EVENT_WAIT, MEM0_SEARCH_TIMEOUT,
    MEM0_TOP_K, MEM0_URL, MEM0_USER_ID, PROMPT_MARK, REPLAY_EXCHANGES,
)


# ─── Conversation History ─────────────────────────────────────────────────────

# Persona name -> list of messages, oldest first. Each message is a dict
# like {"role": "user", "content": "..."}, the shape the LLM service expects.
history      = {}
history_lock = threading.Lock()


def messages_for(persona_name: str, text: str) -> list[dict]:
    """
    The messages to send for a new input: this persona's earlier exchanges,
    oldest first, then the new input itself as the last message.
    """
    with history_lock:
        earlier = list(history.get(persona_name, []))

    new_message = {"role": "user", "content": text}

    return earlier + [new_message]


def remember_exchange(persona_name: str, text: str, reply: str) -> None:
    """
    Add one exchange (the owner's input and the persona's reply) to this
    persona's history, and forget the oldest exchanges beyond REPLAY_EXCHANGES.

    An empty reply is not kept, and neither is its input. That way the
    history always alternates user, assistant, user, assistant -- some
    providers refuse two user messages in a row.
    """
    if not reply.strip():
        return

    with history_lock:
        messages = history.setdefault(persona_name, [])

        messages.append({"role": "user",      "content": text})
        messages.append({"role": "assistant", "content": reply})

        messages_kept = REPLAY_EXCHANGES * 2
        del messages[:-messages_kept]


def exchanges_kept(persona_name: str) -> int:
    """How many earlier exchanges this persona would replay right now."""
    with history_lock:
        return len(history.get(persona_name, [])) // 2


# ─── mem0 ─────────────────────────────────────────────────────────────────────

def mem0_key() -> str:
    """The mem0 API key from MEM0_API_KEY (set in .env), or "" if there is none."""
    return os.environ.get("MEM0_API_KEY", "")


def mem0_headers() -> dict:
    """The header every mem0 request carries: the API key, mem0's "Token" style."""
    return {"Authorization": "Token " + mem0_key()}


def mem0_search(text: str) -> dict:
    """
    Ask mem0 for the stored memories closest to this text, best match first.
    Each hit and its score also goes to the hub log.

    Returns what happened, for the reply and for the Memory window:

        {"query": the text, "hits": [{"memory", "score", "created"}, ...],
         "seconds": how long mem0 took, "error": "" or what went wrong}

    The reply is waiting on this, so any trouble (no key, no answer in
    MEM0_SEARCH_TIMEOUT seconds, an error) means no hits this turn, with
    the reason in "error" and in the log.
    """
    search = {"query": text, "hits": [], "seconds": 0.0, "error": ""}

    if not mem0_key():
        search["error"] = "skipped: no MEM0_API_KEY in .env"
        print("mem0 search " + search["error"])
        return search

    request = {
        "query":   text,
        "filters": {"user_id": MEM0_USER_ID},
        "top_k":   MEM0_TOP_K,
    }

    started = time.time()

    try:
        answer = httpx.post(MEM0_URL + "/v3/memories/search/", json=request,
                            headers=mem0_headers(), timeout=MEM0_SEARCH_TIMEOUT)
        answer.raise_for_status()

        for result in answer.json()["results"]:
            hit = {
                "memory":  result["memory"],
                "score":   result.get("score"),
                "created": result.get("created_at", ""),
            }
            search["hits"].append(hit)

    except Exception as problem:
        search["error"] = type(problem).__name__ + " " + str(problem)

    search["seconds"] = round(time.time() - started, 2)

    if search["error"]:
        print("mem0 search failed, no memories this turn: " + search["error"])
        return search

    print(f"mem0 search: {len(search['hits'])} memories in {search['seconds']:.2f}s")

    for hit in search["hits"]:
        print(PROMPT_MARK + str(hit["score"]) + "  " + hit["memory"])

    return search


def memories_block(hits: list[dict]) -> str:
    """
    The text added to the end of the system prompt: "Memories:" and one
    memory per line. Empty when there are none, so the prompt is unchanged.
    """
    if not hits:
        return ""

    lines = ["", "", "Memories:"]
    for hit in hits:
        lines.append("- " + hit["memory"])

    return "\n".join(lines)


def mem0_save(text: str, reply: str) -> dict:
    """
    Hand one exchange to mem0, which decides on its own what (if anything)
    to remember from it. mem0 answers at once with "PENDING" and an event
    id, and does the work over the next few seconds; mem0_follow() waits
    for its decision.

    Returns {"event_id": "" if none, "error": "" or what went wrong}.
    """
    if not mem0_key():
        return {"event_id": "", "error": "skipped: no MEM0_API_KEY in .env"}

    request = {
        "messages": [
            {"role": "user",      "content": text},
            {"role": "assistant", "content": reply},
        ],
        "user_id": MEM0_USER_ID,
    }

    started = time.time()

    try:
        answer = httpx.post(MEM0_URL + "/v3/memories/add/", json=request,
                            headers=mem0_headers(), timeout=MEM0_ADD_TIMEOUT)
        answer.raise_for_status()
    except Exception as problem:
        error = type(problem).__name__ + " " + str(problem)
        print("mem0 save failed: " + error)
        return {"event_id": "", "error": error}

    seconds = time.time() - started
    print(f"mem0 save ({seconds:.1f}s): " + answer.text)

    event_id = answer.json().get("event_id", "")
    if not event_id:
        return {"event_id": "", "error": "mem0 gave no event id: " + answer.text}

    return {"event_id": event_id, "error": ""}


def mem0_follow(event_id: str) -> dict:
    """
    Ask mem0 every MEM0_EVENT_POLL seconds how a save is going, until it
    has finished or MEM0_EVENT_WAIT seconds have passed. Meant to run in a
    background thread.

    Returns what mem0 decided:

        {"status": "SUCCEEDED", "FAILED", or the last status seen,
         "decisions": [{"event": "ADD" / "UPDATE" / "DELETE", "memory"}, ...],
         "seconds": mem0's own working time, "error": "" or what went wrong}

    No decisions after SUCCEEDED means mem0 found nothing worth keeping.
    """
    outcome = {"status": "PENDING", "decisions": [], "seconds": 0.0, "error": ""}
    started = time.time()

    while time.time() - started < MEM0_EVENT_WAIT:
        try:
            answer = httpx.get(MEM0_URL + "/v1/event/" + event_id + "/",
                               headers=mem0_headers(), timeout=MEM0_SEARCH_TIMEOUT)
            answer.raise_for_status()
            event = answer.json()
        except Exception as problem:
            outcome["error"] = type(problem).__name__ + " " + str(problem)
            time.sleep(MEM0_EVENT_POLL)
            continue

        outcome["status"] = event.get("status", "")
        outcome["error"]  = event.get("error") or ""

        if outcome["status"] in ("SUCCEEDED", "FAILED"):
            for result in event.get("results") or []:
                decision = {
                    "event":  result.get("event", ""),
                    "memory": result.get("data", {}).get("memory", ""),
                }
                outcome["decisions"].append(decision)

            outcome["seconds"] = round((event.get("latency") or 0) / 1000, 1)
            break

        time.sleep(MEM0_EVENT_POLL)

    if outcome["status"] not in ("SUCCEEDED", "FAILED") and not outcome["error"]:
        outcome["error"] = "mem0 had not finished after " + str(MEM0_EVENT_WAIT) + " s"

    print(f"mem0 decided ({outcome['status']}): {len(outcome['decisions'])} memories")

    for decision in outcome["decisions"]:
        print(PROMPT_MARK + decision["event"] + "  " + decision["memory"])

    return outcome


# ─── Showing the Prompt ───────────────────────────────────────────────────────

def prompt_text(persona_name: str, system_prompt: str, messages: list[dict]) -> str:
    """
    The whole prompt as plain text, for the hub log: one labeled block per
    message, in the order the LLM receives them. Every line starts with
    PROMPT_MARK, so the Logs tab never mistakes what was said for an error.
    """
    text = "── prompt for " + persona_name + " ──\n"
    text = text + "[system]\n" + system_prompt + "\n"

    for message in messages:
        text = text + "[" + message["role"] + "]\n" + message["content"] + "\n"

    text = text + "── end of prompt ──"

    marked = []
    for line in text.split("\n"):
        marked.append(PROMPT_MARK + line)

    return "\n".join(marked)
