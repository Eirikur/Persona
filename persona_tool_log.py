"""Persona Tool Log — a permanent record of every tool call.

Each row is one tool call: when, which persona, the question it was
answering, the arguments it sent the tool, what the tool returned (the text
the persona read, and the full structure if the tool has one), and the reply
the persona gave in the chat afterwards.

Written by persona_llm.py once a reply is finished, since only then is the
reply known. Kept in an SQLite file, which any SQLite tool can open:

    sqlite3 ~/.local/share/persona/tool_log.db
    sqlite> SELECT time, tool, arguments FROM tool_calls ORDER BY id DESC LIMIT 10;
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
