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
import uvicorn
import httpx
from dataclasses import dataclass, field, asdict
from pathlib import Path
from fastapi import FastAPI
from pydantic import BaseModel

PORT = 8400
LLM_URL = "http://127.0.0.1:8401"
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
    system_prompt: str = "You are Persona, a helpful voice assistant."
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
app = FastAPI()

class ThinkRequest(BaseModel):
    text: str

@app.post("/think")
def think(req: ThinkRequest):
    persona = state.personas[state.active_persona]
    r = httpx.post(f"{LLM_URL}/v1/chat/completions", timeout=60.0, json={
        "provider": persona.provider,
        "model": persona.model,
        "system_prompt": persona.system_prompt,
        "messages": [{"role": "user", "content": req.text}],
    })
    r.raise_for_status()
    return {"text": r.json()["choices"][0]["message"]["content"]}

services = ['speech_input', 'llm', 'speech_output']

def check_services():
    pass

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=PORT)
