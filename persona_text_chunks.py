"""Split a reply into chunks that can be rendered and played one at a time.

Chatterbox renders slower than real time on this machine, so the speech
service renders the first chunk, starts playing it, and renders the next chunk
while the first one plays. Sound starts after one chunk's render time instead
of the whole reply's.

This file has no model or audio code, so it can be tested on its own.
"""

import re


# ─── Settings ────────────────────────────────────────────────────────────────

# A sentence ends at . ! or ? followed by a space and then a capital letter or
# an opening quote. Requiring the capital keeps "3.5 percent" in one piece.
SENTENCE_BREAK = re.compile(r"(?<=[.!?])\s+(?=[A-Z\"'])")


# ─── Splitting ───────────────────────────────────────────────────────────────

def split_into_sentences(text: str) -> list[str]:
    """Cut text after each sentence-ending mark. Expects normalized text."""

    return SENTENCE_BREAK.split(text.strip())


def word_count(text: str) -> int:
    """Count the words in a piece of text."""

    return len(text.split())


def split_into_chunks(text: str, min_words: int) -> list[str]:
    """
    Group sentences into chunks of at least min_words words each.

    A short sentence like "Yes." is joined to the sentence after it, because
    rendering it alone costs a full model call for almost no speech. A short
    leftover at the end is joined to the chunk before it. A big min_words
    gives one chunk, which is the same as not splitting at all.
    """

    chunks = []
    pending = ""

    for sentence in split_into_sentences(text):
        if pending:
            pending = pending + " " + sentence
        else:
            pending = sentence

        if word_count(pending) >= min_words:
            chunks.append(pending)
            pending = ""

    if pending and chunks:
        chunks[-1] = chunks[-1] + " " + pending
    elif pending:
        chunks.append(pending)

    return chunks
