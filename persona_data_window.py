"""Persona Data Window — what the personas' tools returned.

Every tool call a persona makes (news_read, web_search, ...) is reported to
the hub by persona_llm.py: who asked, what they were answering, the exact
arguments the model sent, and the exact result it got back. This file keeps
the most recent of those in memory, so the data window can show them even
if it was opened after the fact. The list is lost when the hub restarts.

The hub only sends a short notice over its event stream; the data window
fetches the full records from the hub over HTTP. Tool results can be long
(a fetched page), and every page listening to the stream would otherwise
receive them.
"""

import subprocess
import threading
import time
from pathlib import Path


# ─── Configuration ────────────────────────────────────────────────────────────

RECORDS_KEPT = 50   # oldest tool results are forgotten beyond this many

DATA_WINDOW_TITLE = "Persona Data"   # must match <title> in persona_data.html
DATA_WINDOW_WIDTH = 1000
DATA_WINDOW_URL   = "http://localhost:8400/ui/persona_data.html"

# Same browser profile as the chat window (see persona_ui_launcher.sh), so the
# data window opens inside the chat window's Chromium.
BROWSER_PROFILE = str(Path.home() / ".config" / "persona" / "chromium")


# ─── Stored Tool Results ──────────────────────────────────────────────────────

records      = []   # oldest first; each one a dict, see add_record()
records_lock = threading.Lock()
next_id      = 1


def add_record(persona: str, question: str, tool: str, arguments: str, result: str, data: str) -> dict:
    """Keep one tool result, give it an id and a time, and return it."""
    global next_id

    with records_lock:
        record = {
            "id":        next_id,
            "time":      time.strftime("%H:%M:%S"),
            "persona":   persona,
            "question":  question,
            "tool":      tool,
            "arguments": arguments,
            "result":    result,
            "data":      data,
        }
        next_id += 1

        records.append(record)
        if len(records) > RECORDS_KEPT:
            records.pop(0)

    return record


def recent_records() -> list[dict]:
    """Every kept tool result, newest first."""
    with records_lock:
        return list(reversed(records))


def find_record(record_id: int) -> dict | None:
    """The kept tool result with this id, or None if it was never kept or has been forgotten."""
    with records_lock:
        for record in records:
            if record["id"] == record_id:
                return record

    return None


def notice_text(record: dict) -> str:
    """The one-line summary sent over the event stream (and shown in Trace)."""
    size = len(record["result"])
    return record["tool"] + " for " + record["persona"] + ": " + str(size) + " characters"


# ─── Opening the Window ───────────────────────────────────────────────────────

def window_ids(title: str) -> list[str]:
    """X11 ids of the windows with exactly this title; empty if none, or if xdotool fails."""
    title_pattern = "^" + title + "$"

    try:
        output = subprocess.check_output(
            ["xdotool", "search", "--name", title_pattern],
            stderr=subprocess.DEVNULL, timeout=2,
        ).decode()
    except (FileNotFoundError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return []

    return output.split()


def window_geometry(window_id: str) -> dict:
    """A window's X, Y, WIDTH and HEIGHT, as whole numbers, from xdotool."""
    output = subprocess.check_output(
        ["xdotool", "getwindowgeometry", "--shell", window_id],
        stderr=subprocess.DEVNULL, timeout=2,
    ).decode()

    geometry = {}
    for line in output.split():
        name, value = line.split("=")
        geometry[name] = int(value)

    return geometry


def screen_width() -> int:
    """Width of the whole X11 screen in pixels."""
    output = subprocess.check_output(["xdotool", "getdisplaygeometry"], timeout=2).decode()
    return int(output.split()[0])


def place_beside_chat(window_id: str, chat_title: str) -> None:
    """
    Move the data window next to the chat window, the same height: on its
    right if there is room, otherwise on its left. A one-time placement;
    the owner can move either window afterwards.
    """
    chat_ids = window_ids(chat_title)
    if not chat_ids:
        return

    chat = window_geometry(chat_ids[0])

    x = chat["X"] + chat["WIDTH"]
    if x + DATA_WINDOW_WIDTH > screen_width():
        x = max(0, chat["X"] - DATA_WINDOW_WIDTH)

    subprocess.run(["xdotool", "windowsize", window_id, str(DATA_WINDOW_WIDTH), str(chat["HEIGHT"])], timeout=2)
    subprocess.run(["xdotool", "windowmove", window_id, str(x), str(chat["Y"])], timeout=2)

    # The window manager moves a window by its outer frame, but xdotool
    # reports where the inside landed, so the first move is off by the
    # frame's size. Measure that and move again to line up with the chat.
    landed = window_geometry(window_id)
    x_off  = landed["X"] - x
    y_off  = landed["Y"] - chat["Y"]

    if x_off or y_off:
        subprocess.run(["xdotool", "windowmove", window_id, str(x - x_off), str(chat["Y"] - y_off)], timeout=2)


def open_window(chat_title: str) -> None:
    """
    Start a new data window and place it beside the chat window.

    Started through systemd-run so the browser is not a child of the hub:
    restarting the hub would otherwise close the window, or leave a browser
    owning the chat window's profile. Waits up to five seconds for the
    window to appear before placing it.
    """
    subprocess.run([
        "systemd-run", "--user", "--collect", "--quiet",
        "chromium",
        "--app=" + DATA_WINDOW_URL,
        "--user-data-dir=" + BROWSER_PROFILE,
        "--window-size=" + str(DATA_WINDOW_WIDTH) + ",1200",
    ], timeout=10)

    for _ in range(50):
        ids = window_ids(DATA_WINDOW_TITLE)
        if ids:
            place_beside_chat(ids[0], chat_title)
            return
        time.sleep(0.1)

    print("data window: did not appear within 5 s, not placed")


def show_window(chat_title: str) -> None:
    """Bring the data window to the front, opening it first if it isn't open."""
    try:
        if window_ids(DATA_WINDOW_TITLE):
            subprocess.Popen(["wmctrl", "-R", DATA_WINDOW_TITLE])
        else:
            open_window(chat_title)
    except Exception as err:
        print(f"data window: could not show it: {err}")
