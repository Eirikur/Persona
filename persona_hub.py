#!/usr/bin/env -S uv run --no-project --script
# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "fastapi",
#     "uvicorn",
#     "httpx",
# ]
# ///

import json
import time
import uvicorn
import httpx
from dataclasses import dataclass, field, asdict
from pathlib import Path
from fastapi import FastAPI
from pydantic import BaseModel

PORT = 8400
LLM_URL = "http://127.0.0.1:8401"
SPEECH_OUTPUT_URL = "http://127.0.0.1:8402"
STATE_FILE = Path.home() / ".config" / "persona" / "state.json"

@dataclass
class VoiceProfile:
    name: str
    sample_file: str = ""
    speed: float = 1.0

@dataclass
class InputProfile:
    name: str
    stt_model: str = "base.en"
    silence_duration: float = 0.6

@dataclass
class Persona:
    name: str
    system_prompt: str = "You are Salice, a helpful voice assistant. Keep responses short and conversational — you are speaking aloud, not writing. Two or three sentences at most unless asked for more."
    voice: str = "default"
    input: str = "default"
    provider: str = "ollama"
    model: str | None = None

@dataclass
class GlobalState:
    active_persona: str = "default"
    personas: dict[str, Persona]      = field(default_factory=lambda: {"default": Persona(name="default")})
    voices:   dict[str, VoiceProfile] = field(default_factory=lambda: {"default": VoiceProfile(name="default")})
    inputs:   dict[str, InputProfile] = field(default_factory=lambda: {"default": InputProfile(name="default")})

def _load() -> GlobalState:
    if not STATE_FILE.exists():
        return GlobalState()
    data = json.loads(STATE_FILE.read_text())
    return GlobalState(
        active_persona=data.get("active_persona", "default"),
        personas={k: Persona(**v)      for k, v in data.get("personas", {}).items()},
        voices  ={k: VoiceProfile(**v) for k, v in data.get("voices",   {}).items()},
        inputs  ={k: InputProfile(**v) for k, v in data.get("inputs",   {}).items()},
    )

def _save(s: GlobalState) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(asdict(s), indent=2))

state = _load()
_speaking = False
_last_spoke = 0.0
SPEAK_COOLDOWN = 8.0
_mode = "open"  # "open" or "named"
app = FastAPI()

class ThinkRequest(BaseModel):
    text: str

def _llm(persona, text: str) -> str:
    r = httpx.post(f"{LLM_URL}/v1/chat/completions", timeout=60.0, json={
        "provider": persona.provider,
        "model": persona.model,
        "system_prompt": persona.system_prompt,
        "messages": [{"role": "user", "content": text}],
    })
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"]

def _speak(response_text: str, voice_prompt: str) -> None:
    try:
        httpx.post(f"{SPEECH_OUTPUT_URL}/speak", timeout=120.0, json={
            "text": response_text,
            "voice_prompt": voice_prompt,
        }).raise_for_status()
    except httpx.ConnectError:
        print("speech output not available")

_NAMES = ("salice", "sal")

def _dispatch(text: str) -> str | None:
    """Return a response string for local commands, or None to fall through to LLM."""
    global _mode
    normalized = text.strip().lower().rstrip(".,!")
    print(f"[{_mode}] dispatch: {normalized!r}")

    if normalized.startswith("stop"):
        httpx.post(f"{SPEECH_OUTPUT_URL}/stop", timeout=5.0)
        return ""

    if "go quiet" in normalized or "quiet mode" in normalized:
        _mode = "named"
        print("mode → named")
        return ""

    if _mode == "named":
        for name in _NAMES:
            if normalized.startswith(name):
                text = text.strip()[len(name):].lstrip(" ,")
                return None if text else ""
        return ""  # ignore — not addressed to Sal

    return None

@app.post("/think")
def think(req: ThinkRequest):
    persona = state.personas[state.active_persona]
    return {"text": _llm(persona, req.text)}

@app.post("/mode/{mode}")
def set_mode(mode: str):
    global _mode
    if mode not in {"open", "named"}:
        return {"error": f"unknown mode {mode!r}"}
    _mode = mode
    print(f"mode → {mode}")
    return {"mode": _mode}

@app.post("/stop")
def stop():
    httpx.post(f"{SPEECH_OUTPUT_URL}/stop", timeout=5.0).raise_for_status()
    return {"ok": True}

@app.post("/converse")
def converse(req: ThinkRequest):
    global _speaking, _last_spoke
    persona = state.personas[state.active_persona]
    voice = state.voices.get(persona.voice, state.voices["default"])
    dispatched = _dispatch(req.text)
    if dispatched is not None:
        return {"text": dispatched}
    if _speaking or (time.time() - _last_spoke < SPEAK_COOLDOWN):
        print(f"ignored (cooldown): {req.text!r}")
        return {"text": ""}
    response = _llm(persona, req.text)
    if response:
        print(f"> {response}")
        _speaking = True
        try:
            _speak(response, voice.sample_file or "wav/bird-dream.wav")
        finally:
            _speaking = False
            _last_spoke = time.time()
    return {"text": response}

services = ['speech_input', 'llm', 'speech_output']

def check_services():
    pass

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=PORT)
