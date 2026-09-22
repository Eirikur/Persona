# OMP_NUM_THREADS=16 was starving Chatterbox

2026-09-22. Owner reported the whole system "feels slower" on
`stt-engine-experiment`. Measured, not guessed.

## What was wrong

`ebf53f4` (2026-09-19) set `OMP_NUM_THREADS=16` in `persona_speech_input.py`
to fix recognition latency, and that part worked (5.5s -> 3.9s). But the note
that landed it checked recognition and logs/speech-out.log right after and
called rendering unaffected. It wasn't -- `persona_speech_input.py` runs
`enable_realtime_transcription=True`, so it decodes partials on the mic
continuously, not only during a spoken command. At 16 threads that
background decoding competes hard with Chatterbox's own CPU-bound rendering
in `persona_speech_output.py`, a separate process on the same 16 physical
cores.

`notes/2026-09-20-system-checks.md` already shows this as 0.89 s/word,
already above the 2026-09-19 baseline of 0.61-0.74, just not flagged as a
regression there.

## Confirmed by isolation

Pipeline check (`persona_pipeline_check.py`), render stage, same machine:

| Condition                                  | s/word (several runs)     |
|---------------------------------------------|---------------------------|
| Baseline, 2026-09-19, before the 16-thread change | 0.61-0.74             |
| `OMP_NUM_THREADS=16`, STT service running (today)  | 0.63-1.34, avg ~0.95  |
| `OMP_NUM_THREADS=16`, STT service stopped (today)  | 0.69-0.81             |
| `OMP_NUM_THREADS=8`, STT service running (today)   | 0.54-0.95, avg ~0.79  |

Stopping `persona-speech-in.service` and rerunning the pipeline check
isolates the cause cleanly: render goes back to baseline the moment STT
stops competing for CPU, with no code changes.

## Fix applied

Dropped `OMP_NUM_THREADS` from 16 to 8 in `persona_speech_input.py`.
2026-09-19's own A/B table already showed 8 threads gives a 4.24s
recognition median -- still well under the pre-fix 4.99s baseline. Measured
again today at 8 threads: recognition median 3.73s (same as at 16 -- the
gain from 4 to 8 threads is most of the benefit; 8 to 16 added little),
render back down to an average of ~0.79 s/word.

Not a full fix -- some contention remains (0.79 vs the isolated 0.69-0.81),
because the STT service still decodes continuously at 8 threads whenever
HEARING is on. Two things noticed but not acted on:

- The `goals/listen-while-speaking` problem (Sal's own voice gets
  transcribed and costs a full decode, discarded only after the hub's
  `SPEAK_COOLDOWN`) means STT is often actively decoding at the exact
  moment Chatterbox is rendering the reply -- the worst-case overlap.
- The real structural fix is porting Whisper to ROCm per
  `notes/2026-08-10-rocm-amd-port.md` (Persona was never ported; Whisper
  still always runs on CPU here, `torch.cuda.is_available()` is False in
  this env). That would remove the CPU contention at the source instead of
  trading recognition speed for it. Bigger lift, not done here.

## Not the LLM

`persona_llm.py`'s default provider is `cerebras` (cloud), confirmed at hub
startup ("Warming up LLM for default (cerebras)..."). Inference stage in the
pipeline check is consistently ~0.2-0.4s and was never a suspect.
