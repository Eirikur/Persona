"""Persona Schemas — data definitions and persistent state.

Dataclasses for personas, voices, and speech-input profiles, plus
load/save of the global state file (~/.config/persona/state.json).

persona_hub.py imports from here; this file has no logic of its own
beyond reading and writing state.
"""

### We need more classes here. Classes? I guess that's the Pythonic way.
# System, a persona, nickname Cissy. System can act as the User/Owner. "Cissy, create a new user named Bob."
# Provider Class, holds the details for about a provider. Perhaps providers can  be
# a simple list of dicts without needing class instances. See  ~/.pi/agent/models.json (it should be called providers!) Pi's models JSON database is here:
# is here: ~/.pi/agent/models-store.json All those keys would be useful. I want the 

# When a Persona closes or is closed, the Persona framework receives a session_result dictionary or object, which holds
# start, duration, (the token counts for each type of token use), etc. Anything we can know about the session.




import json
import re
from dataclasses import dataclass, field, asdict
from pathlib import Path


# ─── Storage Location ─────────────────────────────────────────────────────────

STATE_FILE = Path.home() / ".config" / "persona" / "state.json"

# One JSON file per provider: the models it offered at the last startup check
# (see persona_model_lists.py).
MODEL_LIST_DIR = Path.home() / ".local" / "share" / "persona" / "model_lists"

# One JSON file per provider: what each of its models cost at the last
# startup check, in dollars per token (see persona_prices.py).
PRICE_DIR = Path.home() / ".local" / "share" / "persona" / "prices"

# Where each provider publishes its prices. Both answer in the same shape:
# {"data": [{"id": ..., "pricing": {"prompt": ..., "completion": ...}}]}.
# Cerebras's ordinary model list has no prices; its public one does.
PRICE_URLS = {
    "cerebras":   "https://api.cerebras.ai/public/v1/models",
    "openrouter": "https://openrouter.ai/api/v1/models",
}

# Providers that run on this machine: every turn costs nothing.
FREE_PROVIDERS = ("ollama", "echo")


# ─── Default Models ───────────────────────────────────────────────────────────

# The model each provider uses when a persona's model is None. Both the LLM
# service (to make the call) and the hub (to label the bubble) read this table.
# "echo" never calls a model; its entry is only the label shown on the bubble.
DEFAULT_MODELS = {
    "ollama":     "gemma3:12b",
    "openai":     "gpt-4o-mini",
    "cerebras":   "qwen-3.8-27b",
    # "perplexity": "sonar",   switched off, see PROVIDERS in persona_llm.py
    "openrouter": "google/gemini-2.0-flash-001",
    "echo":       "just an echo",
}

# How System says each provider's name out loud.
PROVIDER_NAMES = {
    "ollama":     "Ollama",
    "openai":     "OpenAI",
    "cerebras":   "Cerebras",
    "openrouter": "OpenRouter",
}


# ─── News Sources ─────────────────────────────────────────────────────────────

# The news command-line tools persona_tools.news_read can run. Each entry names
# the program, the environment variable (set in .env) that may hold its full
# path, and the sections it knows. The program is looked up on PATH when the
# environment variable is not set. To add a source, install its program and
# add one entry here.
NEWS_SOURCES = {
    "bbc": {
        "program":  "bbc",
        "env_var":  "BBC_BIN",
        "sections": ("top", "world", "uk", "tech", "science", "health",
                     "business", "entertainment", "sport", "politics"),
    },
}

# The most headlines news_read will return in one call. A voice assistant
# cannot read out more than this before the listener loses the thread.
NEWS_MAX_ITEMS = 8


# ─── Research (Perplexity) ────────────────────────────────────────────────────

# How deep persona_tools.research may go, and the Perplexity Agent API preset
# each depth uses. Deeper is slower and costs more: on 2026-10-15 "quick" took
# 2 s and "normal" 5.5 s, each well under a cent. Perplexity also has "xhigh",
# open-ended agent work that can run code; research has no use for it.
RESEARCH_PRESETS = {
    "quick":   "fast",     # one search, single facts
    "normal":  "low",      # a few searches, may read a page
    "deep":    "medium",   # many steps, many sources; can take minutes
    "deepest": "high",     # exhaustive source coverage; slowest, costs most
}

# Depths a persona may pick on its own. The deeper ones hold up a spoken
# reply for minutes, so only the owner can ask for them: the "research" row
# on the Settings tab, or a RESEARCH_DEEP_PHRASES phrase in the question.
RESEARCH_ALLOWED_DEPTHS = ("quick", "normal")

# Seconds one research call may take, by depth.
RESEARCH_TIMEOUTS = {
    "quick":   50,
    "normal":  50,
    "deep":    300,
    "deepest": 300,
}

# How long the hub waits for a whole reply, which may hold several research
# calls (see MAX_TOOL_ROUNDS in persona_llm.py). The long wait is used only
# when the turn's research depth is "deep" or "deepest".
REPLY_WAIT      = 60    # seconds
REPLY_WAIT_DEEP = 960   # seconds; three deep calls of up to 300 s, plus the answer

# Saying one of these anywhere in a question makes that one question's
# research "deep", whatever the Settings tab says.
RESEARCH_DEEP_PHRASES = (
    "research deeply",
    "deep research",
    "dig deep",
    "research thoroughly",
)


# ─── Memory ───────────────────────────────────────────────────────────────────

# Replay: each persona gets its last few exchanges with the owner sent along
# with every new message (see persona_memory.py). One exchange is the
# owner's message plus the persona's reply. More means a longer memory but
# a bigger, slower, costlier prompt on every turn.
REPLAY_EXCHANGES = 10

# Write the whole prompt (system prompt, replayed turns, new message) to the
# hub log on every LLM call, so it can be read in the Logs tab. Off since
# 2026-11-10: the Backstage window ("show backstage") shows the whole prompt,
# and more besides.
LOG_PROMPTS = False

# mem0 (hosted, free tier): when the "mem0" box on the Settings tab is ticked,
# mem0's own LLM reads every exchange and decides what is worth keeping, and
# the memories closest to each new message are added to the system prompt.
# The API key is MEM0_API_KEY in .env.
MEM0_URL            = "https://api.mem0.ai"
MEM0_USER_ID        = "eirikur"   # whose memories these are; every persona shares them
MEM0_TOP_K          = 5           # most memories added to one prompt
MEM0_MIN_SCORE      = 0.12        # weaker matches are shown in the Memory window but kept out of the prompt
MEM0_SEARCH_TIMEOUT = 3.0         # seconds; the reply waits for this, so keep it short
MEM0_ADD_TIMEOUT    = 30.0        # seconds; saving runs in the background
MEM0_EVENT_POLL     = 1.0         # seconds between asking mem0 whether a save is finished
MEM0_EVENT_WAIT     = 40.0        # seconds; stop following a save after this long


# ─── Reply Text Filter ────────────────────────────────────────────────────────

# LLMs write "curly" quotes and apostrophes (I’m, “each.”). Every reply has
# them swapped for plain ones as it arrives (see persona_text_filter.py), so
# logs, history, mem0 and Emacs all see ordinary ASCII quotes.
STRAIGHT_QUOTES = (
    ("\u2018", "'"),    # ‘  left single quote
    ("\u2019", "'"),    # ’  right single quote, the apostrophe in I’m
    ("\u201c", '"'),    # “  left double quote
    ("\u201d", '"'),    # ”  right double quote
)


# ─── Log Sources ──────────────────────────────────────────────────────────────

# The service logs the Logs tab follows: source name shown in the tab, mapped
# to its file in logs/. The tailer only reads these files, never changes them.
LOG_SOURCES = {
    "hub":        "hub.log",
    "llm":        "llm.log",
    "speech-out": "speech-out.log",
    "speech-in":  "speech-in.log",
    "led-ring":   "led-ring.log",
}

# The stripe colour for each source in the Logs tab. Chosen to read on the
# dark background and to stay clear of red and pink, which are kept for errors.
LOG_COLORS = {
    "hub":        "#6FA8DC",   # blue
    "llm":        "#8FBF7F",   # green
    "speech-out": "#D9B35F",   # gold
    "speech-in":  "#5FBFBF",   # teal
    "led-ring":   "#9A8FD6",   # violet
    "systemd":    "#C8CDD2",   # silver
}

# The sixth source is not a file: it is the user journal, which holds the
# lines systemd writes about the Persona services themselves (started,
# stopped, killed, out of memory). Their own output goes to the files above.
JOURNAL_SOURCE = "systemd"
JOURNAL_UNITS  = "persona-*"

# A log line containing any of these is routine chatter (microphone level
# posts, recording start/stop, LED ring commands) and is not shown.
LOG_NOISE_WORDS = ("mic_level", "recording_start", "recording_stop", "WriteCMD")

# Requests to the hub so frequent that they are not written to hub.log at
# all. The mic level arrives several times a second (it was 95% of a
# 104 MB hub.log); the chat page polls /state. Matched against the web
# server's access line, e.g.  "POST /mic_level/0.03 HTTP/1.1" 200 OK
QUIET_REQUESTS = (
    "POST /mic_level/",
    "GET /state HTTP",
)


# Every line of a prompt written to the hub log starts with this mark (see
# persona_memory.py). Replayed replies repeat on every turn, and a news
# headline saying "killed" must not light the Logs tab red each time.
PROMPT_MARK = "│ "


# ─── Error Detection ──────────────────────────────────────────────────────────

# A log line or trace entry containing any of these is shown as an error
# (red band, "!" in the gutter, red tab). Plain text matches, capitals as written.
ERROR_WORDS = (
    "ERROR", "Error", "Traceback", "Exception",
    "failed", "Failed", "killed", "Killed", "OOM", "oom-kill", "Out of memory",
)

# Text containing any of these is never an error, even if it has an error word.
# Each is a known harmless message, with the reason beside it.
ERROR_IGNORE_WORDS = (
    "timeout graceful shutdown exceeded",   # uvicorn, every time the hub stops with the page open
    "Frame latency is negative",            # Chromium rendering noise from the chat window
    PROMPT_MARK,                            # a line of a logged prompt: what was said, not what went wrong
)

# Trace event types that carry what people said. Their text is never checked
# for error words: a sentence that starts with "Error" is only speech.
SPEECH_EVENT_TYPES = ("heard", "corrected", "user_turn")


# PocketTTS's built-in English voices. A VoiceProfile whose sample_file is one
# of these names uses the preset instead of a cloned sample file. Spoken
# commands say "bill boerst"; the hub turns the space into an underscore.
PRESET_VOICES = (
    "cosette", "marius", "javert", "alba", "jean", "anna", "vera", "fantine",
    "charles", "paul", "eponine", "azelma", "george", "mary", "jane",
    "michael", "eve", "bill_boerst", "peter_yearsley", "stuart_bell",
    "caro_davy",
)


# ─── Data Classes ─────────────────────────────────────────────────────────────

@dataclass
class VoiceProfile:
    """A named voice for speech output. label is the name shown on the bubble; empty means use the sample file's name."""
    name: str
    sample_file: str = ""
    speed: float = 1.0
    label: str = ""


@dataclass
class InputProfile:
    """Speech-to-text settings for an input source."""
    name: str
    stt_model: str = "small.en"
    silence_duration: float = 0.6


@dataclass
class Persona:
    """One AI persona: its wake words, system prompt, voice, and LLM backend."""
    name: str
    wake_words: list[str] = field(default_factory=list)
    system_prompt: str = ("You are Salice, a helpful voice assistant. "
                          "Keep responses short and conversational — you are "
                          "speaking aloud, not writing. Two or three sentences "
                          "at most unless asked for more.")
    voice: str = "default"
    input: str = "default"
    provider: str = "cerebras"
    model: str | None = None
    tools: list[str] = field(default_factory=list)   # names into persona_tools.TOOLS
    font: str = ""    # print font for the bubble text, a path like fonts/dropped/x.ttf; empty = page default


@dataclass
class GlobalState:
    """Everything the hub persists: known personas, voices, and inputs."""
    active_persona: str = "default"
    loaded_personas: list[str] = field(default_factory=lambda: ["default"])

    personas: dict[str, Persona]      = field(default_factory=lambda: {
        "default": Persona(name="default", wake_words=["salice", "sal"], tools=["web_search"]),

        # Echo has provider="echo" -- persona_llm.py's echo branch hands the
        # input straight back with no LLM call, for testing dispatch, voice,
        # and multi-persona routing for free. See persona_llm.py's docstring.
        "echo": Persona(
            name="echo", wake_words=["echo"], provider="echo",
            system_prompt="(no LLM call -- echo provider returns input verbatim)",
        ),

        # Stubs for personas to be filled in later -- name and wake word
        # only, no system prompt written yet.
        "major": Persona(name="major", wake_words=["major"], system_prompt="(not yet defined)"),
        "hal":   Persona(name="hal",   wake_words=["hal"],   system_prompt="(not yet defined)"),
        "house": Persona(name="house", wake_words=["house"], system_prompt="(not yet defined)"),

        # The owner's own persona, nickname Cissy -- intended to act with
        # the owner's authority (including filesystem access) once personas
        # can call tools. No tools exist yet, so this is a stub too.
        "system": Persona(name="system", wake_words=["system", "cissy"],
                           system_prompt="(not yet defined -- intended to act as the owner)"),
    })
    voices:   dict[str, VoiceProfile] = field(default_factory=lambda: {"default": VoiceProfile(name="default")})
    inputs:   dict[str, InputProfile] = field(default_factory=lambda: {"default": InputProfile(name="default")})


# ─── Load & Save ──────────────────────────────────────────────────────────────

def load() -> GlobalState:
    """Read state from disk, or return defaults if no state file exists."""
    if not STATE_FILE.exists():
        return GlobalState()

    data = json.loads(STATE_FILE.read_text())
    personas = {k: Persona(**v) for k, v in data.get("personas", {}).items()}

    # Migrate: persona saved before wake_words was added
    if "default" in personas and not personas["default"].wake_words:
        personas["default"].wake_words = ["salice", "sal"]

    return GlobalState(
        active_persona  = data.get("active_persona", "default"),
        loaded_personas = data.get("loaded_personas", ["default"]),
        personas = personas,
        voices   = {k: VoiceProfile(**v) for k, v in data.get("voices", {}).items()},
        inputs   = {k: InputProfile(**v) for k, v in data.get("inputs", {}).items()},
    )


def save(state: GlobalState) -> None:
    """Write state to disk, creating the config directory if needed."""
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(asdict(state), indent=2))


def save_roster(state: GlobalState) -> None:
    """
    Write only who is in the chat room into state.json, leaving everything
    else in the file as it was. Joining or leaving the room saves at once,
    but session-only changes (a dropped font or voice) are kept on disk
    only by "system persist".

    With no state file yet, there is nothing to leave alone, so the whole
    state is written.
    """
    if not STATE_FILE.exists():
        save(state)
        return

    data = json.loads(STATE_FILE.read_text())
    data["loaded_personas"] = state.loaded_personas
    STATE_FILE.write_text(json.dumps(data, indent=2))


# ─── Setups ───────────────────────────────────────────────────────────────────

# A setup is a named copy of the whole system state, in the same format as
# state.json. Say "system persist as <name>" to save one. To start Persona
# from one, run: ./persona_start.sh --setup <name>
SETUP_DIR = Path.home() / ".config" / "persona" / "setups"


def clean_setup_name(spoken: str) -> str:
    """Turn spoken words into a safe file name: lowercase letters and digits,
    with a single hyphen between words. "My News Setup" becomes "my-news-setup".
    Returns an empty string if nothing usable is left."""
    not_a_letter_or_digit = r"[^a-z0-9]+"
    return re.sub(not_a_letter_or_digit, "-", spoken.lower()).strip("-")


def save_setup(state: GlobalState, name: str) -> Path:
    """Write the whole state to a named setup file and return its path."""
    SETUP_DIR.mkdir(parents=True, exist_ok=True)
    path = SETUP_DIR / (name + ".json")
    path.write_text(json.dumps(asdict(state), indent=2))
    return path
