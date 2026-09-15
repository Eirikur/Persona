# LED ring color research

Prompted by tuning `persona_led_ring.py`'s `STATE_LOOKS` after the ReSpeaker
LED ring went live (2026-09-14). No single canonical study exists for
"voice assistant status ring" colors, but two real anchor points are worth
knowing.

## IEC 60073 (industrial indicator-light standard)

- **Red** — stop / emergency / fault
- **Yellow / amber** — warning / caution / abnormal condition
- **Green** — normal / safe / go
- **Blue** — mandatory action / informational
- White / grey — auxiliary or indeterminate states

A lot of consumer status-light design echoes this loosely, even where
nobody consciously referenced the standard.

## Amazon Echo light ring (closest direct precedent)

Heavily user-tested, and the most directly comparable product (voice
assistant, ring-shaped, always-on mic array):

- **Blue** (solid, or pulsing blue/cyan) — actively listening / processing
  a request
- **Red** — mic muted/off (used for nothing else)
- **Green** — live call / drop-in (spinning = incoming, pulsing = active)
- **Yellow** — non-urgent notification waiting
- **Purple** — do-not-disturb / setup issue
- **Orange** — setup mode / connecting
- **White** — volume level feedback

The open-source `assistant-ui` VoiceOrb component converges on something
similar: grey idle, amber connecting, green listening/speaking, red muted.

## The one strong convergent signal

**Red reserved specifically for "muted"** shows up independently in Alexa
and in `assistant-ui` — that's the most battle-tested single convention
here, and worth reserving even though Persona's current palette doesn't use
red for anything yet.

## Persona's current mapping, for comparison

`persona_led_ring.py`'s first-pass `STATE_LOOKS` (not tuned, just functional):

| Pipeline state | Color            | Look |
|-----------------|-------------------|------|
| listening (idle)| —                 | DOA tracking (effect 4) |
| transcribing    | `0x3050FF` blue   | single color (effect 3) |
| inference       | `0xFFA000` amber  | single color (effect 3) |
| speaking        | `0x30C060` green  | single color (effect 3) |

This doesn't match any one product exactly, but it's a coherent read of the
same underlying logic (neutral/active → caution/in-progress → positive/
complete) rather than Alexa's channel-based mapping (whose audio is this).
Worth trusting the intuition here; the main gap is mute has no reserved
color yet.

## Sources

- [Alexa light ring colors explained](https://www.gearbrain.com/what-alexa-light-colors-mean-2647105676.html)
- [Echo & Alexa Light Colors — Amazon](https://www.amazon.com/gp/help/customer/display.html?nodeId=GKLDRFT7FP4FZE56)
- [Industrial Indicator Lamp Color Standards (IEC 60073)](https://industrialmonitordirect.com/blogs/knowledgebase/industrial-indicator-lamp-color-standards-iec-60073-iso-conventions)
- [Orb / VoiceOrb — assistant-ui](https://assistant-ui.com/docs/ui/voice)
