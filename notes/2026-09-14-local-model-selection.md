# Local model selection for persona_llm.py

This is about the model Persona *runs on* at inference time (the `ollama`
provider in `persona_llm.py`), not about which model drives the coding agent.
Those are separate problems — see the machine facts in
`2026-08-10-rocm-amd-port.md`, which this note assumes.

## What's actually installed right now

```
$ ollama list
NAME                                  ID              SIZE
qwen3.8-flash-next:125b-a6b-q4_K_M    f79436a1cc83    120 GB
```

That's a 125B-total / ~6B-active MoE quant, ~112 GB on disk
(`/usr/share/ollama/.ollama/models`, confirmed via `du -sh`).

**This is very likely the whole reason local development felt slow.** Ollama's
own log for this box shows:

```
inference compute ... type=iGPU total="96.0 GiB" available="95.8 GiB"
add: tensor per_layer_token_embd.weight (size = 33569 MiB) lazy read enabled
```

The model is bigger than the 96 GiB VRAM budget the GPU reports, so ollama
falls back to lazy-reading weight tensors off disk instead of holding them
resident — one embedding tensor alone is 33.5 GB. That turns every token into
partial disk I/O instead of pure compute. No model this size was going to feel
responsive here, regardless of ROCm being set up correctly (it is — `ROCm0
gfx1151` is detected and used, this isn't a driver problem).

## The hardware constraint that actually matters

Strix Halo is a **unified-memory APU**, not a discrete GPU with dedicated
VRAM. The 96 GiB "VRAM" ollama reports is a BIOS UMA carve-out of the same
LPDDR5X pool the CPU uses — quad-channel, roughly 256 GB/s. That's about a
quarter of what a discrete card like a 4090 has. Two consequences:

- **Capacity is generous (96 GB); bandwidth is the real ceiling.** Token
  generation speed is bounded by how many bytes have to stream from memory
  per token, not by whether the model "fits."
- **This favors small-active-parameter MoE models over big dense ones.** A
  dense 30B model streams all 30B params' worth of weights every token. A
  30B-total/3B-active MoE model streams roughly a tenth of that per token —
  much faster on bandwidth-bound hardware — while still fitting entirely
  resident in the 96 GB budget instead of lazy-reading from disk.

For a voice assistant, latency per turn matters more than raw benchmark
scores. A mid-size model that answers in under a second beats a huge one that
takes ten.

## Measured results

All four candidates were pulled and run on this box (`ollama run --verbose`,
same one-sentence prompt: *"You are Persona, a helpful voice assistant. In
one short spoken sentence, what time zone is UTC based on?"*). Numbers below
are from actual runs on 2026-09-14, not estimates.

| Model            | Shape              | Disk size | Eval rate (default) | Time to spoken answer | Notes |
|-------------------|---------------------|-----------|----------------------|--------------------------|-------|
| Qwen3-30B-A3B      | MoE, 30B/3B active  | 18 GB     | **73.7 tok/s**       | 4.5s (eval), worse with `think:false` | Fastest raw throughput, but is a reasoning model that thinks by default — see below. |
| gpt-oss:20b        | MoE, ~3.6B active   | 13 GB     | 50.6 tok/s           | **2.46s with `think:false`** | Only candidate that properly honors the API's `think: false` flag — cut output from 186 to 123 tokens and dropped eval time from 3.68s to 2.46s. |
| Qwen3-8B (dense)   | dense               | 5.2 GB    | 39.3 tok/s (slowest) | 10.4s (worst of all four) | Worst combination: slowest raw tok/s *and* the in-prompt `/no_think` trick didn't suppress thinking (407 tokens either way). Rule out. |
| Gemma3-12B (dense) | dense               | 8.1 GB    | 26.8 tok/s (lowest)  | **1.16s** (best overall) | Never does hidden reasoning at all, so lowest raw tok/s still wins on the metric that matters: 31 tokens, straight to the answer. |

**The headline finding: raw tokens/sec is the wrong metric for a voice
assistant.** Time-to-spoken-answer is what the user experiences, and that's
dominated by whether the model does invisible chain-of-thought before
replying, not by tokens/sec. Gemma3-12B answered in 1.16s by never thinking
out loud; the reasoning MoE models were 2–9x slower even though they generate
raw tokens 2–3x faster.

**`think: false` behaved inconsistently.** Passed through the
`/api/chat` REST endpoint (not the CLI's in-prompt `/no_think`, which failed
outright on Qwen3-8B): `gpt-oss:20b` honored it cleanly. `qwen3:30b-a3b`
**ignored it** — same visible `<think>...</think>` dump, and actually *more*
tokens (473 vs 334 default). That's a real limitation of this quant/version,
not a config mistake on this end — don't spend more time trying to prompt
Qwen3-30B-A3B into skipping thinking; it doesn't reliably comply.

## Recommendation

- **Try `gemma3:12b` as the default first.** Fastest real-world latency by a
  wide margin, smallest model of the four that still gave a correct, well-
  phrased answer, and it's already a known quantity (`z800` provider already
  points at `gemma3:latest`).
- **`gpt-oss:20b` with `think: false` set in the request** is the strongest
  fallback if Gemma3's answers turn out too shallow for some tasks — it's the
  only reasoning-capable candidate that can actually be told to skip
  reasoning.
- **Rule out Qwen3-30B-A3B and Qwen3-8B** for this role. The 30B-A3B has the
  best raw throughput but no way found here to stop it narrating its
  reasoning out loud, which kills voice latency; the 8B dense model is
  slower *and* has the same problem, with no upside.

`persona_llm.py`'s OpenAI-compatible wrapper doesn't currently pass through
provider-specific extras like `think`, so wiring that through is a small
follow-up if `gpt-oss:20b` is chosen — flagging it here, not doing it now
since it wasn't asked for.

## How to compare candidates yourself

```
curl -s http://localhost:11434/api/chat -d '{
  "model": "gemma3:12b",
  "messages": [{"role":"system","content":"You are Persona, a helpful voice assistant."},
               {"role":"user","content":"<your test question>"}],
  "stream": false
}'
```

Once a winner is picked, decide whether to keep the existing 120 GB model
around — it's occupying 112 GB of the 1.4 TB free on `/`, which is fine
space-wise, but there's no reason to keep it loaded as a live candidate if
it's not going to be the daily driver.

## Also noticed, not fixed

- `persona_llm.py`'s `_PROVIDERS` table still lists `"gemma2"` as the ollama
  default model — that's not what's actually installed. Worth updating once a
  target model is chosen, so the default in code matches reality.
- The `401 Wrong API Key` in `notes/llm.log-this-happens-sometime.txt` is a
  request hitting a provider with no key in `.env` (only `CEREBRAS_API_KEY` is
  set) — unrelated to model selection, but explains that log entry if it comes
  up again.
