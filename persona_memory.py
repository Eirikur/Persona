"""Persona Memory — what a persona remembers between turns.

Replay: every persona keeps its last few exchanges with the owner (what the
owner said, what the persona answered) and they are sent along with each
new message. That is what lets a follow-up question like "and what about
the second one?" make sense. The number kept is REPLAY_EXCHANGES in
persona_schemas.py.

The history lives in memory only. A hub restart starts every persona fresh.

The prompt that goes to the LLM is a list of messages, each a role and some
text, in this order:

    system     the persona's system prompt (sent separately, see llm())
    user       an earlier message from the owner
    assistant  the persona's reply to it
    ...        more earlier exchanges, oldest first
    user       the new message -- always last

persona_hub.py only calls into this file; it never handles the history itself.
"""

import threading

from persona_schemas import REPLAY_EXCHANGES


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
