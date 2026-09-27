# Voice samples: legal orientation and repo cleanup plan

Written 2026-09-23. Not legal advice; Claude is not a lawyer and its
knowledge of this area stops around January 2026 (plus the web searches below).

## Situation

- One of the voice files was a test conversion from a voiceover by a Scottish
  actor. Chatterbox cloned it strongly: Salice came out sounding like an older
  male Scot from an unfinished sample, so the result is recognizably his
  voice (relevant to how much the "ask him" instinct matters). Owner's instinct: email him and politely ask permission to use the
  final version at home. Not believed to be required, but kind.
- The Persona repo on GitHub is PUBLIC (checked 2026-09-23 without
  credentials: github.com/Eirikur/Persona, private=false, 0 forks, 0 stars).
- Voice samples are tracked in git and have been in history since 2026-07-01.

## Legal orientation

- "Identity theft" is not the legal category. Relevant theories: right of
  publicity (US), passing off (UK), copyright in the recording, and contract.
- Most of those need commercial use, public distribution, or implied
  endorsement. A private home voice that is never distributed: very low risk.
- The recording is probably owned by whoever commissioned the voiceover, not
  the actor, and the original contract may restrict AI use.
- UK has no general personality right; passing off needs commercial false
  endorsement. Equity (UK actors' union) is active on AI voice terms.
- Older US cases: Midler v. Ford (1988), Waits v. Frito-Lay (1992). Both
  commercial, both imitation of a distinctive voice.
- Lehrman & Sage v. Lovo (S.D.N.Y., July 10 2025): federal trademark and most
  copyright claims dismissed; NY right-of-publicity ("digital replica"
  provision applies to voice-only clones), consumer-protection and contract
  claims proceeded; one copyright claim survived (use of a recording beyond
  its license). No later merits ruling found.
- Statutes: Tennessee ELVIS Act (2024); California digital-replica laws (2024).
- NO FAKES Act of 2026 (S.4591): federal right against unauthorized digital
  replicas of voice/likeness; licensable; notice-and-takedown; First Amendment
  carve-outs. Senate Judiciary advanced it unanimously 2026-06-22. NOT law yet
  (needs full Senate and House).
- Japan: guidelines finalized 2026-08-08 treat unconsented voice cloning as a
  civil publicity-rights violation (single source, treat with caution).
- Vendor blogs (Soundverse, Percify, etc.) make broad claims like "voice is
  biometric property"; do not rely on them.

Sources:
- https://www.loeb.com/en/insights/publications/2025/07/lehrman-v-lovo-inc
- https://www.skadden.com/insights/publications/2025/07/new-york-court-tackles-the-legality-of-ai-voice-cloning
- https://www.hklaw.com/en/insights/publications/2026/06/senate-judiciary-committee-advances-legislation-to-protect-name
- https://www.congress.gov/bill/119th-congress/senate-bill/4591
- https://www.techtimes.com/articles/323616/20260808/japan-rules-ai-voice-cloning-requires-consent-developers-face-civil-liability.htm

## If emailing the actor

Say it is personal, non-commercial, and never shared. Try his agent or
website. If he says no, the owner must then decide what to do with the voice;
that is the main reason not to ask lightly. Check the original voiceover
contract terms if known.

## Repo cleanup: NOT DONE, awaiting owner's go-ahead

Deleting the files and adding `.gitignore` is not enough: git history keeps
every past version. Files found in history (all branches: main,
stt-engine-experiment, led-ring-vad-states, all pushed):

- audio/bird-dream.wav
- audio/warmup_audio.wav
- audio/system-voice.wav
- tests/test_speech.wav
- warmup_audio.wav (older root-level path)

Owner has not said which one is the actor's voice (`wav/` is already
gitignored). Note `persona_hub.py` falls back to `audio/bird-dream.wav` and
warmup uses `warmup_audio.wav`, so those need a replacement path.

Proposed order:

1. Make the GitHub repo private now (reversible, one click).
2. Back up the repo to a tarball outside it.
3. Move the chosen audio files to an untracked location.
4. Purge those paths from all branches with `git filter-repo`.
5. Add the directory to `.gitignore`.
6. Force-push all three branches; re-clone anywhere else the repo is used.
7. GitHub may keep old commits reachable by SHA: ask GitHub support to run
   garbage collection, or delete and recreate the repo (easy with 0 forks).
8. Copies already cloned or crawled cannot be recalled; the aim is to stop
   further distribution.

Force-push and history rewrite are destructive: do them only with the owner
at the keyboard, after the backup.

## Related decisions

- `audio/dropped/` (voice-drop feature) stays untracked and not gitignored
  for now; voice-data handling gets decided deliberately during the
  installer/setup work. Revisit alongside the cleanup above.
- Context: owner wrote an article on Massive Attack and the sample that became
  "Teardrop", a permission-and-credit collaboration; a good model for how to
  approach the actor.
