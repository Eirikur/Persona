#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "RealtimeSTT",
#     "openai",
#     "requests",
# ]
# ///

import os
import logging
from dataclasses import dataclass
import asyncio
import threading
import requests

from RealtimeSTT import AudioToTextRecorder
from openai import AsyncOpenAI

TTS_SERVER = "http://127.0.0.1:8100"
VOICE = "/home/eh/Proj/bird-dream.wav"

# OpenAI-compatible providers: base_url, key env var, default model
_OAI = {
    "ollama":     ("http://localhost:11434/v1",  None,                "qwen3:8b"),
    "openai":     (None,                         "OPENAI_API_KEY",    "gpt-4o-mini"),
    "cerebras":   ("https://api.cerebras.ai/v1", "CEREBRAS_API_KEY",  "llama-3.3-70b"),
    "perplexity": ("https://api.perplexity.ai",  "PPLX_API_KEY",      "sonar"),
    "z800":       ("http://z800.local:11434/v1", None,                "gemma3:latest"),
    "llamacpp":   ("http://z800.local:8080/v1",  None,                None),
    "vllm":       ("http://z800.local:8000/v1",  None,                None),
}


@dataclass
class Config:
    provider: str = "ollama"
    model: str | None = None
    muted: bool = False


def set_provider(cfg: Config, name: str) -> None:
    if name not in _OAI:
        print(f"[unknown provider: {name!r}]")
        return
    cfg.provider = name
    cfg.model = None  # clear model override when switching provider
    print(f"[provider → {name}]")


def set_model(cfg: Config, name: str) -> None:
    cfg.model = name
    print(f"[model → {name}]")


async def ask_llm(cfg: Config, text: str) -> str:
    if cfg.provider not in _OAI:
        raise ValueError(f"Unknown provider: {cfg.provider!r}")

    base_url, key_env, default_model = _OAI[cfg.provider]
    api_key = os.environ.get(key_env, "local") if key_env else "local"
    model = cfg.model or default_model
    if not model:
        raise ValueError(f"No default model for {cfg.provider!r}; set PERSONA_MODEL or use 'model <name>'")

    client = AsyncOpenAI(api_key=api_key, base_url=base_url)
    resp = await client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": text}],
    )
    return resp.choices[0].message.content


def tts_speak(text: str) -> None:
    try:
        requests.post(f"{TTS_SERVER}/speak", json={"text": text, "voice": VOICE})
    except requests.exceptions.ConnectionError:
        print("[TTS server not reachable]")


async def get_response(cfg: Config, user_input: str) -> None:
    try:
        response = await ask_llm(cfg, user_input)
    except Exception as e:
        print(f"[LLM error: {e}]")
        return
    print(response)
    print()
    cfg.muted = True
    tts_speak(response)
    cfg.muted = False


# Whisper mishearing corrections for provider/model names
_ALIASES = {
    "alama": "ollama",
    "llama": "ollama",
    "preplexity": "perplexity",
    "proplexity": "perplexity",
    "quen": "qwen",
    "cerebra": "cerebras",
}


def _normalize(word: str) -> str:
    return _ALIASES.get(word, word)


def dispatch(cfg: Config, loop: asyncio.AbstractEventLoop, text: str) -> None:
    words = [_normalize(w.strip('.,!?;:')) for w in text.lower().strip().split()]
    if not words:
        return
    if words[0] == "provider" and len(words) > 1:
        set_provider(cfg, words[1])
    elif words[0] in ("llm", "model") and len(words) > 1:
        set_model(cfg, " ".join(words[1:]))
    elif words[0] in _OAI:
        set_provider(cfg, words[0])
    else:
        asyncio.run_coroutine_threadsafe(get_response(cfg, text), loop)


if __name__ == '__main__':
    print("*** persona.py starting ***")
    cfg = Config(
        provider=os.environ.get("PERSONA_PROVIDER", "ollama"),
        model=os.environ.get("PERSONA_MODEL"),
    )
    default_model = _OAI.get(cfg.provider, (None, None, None))[2]
    print(f"Provider: {cfg.provider}  Model: {cfg.model or default_model or 'provider default'}")
    # Suppress RealtimeSTT debug/info chatter
    for _log in ("realtimestt", "faster_whisper", "ctranslate2"):
        logging.getLogger(_log).setLevel(logging.WARNING)

    print("Whisper init....")
    # Suppress ALSA/JACK C-library noise on stderr during init
    _devnull = os.open(os.devnull, os.O_WRONLY)
    _old_stderr = os.dup(2)
    os.dup2(_devnull, 2)
    os.close(_devnull)
    recorder = AudioToTextRecorder(
        model="base.en",
        enable_realtime_transcription=True,
        initial_prompt="Provider names: ollama, OpenAI, cerebras, perplexity. Model names: qwen, gemma, llama, phi, granite.",
	#        device="cpu",
    )
    os.dup2(_old_stderr, 2)
    os.close(_old_stderr)

    loop = asyncio.new_event_loop()
    threading.Thread(target=loop.run_forever, daemon=True).start()

    try:
        while True:
            recorder.text(lambda text: dispatch(cfg, loop, text))
    finally:
        loop.call_soon_threadsafe(loop.stop)
