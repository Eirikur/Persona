#!/usr/bin/env -S uv run --no-project --script
# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "realtimestt",
#     "chatterbox-tts>=0.1.5",
#     "sounddevice",
#     "nvidia-cublas-cu12",
#     "nvidia-cudnn-cu12",
# ]
# ///

import argparse
import logging
import time
import ctranslate2
from persona_audio_recorder import AudioToTextRecorder
from speak import speak

def ts():
    return time.strftime('%H:%M:%S')

VOICE = 'bird-dream.wav'
MUTE = True   # silence the mic while speaking to prevent feedback loop

recorder = None


def process_echo(text):
    text = text.strip()
    if not text:
        return
    print(f"[{ts()}] < {text}")
    if MUTE:
        print(f"[{ts()}] mic off")
        recorder.set_microphone(False)
    speak(VOICE, text)
    if MUTE:
        recorder.set_microphone(True)
        print(f"[{ts()}] mic on")


def process_text(text):
    print(f"< {text}")
    # Future: dispatch to LLM / persona pipeline


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Persona speech input')
    parser.add_argument('--echo', action='store_true',
                        help='Echo transcribed speech back via Chatterbox TTS')
    parser.add_argument('--model', default='tiny.en',
                        help='Whisper model (default: tiny.en)')
    args = parser.parse_args()

    try:
        cuda_ok = 'float16' in ctranslate2.get_supported_compute_types('cuda')
    except RuntimeError:
        cuda_ok = False

    device = 'cuda' if cuda_ok else 'cpu'
    compute_type = 'float16' if cuda_ok else 'int8'
    print(f"Using {device} ({compute_type})")

    recorder = AudioToTextRecorder(
        model=args.model,
        device=device,
        compute_type=compute_type,
        spinner=False,
        level=logging.WARNING,
        no_log_file=True,
        post_speech_silence_duration=0.3, #.05
        enable_realtime_transcription=True,
    )

    callback = process_echo if args.echo else process_text
    mode = "echo" if args.echo else "transcribe"
    print(f"Listening ({mode} mode) — speak now")
    while True:
        recorder.text(callback)
