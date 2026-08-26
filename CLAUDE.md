# Persona

A local voice assistant. Speech and keyboard input are merged into one stream,
which the hub routes to one of four destinations: system commands, external
shell commands, the habitat (chat room of personas), or a broadcast to all
loaded personas.

## Services

| File                     | Port | Role                                  |
|--------------------------|------|---------------------------------------|
| persona_hub.py           | 8400 | Routing, dispatch, chat UI, SSE       |
| persona_llm.py           | 8401 | LLM inference (ollama and others)     |
| persona_speech_output.py | 8402 | TTS (Chatterbox, CPU)                 |
| persona_speech_input.py  | 8403 | STT (Whisper)                         |

Shared dataclasses and state live in `persona_schemas.py`
(state file: `~/.config/persona/state.json`).

Run: `./persona_start.sh [--no-voice] [--no-attach]` — tmux session "persona".
`--no-voice` skips the speech services; use it when verifying hub changes.

## Hardware — AMD, not NVIDIA

This runs on a Strix Halo box (Radeon 8060S, gfx1151) with ROCm 7.2.2
installed. Read `notes/2026-08-10-rocm-amd-port.md` before touching speech
input, speech output, torch, ROCm, or GPU-related dependencies.

Current decision: Chatterbox TTS runs on the CPU. It is faster than the iGPU on
this machine, and it leaves the GPU free for LLM and Whisper work. Whisper is
expected to benefit from the GPU.

## Process — keep the ground solid

The owner may be working with low energy or after interrupted sessions. Before
making important changes, help re-establish solid ground.

- Check `git status --short` before editing.
- If there are uncommitted changes that are not part of the current task, save
  them outside the repo before resetting or cleaning.
- Make one small change at a time.
- Test one service directly before testing the full Persona stack.
- Commit each known-good step before starting the next risky change.
- Prefer explicit handoff notes over relying on memory.

## Code style — read this before writing any code

The owner reads and hand-edits every line, in Emacs. Optimize for readability
at a glance, not density or cleverness. Dense, idiomatic-but-compressed code
has been rejected here before; do not produce it.

- Divide files with section banners: `# ─── Section Name ───────...` out to
  column 80.
- Give every function and route a plain-language docstring.
- No leading underscores on module-level names. This project does not use
  underscore-privacy conventions.
- Generous whitespace: two blank lines between definitions, blank lines
  inside functions to separate steps.
- Columnar alignment in dict literals and config tables is welcome.
- Plain data structures over typing cleverness — a tuple of strings, not a
  `Literal[...]` union. Emacs string-search must be able to find every string.
- Build strings with plain concatenation or simple f-strings. Avoid combined
  prefixes like `rf"..."` — construct regex patterns as
  `r"\b" + re.escape(word) + r"\b"`, in a named variable.
- Delete unused code and empty stubs; do not leave them behind.
- Prefer several small clear files over one long one. Data definitions go in
  `persona_schemas.py`; `persona_hub.py` should read as flow logic only.
- If a construct would look unusual in a tutorial, don't use it.

## Direction (see claude.txt and persona_new.py for the owner's notes)

- Planned: a habitat/room object that owns the loaded personas. Input arriving
  in the room goes to every persona present; each persona (or the room) decides
  whether to reply based on named/open mode. Non-responding personas may still
  "hear" text via prompt injection.
- Dispatch may become its own file; keep the one-input/four-destinations
  structure obvious.
- The dispatch tables (MISHEARINGS, COMMANDS, system commands,
  broadcast introducers) will eventually get a table editor in the chat UI.
- Chat window: rename "Salice" label to "Persona Chat"; add a short tab bar
  (Logs tab, Settings editor tab).
