# Memory: conversation replay + optional mem0 (2026-11-05)

## State

Built and tested on branch `memory` (off `data-window`), two commits:

- 73133cb  step 1: replay
- 116021d  step 2: mem0 + Settings checkbox (+ hub log line-buffering)

Not merged. Only the hub needs restarting to pick it up; persona_llm.py is
unchanged.

## What it does

- **Replay (always on).** Each persona keeps its last 10 exchanges with
  the owner and sends them with every new message. Follow-up questions
  work. In memory only: a hub restart forgets everything.
- **mem0 (Settings tab, "memory" box).** Before each reply the hub searches
  mem0 for the 5 memories closest to the input and appends them to the
  system prompt under `Memories:`. After the reply, the exchange goes to
  mem0 in the background, and mem0's own LLM decides what to keep. These
  memories survive restarts.
- **The whole prompt is printed to the hub log** on every call
  (`LOG_PROMPTS`), along with mem0 hits, scores and timings. Read it in the
  Logs tab or `logs/hub.log`.

## Defaults chosen (all in persona_schemas.py, section "Memory")

| Setting             | Value     | Why                                          |
|---------------------|-----------|----------------------------------------------|
| REPLAY_EXCHANGES    | 10        | plenty for follow-ups, prompt stays small    |
| LOG_PROMPTS         | True      | the owner wants to see exact prompts         |
| MEM0_USER_ID        | "eirikur" | memories are about the owner; all personas share them |
| MEM0_TOP_K          | 5         | same as mem0's companion example             |
| MEM0_SEARCH_TIMEOUT | 3.0 s     | the spoken reply waits on the search         |

- The mem0 box starts **off** on every hub start, like mode. It is not
  saved to state.json (adding fields there breaks older branches; see
  the state.json branch-drift memory).
- The hub refuses to switch mem0 on without `MEM0_API_KEY`; the box
  un-ticks itself.
- Echo never uses mem0.
- `/think` stays single-turn (no callers found).

## Observed during testing

- mem0 search took 0.5-0.8 s; that is added to every reply while mem0 is on.
- mem0 add answers `PENDING` in about 0.5 s; the memory becomes
  searchable about 5 s later. Replay covers that gap.
- mem0 rewrites facts in third person: "User's sister Gudrun lives in
  Reykjavik and plays the cello". It stored nothing for "just say ok" or
  for a question about something it already knew.
- All test memories were deleted from the mem0 account afterwards.

## Known limits

- **Research results are not replayed.** Tool rounds happen inside
  persona_llm.py, so the replay holds Sal's spoken summary, not
  Perplexity's full answer. A follow-up that needs detail Sal didn't say
  aloud will miss. Fix: have persona_llm.py return the tool messages too,
  and keep them in the history (the tool_call_id pairing must be kept
  intact).
- **Multi-persona:** each persona replays only its own exchanges. It
  doesn't hear what the other personas said.
- No way to clear replay without restarting the hub. A "forget" command
  would be easy to add.

## Next (owner's plan)

- **Conversation Trace window**: show each call's exact prompt, mem0
  search request and results, mem0 add request and event id, and the
  reply. Model it on the data window (persona_data_window.py). Note that
  the chat window already has a tab called "Trace" (the events tab), so
  the new window's name may need thought.
- mem0's `event_id` can be looked up later to see what mem0 actually
  decided to store from an exchange. That is the instrumenting step.
