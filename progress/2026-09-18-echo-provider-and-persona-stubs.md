# Echo provider, for testing with no LLM, and persona stubs

2026-09-18. Two things needed for multi-persona testing: a way to exercise
the whole pipeline (dispatch, voice, speech output) without burning real
LLM calls, and more than one persona actually registered.

## The "echo" provider

`persona_llm.py`'s `/v1/chat/completions` route now special-cases
`provider == "echo"` right at the top, before any real-provider logic
(API key lookup, model selection, the OpenAI client) runs. It returns the
last message's content verbatim, in the normal OpenAI response shape, with
no network call:

```python
if req.provider == "echo":
    heard = req.messages[-1]["content"] if req.messages else ""
    return {"choices": [{"message": {"role": "assistant", "content": heard}}]}
```

Switching a persona's provider to `echo` (via `/provider/echo`, or the
Settings tab's provider dropdown, which now lists it) means anything you
say or type to that persona comes right back, letting you verify dispatch,
wake-word routing, the chat bubble, and TTS without touching a real model.

Also renamed `_PROVIDERS` -> `PROVIDERS` in the same file (no
underscore-privacy convention in this project) while in there.

## Persona stubs

`persona_schemas.py`'s `GlobalState.personas` default factory now
registers, alongside `default`:

| name     | provider | wake words        | notes |
|----------|----------|--------------------|-------|
| `echo`   | `echo`   | "echo"             | ready to use |
| `major`  | cerebras | "major"            | stub -- `system_prompt` is literally `(not yet defined)` |
| `hal`    | cerebras | "hal"              | stub |
| `house`  | cerebras | "house"            | stub |
| `system` | cerebras | "system", "cissy"  | stub -- intended to act as the owner, including filesystem access, once tool-calling exists |

None of these are in `loaded_personas` (still just `["default"]`), so
they're registered but won't respond to anything yet -- there's no UI for
editing the loaded roster (that's the settings-table-editor work mentioned
in `CLAUDE.md`'s Direction section). They exist so the owner can fill in
`system_prompt` and load them later without touching code.

`system`/Cissy's name and role ("System can act as the User/Owner") come
from a comment already sitting at the top of `persona_schemas.py` before
this session -- not invented here.

## Files

`persona_llm.py`, `persona_schemas.py`, `persona_chat.html` (provider
dropdown).

Commit: `3403b88`.
