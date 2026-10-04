"""Persona Log Tailer — follows the service logs for the Logs tab.

Reads logs/*.log without ever changing them (no truncating, no renaming,
no new files). At start it remembers the last few lines of each file; after
that it watches for new lines and hands each one to a callback.
"""


import re
import threading
import time
from collections import deque
from pathlib import Path

from persona_schemas import LOG_COLORS, LOG_NOISE_WORDS, LOG_SOURCES


# ─── Configuration ────────────────────────────────────────────────────────────

LOG_DIR           = Path(__file__).parent / "logs"
REPLAY_LINES      = 50           # lines remembered per file at start
TAIL_READ_BYTES   = 256 * 1024   # how far back from the end to look for them
POLL_SECONDS      = 0.5
RECENT_LIMIT      = 500          # lines kept for pages that connect later


# An access-log line such as:
#   INFO:     127.0.0.1:50166 - "POST /converse HTTP/1.1" 200 OK
access_line_pattern = r'^INFO:\s+\S+ - "(\w+) (\S+) HTTP/[0-9.]+" (\d+)'


# ─── Recent Lines ─────────────────────────────────────────────────────────────

# Newest last. Each entry is a dict: source, text, time ("" for lines that
# were already in the file when the hub started).
recent_lines = deque(maxlen=RECENT_LIMIT)


# ─── Reading ──────────────────────────────────────────────────────────────────

def is_noise(line: str) -> bool:
    """True if the line is routine chatter that should not be shown."""
    for word in LOG_NOISE_WORDS:
        if word in line:
            return True
    return False


def shorten(line: str) -> str:
    """Boil an access-log line down to "POST /converse 200"; other lines are unchanged."""
    match = re.match(access_line_pattern, line)
    if not match:
        return line

    method, path, status = match.groups()
    return method + " " + path + " " + status


def make_entry(source: str, line: str, when: str) -> dict:
    """Build the dict the page shows for one log line."""
    return {
        "source": source,
        "text":   shorten(line),
        "full":   line,
        "time":   when,
        "color":  LOG_COLORS.get(source, "#8FA0AE"),
    }


def read_last_lines(path: Path) -> list[str]:
    """Return the last few worth-showing lines of a file, reading only its end."""
    if not path.exists():
        return []

    with path.open("rb") as handle:
        handle.seek(0, 2)
        size = handle.tell()
        handle.seek(max(0, size - TAIL_READ_BYTES))
        chunk = handle.read()

    lines = chunk.decode("utf-8", errors="replace").splitlines()

    # The first line may have been cut in half by the seek.
    if size > TAIL_READ_BYTES:
        lines = lines[1:]

    shown = [line for line in lines if line.strip() and not is_noise(line)]
    return shown[-REPLAY_LINES:]


# ─── Following ────────────────────────────────────────────────────────────────

def follow_file(source: str, path: Path, on_line) -> None:
    """Watch one file forever, calling on_line(entry) for each new line."""
    position = path.stat().st_size if path.exists() else 0
    partial  = b""

    while True:
        time.sleep(POLL_SECONDS)

        if not path.exists():
            position = 0
            partial  = b""
            continue

        size = path.stat().st_size

        # A smaller file means it was replaced or emptied: start over.
        if size < position:
            position = 0
            partial  = b""

        if size == position:
            continue

        with path.open("rb") as handle:
            handle.seek(position)
            data = handle.read()
            position = handle.tell()

        # Only complete lines are passed on; a half-written one waits.
        pieces  = (partial + data).split(b"\n")
        partial = pieces.pop()

        for piece in pieces:
            line = piece.decode("utf-8", errors="replace").rstrip("\r")
            if not line.strip() or is_noise(line):
                continue

            entry = make_entry(source, line, time.strftime("%H:%M:%S"))
            recent_lines.append(entry)
            on_line(entry)


def start_tailing(on_line) -> None:
    """Remember each file's last lines, then follow every log in its own thread."""
    for source, file_name in LOG_SOURCES.items():
        path = LOG_DIR / file_name

        for line in read_last_lines(path):
            recent_lines.append(make_entry(source, line, ""))

        thread = threading.Thread(
            target = follow_file,
            args   = (source, path, on_line),
            daemon = True,
        )
        thread.start()
