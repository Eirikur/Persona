# 2026-11-20 — Memory window (mem0 searches and saves)

Branch `mem0-window`, not merged. Live-tested by the owner: typed facts to
Sal, saw the save and mem0's decisions, then a mention of the Kerch bridge
recalled the earlier turn's facts.

## What was built

- **persona_memory_window.py** — keeps the last 50 records (search or
  save) in memory, like persona_backstage.py. Each record names its memory
  system (`"mem0"`), so another one (Cognee, say) could share the window.
- **persona_memory.py** — `mem0_search()` and `mem0_save()` return what
  happened instead of only printing it. New `mem0_follow()` polls
  `GET /v1/event/{event_id}/` once a second (up to 40 s) until mem0 has
  decided, and returns the decisions plus mem0's raw results.
- **persona_hub.py** — `show_memory_record()`, `save_to_mem0()` (runs in a
  thread: record as pending, follow, update the same record, notify again),
  routes `/memory/recent` and `/memory/{id}`, "memory" event notices,
  MEMORY_PHRASES ("show memory", "show memories", "show mem zero", typed
  "show mem0"), and the window counts as a side window for raise_chat_window.
- **persona_memory.html** — newest on top. Search: what was searched for,
  each hit with score and when it was kept (local time). Save: the exchange
  sent, then ADD / UPDATE / DELETE lines, raw answer folded. A pending save
  is replaced in place when mem0 decides. Header says whether mem0 is on.

Commits: 0eece52, cf08f7b, 6350608, 1e877ac. The roster-on-reconnect fix
from 2026-11-11 was committed on main first (42c8645).

## What mem0 actually does (observed)

- Add answers `{"event_id", "status": "PENDING"}` at once; the event goes
  RUNNING then SUCCEEDED after 3-5 s for short exchanges, 13.5 s for a
  long reply.
- Event `results` entries: `{"id", "event": "ADD", "data": {"memory"}, ...}`.
  Search hits use `"memory"` directly, plus `score` and `score_breakdown`
  (semantic, bm25, entity).
- It keeps facts from the persona's reply too, labeled "Assistant
  clarified that ...", and keeps the owner's wrong claims as "User claimed
  that ...". One exchange gave five ADDs.
- A correction ("Pixel is black, not grey") was a second ADD, not an
  UPDATE; both versions then came back from search at nearly equal scores.
  UPDATE and DELETE have not been seen yet; the raw answer is kept for
  when they are.

## Merge and push plan (owner approved, 2026-11-20)

1. Commit this note on `mem0-window`.
2. `git switch main`, then `git merge --ff-only mem0-window`. main has not
   moved since the branch began (42c8645), so it fast-forwards; no merge
   commit, nothing rewritten.
3. `git push origin main`. This also carries 5 earlier commits that were
   never pushed: e2ba7c9, 159c3a1, 5353f43, 269f434 (2026-11-11 room
   fixes) and 42c8645 (roster on reconnect).
4. The live hub runs from the working tree, which is identical after the
   fast-forward, so it needs no restart.

## Open ideas (not built)

The owner asked to keep the first two for later (2026-11-20).

- **Score cut-off for search.** BUILT 2026-11-23 on `mem0-score-cutoff`:
  MEM0_MIN_SCORE = 0.12 in persona_schemas.py (the Kerch test had related
  hits at 0.16-0.31, unrelated at 0.04-0.08). Weaker hits stay in the
  Memory window, dimmed and marked "not used"; only used hits reach the
  prompt. Each search record keeps the cut-off it was made with.
- **"List everything mem0 holds"** view, as opposed to the per-turn log.
- **Event polls vs free tier.** Each save makes about 4-5 event lookups.
  Check the mem0 dashboard to see whether those count; if they do, wait
  ~2 s before the first poll.
- **Cognee as a second watched memory system** (owner's idea, not asked for).
- The search runs on the whole input, "Sal," prefix included.

## Side issue the same evening

The chat input stopped taking keys (cursor blinks, F5 does nothing) after
a restart. Cause was outside Persona: `~/.cache/ibus/` (ibus's socket) had
been deleted while ibus-daemon kept running. Fix:
`pkill -x ibus-daemon; ibus-daemon --daemonize --xim`. Quick check: a
reload always logs `GET /ui/persona_chat.html` in logs/hub.log; none means
keys aren't reaching Chromium.
