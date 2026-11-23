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

A list of the personas the owner is talking with ([] = nobody). For now
naming a persona replaces whoever was in it, so it holds at most one; the
list is there so a conversation can later hold several (how a second
persona joins is the owner's to decide). It lives on
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

While a conversation is in effect, the persona's newest bubble gets a
highlight border (--accent-sal, the gold), moving to each new bubble, and
its name in the roster turns gold. The owner's bubbles don't change. Both
go back to normal when the conversation ends. It uses the
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

    Earlier, you overheard these exchanges in the room. They were not
    addressed to you, so you did not reply to them:
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

1. This note. (a886a41)
2. IN_CONVERSATION_WITH routing, the 30-second drop, and the bubble
   border. (831036d) Tested by typed /converse lines: unnamed lines reach
   only the partner, naming switches partner, go quiet / open mode /
   leaving the room / 30 s of quiet each end it. The clock waits while
   the persona thinks (`replying`) or talks (`speaking`).
3. List instead of one name, newest bubble only, roster name gold.
   Checked in headless Chromium driven over its debugging port.
4. Overhearing, with OVERHEARD_EXCHANGES (0 = off), OVERHEARD_OWNER_LABEL
   ("User") and OVERHEARD_HEADER in
   persona_schemas.py; overhear() / overheard_block() in
   persona_memory.py. Tested: told Sal a container number, Echo answered
   it; Sal then knew what Echo said. Backstage shows the block at the end
   of the system prompt. Every reply is overheard by everyone else in the
   room, so in a broadcast a later persona sees the earlier ones' answers
   to the same line.
5. OVERHEARD_HEADER reworded to the past tense. A persona reads it only
   when it is addressed itself (that is when its prompt is built), so the
   first wording's present "do not respond" could be taken as being about
   the current line. Now: "Earlier, you overheard these exchanges in the
   room. They were not addressed to you, so you did not reply to them:".

## Side effects told to the owner

- Sal alone in named mode no longer listens until "go quiet"; unnamed
  lines stop reaching her 30 s after she speaks. persona_sal.sh uses open
  mode, so it is unaffected.
- The first-word false alarm costs more now: with House out of the room,
  "House prices are up" to Sal gets System's miss notice and Sal never
  gets the line. Addressed mode is the later fix.

## Later, not designed

- Personas-only conversations: the owner decided not to go there for now
  (2026-11-23). A reply handed on to another persona is a feedback loop
  and would need a stopping rule (turn cap, time cap).
- How a second persona joins a conversation (add or replace).
- One clock and one `replying` flag serve the whole room; two
  conversations at once would each need their own.

- Major or System breaking into a conversation they aren't part of.
- Addressed mode (name anywhere in the first sentence) deciding who the
  conversation is with.
