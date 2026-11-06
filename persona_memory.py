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
log shows.

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
    MEM0_ADD_TIMEOUT, MEM0_SEARCH_TIMEOUT, MEM0_TOP_K, MEM0_URL, MEM0_USER_ID,
    REPLAY_EXCHANGES,
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


def mem0_search(text: str) -> list[str]:
    """
    Ask mem0 for the stored memories closest to this text, best match first,
    and return their wording. Each hit and its score goes to the hub log.

    The reply is waiting on this, so any trouble (no key, no answer in
    MEM0_SEARCH_TIMEOUT seconds, an error) means no memories this turn,
    with a line in the log saying why.
    """
    if not mem0_key():
        print("mem0 search skipped: no MEM0_API_KEY in .env")
        return []

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
        results = answer.json()["results"]
    except Exception as problem:
        print(f"mem0 search failed, no memories this turn: {type(problem).__name__} {problem}")
        return []

    seconds = time.time() - started
    print(f"mem0 search: {len(results)} memories in {seconds:.2f}s")

    memories = []
    for result in results:
        print(f"  {result['score']:.3f}  {result['memory']}")
        memories.append(result["memory"])

    return memories


def memories_block(memories: list[str]) -> str:
    """
    The text added to the end of the system prompt: "Memories:" and one
    memory per line. Empty when there are none, so the prompt is unchanged.
    """
    if not memories:
        return ""

    lines = ["", "", "Memories:"]
    for memory in memories:
        lines.append("- " + memory)

    return "\n".join(lines)


def mem0_save(text: str, reply: str) -> None:
    """
    Hand one exchange to mem0, which decides on its own what (if anything)
    to remember from it. mem0 answers at once with "PENDING" and does the
    work over the next few seconds. Meant to run in a background thread.
    """
    if not mem0_key() or not reply.strip():
        return

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
        seconds = time.time() - started
        print(f"mem0 save ({seconds:.1f}s): " + answer.text)
    except Exception as problem:
        print(f"mem0 save failed: {type(problem).__name__} {problem}")


# ─── Showing the Prompt ───────────────────────────────────────────────────────

def prompt_text(persona_name: str, system_prompt: str, messages: list[dict]) -> str:
    """
    The whole prompt as plain text, for the hub log: one labeled block per
    message, in the order the LLM receives them.
    """
    lines = ["── prompt for " + persona_name + " ──", "[system]", system_prompt]

    for message in messages:
        lines.append("[" + message["role"] + "]")
        lines.append(message["content"])

    lines.append("── end of prompt ──")

    return "\n".join(lines)
