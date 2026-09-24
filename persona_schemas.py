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
from dataclasses import dataclass, field, asdict
from pathlib import Path


# ─── Storage Location ─────────────────────────────────────────────────────────

STATE_FILE = Path.home() / ".config" / "persona" / "state.json"


# ─── Default Models ───────────────────────────────────────────────────────────

# The model each provider uses when a persona's model is None. Both the LLM
# service (to make the call) and the hub (to label the bubble) read this table.
# "echo" has no model -- it never calls one.
DEFAULT_MODELS = {
    "ollama":     "gemma3:12b",
    "openai":     "gpt-4o-mini",
    "cerebras":   "qwen-3.8-27b",
    "perplexity": "sonar",
    "openrouter": "google/gemini-2.0-flash-001",
}


# ─── Data Classes ─────────────────────────────────────────────────────────────

@dataclass
class VoiceProfile:
    """A named voice for speech output."""
    name: str
    sample_file: str = ""
    speed: float = 1.0


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
