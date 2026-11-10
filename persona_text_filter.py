"""Clean up reply text as it arrives from the LLM, before anything else sees it.

The hub runs every reply through here (see llm() in persona_hub.py), so the
chat bubble, the speech, the replayed history and mem0 all get the same
cleaned text. For now it only straightens curly quotes.

This file has no service code, so it can be tested on its own.
"""

from persona_schemas import STRAIGHT_QUOTES


# ─── Quotes ───────────────────────────────────────────────────────────────────

def straighten_quotes(text: str) -> str:
    """Swap curly quotes and apostrophes for plain ones (see STRAIGHT_QUOTES)."""
    for curly, plain in STRAIGHT_QUOTES:
        text = text.replace(curly, plain)

    return text
