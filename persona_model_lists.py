"""Persona model lists — what each provider says it offers.

At startup the hub asks the LLM service for every provider's model list.
That proves each provider's URL works, and the list is kept here, one JSON
file per provider in MODEL_LIST_DIR. Comparing a fresh list with the kept
one tells us which models are new since last time.

A list is only saved after a successful fetch, so a provider that is down
never wipes its kept list (which would make every model look new later).
"""

import json
from pathlib import Path

from persona_schemas import MODEL_LIST_DIR


# ─── Configuration ────────────────────────────────────────────────────────────

MAX_SPOKEN_MODELS = 3   # more new models than this: name a few, count the rest


# ─── Load & Save ──────────────────────────────────────────────────────────────

def list_file(provider: str) -> Path:
    """The file holding one provider's kept model list."""
    return MODEL_LIST_DIR / (provider + ".json")


def load_list(provider: str) -> list[str] | None:
    """The kept model list for this provider, or None if there isn't one yet."""
    path = list_file(provider)

    if not path.exists():
        return None

    return json.loads(path.read_text())


def save_list(provider: str, models: list[str]) -> None:
    """Keep this provider's model list, sorted, replacing the old one."""
    MODEL_LIST_DIR.mkdir(parents=True, exist_ok=True)
    list_file(provider).write_text(json.dumps(sorted(models), indent=2))


# ─── Comparing ────────────────────────────────────────────────────────────────

def new_models(kept: list[str], current: list[str]) -> list[str]:
    """Models in the current list that the kept list doesn't have, sorted."""
    return sorted(set(current) - set(kept))


def announcement(provider_name: str, models: list[str]) -> str:
    """
    What System says about new models at one provider, e.g.
    "New model Nancy Drew seen at provider Cerebras."
    Past MAX_SPOKEN_MODELS, the first few are named and the rest counted.
    """
    if len(models) == 1:
        return "New model " + models[0] + " seen at provider " + provider_name + "."

    named = models[:MAX_SPOKEN_MODELS]
    rest  = len(models) - len(named)

    sentence = "New models " + ", ".join(named) + " seen at provider " + provider_name

    if rest > 0:
        sentence = sentence + ", and " + str(rest) + " more"

    return sentence + "."
