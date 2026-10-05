# 2026-10-05 handoff: chunked speech back, latency bench, disk full

Everything below is committed on `main` (1306131, c1a6e3f, 7132e17).
The stack is running. `persona-ui` (chat window) was left stopped.
Untracked and not mine: `.letta/`, `audio/dropped/`, `fonts/dropped/`.

## Done

- **Chunked speech output is back** (`persona_speech_output.py`). It was
  reverted under Chatterbox (7eddf79) because render was slower than playback.
  PocketTTS renders about 4x faster than playback (~0.08 s/word against
  ~0.32 s/word), so the next chunk is ready in time. Long reply, wait before
  first sound: about 6 s -> about 1.2 s. The owner listened: "perfect for now".
  - `CHUNK_MIN_WORDS = 4` (1000 renders replies whole)
  - `CHUNK_PAUSE = 0.25` seconds of silence after each chunk but the last
- **`persona_latency_bench.py`**: repeats the pipeline check over short,
  medium and long prompts, prints median and worst per stage, saves JSON to
  `tests/latency_results/`. `--baseline FILE` compares. Typed input only, so
  speech-in and endpointing lag are not covered. Addresses the first loaded
  persona (the hub only lists names, so wake word and provider come from
  `~/.config/persona/state.json`).
- Baseline: `2026-10-05-065457-baseline.json` (whole-reply render).
- Removed the stray `notes/CLAUDE.md` (the real one is at the repo root).

## Disk full (root filesystem hit 100%)

- Cause: model files. When the USB drive (Target10) drops off, writes to its
  mount point land on the main disk. `/tmp` is not a separate filesystem, so
  a full disk made Claude Code's own temp folder fail (ENOSPC).
- Now: root is 31% used, 2.4 TB free. Models live in
  `/media/eh/Target10/AImodels/hub` (862 GB). Copied there from
  `~/.cache/huggingface` and `/var/cache/huggingface`, verified by a second
  `rsync --dry-run`. `/var/cache/huggingface/hub` was then deleted by the owner
  (it belonged to the `lemonade` user and `lemond.service`; lemonade will need
  re-pointing or re-downloading).
- Policy (owner): models used by Persona stay on the local SSD (PocketTTS,
  Whisper). Everything else may live on Target10.
- Owner still to do: check for stray data hidden under the Target10 mount
  point (`sudo mount --bind / /mnt`, `du`, `umount`), and
  `sudo chattr +i /media/eh/Target10` while unmounted so a drop fails
  instead of filling the disk. `~/.cache/huggingface` (189 GB) not pruned.

## Open

1. Hal/Echo production voices (owner doing tonight). `.safetensors` export.
2. PocketTTS quality options not tried: `temp` (0.3), `sampler_decode_steps`
   (1), the 24-layer models (`english_2026-09_24l`). No speaking-rate setting.
3. Tutor questions "confusion lags" (answered: long-reply render wait, now
   fixed by chunking) and "ignored utterance" (still open).

## Cautions

- Roster in the live hub is in memory only: Sal loaded, Echo unloaded.
  Not persisted.
- `systemctl is-active` needs `--user` for Persona's units.
