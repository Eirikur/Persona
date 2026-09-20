# System checks on the Test tab

2026-09-20. Built on branch `stt-engine-experiment`. Goal, from the owner:
"anytime the speech system feels weird, I can ask for this" -- a way to run
the speech pipeline against a known input, see per-stage latencies, and
see plainly which stage broke when one does.

Two independent checks, one generic way to run either from the chat UI, and
spoken commands ("System, run test") that do the same as the buttons.

## What exists now

| File                        | Role                                                        |
|-----------------------------|-------------------------------------------------------------|
| `persona_stt_check.py`      | Recognition: known clip in, word error rate + latency out   |
| `persona_pipeline_check.py` | Reply: typed message in, per-stage timings out              |
| `persona_scripts.py`        | `SCRIPTS` table + streaming runner behind `/run_script/`    |
| `persona_hub.py`            | `POST /run_script/{name}`, `SCRIPT_PHRASES`, `say()`        |
| `persona_chat.html`         | Test tab: buttons, output pane; state strip on every tab    |
| `tests/test_speech.wav`     | 1.788 s, 16 kHz mono, speech from 0.0 s to the very end     |
| `tests/test_speech.txt`     | what the clip says; verified by ear by the owner 2026-09-20 |

Commits, in order: `10cfd98` strip on every tab, `dded7df` STT check,
`7cbfdf4` runner + route, `c031ae8` STT button, `776c5d5` pipeline check,
`4fda977` pipeline button, then the voice commands: `6d631a4` chat window
`run_script` event, `e2c00ce` `SCRIPT_PHRASES`, `b8b8847` spoken `SAY:` lines,
`f9adf54` spoken STT summary.

**The live hub must be restarted** (`./persona_restart.sh`) before the Test
tab buttons and spoken commands work: `/run_script`, `SCRIPT_PHRASES` and
`say()` are new. The route, tab and phrase wiring was tested against a
throwaway second hub on port 8499. The pipeline check script itself was also
run directly against the live hub (it passed, all stages seen, before the
`SAY:` lines existed). The spoken *passing* summary has not yet been heard
end to end on the live hub; see the testing caveat below.

## Running them

- From the Test tab: "Check speech recognition", "Check reply pipeline".
- From a shell: `./persona_stt_check.py [rounds]`,
  `./persona_pipeline_check.py [hub_url]`.
- Both exit 0 = pass, 1 = fail. The STT check exits 2 when there is no
  reference text.
- The pipeline check makes the persona speak aloud (same as the Run test
  button) and posts a chat bubble labelled "Pipeline check".
- The "Run test" button is not either of these. It posts typed text straight
  to the hub and skips speech recognition entirely (`/test` in
  `persona_speech_input.py`).

## How they work, and why

**STT check.** Builds its own recorder (no mic, no hub) and feeds the clip at
real-time pace, then silence, timing last-speech-chunk-fed -> `text()`
returned. Model, silence and prompt settings are *imported* from
`persona_speech_input.py`, and that import happens first so
`OMP_NUM_THREADS=16` is set before torch loads. So the check cannot drift from
production. Its uv dependency block is a copy of the service's, so the two
share one cached environment.

The word error rate ignores case and punctuation; limit is 0.2. Swapped words
count as two errors. It compares raw Whisper output, before the hub's
MISHEARINGS table.

**Pipeline check.** Does not touch the hub. It listens to `/events` and times
the gaps between events the hub already emits: `inference` -> `sal_turn`
(reply text ready) -> `playback_start` -> `speak_done`. `/speak` in
`persona_speech_output.py` blocks through rendering *and* playback (`sd.wait`),
so `speak_done` is the true end of the spoken reply and the four stages do not
overlap. A stage that never happened is reported by name.

**Runner.** A worker thread owns the subprocess and the one-at-a-time lock,
and the HTTP response only reads lines off a queue. An earlier draft released
the lock in the response generator; Starlette never finalizes that generator
when the browser disconnects, so one closed tab would have locked out every
later run. Do not move the lock back into the generator. Closing the browser
mid-run lets the script finish on its own (cap: `SCRIPT_TIMEOUT`, 300 s).

Only names in `SCRIPTS` can run, so the UI cannot ask for an arbitrary
command. To add a script: one line in `SCRIPTS`, one button with class
`script-btn` and `data-script="<name>"`.

## Spoken commands and spoken results

Say "System, run test" (or "system check reply") for the pipeline check, and
"System, check recognition" for the STT check. Buttons and voice do exactly the
same thing, on purpose.

Flow: `dispatch()` matches a phrase in `SCRIPT_PHRASES` -> hub emits a
`run_script` event -> the chat window flips to the Test tab and runs the script
through the same `runScriptLocked()` the buttons use (all script buttons are
disabled during any run, and a second run started while one is going is
ignored). The hub does not run the script itself, so `/converse` returns at
once and the live recorder is not held up.

**Spoken results.** A script prints a line starting `SAY: `. After the script
exits, the runner hands that text to `say_summary()` in the hub, which has the
active persona (Sal, until System has its own voice) show and speak it. After,
never during, so speaking cannot skew what was measured. `say()` is the one
place a reply gets shown, marked as speaking and given its cooldown, so the mic
does not hear the summary and answer it. `converse()` uses the same `say()`.
A run's stream (and so the buttons) stays busy until the summary has finished
speaking.

**The self-trigger trap.** The pipeline check's canned message ("Sal, this is a
system test. Do you hear me?") goes through `dispatch()` like any input. A
phrase in `SCRIPT_PHRASES` that matched it would make the check start itself
and fail every stage. Phrases are matched only at the very START of the input,
ignoring case and punctuation, and there is a comment beside the table. When
adding phrases, test that the canned message still does not trigger.

**Testing caveat.** A throwaway hub on another port cannot see `render` or
`playback`: `persona_speech_output.py` reports `playback_start` to the hub at
8400 (hard-coded), so a test hub on 8499 sees those stages as "not seen" even
when the speech was really spoken. Verify the passing path against the live hub.

Spoken summaries cost render time too: about 11 words took 16 s. If that
becomes annoying, shorten the `SAY:` text in the script, not the runner.

## Measurements, 2026-09-20 (this machine, Chatterbox on CPU)

- Recognition latency, clip end -> text: 3.55-3.9 s typical, up to 5.0 s in a
  few runs. Run-to-run variation is about 20%; the runner adds nothing
  measurable (3.65 s median both directly and through the hub). Judge by
  several runs, not one.
- Reply pipeline, one run: routing 0.00 s, inference 0.28 s, render 8.93 s for
  10 words (0.89 s per word), playback 3.65 s, total 12.86 s. Rendering
  dominates. Reply length changes render and playback, so compare the
  seconds-per-word figure rather than raw render time.

## Things noticed, not acted on

- LLM replies arrive with leading `\n\n` (visible in the check's Reply line).
  Harmless so far; not investigated.
- The live hub was found muted (HEARING struck through) on load. The mute is
  in-memory only (`MUTED` in `persona_hub.py`, starts False), so a restart
  clears it. Not a bug in this work.
- RealtimeSTT 1.1.2 prints harmless close-time tracebacks (`FasterWhisperEngine`
  has no `close`; a pipe read after close). The STT check silences all logging
  around `rec.shutdown()`; it reports with `print`.
- The Test-tab output pane is plain text; PASS/FAIL is not colored.

## Ideas the owner raised (not built)

- Keep a few runs and show them side by side for comparison. Cheapest route:
  each check appends one JSON line to a file; the tab reads it back.
- A longer clip for finer latency resolution, only if needed. It is just
  another wav + txt pair and a `SCRIPTS` entry.
- The system persona (Cissy) speaking these results in her own voice, instead
  of Sal reading them (see `say_summary()`); needs the multi-persona work.
- Test-triggered input as its own persona (already bookmarked in memory).
