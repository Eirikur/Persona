"""Persona Tool Log — a permanent record of every tool call.

Each row is one tool call: when, which persona, the question it was
answering, the arguments it sent the tool, what the tool returned (the text
the persona read, and the full structure if the tool has one), and the reply
the persona gave in the chat afterwards.

Written by persona_llm.py once a reply is finished, since only then is the
reply known. Kept in an SQLite file, which any SQLite tool can open
(the sqlite3 command is in the Ubuntu package of the same name):

    sqlite3 ~/.local/share/persona/tool_log.db
    sqlite> SELECT time, tool, arguments FROM tool_calls ORDER BY id DESC LIMIT 10;

The same file has a second table, turns: one row of numbers per reply
(tokens, rounds, cost). Tokens and dollars per day, for example:

    sqlite> SELECT substr(time, 1, 10) AS day, SUM(tokens_in), SUM(tokens_out), SUM(cost)
       ...> FROM turns GROUP BY day;
"""

import sqlite3
import time
from pathlib import Path


# ─── Configuration ────────────────────────────────────────────────────────────

LOG_DIR  = Path.home() / ".local" / "share" / "persona"
LOG_FILE = LOG_DIR / "tool_log.db"

CREATE_TABLE = """
    CREATE TABLE IF NOT EXISTS tool_calls (
        id        INTEGER PRIMARY KEY,
        time      TEXT,   -- local time, "2026-10-15 13:27:09"
        persona   TEXT,
        question  TEXT,   -- the input the persona was answering
        tool      TEXT,
        arguments TEXT,   -- JSON text, exactly as the model sent it
        result    TEXT,   -- what the persona read
        data      TEXT,   -- the tool's full structure as JSON text, or ""
        reply     TEXT    -- what the persona then said in the chat
    )
"""

# One row per reply from a real model: the numbers only, kept forever for
# daily and monthly totals. The full text of recent turns is in the
# Backstage window (persona_backstage.py), in the hub's memory.
CREATE_TURNS_TABLE = """
    CREATE TABLE IF NOT EXISTS turns (
        id               INTEGER PRIMARY KEY,
        time             TEXT,      -- local time, "2026-11-10 13:27:09"
        persona          TEXT,
        provider         TEXT,
        model            TEXT,
        rounds           INTEGER,   -- answers from the model; more than 1 means tools were used
        tool_calls       INTEGER,
        tokens_in        INTEGER,   -- added up over all rounds
        tokens_cached    INTEGER,   -- part of tokens_in the provider had cached
        tokens_out       INTEGER,
        tokens_reasoning INTEGER,   -- part of tokens_out spent thinking
        cost             REAL       -- dollars; NULL when the price isn't known
    )
"""


# ─── Writing ──────────────────────────────────────────────────────────────────

def save_calls(calls: list[dict], reply: str) -> None:
    """
    Add one row per tool call made for a single reply. Each call is a dict
    with persona, question, tool, arguments, result and data. A failure is
    printed, never raised: a lost log row must not lose the reply.
    """
    if not calls:
        return

    now = time.strftime("%Y-%m-%d %H:%M:%S")

    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(LOG_FILE)

        with connection:
            connection.execute(CREATE_TABLE)

            for call in calls:
                connection.execute(
                    "INSERT INTO tool_calls (time, persona, question, tool, arguments, result, data, reply)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (now, call["persona"], call["question"], call["tool"],
                     call["arguments"], call["result"], call["data"], reply),
                )

        connection.close()

    except sqlite3.Error as err:
        print(f"tool log: could not save {len(calls)} call(s): {err}")


def save_turn(persona: str, provider: str, model: str, tokens: dict, tool_calls: int, cost: float | None) -> None:
    """
    Add one row to the turns table. tokens is total_tokens() from
    persona_backstage.py; cost is turn_cost() from persona_prices.py, None
    (stored as NULL) when the price isn't known. A failure is printed,
    never raised, as in save_calls().
    """
    now = time.strftime("%Y-%m-%d %H:%M:%S")

    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(LOG_FILE)

        with connection:
            connection.execute(CREATE_TURNS_TABLE)

            connection.execute(
                "INSERT INTO turns (time, persona, provider, model, rounds, tool_calls,"
                " tokens_in, tokens_cached, tokens_out, tokens_reasoning, cost)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (now, persona, provider, model, tokens["rounds"], tool_calls,
                 tokens["in"], tokens["cached"], tokens["out"], tokens["reasoning"], cost),
            )

        connection.close()

    except sqlite3.Error as err:
        print(f"tool log: could not save the turn: {err}")
