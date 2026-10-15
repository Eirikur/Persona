# 2026-10-15 — data window, research tool, tool log

Branch `data-window` (off `speak-over-queue`; neither merged to main).

## What was built

- **Data window** (7e268bc, 2fcb585, 52fd974). `persona_llm.py` reports
  every tool call to the hub's `/tool_result`; `persona_data_window.py`
  keeps the last 50 in memory (lost on hub restart). `persona_data.html`
  shows each one, newest on top: what the persona was answering, the
  arguments it sent the tool, what came back, and (for research) the full
  API response under "full data". "show data" / "show the data" /
  "show me the data" anywhere in the input opens it flush against the
  chat window's right edge, or raises it if open. Started via
  `systemd-run --user`, so restarting the hub doesn't close it.
- **Perplexity as a persona's model switched off** (f1c38df). Sonar's
  /chat/completions was retired. Kept as a commented-out line in
  PROVIDERS: wanted back later as a persona of its own, with follow-up
  questions (`previous_response_id` in the Agent API looks like the way).
  `.env` key renamed to `PPLX_API_KEY`.
- **research tool** (5beae97). Perplexity Agent API, `/v1/agent`.
  depth quick → preset `fast` (~2 s), normal → `low` (~5.5 s); each well
  under a cent. `deep` → `medium` is defined but not allowed
  (RESEARCH_ALLOWED_DEPTHS) until it can run in the background. The
  persona gets the answer with `[web:n]` markers removed plus a numbered
  source list. Tools may now return `{"text": ..., "data": ...}`.
- **Tool log** (0846bf5). `persona_tool_log.py`: every tool call, with the
  persona's final reply, in `~/.local/share/persona/tool_log.db` (SQLite,
  table `tool_calls`).

## Not done

- Sal got `research` 2026-10-15 by a one-time script edit of `state.json` (hub stopped). A spoken/settings way to change tools is wanted later.
- The data window could read history from the tool log, so it survives
  restarts.
- Deep research as a background job (persona says "I'll look into it",
  a bubble arrives later).
- Perplexity follow-ups.

## Observed

Asked about the Black Sea tanker, Sal called news_read, web_search and
research (10 s), then said the drones were "almost certainly Russian".
Perplexity's own answer said Russian involvement was suspected, not
confirmed. The data window is how to catch that.
