#!/usr/bin/env -S uv run --no-project --script
# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "fastapi",
#     "uvicorn",
#     "httpx",
# ]
# ///

"""Persona Hub — voice assistant routing server.

Merges speech and keyboard input, dispatches to personas, and serves the chat UI.
Single input source feeds four destinations: system commands, shell commands,
the active habitat (persona group), or a broadcast to all loaded personas.
"""

import asyncio
import json
import re
import subprocess
import threading
import time
import uvicorn
import httpx
from pathlib import Path
from fastapi import FastAPI
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from persona_schemas import Persona, load, save


# ─── Configuration ────────────────────────────────────────────────────────────

PORT              = 8400
LLM_URL           = "http://127.0.0.1:8401"
SPEECH_OUTPUT_URL = "http://127.0.0.1:8402"
SPEECH_INPUT_URL  = "http://127.0.0.1:8403"

SPEAK_COOLDOWN  = 8.0
SHUTDOWN_GRACE  = 2.0   # seconds to wait for a reload's SSE reconnect before really shutting down


# ─── Dispatch Tables ──────────────────────────────────────────────────────────

# Shell commands triggered by voice. Each key is matched against normalized input.
COMMANDS: dict[str, str] = {
    "firefox":     "~/scripts/toggle.sh Firefox ~/Applications/firefox/firefox",
    "thunderbird": "~/scripts/toggle.sh Thunderbird thunderbird",
    "email":       "~/scripts/toggle.sh Thunderbird thunderbird",
    "emacs":       "wmctrl -R 'ξmacs:' || emacsclient -n -a '' ",
    "restart":     "~/Proj/Persona/persona_start.sh &> ~/Proj/Persona/persona.log",
}

# STT mishearing corrections. Applied to every input before dispatch.
MISHEARINGS: dict[str, str] = {
    "emax":     "emacs",
    "e-backs":  "emacs",
    "e-racks":  "emacs",
    "e-max":    "emacs",
    "imax":     "emacs",
    "solace":   "salice",
    "alice":    "salice",
    "sal ease": "salice",
    "salish":    "salice",
    "ciao":     "salice",

}

# Phrases that route input to all loaded personas simultaneously.
BROADCAST_PHRASES = (
    "hi gang",    "hello gang",    "hey gang",
    "hi everyone","hello everyone","hey everyone",
)


# ─── Runtime State ────────────────────────────────────────────────────────────

state          = load()
speaking       = False
last_spoke     = 0.0
MODE           = "named"   # "named" = wake-word required, "open" = always listening
MUTED          = False     # True = ignore voice input; typed input still goes through
shutdown_timer = None      # pending threading.Timer, or None if no shutdown is queued


# ─── FastAPI App & SSE Event Bus ──────────────────────────────────────────────

app = FastAPI(title="Persona Chat", description="AI model habitat")
app.mount("/ui", StaticFiles(directory=Path(__file__).parent, html=True), name="ui")

event_queues: list[asyncio.Queue]          = []
event_loop:   asyncio.AbstractEventLoop | None = None


@app.on_event("startup")
async def startup_event():
    """Initialize the event loop and warm up the active LLM to reduce first-turn latency."""
    global event_loop
    event_loop = asyncio.get_running_loop()

    # Warmup the active persona's LLM to avoid first-turn latency (e.g. Ollama loading)
    try:
        active_name = state.active_persona
        persona = state.personas.get(active_name)
        if persona:
            print(f"Warming up LLM for {active_name} ({persona.provider})...")
            async with httpx.AsyncClient() as client:
                await client.post(f"{LLM_URL}/v1/chat/completions", timeout=60.0, json={
                    "provider":      persona.provider,
                    "model":         persona.model,
                    "system_prompt": persona.system_prompt,
                    "messages":      [{"role": "user", "content": "warmup"}],
                })
            print("LLM warmup complete.")
    except Exception as e:
        print(f"LLM warmup failed: {e}")


def emit(event_type: str, text: str) -> None:
    """Push a generic event to all connected SSE clients."""
    if not event_loop:
        return
    data = json.dumps({"type": event_type, "text": text})
    for q in event_queues:
        asyncio.run_coroutine_threadsafe(q.put(data), event_loop)


def emit_sal(persona_name: str, text: str) -> None:
    """Push a persona response event to all connected SSE clients."""
    if not event_loop:
        return
    data = json.dumps({"type": "sal_turn", "persona": persona_name, "text": text})
    for q in event_queues:
        asyncio.run_coroutine_threadsafe(q.put(data), event_loop)


def emit_mic_level(level: float) -> None:
    """Push a raw microphone brightness reading (0..1) to all connected SSE clients."""
    if not event_loop:
        return
    data = json.dumps({"type": "mic_level", "level": level})
    for q in event_queues:
        asyncio.run_coroutine_threadsafe(q.put(data), event_loop)


@app.get("/events")
async def events():
    """
    SSE endpoint — clients connect here to receive real-time chat events.

    A reload tears the page down and reconnects here within a fraction of a
    second, so a fresh connection cancels any shutdown that reload's unload
    handler just queued. Only a real window close, with no reconnect, lets
    that shutdown actually run.
    """
    global shutdown_timer
    if shutdown_timer is not None:
        print("reconnect seen -- cancelling queued shutdown")
        shutdown_timer.cancel()
        shutdown_timer = None

    q: asyncio.Queue = asyncio.Queue()
    event_queues.append(q)

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
                event_queues.remove(q)
            except ValueError:
                pass

    return StreamingResponse(generate(), media_type="text/event-stream", headers={
        "Cache-Control":    "no-cache",
        "X-Accel-Buffering": "no",
    })


# ─── LLM & Speech Clients ─────────────────────────────────────────────────────

def llm(persona: Persona, text: str) -> str:
    """Send text to the LLM service and return the response string."""
    r = httpx.post(f"{LLM_URL}/v1/chat/completions", timeout=60.0, json={
        "provider":      persona.provider,
        "model":         persona.model,
        "system_prompt": persona.system_prompt,
        "messages":      [{"role": "user", "content": text}],
    })
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"]


def speak(response_text: str, voice_prompt: str) -> None:
    """Send text to the speech output service. Silent no-op if service is down."""
    try:
        httpx.post(f"{SPEECH_OUTPUT_URL}/speak", timeout=120.0, json={
            "text":         response_text,
            "voice_prompt": voice_prompt,
        }).raise_for_status()
    except httpx.ConnectError:
        print("speech output not available")


# ─── Dispatch Logic ───────────────────────────────────────────────────────────

def dispatch(text: str, typed: bool = False) -> list[str]:
    """
    Decide which loaded personas should respond to this input.

    Returns a list of persona names. Empty list = no response needed.

    `typed` input (from the chat box) is a deliberate, addressed act, so it
    skips the named-mode wake-word gate and reaches the loaded personas
    directly. Only voice input is gated by wake words in named mode.

    Routing order:
      1. Apply MISHEARINGS corrections
      2. "stop"            → interrupt speech, return []
      3. COMMANDS match    → run shell command, return []
      4. Quiet phrases     → switch to named mode, return []
      5. BROADCAST_PHRASES → all loaded personas
      6. Named mode + voice → persona whose wake word matches, or []
      7. Open mode or typed → all loaded personas
    """
    global MODE

    normalized = text.strip().lower().rstrip(".,!")
    original   = normalized

    # Whole-word replacement only: \b marks a word boundary, so "alice"
    # corrects to "salice" but the "alice" inside "salice" is left alone.
    for heard, intended in MISHEARINGS.items():
        pattern = r"\b" + re.escape(heard) + r"\b"
        normalized = re.sub(pattern, intended, normalized)

    emit("heard", original)
    if normalized != original:
        emit("corrected", normalized)

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

    if MODE == "named" and not typed:
        for pname in loaded:
            persona = state.personas.get(pname)
            if not persona:
                continue
            for ww in persona.wake_words:
                if normalized.startswith(ww):
                    return [pname]
        return []

    return list(loaded)


# ─── API Routes ───────────────────────────────────────────────────────────────

class ThinkRequest(BaseModel):
    text: str
    typed: bool = False   # True = from chat box, skips wake-word gate + cooldown


@app.get("/state")
def get_state():
    """Report current mode, the loaded roster, and the active persona's provider/model."""
    persona = state.personas[state.active_persona]
    return {
        "mode":             MODE,
        "muted":            MUTED,
        "persona":          state.active_persona,
        "provider":         persona.provider,
        "model":            persona.model,
        "loaded_personas":  state.loaded_personas,
    }


@app.post("/think")
def think(req: ThinkRequest):
    """Send text directly to the active persona's LLM. No dispatch, no speech."""
    persona = state.personas[state.active_persona]
    return {"text": llm(persona, req.text)}


@app.post("/mode/{mode}")
def set_mode(mode: str):
    """Switch between 'named' (wake-word required) and 'open' (always listening) modes."""
    global MODE
    if mode not in {"open", "named"}:
        return {"error": f"unknown mode {mode!r}"}
    MODE = mode
    print(f"mode → {mode}")
    return {"mode": MODE}


@app.post("/mute/{setting}")
def set_mute(setting: str):
    """
    Mute or unmute voice input. Muted voice input is ignored before it
    reaches dispatch, so it never triggers an LLM response or speech.
    Typed input (the chat box, the Test button) always goes through.
    """
    global MUTED
    if setting not in {"on", "off"}:
        return {"error": f"unknown mute setting {setting!r}"}
    MUTED = (setting == "on")
    print(f"muted → {MUTED}")
    return {"muted": MUTED}


@app.post("/mic_level/{value}")
def mic_level(value: float):
    """Relay a raw microphone brightness reading (0..1) from the speech-input
    service to the chat UI, where it drives the HEARING label's flicker."""
    emit_mic_level(value)
    return {"ok": True}


@app.post("/model/{model}")
def set_model(model: str):
    """Update the model for the active persona."""
    persona = state.personas[state.active_persona]
    persona.model = model
    save(state)
    print(f"active persona {state.active_persona} model → {model}")
    return {"active_persona": state.active_persona, "model": model}


@app.post("/provider/{provider}")
def set_provider(provider: str):
    """Update the provider for the active persona."""
    persona = state.personas[state.active_persona]
    persona.provider = provider
    save(state)
    print(f"active persona {state.active_persona} provider → {provider}")
    return {"active_persona": state.active_persona, "provider": provider}


@app.post("/stop")
def stop():
    """Interrupt current speech output."""
    httpx.post(f"{SPEECH_OUTPUT_URL}/stop", timeout=5.0).raise_for_status()
    
    return {"ok": True}


@app.post("/trigger_test")
def trigger_test():
    """Ask the speech input service to feed the test audio file."""
    try:
        r = httpx.post(f"{SPEECH_INPUT_URL}/test", timeout=10.0)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        return {"error": str(e)}


def run_shutdown():
    """Actually stop every Persona service. Runs once the grace period elapses."""
    print(f"no reconnect within {SHUTDOWN_GRACE}s -- shutting down")
    subprocess.Popen(["/bin/bash", "./persona_shutdown.sh"])


@app.post("/shutdown")
def shutdown():
    """
    Queue a shutdown after SHUTDOWN_GRACE seconds. The chat window's unload
    handler calls this on both a page reload and a real window close -- a
    reload reconnects to /events almost immediately and cancels this timer,
    so only a real close (no reconnect) ends up stopping the services.
    """
    global shutdown_timer
    print(f"shutdown requested, waiting {SHUTDOWN_GRACE}s for a reload to cancel it")
    shutdown_timer = threading.Timer(SHUTDOWN_GRACE, run_shutdown)
    shutdown_timer.start()
    return {"ok": True}


@app.post("/converse")
def converse(req: ThinkRequest):
    """
    Main input endpoint. Accepts merged speech+keyboard text, dispatches to
    personas, runs LLM inference, and speaks each response in turn.
    """
    global speaking, last_spoke

    if MUTED and not req.typed:
        return {"text": ""}

    start_time = time.time()
    to_respond = dispatch(req.text, req.typed)
    if not to_respond:
        emit("speak_done", "")
        return {"text": ""}

    if not req.typed and (speaking or (time.time() - last_spoke < SPEAK_COOLDOWN)):
        print(f"ignored (cooldown): {req.text!r}")
        return {"text": ""}

    emit("user_turn", req.text)
    responses = []

    for pname in to_respond:
        persona  = state.personas[pname]
        voice    = state.voices.get(persona.voice, state.voices["default"])
        
        # Time LLM inference
        llm_start = time.time()
        response = llm(persona, req.text)
        llm_duration = time.time() - llm_start
        
        if response:
            print(f"[{pname}] > {response} (LLM: {llm_duration:.2f}s)")
            emit_sal(pname, response)
            speaking = True
            try:
                # Time speech synthesis
                speak_start = time.time()
                speak(response, voice.sample_file or "audio/bird-dream.wav")
                speak_duration = time.time() - speak_start
                print(f"Speech output triggered in {speak_duration:.2f}s")
            finally:
                speaking   = False
                last_spoke = time.time()
        responses.append(response)

    total_duration = time.time() - start_time
    print(f"Total converse cycle: {total_duration:.2f}s")
    emit("speak_done", "")
    return {"text": "\n".join(r for r in responses if r)}


# ─── Entry Point ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=PORT)
