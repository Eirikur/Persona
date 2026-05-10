#!/usr/bin/env -S uv run --no-project --script
# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "fastapi",
#     "uvicorn",
#     "httpx",
# ]
# ///

import asyncio
import json
import subprocess
import time
import uvicorn
import httpx
from dataclasses import dataclass, field, asdict
from pathlib import Path
from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
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
    stt_model: str = "small.en"
    silence_duration: float = 0.6

@dataclass
class Persona:
    name: str
    wake_words: list[str] = field(default_factory=list)
    system_prompt: str = "You are Salice, a helpful voice assistant. Keep responses short and conversational — you are speaking aloud, not writing. Two or three sentences at most unless asked for more."
    voice: str = "default"
    input: str = "default"
    provider: str = "ollama"
    model: str | None = None

@dataclass
class GlobalState:
    active_persona: str = "default"
    loaded_personas: list[str] = field(default_factory=lambda: ["default"])
    personas: dict[str, Persona]      = field(default_factory=lambda: {"default": Persona(name="default", wake_words=["salice", "sal"])})
    voices:   dict[str, VoiceProfile] = field(default_factory=lambda: {"default": VoiceProfile(name="default")})
    inputs:   dict[str, InputProfile] = field(default_factory=lambda: {"default": InputProfile(name="default")})

def _load() -> GlobalState:
    if not STATE_FILE.exists():
        return GlobalState()
    data = json.loads(STATE_FILE.read_text())
    personas = {k: Persona(**v) for k, v in data.get("personas", {}).items()}
    # Migrate: persona saved before wake_words was added
    if "default" in personas and not personas["default"].wake_words:
        personas["default"].wake_words = ["salice", "sal"]
    return GlobalState(
        active_persona  =data.get("active_persona", "default"),
        loaded_personas =data.get("loaded_personas", ["default"]),
        personas=personas,
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
MODE = "named"

# Shell commands triggered by voice. Values are passed to the shell.
COMMANDS: dict[str, str] = {
    "firefox":     "~/scripts/toggle.sh Firefox firefox",
    "thunderbird": "~/scripts/toggle.sh Thunderbird thunderbird",
    "email":       "~/scripts/toggle.sh Thunderbird thunderbird",
    "emacs":       "emacsclient -n -a '' -e '(eh/toggle-visible)'",
}

# STT mishearing corrections. Applied before any dispatch logic.
MISHEARINGS: dict[str, str] = {
    "e-racks":  "emacs",
    "e-max":    "emacs",
    "imax":     "emacs",
    "solace":   "salice",
    "alice":    "salice",
    "sal ease": "salice",
}

BROADCAST_PHRASES = (
    "hi gang", "hello gang", "hey gang",
    "hi everyone", "hello everyone", "hey everyone",
)

app = FastAPI()
app.mount("/ui", StaticFiles(directory=Path(__file__).parent, html=True), name="ui")

_event_queues: list[asyncio.Queue] = []
_loop: asyncio.AbstractEventLoop | None = None

@app.on_event("startup")
async def _capture_loop():
    global _loop
    _loop = asyncio.get_running_loop()

def _emit(event_type: str, text: str) -> None:
    if not _loop:
        return
    data = json.dumps({"type": event_type, "text": text})
    for q in _event_queues:
        asyncio.run_coroutine_threadsafe(q.put(data), _loop)

@app.get("/events")
async def events():
    q: asyncio.Queue = asyncio.Queue()
    _event_queues.append(q)
    async def generate():
        try:
            while True:
                try:
                    data = await asyncio.wait_for(q.get(), timeout=15.0)
                    yield f"data: {data}\n\n"
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
        finally:
            try:
                _event_queues.remove(q)
            except ValueError:
                pass
    return StreamingResponse(generate(), media_type="text/event-stream", headers={
        "Cache-Control": "no-cache",
        "X-Accel-Buffering": "no",
    })

class ThinkRequest(BaseModel):
    text: str

def _llm(persona: Persona, text: str) -> str:
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

def _dispatch(text: str) -> list[str]:
    """Return list of persona names that should respond. Empty list = no response needed."""
    global MODE
    normalized = text.strip().lower().rstrip(".,!")
    original = normalized
    for heard, intended in MISHEARINGS.items():
        normalized = normalized.replace(heard, intended)
    _emit("heard", original)
    if normalized != original:
        _emit("corrected", normalized)
    print(f"[{MODE}] dispatch: {normalized!r}")

    if normalized.startswith("stop"):
        httpx.post(f"{SPEECH_OUTPUT_URL}/stop", timeout=5.0)
        return []

    for phrase, cmd in COMMANDS.items():
        if phrase in normalized:
            print(f"command: {cmd!r}")
            subprocess.Popen(cmd, shell=True)
            return []

    if "go quiet" in normalized or "be quiet" in normalized or "quiet mode" in normalized:
        MODE = "named"
        print("mode → named")
        return []

    loaded = state.loaded_personas

    for phrase in BROADCAST_PHRASES:
        if normalized.startswith(phrase):
            return list(loaded)

    if MODE == "named":
        for pname in loaded:
            persona = state.personas.get(pname)
            if not persona:
                continue
            for ww in persona.wake_words:
                if normalized.startswith(ww):
                    return [pname]
        return []  # not addressed to any loaded persona

    return list(loaded)

@app.post("/think")
def think(req: ThinkRequest):
    persona = state.personas[state.active_persona]
    return {"text": _llm(persona, req.text)}

@app.post("/mode/{mode}")
def set_mode(mode: str):
    global MODE
    if mode not in {"open", "named"}:
        return {"error": f"unknown mode {mode!r}"}
    MODE = mode
    print(f"mode → {mode}")
    return {"mode": MODE}

@app.post("/stop")
def stop():
    httpx.post(f"{SPEECH_OUTPUT_URL}/stop", timeout=5.0).raise_for_status()
    return {"ok": True}

@app.post("/converse")
def converse(req: ThinkRequest):
    global _speaking, _last_spoke
    to_respond = _dispatch(req.text)
    if not to_respond:
        return {"text": ""}
    if _speaking or (time.time() - _last_spoke < SPEAK_COOLDOWN):
        print(f"ignored (cooldown): {req.text!r}")
        return {"text": ""}
    responses = []
    for pname in to_respond:
        persona = state.personas[pname]
        voice = state.voices.get(persona.voice, state.voices["default"])
        response = _llm(persona, req.text)
        if response:
            print(f"[{pname}] > {response}")
            _speaking = True
            try:
                _speak(response, voice.sample_file or "wav/bird-dream.wav")
            finally:
                _speaking = False
                _last_spoke = time.time()
        responses.append(response)
    return {"text": "\n".join(r for r in responses if r)}

services = ['speech_input', 'llm', 'speech_output']

def check_services():
    pass

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=PORT)
