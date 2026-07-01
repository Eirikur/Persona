"""Persona Schemas — data definitions and persistent state.

Dataclasses for personas, voices, and speech-input profiles, plus
load/save of the global state file (~/.config/persona/state.json).

persona_hub.py imports from here; this file has no logic of its own
beyond reading and writing state.
"""

import json
from dataclasses import dataclass, field, asdict
from pathlib import Path


# ─── Storage Location ─────────────────────────────────────────────────────────

STATE_FILE = Path.home() / ".config" / "persona" / "state.json"


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
    provider: str = "ollama"
    model: str | None = None


@dataclass
class GlobalState:
    """Everything the hub persists: known personas, voices, and inputs."""
    active_persona: str = "default"
    loaded_personas: list[str] = field(default_factory=lambda: ["default"])

    personas: dict[str, Persona]      = field(default_factory=lambda: {"default": Persona(name="default", wake_words=["salice", "sal"])})
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
