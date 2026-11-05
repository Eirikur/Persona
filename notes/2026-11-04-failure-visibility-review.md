# 2026-11-04 — Failure visibility review (planned session)

Status: **planned, not started.** Nothing in this note is built yet.


## Why

On 2026-11-04 every cloned-voice reply had been failing for about two weeks.
A cleanup of `~/AImodels` removed the gated `kyutai/pocket-tts` model, and
there was no Hugging Face token to download it again. Speech-out returned a
500 on every `/speak`. The only visible signs were a flashing Logs/Trace tab
and the speech-out log. The owner doesn't always remember to check the tabs.

Fixed the same day: `uvx hf auth login` (token now in `~/AImodels/token`),
then restart only `persona-speech-out`.

Goal: a failure that blocks use should be impossible to miss, and it should
show up where the owner is already looking.


## Idea from the owner: red bubble outline

Outline a chat bubble in red when its reply could not be spoken or was not
spoken.

Suggestions to decide on during the session:

- Use a separate colour (amber?) for "still waiting, past the normal time",
  so a slow reply doesn't look like a broken one.
- Hover or click a red bubble to see the one-line reason, e.g.
  "speech-out: voice cloning model missing", without opening the Logs tab.
- Existing alerts (wmctrl raise + notify-send, see the bubble alerts work)
  could also fire for "blocks use" failures.

Two waits, two situations (checked 2026-11-04):

- **LLM wait (up to 60 s): no bubble yet.** Only INFERENCE breathes
  (white, or amber during a tool call).
- **Speech rendering (up to 120 s): bubble already shown.** `say()` shows
  the bubble, then calls `speak()`. SPEAKING is amber while rendering,
  green while playing.

So a red outline has somewhere to go during speaking, but not during
inference.


## Options for a stronger alert (decide during the session)

1. **Placeholder bubble — owner likes this one; first feedback they'd
   expect.** A "…" bubble in the persona's font appears the moment
   inference starts. Amber once past normal time, red on failure or
   timeout. The reply replaces it. One spot to watch at every stage, and
   with several personas it shows *which* reply broke.
   Always shown, even for fast providers: on Cerebras it gets replaced
   in a blink; on local inference it's the main feedback.
2. **LED ring.** Physical and visible from the corner of the eye. For
   example a slow amber spin for "working, longer than usual" and a red
   flash for "failed". The ring already follows the hub's state.
3. **Escalate over time.** Calm at first; amber past normal; red + raise
   window + notify-send on failure.

**"Past normal", not a fixed number** — agreed with the owner. Normal
depends on provider (Cerebras vs local), and on whether a tool call is
running (research takes longer). The latency bench
(`persona_latency_bench.py`) already measures typical times.

Possibly related: the open question of whether the state strip stays
global or goes per-persona. A per-reply placeholder carries the state for
that persona.


## Where the signal starts

`speak()` in `persona_hub.py` already catches
`httpx.HTTPError` from `/speak` and only emits a `"log"` event. It doesn't
know which bubble the reply belongs to, so it needs a bubble/reply id
passed in, plus a new SSE event the page can react to.


## The review session — proposed shape

1. **Inventory.** List every call between parts of Persona, with its
   timeout, the errors it can reasonably return, and what the owner sees
   today when it fails.
2. **Sort each failure** into one of three groups:
   - *blocks use* — red bubble, raise window, notify
   - *degraded* — amber or a tab flash
   - *noise* — log only
3. **Catch quiet fallbacks at startup.** PocketTTS started up "healthy"
   without voice cloning. Each service could check at startup that its
   models and token are present, and fail loudly if they aren't. This
   overlaps with the next item.
4. **Build it in small steps,** one service at a time, committing each step
   once it works.

Timeouts and crashes look different and both need handling: a crash comes
back as an HTTP error with a reason, while a timeout is an exception in the
caller with no reason from the other side.


## Starting inventory (timeouts as of 2026-11-04, data-window branch)

Line numbers will drift; search for the URL instead.

| Caller              | Calls                          | Timeout | Notes                          |
|---------------------|--------------------------------|---------|--------------------------------|
| hub                 | llm `/v1/chat/completions`     | 60 s    | two places (async + sync)      |
| hub                 | speech-out `/speak`            | 120 s   | today's failure; log only      |
| hub                 | speech-out `/stop`             | 5 s     | two places                     |
| hub                 | speech-in `/test`              | 10 s    |                                |
| speech-in           | hub `/converse`                | 120 s   | voice and Test input           |
| speech-in           | hub `/recording_start`, `_stop`| 1 s     |                                |
| speech-out          | hub `/playback_start`          | 1 s     |                                |
| llm                 | hub `/tool_call`, `/tool_result` | 1 s | data window feed               |
| mic indicator       | hub `/mic_level`               | 1 s     | high rate; noise               |
| led ring            | hub `/state`, `/events`        | 5 s / none | SSE stream, reconnects?     |
| tools               | research (Perplexity)          | RESEARCH_TIMEOUT |                       |
| tools               | other HTTP tool                | 10 s    | persona_tools.py               |
| tools               | subprocess tool                | 30 s    | persona_tools.py               |
| data window         | xdotool / wmctrl               | 2–10 s  | window placement only          |

Also worth listing: the hub's SSE keepalive wait (15 s), and whatever the
LLM service itself waits on (ollama / other providers).


## Related

- Owner's next step after this: make Persona's models and token independent
  of the home directory (not designed yet). The startup checks in step 3
  fit naturally with that.
- `logs/hub.log` is ~96 MB; log rotation could go into the same session.
