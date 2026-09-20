"""Persona Scripts — run a named script and stream its output.

The chat UI asks the hub to run a script by name; the hub answers with the
script's output as it appears. Only scripts listed in SCRIPTS can be run, so
the UI can never ask for an arbitrary command.

A script can have the persona speak a result by printing a line that starts
with "SAY: ". The text after it is spoken once the script has finished, never
while it runs, so speaking cannot disturb what the script is measuring.
"""

import os
import queue
import subprocess
import threading
from pathlib import Path


# ─── Configuration ────────────────────────────────────────────────────────────

REPO_DIR       = Path(__file__).parent
SCRIPT_TIMEOUT = 300   # seconds before a script that has not finished is killed
SAY_PREFIX     = "SAY: "

# Name -> command line, run from the repo directory.
SCRIPTS: dict[str, list[str]] = {
    "stt_check":      ["./persona_stt_check.py", "3"],
    "pipeline_check": ["./persona_pipeline_check.py"],
}


# ─── Runtime State ────────────────────────────────────────────────────────────

# Only one script at a time: two speech checks at once would slow each other
# down and spoil the timings.
running_lock = threading.Lock()


# ─── Running a Script ─────────────────────────────────────────────────────────

def run_and_collect(name: str, lines: queue.Queue, say) -> None:
    """
    Run the named script to the end, putting each line of its output on the
    queue, then one line giving its exit code. Then call say(text) for each
    SAY: line the script printed, and finally put None as the end marker, so
    the reader sees the whole run, spoken part included.
    Runs in its own thread and releases running_lock when everything is done,
    so a browser that goes away mid-run cannot leave the lock held.
    """
    proc   = None
    timer  = None
    to_say = []

    try:
        # Unbuffered, so lines arrive while the script runs, not all at the end.
        env = dict(os.environ, PYTHONUNBUFFERED="1")

        proc = subprocess.Popen(
            SCRIPTS[name],
            cwd=REPO_DIR,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )

        timer = threading.Timer(SCRIPT_TIMEOUT, proc.kill)
        timer.start()

        for line in proc.stdout:
            lines.put(line)

            if line.startswith(SAY_PREFIX):
                to_say.append(line[len(SAY_PREFIX):].strip())

        proc.wait()
        lines.put(f"[exit code {proc.returncode}]\n")

        for text in to_say:
            try:
                say(text)
            except Exception as e:
                lines.put(f"[could not speak: {e}]\n")

    except Exception as e:
        lines.put(f"[could not run {name}: {e}]\n")

    finally:
        if timer is not None:
            timer.cancel()

        if proc is not None and proc.poll() is None:
            proc.kill()
            proc.wait()

        running_lock.release()
        lines.put(None)


def script_output(name: str, say):
    """
    Start the named script and yield its output line by line as it is printed,
    ending with its exit code. say(text) is called to speak each SAY: line
    after the script finishes. Yields a single explanatory line instead if
    another script is already running. If the reader goes away, the script
    still runs to its end; it is never left holding the lock.
    """
    if not running_lock.acquire(blocking=False):
        yield "Another script is already running. Try again when it finishes.\n"
        return

    lines = queue.Queue()
    threading.Thread(target=run_and_collect, args=(name, lines, say), daemon=True).start()

    while True:
        line = lines.get()

        if line is None:
            return

        yield line
