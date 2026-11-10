# Backstage window, tokens and costs — plan (2026-11-10)

## Goal

See a whole turn: the full prompt sent (system prompt, mem0 memories,
replayed history, new input), each round's reasoning, every tool call and
result, the final reply, and the tokens and cost of each round.

Name: **Backstage** (owner's choice). Spoken command: "show backstage"
(also "show back stage", since Whisper may split the word).

## Facts found

- persona_llm.py `chat()` holds the whole turn in its `messages` list. It
  has two exits: the plain return, and the tools-off call after
  MAX_TOOL_ROUNDS. Record at both.
- Cerebras qwen-3.8-27b returns its thinking in `message.reasoning`
  (DeepSeek-style models use `reasoning_content`). We used to drop it.
  Never put it back into `messages`: Cerebras rejects extra fields.
- Every response has `usage`: prompt, completion, reasoning, cached tokens.
- Prices: `https://api.cerebras.ai/public/v1/models` (no key) lists
  `pricing: {"prompt": "0.00000099", "completion": "0.00000149"}` in
  dollars per token. OpenRouter's model list uses the same shape.
  On 2026-11-10: qwen-3.8-27b $0.99 / $1.49 per million in/out,
  gpt-oss-120b $0.35 / $0.75.

## Steps (one commit each)

a. Record turns: chat() builds a list of steps and posts it to the hub
   (`POST /turn`), which keeps the last few in memory (like the Data
   window). Token counts per round included.
b. Permanent numbers-only tally: `turns` table in tool_log.db (time,
   persona, model, tokens in/out/reasoning/cached, cost).
c. Cost: read prices from the model lists at startup, price each turn.
   Alert at startup when a price changed (owner's request), like the
   new-model announcement.
d. The Backstage window: copy of the Data window's approach, folding
   sections. Share the window-placement code with persona_data_window.py
   instead of copying it. Add its title to the "chat focused" check
   (persona_hub.py, near line 382).

Leave LOG_PROMPTS on until Backstage is proven.

Full turn text is kept in hub memory only (lost on restart); the numbers
are permanent. Owner agreed to this change from the first idea (a turns
table holding everything).
