# 2026-11-04 — Startup provider check, and what's next for it

Branch `data-window`. Built and committed in ea867fc.


## What was built

- At hub startup, `check_providers()` (persona_hub.py, own thread) waits
  for the LLM service, a connected chat page and speech-out, then calls
  the LLM service's `GET /provider_models`.
- `persona_llm.py` asks each provider for its model list the same way
  chat reaches it. Statuses: `ok`, `bad_url`, `no_key`, `key_rejected`,
  `unreachable`, `error`.
- Each result goes to TRACE. It's flagged as an error only for `bad_url`,
  or for a provider a persona uses (Ollama isn't installed, and would
  otherwise flash TRACE at every start).
- Lists are kept in `~/.local/share/persona/model_lists/<provider>.json`
  (`MODEL_LIST_DIR` in persona_schemas.py). See persona_model_lists.py.
- A first listing is kept quietly. A failed fetch never overwrites the
  kept list.
- New models are named in TRACE, and System says
  "New model X seen at provider Cerebras." Past three, it names three
  and counts the rest.
- The check caught the stray-space typo in the OpenRouter URL; fixed in
  the same commit.

First results: Cerebras OK (2 models), OpenRouter OK (454), OpenAI no
key, Ollama unreachable.


## Planned — not built yet

### 1. Hush busy providers to TRACE (wait and see first)

OpenRouter may add models often. A provider that changes a lot could have
its new models named in TRACE only, without System speaking.

- **Don't build until we've seen how chatty OpenRouter actually is.**
- Rule agreed with the owner: **a provider in use by a persona always
  announces new models out loud**, however busy it is.

### 2. Major alert: a model in use has gone away

If the fresh list no longer has a model a persona uses (its
`effective_model()`), that's a **major alert at startup, as early as
possible**, before the owner looks away.

- Use every layer: red in TRACE, System speaks it, raise the chat window,
  notify-send (see the bubble alerts and the failure-visibility review).
- "As early as possible": notify-send doesn't need the chat page or
  speech-out, so it can fire the moment the list comes back. Speaking
  waits for speech-out, as now.
- Guard against false alarms: an `ok` answer with an **empty** list, or
  one far shorter than the kept list, more likely means a provider
  glitch than mass removal. Treat that as a check failure and keep the
  old list.
- A rename (e.g. `qwen-3.8-27b` → `qwen-3.8-27b-instruct`) will show as
  one model gone plus one new. Owner: renames *will* happen, so recovery
  should be easy to find. The alert names the new models from the same
  provider as possible replacements.
- **Okay button to recover** (owner's request). The alert offers the
  likely replacement with an Okay button. Pressing it sets that model for
  the affected persona(s) and carries on, with no typing.
  - Open: if several models are new, list them, with the closest name
    first (most of the old name kept, e.g. `qwen-3.8-27b` →
    `qwen-3.8-27b-instruct`).
  - `set_model()` today only sets the *active* persona's model. The Okay
    button needs to name the persona, so a route like
    `POST /model/{persona}/{model}`, or a persona field.
  - If it applies to several personas on the same gone model, one press
    covers all of them, and the alert says which ones.
  - Pressing Okay counts as a selection for the useful-models count
    (item 3).
  - Possibly also: notify-send `--action` buttons work on some desktops,
    so the Okay could be offered in the desktop notification too. Check
    whether this desktop's notification daemon supports it.
  - Possibly also: answer by voice ("System, okay").

### 3. Useful models list, alert when one disappears

A **useful model** is one that has been selected for use more than twice.

- "Selected" = the hub's `POST /model/{model}` route (`set_model()`),
  the one place a persona's model is set. Count per provider + model.
- Keep the counts next to the model lists (e.g. `useful_models.json` in
  MODEL_LIST_DIR), not in state.json.
- No history exists before this is built, so counting starts at zero.
  Seed it with the models personas use today, so they count from day
  one.
- When a useful model is missing from a fresh list: alert, but less loudly
  than item 2 (it isn't in use right now). Suggest red in TRACE plus System
  speaking it. Owner to decide.

### Also wanted

- A model listing view (the owner has wanted one). The kept lists in
  MODEL_LIST_DIR are the data for it.


## Related

- notes/2026-11-04-failure-visibility-review.md — the wider review of
  alerts, timeouts and quiet failures.
- The home-dir independence plan would move MODEL_LIST_DIR along with
  everything else; it's a single constant.
