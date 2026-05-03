#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "RealtimeSTT",
#     "chuk-llm",
#     "requests",
#     "sounddevice",
#     "chatterbox",
# ]
# ///

from contextlib import redirect_stderr, redirect_stdout
import io
import asyncio
import requests

# Kolja's RealtimeSTT / Whisper
from RealtimeSTT import AudioToTextRecorder

# Chris Hay chuk-llm
from chuk_llm import conversation

TTS_SERVER = "http://127.0.0.1:8100"
VOICE = "/home/eh/Proj/bird-dream.wav"
MUTED = False

from speak import speak

async def get_response(user_input):
    global MUTED
    async with conversation(provider="ollama") as chat:
        response = await chat.ask(user_input)
        print(response)
        print(user_input)
        print()
        MUTED = True
        speak('bird-dream.wav', user_input)
        MUTED = False


def handle_llm_text(text):
    print(f"<< {text}\n")
    if MUTED:
        print("Not sending to LLM.")
    else:
        asyncio.run(get_response(text))


if __name__ == '__main__':
    print("Whisper init....")
    sink = io.StringIO()
    with redirect_stderr(sink):
        with redirect_stdout(sink):
            recorder = AudioToTextRecorder(
                model="base.en",
                enable_realtime_transcription=True,
            )

    while True:
        recorder.text(handle_llm_text)
