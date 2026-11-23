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
    MEM0_ADD_TIMEOUT, MEM0_EVENT_POLL, MEM0_EVENT_WAIT, MEM0_LIST_MAX_PAGES,
    MEM0_LIST_PAGE_SIZE, MEM0_MIN_SCORE, MEM0_SEARCH_TIMEOUT, MEM0_TOP_K,
    MEM0_URL, MEM0_USER_ID, PROMPT_MARK, REPLAY_EXCHANGES,
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

        {"query": the text,
         "hits": [{"id", "memory", "score", "created", "used"}, ...],
         "min_score": the cut-off in force, "seconds": how long mem0 took,
         "error": "" or what went wrong}

    A hit is "used" (goes into the prompt) when its score is at least
    MEM0_MIN_SCORE. Weaker hits are kept in the list so the Memory window
    can show where the line fell. A hit without a score counts as used.

    The reply is waiting on this, so any trouble (no key, no answer in
    MEM0_SEARCH_TIMEOUT seconds, an error) means no hits this turn, with
    the reason in "error" and in the log.
    """
    search = {"query": text, "hits": [], "min_score": MEM0_MIN_SCORE, "seconds": 0.0, "error": ""}

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
            score = result.get("score")

            hit = {
                "id":      result.get("id", ""),
                "memory":  result["memory"],
                "score":   score,
                "created": result.get("created_at", ""),
                "used":    score is None or score >= MEM0_MIN_SCORE,
            }
            search["hits"].append(hit)

    except Exception as problem:
        search["error"] = type(problem).__name__ + " " + str(problem)

    search["seconds"] = round(time.time() - started, 2)

    if search["error"]:
        print("mem0 search failed, no memories this turn: " + search["error"])
        return search

    used = used_hits(search["hits"])
    print(f"mem0 search: {len(search['hits'])} memories in {search['seconds']:.2f}s, "
          f"{len(used)} at or above {MEM0_MIN_SCORE}")

    for hit in search["hits"]:
        mark = "" if hit["used"] else "  (not used)"
        print(PROMPT_MARK + str(hit["score"]) + "  " + hit["memory"] + mark)

    return search


def without_name(text: str, wake_words: list[str]) -> str:
    """
    The input without the persona's name in front, for searching mem0:
    "Sal, what does the Kerch bridge connect?" becomes "what does the
    Kerch bridge connect?". The name only adds noise to the match.

    Only a whole first word counts, and the comma or other punctuation
    after it goes too. If the name is all there is, the text is kept as it
    was, so the search is never for nothing.
    """
    words = text.split(maxsplit=1)
    if len(words) < 2:
        return text

    first_word = words[0].lower().strip(",.!?:;")
    if first_word in wake_words:
        return words[1]

    return text


def used_hits(hits: list[dict]) -> list[dict]:
    """The hits strong enough to go into the prompt (see mem0_search)."""
    used = []
    for hit in hits:
        if hit["used"]:
            used.append(hit)

    return used


def memories_block(hits: list[dict]) -> str:
    """
    The text added to the end of the system prompt: "Memories:" and one
    memory per line, for the hits strong enough to use. Empty when there
    are none, so the prompt is unchanged.
    """
    used = used_hits(hits)
    if not used:
        return ""

    lines = ["", "", "Memories:"]
    for hit in used:
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
         "decisions": [{"id", "event": "ADD" / "UPDATE" / "DELETE", "memory"}, ...],
         "raw": mem0's results exactly as it sent them,
         "seconds": mem0's own working time, "error": "" or what went wrong}

    No decisions after SUCCEEDED means mem0 found nothing worth keeping.
    "raw" is kept because only ADD has been seen so far; an UPDATE or
    DELETE may carry more (the old text, say) than "decisions" picks out.
    """
    outcome = {"status": "PENDING", "decisions": [], "raw": [], "seconds": 0.0, "error": ""}
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
            outcome["raw"] = event.get("results") or []

            for result in outcome["raw"]:
                decision = {
                    "id":     result.get("id", ""),
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


def mem0_list_all() -> dict:
    """
    Every memory mem0 holds for MEM0_USER_ID, for the Memory window's "All
    memories" view. Read-only. mem0 sends them a page at a time; each page
    names the next one, up to MEM0_LIST_MAX_PAGES pages.

    Returns:

        {"memories": [{"id", "memory", "categories", "created", "updated",
                       "replaced_by", "synthesized"}, ...],
         "count": how many mem0 says it holds,
         "seconds": how long the listing took, "error": "" or what went wrong}

    Times are passed on exactly as mem0 sends them, with their UTC offset,
    for the page to show in local time.
    """
    listing = {"memories": [], "count": 0, "seconds": 0.0, "error": ""}

    if not mem0_key():
        listing["error"] = "no MEM0_API_KEY in .env"
        return listing

    request = {"filters": {"user_id": MEM0_USER_ID}}
    url     = MEM0_URL + "/v3/memories/?page_size=" + str(MEM0_LIST_PAGE_SIZE)
    pages   = 0
    started = time.time()

    try:
        while url and pages < MEM0_LIST_MAX_PAGES:
            answer = httpx.post(url, json=request, headers=mem0_headers(), timeout=MEM0_ADD_TIMEOUT)
            answer.raise_for_status()
            page = answer.json()

            for result in page["results"]:
                memory = {
                    "id":          result.get("id", ""),
                    "memory":      result.get("memory", ""),
                    "categories":  result.get("categories") or [],
                    "created":     result.get("created_at", ""),
                    "updated":     result.get("updated_at", ""),
                    "replaced_by": result.get("replaced_by") or "",
                    "synthesized": bool(result.get("synthesized")),
                }
                listing["memories"].append(memory)

            listing["count"] = page.get("count", len(listing["memories"]))
            url   = page.get("next")
            pages = pages + 1

    except Exception as problem:
        listing["error"] = type(problem).__name__ + " " + str(problem)

    if url and not listing["error"]:
        listing["error"] = "stopped after " + str(MEM0_LIST_MAX_PAGES) + " pages; some memories not shown"

    listing["seconds"] = round(time.time() - started, 2)
    print(f"mem0 list: {len(listing['memories'])} of {listing['count']} memories "
          f"in {listing['seconds']:.2f}s {listing['error']}")

    return listing


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
