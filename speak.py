#!/usr/bin/env -S uv run --script
# 21 Feb '26: Working in a loop with llama3 via chuk_llm
# /// script
# requires-python = ">=3.11,<3.12"
# dependencies = [
#    "numpy",
#    "torch",
#    "torchaudio",
#    "sounddevice",
#    "chatterbox-tts>=0.1.5",
#    "resemble-perth",
# ]
#
# [tool.uv.sources]
# resemble-perth = { path = "../Perth" }
#
# [tool.uv.extra-build-dependencies]
# pkuseg = ["numpy"]
# ///

voice_prompt = 'bird-dream.wav'

import os
import io
import time
import warnings
from contextlib import redirect_stderr, redirect_stdout

import numpy
import sounddevice as sd # Only for direct-to-audio output.

warnings.filterwarnings("ignore", category=UserWarning, module="perth")

import torch
import torchaudio as ta

DEVICE = 'cuda' if torch.cuda.is_available() else 'cpu'

_model_cache = {}

def get_model(turbo=False):
    key = 'turbo' if turbo else 'standard'
    if key not in _model_cache:
        model_type = 'Turbo' if turbo else 'Original'
        print(f"Loading Chatterbox {model_type} on {DEVICE.upper()}...")
        latency_start = time.time()
        if turbo:
            from chatterbox.tts_turbo import ChatterboxTurboTTS
            _model_cache[key] = ChatterboxTurboTTS.from_pretrained(device=DEVICE)
        else:
            from chatterbox.tts import ChatterboxTTS
            _model_cache[key] = ChatterboxTTS.from_pretrained(device=DEVICE)
        print(f"Model loaded in {time.time() - latency_start:.2f}s")
    return _model_cache[key]

MODEL = get_model(turbo=True)


def speak(voice_prompt, line,
          # exaggeration=0.5,
          # cfg_weight=0.3,
          # temperature=0.5,
          turbo=False):
    # print(f"<< {line}")
    print(line)
    start_time = time.time()
    start_cpu_time = time.process_time()

    sink = io.StringIO()
    with redirect_stderr(sink):
        with redirect_stdout(sink):
            wav = MODEL.generate(
                line,
                audio_prompt_path=voice_prompt,
                # exaggeration=exaggeration,
                # cfg_weight=cfg_weight,
                # temperature=temperature)
            )

    print("Generated.")
    end_time = time.time()
    end_cpu_time = time.process_time()
    execution_time = end_time - start_time
    execution_cpu = end_cpu_time - start_cpu_time
    waiting_time = execution_cpu - execution_time
    print(f"Wall time: {execution_time:.2f} CPU time: {execution_cpu:.2f}, Waiting: {waiting_time:.2f}")
    word_count = len(line.split(' '))
    seconds_per_word = execution_time / word_count
    print(f"{word_count} words, rendered in {execution_time:.2f}, seconds/word {seconds_per_word:.2f}")
    # ta.save('speak.wav', wav, MODEL.sr)
    # print('File written.')
    audio_array = wav.squeeze().cpu().numpy()
    sd.play(audio_array, MODEL.sr)
    sd.wait()
    print()


    # ta.save(temp_file, wav, MODEL.sr)
    # os.system(f"aplay {temp_file} &")


def punc_norm(text: str) -> str:
    """
    From Chatterbox demo.
    Quick cleanup func for punctuation from LLMs or
    containing chars not seen often in the dataset
    """
    if len(text) == 0:
        return "You need to add some text for me to talk."

    # Capitalise first letter
    if text[0].islower():
        text = text[0].upper() + text[1:]

    # Remove multiple space chars
    text = " ".join(text.split())

    # Replace uncommon/llm punc
    punc_to_replace = [
        ("...", ", "),
        ("…", ", "),
        (":", ","),
        (" - ", ", "),
        (";", ", "),
        ("—", "-"),
        ("–", "-"),
        (" ,", ","),
        ("“", "\""),
        ("”", "\""),
        ("‘", "'"),
        ("’", "'"),
    ]
    for old_char_sequence, new_char in punc_to_replace:
        text = text.replace(old_char_sequence, new_char)

    # Add full stop if no ending punc
    text = text.rstrip(" ")
    sentence_enders = {".", "!", "?", "-", ","}
    if not any(text.endswith(p) for p in sentence_enders):
        text += "."

    return text



#
if __name__ == '__main__':
    import sys
    voice_prompt = sys.argv[1]
    text_file = sys.argv[2]
    use_turbo = 'turbo' in sys.argv[3:]
    line_count = 0
    # MODEL = get_model(turbo=use_turbo)

    if text_file:
        with open(text_file, 'r') as f:
            speak(voice_prompt, f.read(), turbo=use_turbo)
    else:
        while True:
            line = ""
            if line := input('> '):
                line_count += 1
                speak(voice_prompt, line, turbo=use_turbo)
