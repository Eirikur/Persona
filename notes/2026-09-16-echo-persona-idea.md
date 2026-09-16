# Idea: an "Echo" persona for smoke testing

Captured verbatim from the owner, mid-session on 2026-09-16, while debugging
the LED ring state machine:

> Put Sal on the shelf for a while. Create a new persona named Echo. Its
> behavior bypasses the LLM and simply speaks/types the user input. I'm
> strangely socially awkward about "bothering" Sal with smoke tests. She
> always wants to help.

## What this would mean

A persona whose `provider`/response path skips `llm()` entirely and just
echoes the input text back (spoken via TTS, and/or typed into the chat) —
same wake-word/dispatch/state-machine plumbing as any other persona, but with
a trivial "responder" instead of an LLM call. Useful for testing the
recording → transcribing → inference → speaking → resting pipeline (and now
the LED ring) without spinning up a real model or feeling like you're
wasting Sal's help on a test.

Not built yet — just filing the idea so it isn't lost. Loading/multi-persona
plumbing is already flagged for cleanup (see CLAUDE.md's Direction section),
so this is a candidate to fold into that pass rather than a one-off hack.
