# Search tool design: fetch_page and perplexity_search (owner + Claude, 2026-09-27)

Converted from a saved Claude Code session transcript (`tools-chat-session.txt`,
a different working session in this same directory). Two tool ideas came out
of it; neither is built.

## How web_search already works (context for the ideas below)

The owner asked why Sal's search answers read as her own knowledge instead of
raw search output. Traced through the code:

1. `web_search()` in `persona_tools.py` hits Brave, keeps the top 5 results,
   and reformats each as `title -- url\ndescription`. Already trimmed, not
   raw JSON, but still metadata, not prose.
2. That trimmed text goes back into the message list as a `role: "tool"`
   message (`persona_llm.py:133`) — it's appended to what the model sees, not
   sent to the chat UI directly.
3. The tool loop (`persona_llm.py:112`, inside `for _ in
   range(MAX_TOOL_ROUNDS)`) calls the LLM again with that tool result in
   context. Sal, still under her own system prompt, writes a fresh reply
   using the snippets.
4. Only that second (or third) completion is shown as her bubble.

So there's no separate summarization step — the same persona and system
prompt that write her normal answers write the search-informed one, which is
why it sounds like her own knowledge. Owner: keep `web_search()` exactly as
it is, this result is good and shouldn't be disturbed.

## Idea 1: fetch_page(url) — a "get me X" tool

Owner's observation: some requests are "get me the data" rather than "what
is," and that distinction might be better handled as a second tool than as a
parser or mode flag on the existing one.

Design: no fork in behavior needed between "what is" and "get me." Add
`fetch_page(url)` alongside `web_search` as a second tool. The existing loop
already runs up to `MAX_TOOL_ROUNDS = 3` (`persona_llm.py:108`), so Sal can
call `web_search`, see the five snippets, and decide for herself whether the
description is enough or whether she needs `fetch_page` on one of the URLs
for the actual page text. No new routing logic — the phrasing difference is
exactly the kind of judgment call a tool-using model makes on its own.

The one new piece of work: raw HTML from an arbitrary page is messy, so
`fetch_page` needs an HTML-to-readable-text extraction step (a library like
`trafilatura`) rather than returning `response.text` as-is.

Not built. Plan when picked up: draft `fetch_page` in `persona_tools.py`,
same shape as `web_search`, tested standalone before it's wired into a
persona's tools list.

## Idea 2: perplexity_search() — Perplexity as a second search tool

Owner uses Perplexity's free web UI and likes the model, but the free tier
has scraping protection. Wants a Perplexity tool alongside the Brave one,
willing to pay for API use but not for a bundled subscription.

Research (2026-09-27, web search): use Perplexity's Sonar API, not the free
web UI — a separate product from Perplexity Pro, billed independently.

- No subscription needed: prepaid credits, no minimum, at
  perplexity.ai/account/api/keys. (Pro subscriptions no longer include free
  API credits — that perk ended Feb 2026.)
- Cost is low for occasional use: base `sonar` model ~$1/$1 per million
  tokens (small tier $0.20/$0.20), plus a flat per-request search fee of
  $5-12 per 1,000 requests depending on search-context depth
  (low/medium/high) — roughly half a cent to a cent per query. A $5-10
  prepaid balance would last a long time at voice-assistant query volumes.
- OpenAI-compatible: same `chat.completions.create()` shape `persona_llm.py`
  already uses for other providers, pointed at `https://api.perplexity.ai`
  with model `sonar` (or `sonar-pro`). Responses include citations, so the
  tool can return `title -- url\ndescription` blocks exactly like
  `web_search` does, keeping the same "Sal synthesizes it" pattern.

Design: `perplexity_search()` in `persona_tools.py`, structurally a near-twin
of `web_search()` — calls a chat-completions endpoint instead of a search
endpoint — gated by its own env var (`PERPLEXITY_API_KEY`).

Not built. Owner wants both this and `fetch_page` (2026-09-27: "I think I
want both").

## Adjacent idea, out of scope here: guest personas

Owner's separate future vision, explicitly called out as different from
either tool above: cloud/API models appearing directly in the chat room as
"guest" personas, rather than a local persona calling out to them as a tool.
Not designed, not started — noted so it isn't lost.
