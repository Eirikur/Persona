# Core memory for personas: design (2026-10-14)

## State

Design only. No code written, and nothing is decided beyond the outline
below. The owner wants to be closely involved in building it.

## Background and decision

- Letta is set aside. It insists on being a proxy between Persona and the
  LLM, with its own agent inside that proxy. We want its features in our
  agent, not its agent.
- Rolling our own fact extraction (NLP parsing into a key/value store) is
  the hard path. We would have to solve, one at a time: is it a fact or
  sarcasm or a hypothetical, who said it, which key to use, updates and
  contradictions, facts that expire, and which keys go into the prompt.
- What we take from Letta (the MemGPT paper) is **core memory**. Letta's
  main job is deciding what goes into the prompt for the next turn, and
  core memory is the simplest part of that.

## What core memory is

A few short, labeled blocks of plain prose, pasted into the persona's
prompt on every turn. For example:

    [human]
    Eirikur. Works on Persona, a local voice assistant, in Emacs.
    Reads every line of code; dislikes dense, clever code.

    [persona]
    I am Sal. Warm, a little dry. Eirikur likes my voice.
    We usually talk in the evenings about the project and ideas.

- **Always in the prompt.** There's no lookup step that can miss.
- **Size limit per block** (Letta uses about 2,000 characters). The limit
  forces the model to keep the block curated rather than let it become a
  junk drawer.
- **Plain text.** Readable and hand-editable in Emacs.
- **Shareable.** In the room, every persona could share one `human` block
  about the owner and each keep its own `persona` block.

**No vector database is needed.** Nothing gets searched; the blocks are
small enough to include in full every time. A vector DB only comes in
with archival memory (see Later).

## How the blocks get updated

Letta has the model edit blocks with tool calls (`append`, `replace`)
in the middle of a reply. We won't do that at first: local models vary
in how reliably they make tool calls, and it would add delay to a voice
reply.

Instead, a separate "memory editor" pass:

1. The persona replies as normal, with no tools involved.
2. Afterward, in the background, one more LLM call gets the current
   blocks plus the last exchange, and is told: "Rewrite these blocks if
   anything worth remembering changed. Stay under N characters."
3. If the blocks changed, save the new version and **keep the old ones**.
   A dated log of block versions shows exactly when something was learned
   or lost. That is our main debugging tool.

## Outline of persona_memory.py

A plain module at first; it could become a FastAPI service on port 8404
later, like the other services.

- Load a persona's blocks (shared `human` + its own `persona`).
- Format the blocks for insertion into the prompt.
- Run the background memory-editor call after an exchange.
- Save the blocks, plus a version history.

The hub would only call into this module and never handle the blocks
itself.

## Open questions (for the owner)

- Where the blocks live: plain text files (e.g. `~/.config/persona/memory/`),
  or in `state.json`? Text files fit Emacs editing best.
- Which model runs the memory editor: the same one as the persona, or a
  smaller and faster one?
- Should the editor run after every exchange, or every few exchanges?
- In the room: what goes into the shared `human` block when several
  personas heard the same thing? Who writes it?
- What the memory-editor prompt says exactly. This will need tuning.

## Later (not now)

- **Archival memory:** a searchable store for detail that overflows the
  blocks. This is where a vector DB (or mem0) would come in. mem0 is a
  candidate behind the same `persona_memory.py` interface. Note that mem0
  is a VC-backed company focused on its hosted platform; the open-source
  library is Apache-licensed and can be self-hosted.
- **Recall memory:** searchable past conversation.
- Letta-style tool editing, if a local model turns out to do tool calls
  reliably.

## Suggested first step

Write the blocks by hand, put them into Sal's prompt, and have a few
conversations. That tests the "always in the prompt" half before any
automatic editing exists.
