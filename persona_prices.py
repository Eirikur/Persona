"""Persona prices — what each model costs, and what each turn cost.

At startup the LLM service fetches each provider's price list (PRICE_URLS
in persona_schemas.py) along with its model list. The hub keeps the prices
here, one JSON file per provider in PRICE_DIR, and compares a fresh list
with the kept one to see which prices changed since last time.

persona_llm.py reads the kept prices to work out what each turn cost.

Prices are in dollars per token, as the providers give them: $0.99 per
million tokens is 0.00000099. A list is only saved after a successful
fetch, so a provider that is down never wipes its kept prices.
"""

import json
from pathlib import Path

from persona_schemas import FREE_PROVIDERS, PRICE_DIR


# ─── Reading a Price List ─────────────────────────────────────────────────────

def read_price_list(listing: dict) -> dict:
    """
    The prices in a provider's answer, as {model: {"in": ..., "out": ...}}.
    Models without a price, and routers whose price varies (OpenRouter
    gives those as -1), are left out: their cost is unknown.
    """
    prices = {}

    for model in listing.get("data", []):
        pricing = model.get("pricing") or {}

        try:
            price_in  = float(pricing["prompt"])
            price_out = float(pricing["completion"])
        except (KeyError, TypeError, ValueError):
            continue

        if price_in < 0 or price_out < 0:
            continue

        prices[model["id"]] = {"in": price_in, "out": price_out}

    return prices


# ─── Load & Save ──────────────────────────────────────────────────────────────

def price_file(provider: str) -> Path:
    """The file holding one provider's kept prices."""
    return PRICE_DIR / (provider + ".json")


def load_prices(provider: str) -> dict | None:
    """The kept prices for this provider, or None if there aren't any yet."""
    path = price_file(provider)

    if not path.exists():
        return None

    return json.loads(path.read_text())


def save_prices(provider: str, prices: dict) -> None:
    """Keep this provider's prices, replacing the old ones."""
    PRICE_DIR.mkdir(parents=True, exist_ok=True)
    price_file(provider).write_text(json.dumps(prices, indent=2, sort_keys=True))


# ─── Comparing ────────────────────────────────────────────────────────────────

def changed_prices(kept: dict, current: dict) -> list[str]:
    """Models in both lists whose input or output price changed, sorted."""
    changed = []

    for model in current:
        if model in kept and kept[model] != current[model]:
            changed.append(model)

    return sorted(changed)


def per_million(price: float) -> str:
    """A per-token price as dollars per million tokens, e.g. "$0.99"."""
    return "$" + format(price * 1000000, ".2f")


def price_change_text(provider_name: str, model: str, old: dict, new: dict) -> str:
    """
    What System says about one price change, e.g. "Price change at
    Cerebras for qwen-3.8-27b: input $0.99 to $1.10 per million tokens."
    """
    parts = []

    if old["in"] != new["in"]:
        parts.append("input " + per_million(old["in"]) + " to " + per_million(new["in"]))

    if old["out"] != new["out"]:
        parts.append("output " + per_million(old["out"]) + " to " + per_million(new["out"]))

    return ("Price change at " + provider_name + " for " + model + ": "
            + ", ".join(parts) + " per million tokens.")


# ─── Cost of a Turn ───────────────────────────────────────────────────────────

def turn_cost(provider: str, model: str, tokens: dict) -> float | None:
    """
    What one turn cost in dollars, from its token totals (total_tokens() in
    persona_backstage.py) and the kept prices. None if the price isn't known.
    Reasoning tokens are already counted in tokens["out"].

    Only the model's own cost: a tool's charges (Perplexity research) are
    not included. Cached input is priced as ordinary input, so a provider
    that discounts it is slightly overestimated.
    """
    if provider in FREE_PROVIDERS:
        return 0.0

    prices = load_prices(provider)
    if prices is None or model not in prices:
        return None

    price = prices[model]
    return tokens["in"] * price["in"] + tokens["out"] * price["out"]


def cost_text(cost: float | None) -> str:
    """A turn's cost for showing, e.g. "$0.0014", or "cost unknown"."""
    if cost is None:
        return "cost unknown"

    return "$" + format(cost, ".4f")
