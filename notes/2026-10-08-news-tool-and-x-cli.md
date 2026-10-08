# 2026-10-08 — news_read tool (BBC), and why X search is parked

Goal: give personas a way to hear "what is happening now", ideally from people
on the ground (Ukraine was the test case).

## What was built

- `persona_tools.py`: new `news_read` tool. Runs a news command-line program,
  reads its JSON lines, optionally filters by keyword, returns plain sentences
  (title. description. (published time)). URLs are dropped; they are no use
  spoken aloud.
- `persona_schemas.py`: new `NEWS_SOURCES` table (program, env var, sections)
  and `NEWS_MAX_ITEMS = 8`. Adding a source means installing its program and
  adding one entry.
- Tested directly (not through the stack): keyword filter, section, bad
  section, no-match, all behave. Live BBC world feed returned today's items.

## To switch it on (not done yet)

1. Put `BBC_BIN=/home/eh/Projects/External/tamnds-data-access-modules/bbc-cli/bin/bbc`
   in `.env` (or put `bbc` on PATH).
2. Add `"news_read"` to a persona's `tools` list. The default persona is
   `tools=["web_search"]` in `persona_schemas.py`, but an existing
   `~/.config/persona/state.json` may override it, so check there too.
3. Restart the LLM service. Not yet tried end to end through the hub.

## The BBC program

- Source: `tamnd-data-access-modules/bbc-cli` (Go). Reads BBC's public RSS
  feeds. Headline + one-sentence summary only, no article text. No search.
- Build quirk: its go.mod says `go 1.26`, which Go cannot download, and the
  system Go is 1.22. Build with:
  `GOTOOLCHAIN=go1.26.5 go build -o bin/bbc ./cmd/bbc`
- The `world` feed holds only a couple of Ukraine items at a time.
  There is probably a `world/europe` feed; not checked whether `bbc feed`
  accepts it.

## X (x-cli) findings

`x` (same family, `x-cli`, built with `make build`) works for single tweets,
profiles, threads and trends with no login. It is read-only.

- `x timeline <user>` without a session is NOT a live feed. It returns a
  selected window of posts, out of date order. Tested on three Ukrainian
  accounts: newest posts were 2026-10 (one account), 2025-07 and 2023-04.
  `--guest` returned the same posts. Not usable for current events.
- `x trends [woeid]` works but is rate-limited (exit code 5, ~90 s window).
  Worldwide trends were dominated by Asian-language hashtags.
- `x search` (the real tool for this) needs the owner's logged-in session:
  `x auth import --auth-token ... --ct0 ...` (cookies copied by hand from the
  browser; the binary does not extract them). Nothing is imported.
  Owner would need a new X account; signup is difficult, so this is parked
  while the owner researches it. A secondary account is advisable because
  automated reads through a session can get an account flagged.
- Persona integration, if resumed: add an `x_search` tool in the same shape
  as `news_read`; trim to author, time, text; cap at ~5; handle exit code 4
  (needs session) and 5 (rate limited) without retry loops.

## The wider family

`tamnds-data-access-modules/` holds ~10 CLIs sharing a framework
(`any-cli/kit`): amz, archive, bbc, britannica, csfieldguide,
deeplearningbook, dictionary, ytb, x, plus `ant` (one URI address space over
all of them) and `any` (scaffolds a new site CLI: `any new <site>`). None are
installed on PATH. `news_read`'s `NEWS_SOURCES` table is meant to take more
RSS-style CLIs (Al Jazeera, DW, Kyiv Independent, Ukrainska Pravda English
publish RSS). Reuters/AP/UPI are not in the family and mostly restrict feeds.

## Next

- Owner is looking at Perplexity (already a provider in `PROVIDERS`;
  default model `sonar`, which searches the web itself) as an alternative
  route to current events.
- Try `news_read` end to end through the hub, with a persona that has it.
