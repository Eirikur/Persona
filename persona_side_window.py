"""Persona side windows — opening a window beside the chat window.

The data window and the Backstage window are both web pages from the hub,
shown in their own Chromium window next to the chat window. This file
opens one, places it, and brings it forward when asked again. Each caller
passes its window's title, address and width.

Placement uses xdotool and wmctrl, so it works on X11 only.
"""

import subprocess
import time
from pathlib import Path


# ─── Configuration ────────────────────────────────────────────────────────────

# Same browser profile as the chat window (see persona_ui_launcher.sh), so a
# side window opens inside the chat window's Chromium.
BROWSER_PROFILE = str(Path.home() / ".config" / "persona" / "chromium")


# ─── Finding and Measuring Windows ────────────────────────────────────────────

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


# ─── Opening and Placing ──────────────────────────────────────────────────────

def place_beside_chat(window_id: str, width: int, chat_title: str) -> None:
    """
    Move a side window next to the chat window, the same height: on its
    right if there is room, otherwise on its left. A one-time placement;
    the owner can move either window afterwards.
    """
    chat_ids = window_ids(chat_title)
    if not chat_ids:
        return

    chat = window_geometry(chat_ids[0])

    x = chat["X"] + chat["WIDTH"]
    if x + width > screen_width():
        x = max(0, chat["X"] - width)

    subprocess.run(["xdotool", "windowsize", window_id, str(width), str(chat["HEIGHT"])], timeout=2)
    subprocess.run(["xdotool", "windowmove", window_id, str(x), str(chat["Y"])], timeout=2)

    # The window manager moves a window by its outer frame, but xdotool
    # reports where the inside landed, so the first move is off by the
    # frame's size. Measure that and move again to line up with the chat.
    landed = window_geometry(window_id)
    x_off  = landed["X"] - x
    y_off  = landed["Y"] - chat["Y"]

    if x_off or y_off:
        subprocess.run(["xdotool", "windowmove", window_id, str(x - x_off), str(chat["Y"] - y_off)], timeout=2)


def open_window(title: str, url: str, width: int, chat_title: str) -> None:
    """
    Start a new side window and place it beside the chat window.

    Started through systemd-run so the browser is not a child of the hub:
    restarting the hub would otherwise close the window, or leave a browser
    owning the chat window's profile. Waits up to five seconds for the
    window to appear before placing it.
    """
    subprocess.run([
        "systemd-run", "--user", "--collect", "--quiet",
        "chromium",
        "--app=" + url,
        "--user-data-dir=" + BROWSER_PROFILE,
        "--window-size=" + str(width) + ",1200",
    ], timeout=10)

    for _ in range(50):
        ids = window_ids(title)
        if ids:
            place_beside_chat(ids[0], width, chat_title)
            return
        time.sleep(0.1)

    print(title + ": did not appear within 5 s, not placed")


def show_window(title: str, url: str, width: int, chat_title: str) -> None:
    """Bring a side window to the front, opening it first if it isn't open."""
    try:
        if window_ids(title):
            subprocess.Popen(["wmctrl", "-R", title])
        else:
            open_window(title, url, width, chat_title)
    except Exception as err:
        print(title + ": could not show it: " + str(err))
