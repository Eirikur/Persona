# 2026-10-10 — where the "after I stop talking" wait goes

Branch: tts-backends. Stack was down during all runs (quiet CPU).

## The complaint

The owner feels the lag right after they stop talking: the HEARING ->
TRANSCRIBING change "seems too slow, almost as if the display is laggy".

## Finding 1: the display really is late

`persona_chat.html` lights TRANSCRIBING on the `heard` event, which arrives
only after Whisper has finished. The hub already emits `recording_stop` (the
moment transcription begins) but the state strip ignores it. So HEARING stays
lit through the whole endpoint + decode wait, then TRANSCRIBING flashes with
the text already in hand and is held for a 2-second minimum (`minEndTime`),
which can also hold back INFERENCE and SPEAKING.

**Fixed in b2d59b0:** TRANSCRIBING now lights on `recording_stop` (only from
HEARING and not muted, so the persona's own voice can't knock SPEAKING off),
and falls back to HEARING after `TRANSCRIBE_GIVE_UP_MS` (6 s) if nothing
follows. Checked in headless Chromium against a hub-only stack. Not yet seen
by the owner on the live window. The 2 s `minEndTime` hold is unchanged; it
now starts earlier, so it rarely delays INFERENCE. Revisit if the model
switch makes decode much shorter than 2 s.

**Checked live 10:24-10:26** (strip photographed every 0.4 s, matched to logs):
TRANSCRIBING lit at recording_stop and held ~3.5 s until INFERENCE, as
intended. But after every Echo reply it lit again for ~6 s: the mic records
the reply, the hub drops it as self-hear (`ignored`), and the strip waited
for the fallback. Fixed: `ignored` returns the strip to HEARING (ae1653a),
and a recording that began while a persona was busy never lights
TRANSCRIBING. Lesson: the window does not pick up page edits until reloaded
(Ctrl+R); an SSE reconnect is not a reload.

## Finding 2: measured split (persona_stt_check.py, 5 rounds each)

`persona_stt_check.py` now reports endpoint (end of speech -> recorder's
`recording_stop`) and decode (`recording_stop` -> text) separately, and uses
production's `SILERO_SENSITIVITY` (it had a hard-coded 0.4). Clip:
`tests/test_speech.wav`, 1.8 s, "Sal, do you know what time it is?".
Every run below heard it perfectly.

| Configuration                            | Endpoint | Decode | Total  |
|------------------------------------------|----------|--------|--------|
| production: large-v3-turbo, 8 threads    | 1.03 s   | 2.58 s | 3.64 s |
| large-v3-turbo, OMP_NUM_THREADS=16       | 1.03 s   | 2.78 s | 3.84 s |
| large-v3-turbo, realtime partials off    | 1.06 s   | 2.78 s | 3.83 s |
| medium.en                                | 1.03 s   | 0.99 s | 2.01 s |
| small.en                                 | 1.03 s   | 0.37 s | 1.41 s |

Device is CPU (int8); CTranslate2 does not see the ROCm GPU here.

- Thread count and realtime partials: no gain. Both ruled out.
- Endpoint ~1.0 s = `SILENCE_DURATION` 0.6 + RealtimeSTT's 0.16 confirmation
  + VAD lag. Tunable, but too short cuts people off mid-pause.
- Model size is the lever: small.en decodes 7x faster than large-v3-turbo.

The non-production rows were throwaway copies of the check script (in the
Claude job's tmp dir), not committed. small.en / medium.en came from
`~/.cache/huggingface` (HF_HOME points at ~/AImodels, which only has
large-v3-turbo and tiny), run with `HF_HUB_OFFLINE=1`.

## Caveat before switching models

One clean clip proves speed, not accuracy. large-v3-turbo was chosen for
accuracy, and "Sal"/"Salice" recognition is why MISHEARINGS exists. Before
switching, build a small accuracy corpus: a dozen or so real utterances in the
owner's voice and room (names, commands, quiet speech), each with reference
text, and compare models on word errors as well as time.

## Next steps (proposed, not started)

1. ~~UI: light TRANSCRIBING on `recording_stop`~~ done (b2d59b0).
2. Accuracy corpus + make the check take a model name and several clips.
3. Decide model (small.en / medium.en / distil) from corpus numbers.
4. Voice-path bench through the live stack (stop talking -> first sound).
5. Later: Whisper on the GPU (needs a ROCm-capable backend), endpoint tuning.

## Model comparison on the owner's own recordings (11:12)

Test set: `tests/stt_corpus/` (16 clips recorded with
`tests/stt_corpus_record.py`: 14 sentences on the ReSpeaker with heavy
traffic noise, plus 28 s and 65 s of room noise only). Not committed: the
owner hasn't decided whether recordings of their voice go into git.
Run: `HF_HOME=~/.cache/huggingface HF_HUB_OFFLINE=1 ./persona_stt_compare.py`
(live speech-in was running, so delays are slightly slower than quiet).
Raw results: `tests/stt_corpus_results/2026-10-10-111206.json`.

The owner improvised on most sentences, so the reference texts were then
rewritten to the wording the models agreed on (owner: "assume improvs"),
and the saved results rescored:

| Model          | Words wrong (of 123) | Median decode | Worst  |
|----------------|----------------------|---------------|--------|
| large-v3-turbo | 3 ("Hal"->"Now", "Sal"->"So", "shims"->"streams") | 3.26 s | 3.56 s |
| medium.en      | 1 ("Hal"->"Hell")    | 1.05 s        | 1.51 s |
| small.en       | 3 ("Sal"->"So", dropped "So", "shims"->"streams") | 0.39 s | 0.61 s |

- Noise clips: no model invented a single word; VAD at 0.25 never even
  opened a recording, including the loud 65 s stretch.
- Clip 13 (deliberate pause after "remind me"): every model split it into
  two pieces. Live, that is two turns. `SILENCE_DURATION` (0.6 s) decides.
- Caveat: references came from model consensus, so this measures agreement
  as much as truth; 13 sentences, one speaker, one run each.

Recommendation: medium.en. Most accurate here, and ~2.2 s faster per turn.
small.en saves another ~0.7 s but turned "Sal" into "So", and the wake name
is what routing depends on. Not switched yet.
