#!/usr/bin/env -S uv run --no-project --script
# /// script
# requires-python = ">=3.11"
# dependencies = [
#    "onnxruntime-gpu[cuda, cudnn]",
#    "transformers",
#    "torch",
#    "librosa",
#    "huggingface_hub",
#    "numpy",
#    "sounddevice",
# ]
# ///

# Usage: speak-current.py <voice.wav> [textfile] [-o out.wav] [fp32|fp16|q8|q4|q4f16] [cuda|cpu]
# Renders each utterance while the previous one plays.

import sys
import re
import wave
import signal
import queue
import threading
import sounddevice as sd

# Extract flags before other parsing
_output_file = None
if '-o' in sys.argv:
    _i = sys.argv.index('-o')
    _output_file = sys.argv[_i + 1]
    sys.argv[_i:_i+2] = []

_timings = '--timings' in sys.argv
if _timings:
    sys.argv.remove('--timings')

sys.path.insert(0, __file__.rsplit('/', 1)[0])
import importlib.util, pathlib
spec = importlib.util.spec_from_file_location(
    "speak_onnx",
    pathlib.Path(__file__).parent / "speak-chatterbox-turbo-onnx.py")
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

VOICE_PREFIX = ""

_play_q = queue.Queue()


def split_sentences(text, min_words=8, max_words=15): # min_words=8, max_words=15):
    """Split text into render chunks sized between min_words and max_words.
    Sentences over max_words are split at commas first. Short pieces are then
    merged up to min_words, but never past max_words unless the accumulator
    hasn't yet reached min_words (avoids orphaned tiny chunks).
    """
    raw = []
    for para in re.split(r'\n\s*\n', text):
        para = re.sub(r'\s+', ' ', para).strip()
        if not para:
            continue
        marked = re.sub(r'([.!?]["\']?)\s+(?=[A-Z"\'])', r'\1\n', para)
        for sent in marked.split('\n'):
            sent = sent.strip()
            if not sent:
                continue
            if len(sent.split()) > max_words:
                clauses = re.sub(r',\s+', ',\n', sent).split('\n')
                raw.extend(c.strip() for c in clauses if c.strip())
            else:
                raw.append(sent)

    merged = []
    current = ''
    for s in raw:
        candidate = (current + ' ' + s).strip() if current else s
        current_len = len(current.split()) if current else 0
        if current_len >= min_words and len(candidate.split()) > max_words:
            merged.append(current)
            current = s
        else:
            current = candidate
            if len(current.split()) >= min_words:
                merged.append(current)
                current = ''
    if current:
        merged.append(current)
    return merged


def write_wav(path, chunks, sr):
    import numpy as np
    audio = np.concatenate([c.flatten() for c in chunks])
    samples = (audio * 32767).clip(-32768, 32767).astype(np.int16)
    with wave.open(path, 'w') as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(sr)
        f.writeframes(samples.tobytes())
    print(f"Wrote {path}")


def _playback_worker():
    try:
        with sd.OutputStream(samplerate=m.SAMPLE_RATE, channels=1, dtype='float32') as stream:
            stream.write(m.np.zeros(m.SAMPLE_RATE, dtype=m.np.float32))  # 1s silence, stream stays open
            while True:
                item = _play_q.get()
                if item is None:
                    break
                try:
                    stream.write(item[0].flatten().astype('float32'))
                except Exception as e:
                    print(f"[playback error] {e}")
                    break
    except Exception:
        pass


def main():
    voice_prompt = sys.argv[1]
    text_file = next(
        (a for a in sys.argv[2:] if a not in m.VALID_DTYPES + m.VALID_DEVICES), None)
    dtype  = next((a for a in sys.argv[2:] if a in m.VALID_DTYPES), "fp16")
    device = next((a for a in sys.argv[2:] if a in m.VALID_DEVICES), "cuda")

    m.get_model(dtype=dtype, device=device)

    print("Warming up...")
    import io, contextlib
    with contextlib.redirect_stdout(io.StringIO()):
        m.render(voice_prompt, "one two three four five six seven eight", dtype=dtype, device=device)
    print("Ready.")

    def _sigint(sig, frame):
        m.stop_event.set()
        sd.stop()
        raise KeyboardInterrupt
    signal.signal(signal.SIGINT, _sigint)

    pb_thread = threading.Thread(target=_playback_worker, daemon=False)
    pb_thread.start()

    wav_chunks = [] if _output_file else None

    try:
        if text_file:
            with open(text_file) as f:
                for sentence in split_sentences(f.read()):
                    if m.stop_event.is_set():
                        break
                    result = m.render(voice_prompt, VOICE_PREFIX + sentence, dtype=dtype, device=device, verbose=_timings)
                    if result[0] is not None:
                        _play_q.put(result)
                        if wav_chunks is not None:
                            wav_chunks.append(result[0])
        else:
            while not m.stop_event.is_set():
                if line := input('> '):
                    for sentence in split_sentences(line):
                        if m.stop_event.is_set():
                            break
                        result = m.render(voice_prompt, VOICE_PREFIX + sentence, dtype=dtype, device=device, verbose=_timings)
                        if result[0] is not None:
                            _play_q.put(result)
                            if wav_chunks is not None:
                                wav_chunks.append(result[0])
    except (KeyboardInterrupt, EOFError):
        pass
    finally:
        _play_q.put(None)
        pb_thread.join(timeout=3)
        if wav_chunks:
            write_wav(_output_file, wav_chunks, m.SAMPLE_RATE)

if __name__ == "__main__":
    main()
