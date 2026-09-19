# Tool-calling for personas, with a Brave-backed web_search tool for Sal

2026-09-18. First step toward personas that can act, not just talk --
prompted by wanting Sal to be able to answer "what's happening right now"
questions instead of only what's in the model's training data.

## Design

Personas don't need to be Python objects to get programmed behavior. A
persona is a plain data record; a string field on it (already true of
`provider`) is looked up in a small table by whichever service needs that
behavior. Tool-calling follows the same shape:

- **`persona_tools.py`** (new) -- a registry: tool name -> OpenAI-style
  function schema + a plain Python function that runs it. One tool so
  far, `web_search`, backed by the Brave Search API (`BRAVE_API_KEY` in
  `.env`). Adding a tool later is: write the function, write its schema,
  add one line to `TOOLS`.
- **`Persona.tools: list[str]`** (new field, `persona_schemas.py`) --
  names into that registry. `default` (Sal) has `["web_search"]`; nobody
  else does yet.
- **`persona_llm.py`** -- `/v1/chat/completions` now takes a `tools: list[str]`
  field, looks up the matching schemas, and passes them to the model. If
  the model asks for a tool call, the handler runs it and the result is
  fed back for up to `MAX_TOOL_ROUNDS` (3) rounds before returning
  whatever the model says last.
- **`persona_hub.py`** -- `llm()` passes `persona.tools` through in the
  request payload. That's the only hub-side change; dispatch and
  `converse()` don't know or care that a tool call happened.

## A real bug, found and fixed

First attempt crashed against Cerebras with a 400: `messages.2.assistant.refusal:
property 'messages.2.assistant.refusal' is unsupported` (and three more like
it). The OpenAI SDK's `message.model_dump()` includes a bunch of
`None`-valued fields (`refusal`, `annotations`, `audio`, `function_call`)
that OpenAI's own API tolerates but Cerebras's stricter OpenAI-compatible
endpoint rejects outright. Fixed by building the assistant message
by hand with only the fields that matter (`role`, `content`, `tool_calls`)
instead of dumping the whole SDK object back into the next request.

## Verified live

Directly against `persona_llm.py` and through the full `/converse`
pipeline, with a real Cerebras model (`qwen-3.8-27b`) and, once the Brave
key was added, real search results (confirmed against live weather,
SpaceX news, and Bitcoin price queries -- the numbers were current, not
memorized).

## Known gaps, not addressed

- No confirmation gate for tool calls -- fine for `web_search`
  (read-only), but explicitly agreed this is required before any
  destructive tool (filesystem write, shell exec) gets added for `system`.
- Tool-calling support is provider/model dependent; not every
  provider+model combination is guaranteed to support it.
- `.env` (holds `CEREBRAS_API_KEY` and `BRAVE_API_KEY`) was not in
  `.gitignore` before this session -- added, since it wasn't tracked but
  could have been committed by accident.

## Files

`persona_tools.py` (new), `persona_llm.py`, `persona_schemas.py`,
`persona_hub.py`, `.gitignore`.

Commit: `3403b88`.
