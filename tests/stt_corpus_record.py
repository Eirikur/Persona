#!/usr/bin/env -S uv run --no-project --script
# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "numpy",
#     "sounddevice",
#     "soundfile",
# ]
# ///

"""Record the speech-recognition test set: real sentences in the owner's
voice and room, each saved with the words it is supposed to contain.

The clips let speech-input changes (a different Whisper model, new VAD
settings) be compared on accuracy and time against real speech, instead of
one clean test clip. The recognition comparison reads them later.

For each sentence: press Enter, say it, press Enter again. Then keep it,
listen to it, or record it again. Sentences already recorded are skipped,
so the script can be stopped and run again to carry on.

Records from the default microphone (whatever PipeWire has as the default
source), 16 kHz mono, the format the recognizer uses.

Usage:
  tests/stt_corpus_record.py          record every sentence not yet recorded
  tests/stt_corpus_record.py 3 7      record sentences 3 and 7 again
  tests/stt_corpus_record.py --list   show which sentences are recorded
"""

import re
import sys
from pathlib import Path

import numpy as np
import sounddevice as sd
import soundfile as sf


# ─── Configuration ────────────────────────────────────────────────────────────

CORPUS_DIR  = Path(__file__).parent / "stt_corpus"
SAMPLE_RATE = 16000

# (what to say, how to say it). The text is written the way the recognizer
# should spell it; case and punctuation are ignored when comparing. An empty
# text means "say nothing": those clips are room noise only, and the right
# result is no words at all.
SENTENCES = (
    ("Sal, what's the weather for tonight?",            "normal voice"),
    ("Salice, can you hear me?",                         "normal voice"),
    ("Hey Sal, what time is it?",                        "normal voice"),
    ("Echo, say something back to me.",                  "normal voice"),
    ("Major, what do you think about that?",             "normal voice"),
    ("Hal, are you there?",                              "normal voice"),
    ("House, tell me a joke.",                           "normal voice"),
    ("System check recognition.",                        "normal voice"),
    ("System persist evening setup.",                    "normal voice"),
    ("Hi everyone, I'm back.",                           "normal voice"),
    ("Sal, open Emacs please.",                          "normal voice"),
    ("Sal, what's on the news today?",                   "QUIETLY, the way you'd talk late at night"),
    ("Sal, remind me to check the window shims.",        "with a real pause after \"remind me\""),
    ("Sal, I was thinking about the latency work, and I'd like to know "
     "whether a smaller model would be good enough.",    "normal voice, one long sentence"),
    ("",                                                 "SAY NOTHING: about ten seconds of room noise"),
    ("",                                                 "SAY NOTHING: another ten seconds, ideally a loud stretch"),
)


# ─── Files ────────────────────────────────────────────────────────────────────

def clip_name(number, text):
    """File name without extension: the sentence number, then a few of its words."""
    words = re.sub(r"[^a-z0-9 ]+", "", text.lower()).split()[:5]

    if not words:
        words = ["room", "noise"]

    return f"{number:02d}-" + "-".join(words)


def clip_path(number):
    """Where sentence number N's audio is saved."""
    text, how = SENTENCES[number - 1]

    return CORPUS_DIR / (clip_name(number, text) + ".wav")


def save_clip(number, audio):
    """Write the audio and, beside it, the text it should contain."""
    text, how = SENTENCES[number - 1]
    wav_path  = clip_path(number)

    sf.write(wav_path, audio, SAMPLE_RATE, subtype="PCM_16")
    wav_path.with_suffix(".txt").write_text(text + "\n")

    print(f"  saved {wav_path.name}")


# ─── Recording ────────────────────────────────────────────────────────────────

def record_until_enter():
    """Record from the default microphone until Enter is pressed. Returns float samples."""
    pieces = []

    def keep(block, frames, timing, status):
        """Sound-card callback: hold on to each block as it arrives."""
        pieces.append(block.copy())

    with sd.InputStream(samplerate=SAMPLE_RATE, channels=1, dtype="float32", callback=keep):
        input("  RECORDING... press Enter when done ")

    if not pieces:
        return np.zeros(0, dtype=np.float32)

    return np.concatenate(pieces)[:, 0]


def decibels(level):
    """A level between 0 and 1 as decibels below full scale (0 dB is the loudest possible)."""
    return 20 * np.log10(max(level, 1e-9))


def describe_loudness(audio):
    """
    Print the length, the loudest and the quietest half-second. The quiet
    stretch is roughly the room's background noise, so a small gap between
    the two numbers means traffic is nearly as loud as the speech.
    """
    seconds = len(audio) / SAMPLE_RATE
    window  = SAMPLE_RATE // 2

    levels = []
    for start in range(0, len(audio) - window + 1, window):
        piece = audio[start:start + window]
        levels.append(np.sqrt(np.mean(piece ** 2)))

    if not levels:
        print(f"  {seconds:.1f} s -- too short to measure")
        return

    loudest  = decibels(max(levels))
    quietest = decibels(min(levels))

    print(f"  {seconds:.1f} s   loudest {loudest:.0f} dB   quietest {quietest:.0f} dB   "
          f"gap {loudest - quietest:.0f} dB")


def record_one(number):
    """
    Show one sentence, record it, and let the owner keep it, hear it, or
    try again. Returns False if the owner asked to quit.
    """
    text, how = SENTENCES[number - 1]

    print()
    print(f"── {number} of {len(SENTENCES)} ─ {how}")
    if text:
        print(f"   \"{text}\"")

    choice = input("  Enter = start recording, s = skip, q = quit: ").strip().lower()
    if choice == "q":
        return False
    if choice == "s":
        return True

    while True:
        audio = record_until_enter()
        describe_loudness(audio)

        choice = input("  Enter = keep, p = play it back, r = record again, q = quit: ").strip().lower()

        while choice == "p":
            sd.play(audio, SAMPLE_RATE)
            sd.wait()
            choice = input("  Enter = keep, p = play again, r = record again, q = quit: ").strip().lower()

        if choice == "q":
            return False

        if choice == "r":
            input("  Enter = start recording again: ")
            continue

        save_clip(number, audio)
        return True


# ─── Main ─────────────────────────────────────────────────────────────────────

def show_list():
    """Print every sentence with a mark for the ones already recorded."""
    for number, (text, how) in enumerate(SENTENCES, start=1):
        if clip_path(number).exists():
            mark = "done"
        else:
            mark = "    "

        print(f"  {mark}  {number:2d}  {text or '(room noise: ' + how + ')'}")


def main():
    """Record the sentences asked for on the command line, or every one not yet recorded."""
    CORPUS_DIR.mkdir(exist_ok=True)

    if "--list" in sys.argv:
        show_list()
        return

    asked_for = [int(word) for word in sys.argv[1:]]

    if asked_for:
        numbers = asked_for
    else:
        numbers = []
        for number in range(1, len(SENTENCES) + 1):
            if not clip_path(number).exists():
                numbers.append(number)

    if not numbers:
        print("Every sentence is recorded. Name numbers to redo some, or --list to see them.")
        return

    print(f"Microphone: {sd.query_devices(kind='input')['name']}")
    print(f"Saving to:  {CORPUS_DIR}")
    print("Leave a breath of silence before and after each sentence.")

    for number in numbers:
        if not record_one(number):
            break

    print()
    show_list()


if __name__ == "__main__":
    main()
