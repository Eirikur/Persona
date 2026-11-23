#!/usr/bin/env -S uv run --no-project --script
# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "fastapi",
#     "uvicorn",
#     "httpx",
#     "python-dotenv",
# ]
# ///


"""Persona Hub — voice assistant routing server.

Merges speech and keyboard input, dispatches to personas, and serves the chat UI.
Single input source feeds four destinations: system commands, shell commands,
the active habitat (persona group), or a broadcast to all loaded personas.
"""


import asyncio
import json
import logging
import re
import subprocess
import sys
import threading
import time
import uvicorn
import httpx
from pathlib import Path
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import StreamingResponse
from dotenv import load_dotenv
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from persona_schemas import (
    DEFAULT_MODELS, LOG_PROMPTS, PRESET_VOICES, PROVIDER_NAMES, QUIET_REQUESTS,
    REPLY_WAIT, REPLY_WAIT_DEEP, RESEARCH_DEEP_PHRASES, RESEARCH_PRESETS,
    SPEECH_EVENT_TYPES, Persona, VoiceProfile, clean_setup_name, load, save,
    save_roster, save_setup,
)
from persona_scripts import SCRIPTS, script_output
import persona_backstage
import persona_data_window
import persona_memory_window
import persona_memory
import persona_text_filter

load_dotenv()   # API keys from .env (mem0's, for persona_memory.py)

# The hub's output goes to logs/hub.log, and Python holds file output back
# in 8 KB blocks. Write each line as it is printed instead, so the Logs tab
# shows what happened when it happened -- including lines printed later by
# background threads, like mem0's saves.
sys.stdout.reconfigure(line_buffering=True)


class QuietRequests(logging.Filter):
    """Keep the web server from logging the requests in QUIET_REQUESTS."""

    def filter(self, record) -> bool:
        """False (drop the line) if it's one of QUIET_REQUESTS, else True."""
        line = record.getMessage()

        for request in QUIET_REQUESTS:
            if request in line:
                return False

        return True


# uvicorn writes one "access" line per request; this drops the noisy ones.
logging.getLogger("uvicorn.access").addFilter(QuietRequests())

from persona_model_lists import announcement, load_list, new_models, save_list
from persona_prices import changed_prices, load_prices, price_change_text, save_prices
from persona_log_tailer import looks_like_error, recent_lines, start_tailing


# ─── Configuration ────────────────────────────────────────────────────────────

PORT              = 8400
LLM_URL           = "http://127.0.0.1:8401"
SPEECH_OUTPUT_URL = "http://127.0.0.1:8402"
SPEECH_INPUT_URL  = "http://127.0.0.1:8403"

# A recording that starts within this long after a persona stops talking
# still counts as hearing the persona: the last word may still be leaving
# the speaker, and the voice detector opens a moment after sound begins.
SELF_HEAR_MARGIN = 1.0   # seconds

# Voice input caught while a persona talks is held and replayed once the
# persona is done -- unless it is mostly the persona's own words coming back
# through the mic. ECHO_OVERLAP is the share of a transcript's words that must
# also be in a recent reply for it to count as that echo and be dropped.
ECHO_OVERLAP   = 0.6
REPLIES_KEPT   = 3     # how many recent replies the echo check compares against

SUMMARY_SPEAKER = "system"   # persona whose voice speaks script results (SAY: lines)
SHUTDOWN_GRACE  = 2.0   # seconds to wait for a reload's SSE reconnect before really shutting down

# Every new chat bubble tries to get the owner's attention, so Persona doesn't
# keep listening unnoticed behind other windows. Two independent alerts, each
# safe to flip off on its own:
#   - RAISE_CHAT_WINDOW uses wmctrl, which needs X11 -- it won't do anything
#     useful under a native Wayland session.
#   - NOTIFY_ON_BUBBLE uses notify-send (freedesktop.org desktop
#     notifications over D-Bus), which works the same under X11 and Wayland,
#     so it keeps alerting even if RAISE_CHAT_WINDOW quietly stops working
#     after a future Wayland migration.
CHAT_WINDOW_TITLE  = "Persona Chat"   # must match <title> in persona_chat.html
RAISE_CHAT_WINDOW  = True
NOTIFY_ON_BUBBLE   = True

# Providers that run on this machine rather than over the network -- the chat
# UI shows local providers in plain text and remote ones in the highlight
# color, so a glance says whether a reply left the box.
LOCAL_PROVIDERS = ("ollama", "echo")

# What the bubble shows for a provider, where the plain name would confuse.
# The echo provider is not a service, so its bubble just says "internal"
# ("local" could mean anything on this machine or the LAN).
PROVIDER_LABELS = {
    "echo": "internal",
}

# Voice samples dropped onto a bubble are saved here, one new file per drop,
# so the original voice files are never overwritten and old drops stay
# available to switch back to.
DROPPED_VOICE_DIR = Path(__file__).parent / "audio" / "dropped"

# Longest voice sample a drop may carry. The speech engine reads the whole
# sample into memory: a 35 MB (three-minute) wav grew the speech service to
# 16 GB and got it killed, while 10 MB samples are fine.
MAX_VOICE_BYTES = 12_000_000

# Fonts dropped onto a bubble are copied here, same never-overwrite rule.
# The first four bytes of a font file say what kind it is.
DROPPED_FONT_DIR = Path(__file__).parent / "fonts" / "dropped"
FONT_SIGNATURES  = {
    b"\x00\x01\x00\x00": ".ttf",
    b"true":             ".ttf",
    b"OTTO":             ".otf",
    b"wOFF":             ".woff",
    b"wOF2":             ".woff2",
}

# Sample used when a voice profile names no file of its own.
DEFAULT_VOICE_SAMPLE = "audio/bird-dream.wav"


# ─── Dispatch Tables ──────────────────────────────────────────────────────────

# Shell commands triggered by voice. Each key is matched against normalized input.
COMMANDS: dict[str, str] = {
    "firefox":     "~/scripts/toggle.sh Firefox ~/Applications/firefox/firefox",
    "thunderbird": "~/scripts/toggle.sh Thunderbird thunderbird",
    "email":       "~/scripts/toggle.sh Thunderbird thunderbird",
    "emacs":       "wmctrl -R 'ξmacs:' || emacsclient -n -a '' ",
    "restart":     "~/Proj/Persona/persona_start.sh &> ~/Proj/Persona/persona.log",
}

# Spoken commands that run a script from SCRIPTS (persona_scripts.py). The chat
# window is told to show the Test tab and run it there. Each phrase must be the
# very START of the input, ignoring punctuation and case ("System, run test."
# matches "system run test").
#
# Never use a phrase that appears inside the canned test message ("Sal, this is
# a system test. Do you hear me?"): the pipeline check sends that text through
# dispatch(), so a phrase that matched it would make the check start itself.
SCRIPT_PHRASES: dict[str, str] = {
    "system run test":          "pipeline_check",
    "system check reply":       "pipeline_check",
    "system check recognition": "stt_check",
}

# Spoken command that writes everything unsaved (dropped fonts, roster changes)
# into the stored settings. Matched like SCRIPT_PHRASES: at the very start.
PERSIST_PHRASE = "system persist"

# Spoken command that gives a persona a built-in voice: "system voice sal george".
# Matched like PERSIST_PHRASE, then the persona name and preset name follow.
VOICE_PHRASE = "system voice "

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

# Words that stop a persona mid-speech. While a persona talks, they count
# anywhere in a short recording ("Echo, stop", "uh... hush"): the mic often
# catches a few other words before the owner's. "be quiet" also switches the
# room to named mode. See is_stop_request().
STOP_WORDS = (
    "stop",
    "hush",
    "be quiet",
)
STOP_MAX_WORDS = 8   # more of the owner's own words than this is a sentence, not a stop

# Phrases that open (or bring forward) the data window, which shows what the
# personas' tools returned. Matched as whole words anywhere in the input,
# so "show the data, please" works too.
DATA_PHRASES = (
    "show data",
    "show the data",
    "show me data",
    "show me the data",
)

# Phrases that open (or bring forward) the Backstage window, which shows
# everything behind each reply. Matched like DATA_PHRASES. Whisper may
# write the word as one or two, so both are here.
BACKSTAGE_PHRASES = (
    "show backstage",
    "show back stage",
    "show the backstage",
    "show the back stage",
    "show me backstage",
    "show me back stage",
)

# Phrases that open (or bring forward) the Memory window, which shows what
# mem0 looked up and kept. Matched like DATA_PHRASES. Whisper won't write
# "mem0", so the spoken forms say "memory"; "show mem0" is for typing.
MEMORY_PHRASES = (
    "show memory",
    "show the memory",
    "show me memory",
    "show me the memory",
    "show memories",
    "show the memories",
    "show me the memories",
    "show mem zero",
    "show mem0",
)

# Phrases that route input to all loaded personas simultaneously.
BROADCAST_PHRASES = (
    "hi gang",    "hello gang",    "hey gang",
    "hi everyone","hello everyone","hey everyone",
)


# ─── Runtime State ────────────────────────────────────────────────────────────

state          = load()

# The chat room comes back as it was left: joining and leaving are saved
# as they happen (see save_roster). Names no longer known are dropped. If
# nobody is left, Echo starts alone, so there is always someone to answer.
room = []
for name in state.loaded_personas:
    if name in state.personas:
        room.append(name)

if not room:
    room = ["echo"]

state.loaded_personas = room
state.active_persona  = room[0]

speaking       = False   # True from the moment a reply goes out until its audio ends

# Several replies can be on their way to speech output at once (speech
# output plays them one after another). `speaking` stays True until the
# last of them ends, so the first one finishing doesn't open the mic to the
# others.
replies_in_flight = 0
replies_lock      = threading.Lock()
playing        = False   # True only once the audio is actually audible (after rendering)
last_spoke     = 0.0
last_speaker   = "Sal"     # display name of the persona who spoke most recently
recent_replies = []        # text of the last few spoken replies, newest last (for the echo check)

# Voice input heard over a persona, oldest first, waiting to be replayed one
# at a time as each round of speech finishes. The lock keeps two finishing
# rounds from replaying the same input.
held_inputs    = []
held_lock      = threading.Lock()

# Self-hear verdicts. A recording that began while a persona was talking (or
# just after) has the persona's voice in it, so its transcript is ignored.
# The verdict is taken when the recording starts and handed on when it stops,
# because the transcript arrives after the stop -- by then a new recording
# may already have started.
recording_heard_persona = False   # the recording in progress
finished_heard_persona  = False   # the last recording that ended (its text comes next)

# A stop means "be silent now": voice input recorded before it, mostly the
# persona's own voice, is dropped rather than held and replayed afterwards.
# Start times are handed on from recording to transcript like the verdicts above.
recording_began = 0.0   # when the recording in progress started
finished_began  = 0.0   # when the last recording that ended started
last_stop       = 0.0   # when a stop word last silenced a persona

MODE           = "named"   # "named" = wake-word required, "open" = always listening
MUTED          = False     # True = ignore voice input; typed input still goes through
MEM0_ON        = False     # True = mem0 picks memories for each prompt (Settings tab box)
RESEARCH_DEPTH = "auto"    # research depth from the Settings tab; "auto" = the persona chooses
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

    start_tailing(emit_log_line)

    threading.Thread(target=check_providers, daemon=True).start()

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


def emit(event_type: str, text: str, **extra) -> None:
    """Push a generic event to all connected SSE clients, flagged if its text reads as an error."""
    if not event_loop:
        return

    if "error" not in extra:
        extra["error"] = event_type not in SPEECH_EVENT_TYPES and looks_like_error(text)

    data = json.dumps({"type": event_type, "text": text, **extra})
    for q in event_queues:
        asyncio.run_coroutine_threadsafe(q.put(data), event_loop)



def effective_model(persona: Persona) -> str:
    """The model this persona's replies come from: its own setting, else its provider's default ("just an echo" for echo)."""
    return persona.model or DEFAULT_MODELS.get(persona.provider, "")


def voice_label(voice: VoiceProfile) -> str:
    """The name shown on the bubble: the voice's label if it has one, else its sample file name without directory or extension."""
    return voice.label or Path(voice.sample_file or DEFAULT_VOICE_SAMPLE).stem


def display_name(persona_name: str) -> str:
    """What the owner calls a persona: "Sal" for the internal key "default",
    otherwise the key with a capital letter. Matches personaDisplayName() in
    persona_chat.html."""
    if persona_name == "default":
        return "Sal"

    return persona_name.capitalize()


def emit_persona_turn(persona_name: str, text: str, provider: str, model: str, voice: str) -> None:
    """Push a persona response event to all connected SSE clients."""
    announce_bubble(persona_name, text)
    if not event_loop:
        return
    data = json.dumps({
        "type":           "persona_turn",
        "persona":        persona_name,
        "text":           text,
        "provider":       PROVIDER_LABELS.get(provider, provider),
        "provider_local": provider in LOCAL_PROVIDERS,
        "model":          model,
        "voice":          voice,
    })
    for q in event_queues:
        asyncio.run_coroutine_threadsafe(q.put(data), event_loop)


def emit_log_line(entry: dict) -> None:
    """Push one new service log line to all connected SSE clients."""
    emit("service_log", entry["text"], source=entry["source"], time=entry["time"],
         full=entry["full"], color=entry["color"], error=entry["error"])


def emit_mic_level(level: float) -> None:
    """Push a raw microphone brightness reading (0..1) to all connected SSE clients."""
    if not event_loop:
        return
    data = json.dumps({"type": "mic_level", "level": level})
    for q in event_queues:
        asyncio.run_coroutine_threadsafe(q.put(data), event_loop)


# ─── Attention Alerts ──────────────────────────────────────────────────────────

def chat_window_focused() -> bool:
    """
    True if the Persona Chat window (or the data window) already has focus.

    Checked via xdotool's active-window title rather than a window id, so
    there's no id-format bookkeeping to get wrong. Any failure here (no
    xdotool, no active window, X server hiccup) reports False rather than
    raising, so a broken check just means an alert fires when it didn't
    strictly need to -- never the other way around.
    """
    try:
        name = subprocess.check_output(
            ["xdotool", "getactivewindow", "getwindowname"],
            stderr=subprocess.DEVNULL, timeout=1,
        ).decode().strip()
    except (FileNotFoundError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return False
    # The side windows count too: raising the chat window over one while
    # the owner reads it would hide what they asked to see.
    side_windows = (
        persona_data_window.DATA_WINDOW_TITLE,
        persona_backstage.BACKSTAGE_WINDOW_TITLE,
        persona_memory_window.MEMORY_WINDOW_TITLE,
    )

    return name == CHAT_WINDOW_TITLE or name in side_windows


def raise_chat_window() -> None:
    """Bring the Persona Chat window to the front, via wmctrl (X11 only)."""
    if not RAISE_CHAT_WINDOW:
        return

    try:
        subprocess.Popen(["wmctrl", "-R", CHAT_WINDOW_TITLE])
    except FileNotFoundError:
        print("raise_chat_window: wmctrl not found -- skipping")


def notify_new_bubble(summary: str, body: str) -> None:
    """
    Pop a desktop notification for a new chat bubble.

    Uses notify-send, which goes over the standard freedesktop.org D-Bus
    notifications API -- unlike raise_chat_window, this keeps working
    unchanged under Wayland, so it's the fallback that survives a future
    desktop migration even if window-raising quietly stops working.
    """
    if not NOTIFY_ON_BUBBLE:
        return

    try:
        subprocess.Popen(["notify-send", summary, body])
    except FileNotFoundError:
        print("notify_new_bubble: notify-send not found -- skipping")


def announce_bubble(summary: str, body: str) -> None:
    """Run both attention alerts for a newly-added chat bubble, unless the window already has focus."""
    if chat_window_focused():
        return
    raise_chat_window()
    notify_new_bubble(summary, body)


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

def llm(persona: Persona, system_prompt: str, messages: list[dict], research_depth: str = "auto") -> str:
    """
    Send a prompt to the LLM service and return the response string, with
    curly quotes straightened (see persona_text_filter.py).
    messages is the conversation so far, ending with the newest input
    (see persona_memory.py); the system prompt goes separately.

    research_depth is how deep any research call in this reply goes ("auto"
    lets the persona choose). Deep research can take minutes, so the hub
    then waits REPLY_WAIT_DEEP for the reply instead of REPLY_WAIT.
    """
    if LOG_PROMPTS:
        print(persona_memory.prompt_text(display_name(persona.name), system_prompt, messages))

    wait = REPLY_WAIT
    if research_depth in ("deep", "deepest"):
        wait = REPLY_WAIT_DEEP

    r = httpx.post(f"{LLM_URL}/v1/chat/completions", timeout=wait, json={
        "provider":       persona.provider,
        "model":          persona.model,
        "system_prompt":  system_prompt,
        "messages":       messages,
        "tools":          persona.tools,
        "persona":        display_name(persona.name),
        "research_depth": research_depth,
    })
    r.raise_for_status()

    # A model that says nothing sends no content at all; treat that as "".
    reply = r.json()["choices"][0]["message"]["content"] or ""

    return persona_text_filter.straighten_quotes(reply)


def research_depth_for(text: str) -> str:
    """
    The research depth for one input: the Settings tab's choice, raised to
    "deep" if the input says one of RESEARCH_DEEP_PHRASES ("dig deep").
    A spoken phrase never lowers a deeper Settings choice.
    """
    asked_for_deep = False
    for phrase in RESEARCH_DEEP_PHRASES:
        if phrase in text.lower():
            asked_for_deep = True

    if asked_for_deep and RESEARCH_DEPTH not in ("deep", "deepest"):
        return "deep"

    return RESEARCH_DEPTH


def speak(response_text: str, voice_prompt: str) -> None:
    """
    Send text to the speech output service.

    If the service is down, dies mid-reply (it has been killed for running
    out of memory), or times out, say so in the log and carry on: the reply
    stays on screen and the caller still finishes its turn.
    """
    try:
        httpx.post(f"{SPEECH_OUTPUT_URL}/speak", timeout=120.0, json={
            "text":         response_text,
            "voice_prompt": voice_prompt,
        }).raise_for_status()
    except httpx.HTTPError as problem:
        reason = type(problem).__name__
        print(f"speech output failed: {reason} {problem}")
        emit("log", "speech output failed (" + reason + ") -- no audio for that reply")


def say(persona_name: str, text: str) -> None:
    """
    Show text as this persona's reply and speak it in their voice.

    From now until the audio ends, `speaking` is True (`playing` turns True
    once rendering is done and sound starts), and afterwards the time it
    stopped is noted. Together these let recording_start() tell when the
    microphone is hearing the persona, so it does not answer itself (see
    SELF_HEAR_MARGIN). Every spoken reply goes through here, including the
    summaries scripts ask for.
    """
    global speaking, playing, last_spoke, last_speaker, replies_in_flight

    if not text.strip():
        print(f"persona {persona_name}: empty reply, nothing to say")
        return

    persona = state.personas[persona_name]
    voice   = state.voices.get(persona.voice, state.voices["default"])

    emit_persona_turn(persona_name, text, persona.provider, effective_model(persona), voice_label(voice))
    last_speaker = display_name(persona_name)

    with replies_lock:
        replies_in_flight += 1
        speaking = True

    recent_replies.append(text)
    del recent_replies[:-REPLIES_KEPT]

    try:
        # Time speech synthesis
        speak_start = time.time()
        speak(text, voice.sample_file or DEFAULT_VOICE_SAMPLE)
        speak_duration = time.time() - speak_start
        print(f"Speech output triggered in {speak_duration:.2f}s")
    finally:
        with replies_lock:
            replies_in_flight -= 1
            if replies_in_flight == 0:
                speaking   = False
                playing    = False
            last_spoke = time.time()


def ignored_reason() -> str:
    """Say why voice input is being ignored right now: reply still rendering,
    audio playing, or the recording began while the persona was talking."""
    if speaking and not playing:
        return "while " + last_speaker + "'s reply was still rendering (not yet audible)"

    if speaking:
        return "while " + last_speaker + " was speaking"

    return "recording began while " + last_speaker + " was speaking, or just after"


def say_summary(text: str) -> None:
    """Speak a script's SAY: line in SUMMARY_SPEAKER's voice, so Sal never reads out reports on herself."""
    say(SUMMARY_SPEAKER, text)
    speech_finished()


def speech_finished() -> None:
    """Tell the chat page this round of speech is over, then replay the
    oldest held voice input, if any (see hold_input)."""
    emit("speak_done", "")
    replay_held_input()


# ─── Provider Check ───────────────────────────────────────────────────────────

PROVIDER_CHECK_WAIT = 120   # seconds to wait for the LLM service, chat page and speech-out


def wait_until(ready, seconds: float) -> bool:
    """Call ready() every two seconds until it returns True, or give up
    after this many seconds. Returns whether it became ready."""
    give_up_at = time.time() + seconds

    while time.time() < give_up_at:
        if ready():
            return True
        time.sleep(2)

    return False


def answers_http(url: str) -> bool:
    """True if anything answers at this URL, even "not found": the service is up."""
    try:
        httpx.get(url, timeout=2.0)
        return True
    except httpx.HTTPError:
        return False


def check_providers() -> None:
    """
    At startup, fetch every provider's model list through the LLM service.
    A list that comes back proves the provider's URL (and key) work. Each
    result goes to TRACE; it's flagged as an error when the URL is broken,
    or when a persona actually uses that provider.

    The list is kept (persona_model_lists.py). Models not in the kept list
    are named in TRACE, and System says so out loud. The first listing for
    a provider is only kept, not announced.

    Runs in its own thread, and first waits for the chat page (or TRACE
    lines would be sent to nobody) and for speech-out (or System couldn't
    speak). Everything is also printed, for the hub log.
    """
    wait_until(lambda: answers_http(LLM_URL + "/docs"), PROVIDER_CHECK_WAIT)
    wait_until(lambda: len(event_queues) > 0, PROVIDER_CHECK_WAIT)
    wait_until(lambda: answers_http(SPEECH_OUTPUT_URL + "/docs"), PROVIDER_CHECK_WAIT)

    try:
        # Up to 10 s per model list and 10 s per price list, one provider
        # after another, so allow well over a minute.
        answers = httpx.get(LLM_URL + "/provider_models", timeout=120.0).json()
    except httpx.HTTPError as problem:
        print(f"provider check failed: {problem}")
        emit("log", "provider check failed: the LLM service didn't answer (" + type(problem).__name__ + ")", error=True)
        return

    providers_in_use = set(persona.provider for persona in state.personas.values())
    models_in_use    = set(effective_model(persona) for persona in state.personas.values())
    spoken = []

    for answer in answers:
        provider = answer["provider"]
        status   = answer["status"]
        models   = answer["models"]
        name     = PROVIDER_NAMES.get(provider, provider)

        spoken.extend(check_prices(provider, name, answer.get("prices", {}), models_in_use))

        if status != "ok":
            text    = "provider " + name + ": " + status + " -- " + answer["reason"]
            serious = status == "bad_url" or provider in providers_in_use
            if not serious:
                text = text + " (no persona uses it)"
            print(text)
            emit("log", text, error=serious)
            continue

        kept = load_list(provider)
        save_list(provider, models)

        if kept is None:
            text = "provider " + name + ": OK, " + str(len(models)) + " models (first listing, kept for next time)"
            print(text)
            emit("log", text, error=False)
            continue

        added = new_models(kept, models)
        text  = "provider " + name + ": OK, " + str(len(models)) + " models, " + str(len(added)) + " new"
        if added:
            text = text + ": " + ", ".join(added)
            spoken.append(announcement(name, added))
        print(text)
        emit("log", text, error=False)

    if spoken:
        say_summary(" ".join(spoken))


def check_prices(provider: str, name: str, prices: dict, models_in_use: set) -> list[str]:
    """
    Keep one provider's fresh prices (persona_prices.py) and report any
    that changed since last time. Every change goes to TRACE and the hub
    log; only changes to models a persona uses are returned, for System to
    say out loud. OpenRouter alone lists hundreds of models, and most
    changes there don't matter to us.

    Empty prices mean none were published or the fetch failed: the kept
    ones stay. The first prices for a provider are only kept, not reported.
    """
    if not prices:
        return []

    kept = load_prices(provider)
    save_prices(provider, prices)

    if kept is None:
        text = "provider " + name + ": " + str(len(prices)) + " prices (first listing, kept for next time)"
        print(text)
        emit("log", text, error=False)
        return []

    spoken = []

    for model in changed_prices(kept, prices):
        text = price_change_text(name, model, kept[model], prices[model])
        print(text)
        emit("log", text, error=False)

        if model in models_in_use:
            spoken.append(text)

    return spoken


# ─── Held Voice Input ─────────────────────────────────────────────────────────

def plain_words(text: str) -> list[str]:
    """Lowercase words only, punctuation dropped, so two texts can be compared word by word."""
    not_a_word = r"[^a-z0-9' ]+"
    return re.sub(not_a_word, " ", text.lower()).split()


def sounds_like_echo(text: str) -> bool:
    """
    True when most of this transcript's words are in a recent reply: the
    mic picked up a persona's own voice. ECHO_OVERLAP sets "most".

    A short answer like "yes" counts as echo if the reply also said "yes";
    a recording of the owner and the persona at once lands in between.
    """
    heard = plain_words(text)
    if not heard:
        return True

    reply_words = set()
    for reply in recent_replies:
        reply_words.update(plain_words(reply))

    matching = [word for word in heard if word in reply_words]
    return len(matching) / len(heard) >= ECHO_OVERLAP


def hold_input(text: str) -> None:
    """Keep voice input heard over a persona, to replay once speech finishes."""
    with held_lock:
        held_inputs.append(text)

    print(f"held (spoke over {last_speaker}): {text!r}")
    emit("held", "until " + last_speaker + " finishes: " + text)

    # A recording that began while the persona talked can end after the
    # persona is done. Then no round of speech is left to replay it, so
    # replay it now.
    if not speaking:
        replay_held_input()


def replay_held_input() -> None:
    """
    Send the oldest held voice input through the normal voice path, as if
    it had just been heard. Only one at a time: its own reply ends in
    speech_finished(), which replays the next. Runs in its own thread so
    the round that just finished can return.
    """
    with held_lock:
        if not held_inputs:
            return
        text = held_inputs.pop(0)

    print(f"replaying held input: {text!r}")
    request = ThinkRequest(text=text, replayed=True)
    threading.Thread(target=converse, args=(request,), daemon=True).start()


# ─── Stop Words ───────────────────────────────────────────────────────────────

def is_stop_request(text: str, check_echo: bool) -> bool:
    """
    True when this input asks a talking persona to stop: a short recording
    with one of STOP_WORDS anywhere in it ("stop", "Echo, stop", "hush").

    With check_echo, a recording that is mostly the persona's own words is
    not a stop: "don't stop now" in her reply, coming back through the mic,
    must not cut her off. But only if her reply has a stop word in it: if
    not, the stop word came from the owner, however much of her the mic
    caught too ("...across the table. Stop."). A stop word said on its own
    always counts.
    """
    words = plain_words(text)

    # Count only the owner's words: the mic often catches a sentence of the
    # persona's before the stop, and that shouldn't make it "too long".
    reply_words = set()
    for reply in recent_replies:
        reply_words.update(plain_words(reply))

    owner_words = [word for word in words if word not in reply_words]
    if len(owner_words) > STOP_MAX_WORDS:
        return False

    spoken = " ".join(words)

    remaining = spoken
    for stop_word in STOP_WORDS:
        pattern   = r"\b" + re.escape(stop_word) + r"\b"
        remaining = re.sub(pattern, " ", remaining)

    if remaining == spoken:
        return False    # no stop word in it

    if not remaining.split():
        return True     # nothing but stop words

    if check_echo and replies_have_stop_word() and sounds_like_echo(spoken):
        return False

    return True


def replies_have_stop_word() -> bool:
    """True when a recent persona reply has one of STOP_WORDS in it."""
    for reply in recent_replies:
        reply_words = " ".join(plain_words(reply))

        for stop_word in STOP_WORDS:
            pattern = r"\b" + re.escape(stop_word) + r"\b"
            if re.search(pattern, reply_words):
                return True

    return False


def stop_speaking(normalized: str) -> None:
    """
    Silence the persona that is talking, and forget voice input held while
    it talked: after a stop, nothing queued should start it up again.
    "be quiet" also switches the room to named mode.
    """
    global MODE, last_stop

    print(f"stop: {normalized!r}")
    emit("heard", normalized)

    # Clear the held input before stopping the audio: the stopped reply
    # finishes at once, and its speech_finished() would replay the next one.
    last_stop = time.time()

    with held_lock:
        dropped = len(held_inputs)
        held_inputs.clear()

    if dropped:
        print(f"stop: dropped {dropped} held input(s)")

    httpx.post(f"{SPEECH_OUTPUT_URL}/stop", timeout=5.0)

    if "be quiet" in " ".join(plain_words(normalized)):
        MODE = "named"
        print("mode → named")


# ─── Dispatch Logic ───────────────────────────────────────────────────────────

def absent_persona_named(spoken_words: str, loaded: list[str]) -> str:
    """
    Return the persona whose name is the first word of the input, if that
    persona is not in the chat room. Otherwise return an empty string.

    Used in named mode, where talking to someone who isn't here would
    otherwise get no reply and no sign of why. System is skipped: its
    name starts commands, and it never sits in the room.
    """
    words = spoken_words.split()
    if not words:
        return ""
    first_word = words[0]

    for pname, persona in state.personas.items():
        if pname in loaded or pname == SUMMARY_SPEAKER:
            continue
        if first_word in persona.wake_words:
            return pname

    return ""


def dispatch(text: str, typed: bool = False, replayed: bool = False) -> tuple[list[str], bool]:
    """
    Decide which loaded personas should respond to this input, and whether
    it should show up as a chat bubble at all.

    Returns (persona_names, show_bubble). persona_names is empty when no
    response is needed. show_bubble is False only for voice input dropped
    by the self-hear guard below, so Sal hearing her own voice doesn't
    raise the chat window or fire a notification either.

    replayed is True for voice input that was held because it was spoken
    over a persona (see hold_input); it already passed the guard once.

    Typed input always reaches full dispatch; in named mode it still must
    start with a loaded persona's wake word (e.g. typing "salice ..."
    addresses just Sal), so that with several personas loaded, typing a
    plain sentence doesn't page all of them at once.

    Routing order:
      1. Apply MISHEARINGS corrections
      2. STOP_WORDS        → interrupt speech, return ([], True)
                             ("be quiet" also switches to named mode)
      3. Self-hear guard (voice only) → drop the persona's own echo, or
         hold the owner's words for later; return ([], False) either way
      4. PERSIST_PHRASE    → save state to disk, return ([], True)
         DATA_PHRASES      → open the data window, return ([], True)
         SCRIPT_PHRASES    → tell the chat window to run a script, return ([], True)
      5. COMMANDS match    → run shell command, return ([], True)
      6. Quiet phrases     → switch to named mode, return ([], True)
      7. BROADCAST_PHRASES → all loaded personas
      8. Named mode → persona whose wake word matches (and switches the
         room to open mode for what follows), or []. If the first word
         names a persona who is out of the room, System says so.
      9. Open mode  → all loaded personas
    """
    global MODE

    normalized = text.strip().lower().rstrip(".,!")
    original   = normalized

    # Whole-word replacement only: \b marks a word boundary, so "alice"
    # corrects to "salice" but the "alice" inside "salice" is left alone.
    for heard, intended in MISHEARINGS.items():
        pattern = r"\b" + re.escape(heard) + r"\b"
        normalized = re.sub(pattern, intended, normalized)

    # A persona is talking now, or this voice recording began while one was
    # (see recording_start).
    persona_talking = speaking or (not typed and finished_heard_persona)
    heard_persona   = persona_talking and not typed and not replayed

    # While a persona talks, a stop word anywhere in a short input stops it.
    # Otherwise only input that starts with "stop" does, so a question like
    # "how do I stop a process" still reaches the personas.
    if persona_talking and is_stop_request(normalized, check_echo=heard_persona):
        stop_speaking(normalized)
        return [], True

    if normalized.startswith("stop"):
        stop_speaking(normalized)
        return [], True

    # A persona's own voice reaching the mic would otherwise be free to
    # trigger COMMANDS, scripts, or a reply to itself. Stop words above are
    # the one voice command that must still get through, so a persona can be
    # interrupted by hand. Words that aren't the persona's own are the owner
    # talking over it: hold them until the persona is done.
    if heard_persona:
        if finished_began < last_stop:
            print(f"ignored (recorded before stop): {normalized!r}")
            emit("ignored", "recorded before the stop: " + original)
        elif sounds_like_echo(normalized):
            print(f"ignored (self-hear): {normalized!r}")
            emit("ignored", ignored_reason() + ": " + original)
        else:
            hold_input(text)
        return [], False

    emit("heard", original)
    if normalized != original:
        emit("corrected", normalized)

    print(f"[{MODE}] dispatch: {normalized!r}")

    # Drop punctuation so "System, run test." reads as "system run test".
    not_a_word   = r"[^a-z0-9' ]+"
    spoken_words = " ".join(re.sub(not_a_word, " ", normalized).split())

    if spoken_words.startswith(PERSIST_PHRASE):
        words = spoken_words[len(PERSIST_PHRASE):].split()

        # "as" is optional: speech recognition often drops it.
        if words[:1] == ["as"]:
            words = words[1:]

        if words:
            reply = setup_command(words)
            print(reply)
            emit("log", reply)
            threading.Thread(target=say_summary, args=(reply,), daemon=True).start()
            return [], True

        save(state)
        print("state persisted")
        emit("log", "settings persisted")
        return [], True

    if spoken_words.startswith(VOICE_PHRASE):
        words = spoken_words[len(VOICE_PHRASE):].split()
        reply = voice_command(words)
        print(reply)
        emit("log", reply)
        return [], True

    for phrase in DATA_PHRASES:
        if " " + phrase + " " in " " + spoken_words + " ":
            print("data window: show")
            emit("log", "showing the data window")
            threading.Thread(target=persona_data_window.show_window,
                             args=(CHAT_WINDOW_TITLE,), daemon=True).start()
            return [], True

    for phrase in BACKSTAGE_PHRASES:
        if " " + phrase + " " in " " + spoken_words + " ":
            print("backstage window: show")
            emit("log", "showing the Backstage window")
            threading.Thread(target=persona_backstage.show_window,
                             args=(CHAT_WINDOW_TITLE,), daemon=True).start()
            return [], True

    for phrase in MEMORY_PHRASES:
        if " " + phrase + " " in " " + spoken_words + " ":
            print("memory window: show")
            emit("log", "showing the Memory window")
            threading.Thread(target=persona_memory_window.show_window,
                             args=(CHAT_WINDOW_TITLE,), daemon=True).start()
            return [], True

    for phrase, script in SCRIPT_PHRASES.items():
        if spoken_words.startswith(phrase):
            print(f"script command: {script!r}")
            emit("run_script", script)
            return [], True

    for phrase, cmd in COMMANDS.items():
        if phrase in normalized:
            print(f"command: {cmd!r}")
            subprocess.Popen(cmd, shell=True)
            return [], True

    if "go quiet" in normalized or "be quiet" in normalized or "quiet mode" in normalized:
        MODE = "named"
        print("mode → named")
        return [], True

    loaded = state.loaded_personas

    for phrase in BROADCAST_PHRASES:
        if normalized.startswith(phrase):
            return list(loaded), True

    if MODE == "named":
        for pname in loaded:
            persona = state.personas.get(pname)
            if not persona:
                continue
            for ww in persona.wake_words:
                if normalized.startswith(ww):
                    # Being named switches the room to open mode, so the
                    # rest of the exchange doesn't need a name on every
                    # line. Say "go quiet" to require one again.
                    MODE = "open"
                    print(f"mode → open (named {pname})")
                    return [pname], True

        # Nobody here answers to that name. If it names someone who is
        # out of the room, System says so. The sentence doesn't start
        # with the name, so if the mic hears it, it won't call them again.
        missing = absent_persona_named(spoken_words, loaded)
        if missing:
            notice = "Nobody named " + display_name(missing) + " is in the room."
            print("named miss: " + missing)
            emit("log", notice)
            threading.Thread(target=say_summary, args=(notice,), daemon=True).start()
        return [], True

    return list(loaded), True


# ─── API Routes ───────────────────────────────────────────────────────────────

class ThinkRequest(BaseModel):
    text:     str
    typed:    bool = False   # True = from chat box, skips the self-hear gate
    replayed: bool = False   # True = voice input held while a persona talked, now replayed
    speaker:  str  = "you"   # chat-bubble label for this input; overridden by e.g. the test trigger


class ToolResult(BaseModel):
    persona:   str   # display name of the persona that called the tool
    question:  str   # the input that persona was answering
    tool:      str
    arguments: str   # exactly as the model sent them (JSON text)
    result:    str   # exactly as the model got it back
    data:      str = ""   # the tool's full structure as JSON text, if it has one


class Turn(BaseModel):
    persona:  str          # display name of the persona that replied
    provider: str
    model:    str
    steps:    list[dict]   # see step() in persona_llm.py
    cost:     float | None = None   # dollars; None when the price isn't known


@app.get("/state")
def get_state():
    """Report current mode, the loaded roster, and the active persona's provider/model."""
    persona = state.personas[state.active_persona]
    return {
        "mode":             MODE,
        "muted":            MUTED,
        "mem0":             MEM0_ON,
        "research_depth":   RESEARCH_DEPTH,
        "persona":          state.active_persona,
        "provider":         persona.provider,
        "model":            persona.model,
        "loaded_personas":  state.loaded_personas,
        "personas":         list(state.personas),
        "fonts":            {name: p.font for name, p in state.personas.items() if p.font},
    }


@app.post("/persona/{persona_name}/load")
def load_persona(persona_name: str):
    """Bring a persona into the chat room, so it hears input and may reply."""
    if persona_name not in state.personas:
        raise HTTPException(status_code=404, detail="Unknown persona: " + persona_name)

    if persona_name not in state.loaded_personas:
        state.loaded_personas.append(persona_name)
        save_roster(state)

    emit("roster", "", loaded_personas=state.loaded_personas)
    print(f"persona {persona_name} joined the chat")
    return {"loaded_personas": state.loaded_personas}


@app.post("/persona/{persona_name}/unload")
def unload_persona(persona_name: str):
    """Remove a persona from the chat room. Its earlier bubbles stay on screen."""
    if persona_name not in state.personas:
        raise HTTPException(status_code=404, detail="Unknown persona: " + persona_name)

    if persona_name in state.loaded_personas:
        state.loaded_personas.remove(persona_name)
        save_roster(state)

    emit("roster", "", loaded_personas=state.loaded_personas)
    print(f"persona {persona_name} left the chat")
    return {"loaded_personas": state.loaded_personas}


@app.get("/logs/recent")
def logs_recent():
    """The most recent service log lines, oldest first, for a page that just opened."""
    return list(recent_lines)


@app.post("/think")
def think(req: ThinkRequest):
    """Send text directly to the active persona's LLM. No dispatch, no speech."""
    persona = state.personas[state.active_persona]
    messages = [{"role": "user", "content": req.text}]
    return {"text": llm(persona, persona.system_prompt, messages)}


@app.post("/memory/mem0/{setting}")
def set_mem0(setting: str):
    """
    Turn mem0 on or off ("on" / "off"), from the Settings tab's mem0 box.
    Replay of recent exchanges stays on either way. Refuses to turn on
    without an API key, so the box can't look ticked while doing nothing.
    """
    global MEM0_ON

    if setting not in ("on", "off"):
        raise HTTPException(status_code=400, detail="mem0 setting must be on or off")

    if setting == "on" and not persona_memory.mem0_key():
        emit("log", "mem0 not turned on: no MEM0_API_KEY in .env")
        raise HTTPException(status_code=400, detail="no MEM0_API_KEY in .env")

    MEM0_ON = setting == "on"
    print(f"mem0 → {setting}")
    emit("log", "mem0 " + setting)
    return {"mem0": MEM0_ON}


def show_memory_record(kind: str, persona_name: str, details: dict) -> dict:
    """
    Keep a mem0 search or save for the Memory window, tell listening pages
    about it with a short "memory" notice, and return the record.
    """
    record = persona_memory_window.add_record("mem0", kind, display_name(persona_name), details)
    emit("memory", persona_memory_window.notice_text(record),
         id=record["id"], error=bool(record.get("error")))
    return record


def save_to_mem0(persona_name: str, text: str, reply: str) -> None:
    """
    Hand one exchange to mem0, then follow it until mem0 has decided what
    to keep. The Memory window sees the save at once, as pending, and again
    when the decision is in. Runs in its own thread.
    """
    save = {
        "said":      text,
        "reply":     reply,
        "status":    "PENDING",
        "decisions": [],
        "seconds":   0.0,
    }
    save.update(persona_memory.mem0_save(text, reply))

    if save["error"]:
        save["status"] = "FAILED"

    record = show_memory_record("save", persona_name, save)

    if not save["event_id"]:
        return

    outcome = persona_memory.mem0_follow(save["event_id"])
    record  = persona_memory_window.update_record(record["id"], outcome)

    if record:
        emit("memory", persona_memory_window.notice_text(record),
             id=record["id"], error=bool(record.get("error")))


@app.get("/memory/recent")
def memory_recent():
    """Every kept mem0 search and save, newest first, for the Memory window."""
    return persona_memory_window.recent_records()


# Must come before /memory/{record_id}, or "all" would be taken for a record id.
@app.get("/memory/all")
def memory_all():
    """
    Everything mem0 holds for the owner, for the Memory window's "All
    memories" view. Read-only, and works with mem0 switched off; each
    call asks mem0 afresh.
    """
    return persona_memory.mem0_list_all()


@app.get("/memory/{record_id}")
def memory_record(record_id: int):
    """One kept mem0 search or save, by id; 404 if it has been forgotten."""
    record = persona_memory_window.find_record(record_id)
    if record is None:
        raise HTTPException(status_code=404, detail="no such memory record")

    return record


@app.post("/research/{depth}")
def set_research_depth(depth: str):
    """
    Set how deep the personas' research goes, from the Settings tab:
    "auto" (each persona chooses, quick or normal), or one of the depths in
    RESEARCH_PRESETS for every research call until changed. Back to "auto"
    at every hub start.
    """
    global RESEARCH_DEPTH

    if depth != "auto" and depth not in RESEARCH_PRESETS:
        raise HTTPException(status_code=400, detail="unknown research depth: " + depth)

    RESEARCH_DEPTH = depth
    print(f"research depth → {depth}")
    emit("log", "research depth " + depth)
    return {"research_depth": RESEARCH_DEPTH}


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

    The hub is the one place mute is kept. Every change is announced as a
    "mute" event ("on" or "off"), so the chat page and the LED ring always
    show the hub's real setting rather than their own guess.
    """
    global MUTED
    if setting not in {"on", "off"}:
        return {"error": f"unknown mute setting {setting!r}"}
    MUTED = (setting == "on")
    print(f"muted → {MUTED}")

    emit("mute", setting)
    return {"muted": MUTED}


@app.post("/mic_level/{value}")
def mic_level(value: float):
    """Relay a raw microphone brightness reading (0..1) from the speech-input
    service to the chat UI, where it drives the HEARING label's flicker."""
    emit_mic_level(value)
    return {"ok": True}


@app.post("/recording_start")
def recording_start():
    """Relay the STT recorder's VAD signal that real speech has begun, so the
    LED ring can leave DOA hunting and show it's actively listening. Also notes
    whether a persona was talking as it began, so its transcript can be judged."""
    global recording_heard_persona, recording_began

    just_stopped = time.time() - last_spoke < SELF_HEAR_MARGIN
    recording_heard_persona = speaking or just_stopped
    recording_began         = time.time()

    emit("recording_start", "")
    return {"ok": True}


@app.post("/recording_stop")
def recording_stop():
    """Relay the matching VAD signal that speech has ended, whether or not a
    transcript follows -- lets the LED ring fall back to DOA hunting even if
    the speech didn't turn into a transcribed "heard" event. The transcript that
    follows belongs to this recording, so its self-hear verdict is handed on."""
    global finished_heard_persona, finished_began

    finished_heard_persona = recording_heard_persona
    finished_began         = recording_began

    emit("recording_stop", "")
    return {"ok": True}


@app.post("/tool_call/{name}")
def tool_call(name: str):
    """Relay persona_llm.py's signal that it's about to run a tool call, so
    the LED ring and chat UI can show that the wait includes a tool, not
    just the model thinking."""
    emit("tool_call", name)
    return {"ok": True}


@app.post("/tool_result")
def tool_result(report: ToolResult):
    """Keep a copy of what a tool returned, for the data window. Only a
    one-line notice goes over the event stream; the window fetches the rest."""
    record = persona_data_window.add_record(
        report.persona, report.question, report.tool, report.arguments, report.result, report.data,
    )

    emit("tool_result", persona_data_window.notice_text(record), id=record["id"], error=False)
    return {"ok": True}


@app.get("/data/recent")
def data_recent():
    """Every kept tool result, newest first, for the data window to show when it opens."""
    return persona_data_window.recent_records()


@app.get("/data/{record_id}")
def data_record(record_id: int):
    """One kept tool result, fetched by the data window when a notice for it arrives."""
    record = persona_data_window.find_record(record_id)
    if record is None:
        raise HTTPException(status_code=404, detail="no such tool result (forgotten, or the hub restarted)")

    return record


@app.post("/turn")
def turn(report: Turn):
    """Keep a whole turn for the Backstage window. Only a one-line notice
    goes over the event stream; the window fetches the rest."""
    kept = persona_backstage.add_turn(report.persona, report.provider, report.model, report.steps, report.cost)

    emit("turn", persona_backstage.notice_text(kept), id=kept["id"], error=False)
    return {"ok": True}


@app.get("/backstage/recent")
def backstage_recent():
    """Every kept turn, newest first, for the Backstage window to show when it opens."""
    return persona_backstage.recent_turns()


@app.get("/backstage/{turn_id}")
def backstage_turn(turn_id: int):
    """One kept turn, fetched by the Backstage window when a notice for it arrives."""
    kept = persona_backstage.find_turn(turn_id)
    if kept is None:
        raise HTTPException(status_code=404, detail="no such turn (forgotten, or the hub restarted)")

    return kept


@app.post("/playback_start")
def playback_start():
    """Relay persona_speech_output.py's signal that rendered audio has
    started actually playing, as distinct from persona_turn (text is ready,
    but Chatterbox hasn't rendered it yet) -- the two can be many seconds
    apart on a long reply."""
    global playing
    playing = True
    emit("playback_start", "")
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


@app.post("/voice/{persona_name}")
async def set_voice(persona_name: str, request: Request, name: str = ""):
    """
    Swap a persona's voice sample for the wav file in the request body.

    The optional "name" query parameter is the file's original name; its stem
    is shown on the bubble, while the saved copy gets a timestamped name.

    The persona is not told: its next spoken reply simply comes out in the
    new voice. Gets its own voice profile, so other personas sharing the
    "default" voice are unaffected.
    """
    if persona_name not in state.personas:
        raise HTTPException(status_code=404, detail="Unknown persona: " + persona_name)

    body = await request.body()
    if body[:4] != b"RIFF":
        raise HTTPException(status_code=400, detail="Not a wav file")

    if len(body) > MAX_VOICE_BYTES:
        megabytes = len(body) / 1_000_000
        limit     = MAX_VOICE_BYTES / 1_000_000
        raise HTTPException(status_code=413,
                            detail=f"Voice sample is {megabytes:.0f} MB; the limit is {limit:.0f} MB")

    DROPPED_VOICE_DIR.mkdir(parents=True, exist_ok=True)
    stamp     = time.strftime("%Y%m%d-%H%M%S")
    file_name = persona_name + "-" + stamp + ".wav"
    (DROPPED_VOICE_DIR / file_name).write_bytes(body)

    persona = state.personas[persona_name]
    old     = state.voices.get(persona.voice, state.voices["default"])
    state.voices[persona_name] = VoiceProfile(
        name        = persona_name,
        sample_file = "audio/dropped/" + file_name,
        speed       = old.speed,
        label       = Path(name).stem,
    )
    persona.voice = persona_name
    save(state)

    print(f"persona {persona_name} voice → audio/dropped/{file_name}")
    return {"persona": persona_name, "sample_file": "audio/dropped/" + file_name}


def assign_preset_voice(persona_name: str, preset: str) -> None:
    """
    Give a persona one of PocketTTS's built-in voices, or a Kokoro voice
    written "kokoro:af_bella=0.6,am_adam=0.4", and save.

    Like a voice drop, the persona gets its own voice profile, so other
    personas sharing the "default" voice are unaffected. Raises ValueError
    with a plain message if the persona or the preset is unknown.
    """
    if persona_name not in state.personas:
        raise ValueError("Unknown persona: " + persona_name)

    is_kokoro = preset.startswith("kokoro:")

    if not is_kokoro and preset not in PRESET_VOICES:
        raise ValueError("Unknown preset voice: " + preset + ". Choices: " + ", ".join(PRESET_VOICES) + ", or kokoro:<voice>=<weight>,...")

    persona = state.personas[persona_name]
    old     = state.voices.get(persona.voice, state.voices["default"])
    state.voices[persona_name] = VoiceProfile(
        name        = persona_name,
        sample_file = preset,
        speed       = old.speed,
        label       = preset,
    )
    persona.voice = persona_name
    save(state)

    print(f"persona {persona_name} voice → preset {preset}")


def setup_command(words: list[str]) -> str:
    """
    Carry out "system persist [as] <name>" and return a line to report.

    words is the setup name, which may be several words
    ("my news" is saved as my-news). The whole state goes to a named file;
    start Persona from it with: ./persona_start.sh --setup <name>
    """
    name = clean_setup_name(" ".join(words))
    if not name:
        return "Say: system persist as, then a name for the setup."

    path = save_setup(state, name)
    print("setup written to " + str(path))
    return "Saved setup " + name


def voice_command(words: list[str]) -> str:
    """
    Carry out "system voice <persona> <preset>" and return a line to report.

    words is what follows "system voice": the persona name, then the preset
    name, which may be several words ("bill boerst" is bill_boerst).
    """
    if len(words) < 2:
        return "Say: system voice, a persona name, then a voice name."

    persona_name = words[0]
    preset       = "_".join(words[1:])

    try:
        assign_preset_voice(persona_name, preset)
    except ValueError as problem:
        return str(problem)

    return persona_name + " now uses the " + preset + " voice"


@app.post("/voice_preset/{persona_name}/{preset}")
def save_voice_preset(persona_name: str, preset: str):
    """Give a persona one of PocketTTS's built-in voices (see PRESET_VOICES). Takes effect on its next spoken reply."""
    try:
        assign_preset_voice(persona_name, preset)
    except ValueError as problem:
        raise HTTPException(status_code=400, detail=str(problem))

    return {"persona": persona_name, "preset": preset}


@app.post("/font/{persona_name}")
async def save_font(persona_name: str, request: Request, name: str = ""):
    """
    Keep a copy of a font file dropped onto a persona's bubble.

    Files the font under fonts/dropped/ with a timestamped name and records
    the path on the persona. Like a voice drop it lives in memory until
    saved, but unlike a voice drop it is not saved here: say "system persist".
    """
    if persona_name not in state.personas:
        raise HTTPException(status_code=404, detail="Unknown persona: " + persona_name)

    body      = await request.body()
    extension = FONT_SIGNATURES.get(body[:4])
    if extension is None:
        raise HTTPException(status_code=400, detail="Not a font file")

    DROPPED_FONT_DIR.mkdir(parents=True, exist_ok=True)
    stamp     = time.strftime("%Y%m%d-%H%M%S")
    file_name = persona_name + "-" + stamp + "-" + Path(name).stem + extension
    (DROPPED_FONT_DIR / file_name).write_bytes(body)

    state.personas[persona_name].font = "fonts/dropped/" + file_name

    print(f"persona {persona_name} font → fonts/dropped/{file_name}")
    return {"persona": persona_name, "saved_file": "fonts/dropped/" + file_name}


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


@app.post("/run_script/{name}")
def run_script(name: str):
    """Run one of the named scripts in persona_scripts.SCRIPTS and stream its output as plain text. Speaks any SAY: line it prints once it finishes."""
    if name not in SCRIPTS:
        raise HTTPException(status_code=404, detail="no such script: " + name)

    return StreamingResponse(script_output(name, say_summary), media_type="text/plain")


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
    if MUTED and not req.typed:
        return {"text": ""}

    start_time = time.time()
    to_respond, show_bubble = dispatch(req.text, req.typed, req.replayed)

    if not show_bubble:
        return {"text": ""}

    # Shown as a chat bubble regardless of whether any persona will answer,
    # so the owner can see what speech input heard even when nobody's named.
    emit("user_turn", req.text, speaker=req.speaker)
    announce_bubble(req.speaker, req.text)

    if not to_respond:
        speech_finished()
        return {"text": ""}

    responses = []

    for pname in to_respond:
        persona = state.personas[pname]

        emit("inference", "")

        # The persona hears its earlier exchanges again, then the new input.
        messages = persona_memory.messages_for(pname, req.text)
        print(f"[{pname}] replaying {len(messages) - 1} earlier messages")

        # With mem0 on, the memories closest to the input join the system
        # prompt. Echo never calls a model, so it has no use for them.
        use_mem0      = MEM0_ON and persona.provider != "echo"
        system_prompt = persona.system_prompt

        if use_mem0:
            search_text   = persona_memory.without_name(req.text, persona.wake_words)
            search        = persona_memory.mem0_search(search_text)
            system_prompt = system_prompt + persona_memory.memories_block(search["hits"])
            show_memory_record("search", pname, search)

        depth = research_depth_for(req.text)
        if depth != "auto":
            print(f"[{pname}] research depth for this reply: {depth}")

        # Time LLM inference
        llm_start = time.time()
        response = llm(persona, system_prompt, messages, depth)
        llm_duration = time.time() - llm_start

        persona_memory.remember_exchange(pname, req.text, response)

        if use_mem0 and response.strip():
            threading.Thread(target=save_to_mem0,
                             args=(pname, req.text, response), daemon=True).start()

        if response:
            print(f"[{pname}] > {response} (LLM: {llm_duration:.2f}s)")
            say(pname, response)
        responses.append(response)

    total_duration = time.time() - start_time
    print(f"Total converse cycle: {total_duration:.2f}s")
    speech_finished()
    return {"text": "\n".join(r for r in responses if r)}


# ─── Entry Point ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    # The chat page holds a live-update connection open, which would make a
    # stop wait for systemd's 90-second force-kill. Give connections three
    # seconds to finish, then close them.
    uvicorn.run(app, host="127.0.0.1", port=PORT, timeout_graceful_shutdown=3)
