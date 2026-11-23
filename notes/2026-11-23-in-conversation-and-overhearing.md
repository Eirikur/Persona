# 2026-11-23 — In conversation with, and overhearing

Branch `in-conversation`, made from `mem0-score-cutoff` (not merged yet).
Design agreed with the owner on 2026-11-23. Nothing built yet when this
was written.

## Why

The owner plans personas with roles: Major (major domo, who may overrule
the owner, as in "No, you must go to this appointment"), House (the home,
with sensors later) and System (OS monitoring, history for debugging).
With several of them in the room, the owner must be able to answer a
plain "yes" to one of them without the others replying.

Today, naming a persona switches the whole room to open mode
(persona_hub.py, dispatch), so after "Sal, ..." every persona answers
every line. That saves repeating the name, but it brings in everyone.

## Design

### IN_CONVERSATION_WITH (room level, in the hub)

One value: the persona the owner is talking with, or nobody. It lives on
the room, not on each persona. While only the owner converses, one value
says it all; a copy on each persona could disagree. A per-persona field
can come later, when personas talk to each other.

The room stays in named mode. Routing in named mode:

1. The line starts with a persona's name: that persona answers and
   becomes IN_CONVERSATION_WITH.
2. No name, and a conversation is in effect: the line goes to that
   persona only.
3. No name, no conversation: nobody answers (as today, including the
   "Nobody named X is in the room" notice).
4. "go quiet" ends the conversation.

Open mode is unchanged: a separate Settings choice where everyone answers.
Naming a persona no longer switches the room to open.

### Dropping after 30 seconds

CONVERSATION_TIMEOUT = 30 seconds in persona_schemas.py. The clock starts
when the persona finishes speaking (or when its reply arrives, if voice
is off), not when the owner finishes the line, because a spoken reply can
run past 30 seconds. A new line within the time keeps the conversation
going.

### Chat page

While a conversation is in effect, that persona's bubbles get a highlight
border (--accent-sal, the gold). The owner's bubbles don't change. The
border goes back to normal when the conversation ends. It uses the
border, not the outline, because the outline is used by the voice-drop
pulses.

### Overhearing

Each persona keeps an "overheard" list: exchanges between the owner and
some other persona. One item is a pair: the owner's line plus the other
persona's reply, labelled with who spoke. Capped at OVERHEARD_EXCHANGES
pairs (own setting in persona_schemas.py, start at 10, same as
REPLAY_EXCHANGES), oldest dropped first.

When a persona next speaks, its prompt gets a block built from its
overheard list:

    You hear the following but do not respond because it is not
    addressed to you:
    Owner: "Sal, do you have that shipping data yet?"
    Sal: "Yes, ..."

then its own replayed history, then the new line. Overheard pairs stay in
view until they age out, so a persona can refer back to them.

Kept separate from the replay history because that history must alternate
user, assistant (some providers refuse two user messages in a row), and
putting Sal's words in Echo's history as assistant messages would make
Echo believe it said them. Trade-off: the persona sees "what I overheard"
and "what I said" as two blocks, not one timeline. If that confuses a
persona, a time stamp on each pair would restore the order.

Bystanders don't save to mem0. All personas share the mem0 user ID, so
what the speaking persona saves is found by the others anyway.

## Steps (commit each)

1. This note.
2. IN_CONVERSATION_WITH routing, the 30-second drop, and the bubble
   border.
3. Overhearing, with OVERHEARD_EXCHANGES.

## Later, not designed

- Major or System breaking into a conversation they aren't part of.
- Addressed mode (name anywhere in the first sentence) deciding who the
  conversation is with.
