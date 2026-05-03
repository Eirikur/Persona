#!/usr/bin/env -S uv run --no-project --script
# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "pyautogui",
#     "realtimestt",
#    "chatterbox-tts>=0.1.5",
#     "requests",
#     "sounddevice",
#     "nvidia-cublas-cu12",
#     "nvidia-cudnn-cu12",
#     "ollama",
# ]
# ///

# RealtimeSTT needs scipy, which needs gfortran.
import io
import sys # for sys.argv
from contextlib import redirect_stderr, redirect_stdout
import logging
import shutil
import ctranslate2
from persona_audio_recorder import AudioToTextRecorder
import pyautogui

from brain import get_response




def process_text(text):
    print(f"< {text}")
    # pyautogui.typewrite(text + " ")
    response = get_response(text)
    print(f"> {response}")

def realtime_update(text):
    width = shutil.get_terminal_size().columns - 1
    print(f"\r\033[K{text[:width]}", end="", flush=True)






    if len(sys.argv) >= 4:
        model=sys.arg[1]
        data_type=sys.arg[2]
        realtime=sys.arg[3]
        print("Speech input parameters:")
        print(f"{model} {data_type} {realtime}")
    if len(sys.argv) >= 6: # Update for more parameters.
        voice_name=sys.arg[4]
        voice_model=sys.arg[5]
        distillation=sys.arg[6]
        realtime=sys.arg[7]
        print("Speech out parameters:")
        print(f"{voice_name} {voice_model} {distillation} {realtime}")



       z+


    try:
        cuda_ok = 'float16' in ctranslate2.get_supported_compute_types('cuda')
    except RuntimeError:
        cuda_ok = False

    if cuda_ok:
        device, compute_type = 'cuda', 'float16'
    else:
        device, compute_type = 'cpu', 'int8'

    print(f"Using {device} ({compute_type})")
    recorder = AudioToTextRecorder(
        model='tiny.en',
        device=device,
        compute_type='int8',
        spinner=False,
        level=logging.WARNING,
        no_log_file=True,
        post_speech_silence_duration=0.05,
        enable_realtime_transcription=True,
        # on_realtime_transcription_update=realtime_update,
    )
    print("Listening — speak now")
    while True:
        recorder.text(process_text)



if __name__ == '__main__':
    main()
