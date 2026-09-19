# Always show heard/typed input as a bubble; typed input gated like voice

2026-09-18. Two related bugs in `persona_hub.py`'s dispatch/converse flow,
found while setting up for multi-persona testing.

## Bug 1: unaddressed speech never showed up in the chat window

The chat window only added a "you" bubble when `user_turn` fired, and that
only fired when at least one persona was going to respond. So if you spoke
in named mode without a wake word, nothing appeared at all -- not even a
sign that the mic heard you. The STT preview line briefly showed the raw
text, then vanished.

Fix: `emit("user_turn", req.text)` now fires unconditionally, right after
`dispatch()` returns, before the "did anyone respond" check. Speech and
typed input both always produce a bubble now, whether or not a persona
answers.

This created a side effect: the on-screen INFERENCE label and the LED
ring's inference look were both wired to the `user_turn` event, so an
unaddressed utterance would falsely flash INFERENCE for ~2 seconds with
nothing happening behind it. Fixed by splitting the signal -- `user_turn`
is bubble-only now; a new `inference` event (emitted right before the LLM
call, once per persona in `converse()`) drives the INFERENCE state. The LED
ring's `EVENT_TO_STATE` was updated to match (`inference` -> inference,
`user_turn` dropped from that table entirely).

## Bug 2: typed input bypassed the wake-word gate

`dispatch()` had `if MODE == "named" and not typed:` before the wake-word
check -- meaning typed input always fell through to "respond with every
loaded persona," in both named and open mode, regardless of wake word.
With one persona this was invisible (of course Sal replies to typed text).
With more than one persona loaded, it means you can't address a specific
persona by typing their name -- everyone answers every typed message.

Fix: removed `and not typed`. Typed and voice input are now gated
identically -- in named mode, the text must start with a loaded persona's
wake word. Concrete effect: typing "hello" in named mode now gets no
response (same as saying it), typing "salice hello" gets Sal. This was
confirmed as the intended behavior, not just an artifact of the fix.

`dispatch()` no longer takes a `typed` argument at all -- it was only ever
used for this one check.

## Files

`persona_hub.py` (dispatch, converse), `persona_chat.html` (split
`user_turn`/`inference` handlers), `persona_led_ring.py` (`EVENT_TO_STATE`).

Commit: `3403b88` (bundled with the echo-provider work from the same
session -- see `2026-09-18-echo-provider-and-persona-stubs.md`).
