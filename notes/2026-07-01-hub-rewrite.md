# 2026-07-01 — Hub readability rewrite, wake-word fix, audio/ move

Session summary for commit `184c9ba` (pushed to GitHub).

## What changed

- **Readable rewrite of `persona_hub.py`** — section banners, docstrings on
  every function and route, no leading underscores, generous whitespace.
  The dataclasses and `load`/`save` moved out into the new
  `persona_schemas.py`, so the hub reads as flow logic only.

- **Wake-word fix.** The MISHEARINGS table was applied with plain substring
  `replace()`, and the word "salice" contains "alice" — so the correction
  `"alice" → "salice"` mangled every correct "Salice, ..." input into
  "ssalice ...", which never matched a wake word. The loop now does
  whole-word regex replacement:

  ```python
  pattern = r"\b" + re.escape(heard) + r"\b"
  normalized = re.sub(pattern, intended, normalized)
  ```

  `\b` is a word boundary, so "alice" standing alone still corrects, but the
  "alice" inside "salice" (or "malice") is left alone. Verified live:
  "Salice, please reply with the single word ready." → `{"text":"ready"}`.

- **Audio files are now really in git.** `warmup_audio.wav` was a symlink to
  the gitignored `wav/` directory, so GitHub had no audio content at all.
  A new tracked `audio/` directory now holds `warmup_audio.wav` (moved from
  the repo root) and `bird-dream.wav` (Sal's Chatterbox voice template,
  copied from `wav/`, original left in place). References updated in
  `persona_hub.py`, `persona_speech_output.py`, and
  `persona_audio_recorder.py` (two warmup spots).

- **`CLAUDE.md` added** — project map (services and ports) plus the code
  style rules, including: no `Literal[...]` typing cleverness, no combined
  string prefixes like `rf"..."` (build regex patterns with plain
  concatenation in a named variable), delete unused code, banners and
  docstrings everywhere.

- **Owner's notes committed** — `claude.txt` (refactor wish list) and
  `persona_new.py` (habitat/room sketch).

- Also fixed a stray `0` typed at column zero of persona_hub.py line 50
  (syntax error), and deleted `de4686@de4686.rsync.net`, an accidental
  local copy of persona_hub.py from an scp/rsync command missing its colon.

- The `origin` remote was switched from HTTPS to SSH
  (`git@github.com:Eirikur/Persona.git`) to match the `gh` SSH setup, since
  the HTTPS remote couldn't authenticate non-interactively.

## Deferred / still pending

- The `converse()` body from ~line 286 (`for pname in to_respond:` — the
  per-persona LLM call, voice lookup, speaking flag and cooldown) needs a
  clarity rewrite and a walkthrough; deferred today to get a working
  version committed.
- "Fix #2": personas currently receive their own name in the prompt; the
  old single-persona version stripped the wake word before the LLM call.
- The habitat/room design, dispatch split, shell-command launcher feedback,
  and chat-window tabs — see `claude.txt` and `persona_new.py`.
