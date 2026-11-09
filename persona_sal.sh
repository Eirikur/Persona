#!/bin/bash

# Usage: ./persona_sal.sh            start Persona with only Sal, open mode, quiet mic
#        ./persona_sal.sh --restore  put the mic back to its level before Sal mode
#
# Sal mode: Sal is the only persona in the room, and she answers without
# hearing her name (open mode). The mic is turned down so only a raised
# voice reaches her, not room noise.
#
# The mic level is system-wide: Typist and everything else hear the quieter
# mic too, until --restore is run.

DIR="$(cd "$(dirname "$0")" && pwd)"
HUB="http://localhost:8400"

# Mic input level for Sal mode. Found by hand on 2026-11-09 with the
# POROSVOC mic: 40% ignores most room noise but still hears a raised voice.
# Heater noise still gets through sometimes.
SAL_MIC_LEVEL="40%"

# The mic level before Sal mode, kept here so --restore can put it back.
SAVED_LEVEL_FILE="$HOME/.config/persona/mic-level-before-sal"


# ─── Restore ──────────────────────────────────────────────────────────────────

if [ "$1" = "--restore" ]; then
    if [ ! -f "$SAVED_LEVEL_FILE" ]; then
        echo "No saved mic level. Setting the mic to 100%."
        pactl set-source-volume @DEFAULT_SOURCE@ 100%
        exit 0
    fi

    old_level="$(cat "$SAVED_LEVEL_FILE")"
    pactl set-source-volume @DEFAULT_SOURCE@ "$old_level"
    rm "$SAVED_LEVEL_FILE"
    echo "Mic back to $old_level."
    exit 0
fi


# ─── Quiet Mic ────────────────────────────────────────────────────────────────

# Save the current level only once, so starting Sal mode twice does not
# save 40% as the level to go back to.
if [ ! -f "$SAVED_LEVEL_FILE" ]; then
    current_level="$(pactl get-source-volume @DEFAULT_SOURCE@ | grep -o '[0-9]*%' | head -1)"
    echo "$current_level" > "$SAVED_LEVEL_FILE"
fi

pactl set-source-volume @DEFAULT_SOURCE@ "$SAL_MIC_LEVEL"
echo "Mic set to $SAL_MIC_LEVEL (was $(cat "$SAVED_LEVEL_FILE"))."


# ─── Start Persona ────────────────────────────────────────────────────────────

"$DIR/persona_start.sh"


# ─── Wait for the Hub ─────────────────────────────────────────────────────────

# systemd returns before the hub is listening, so ask until it answers.
echo -n "Waiting for the hub"
for attempt in $(seq 1 30); do
    if curl -sf "$HUB/state" > /dev/null; then
        break
    fi
    echo -n "."
    sleep 1
done
echo

if ! curl -sf "$HUB/state" > /dev/null; then
    echo "The hub did not answer after 30 seconds. Sal mode not set."
    echo "Check: systemctl --user status persona-hub"
    exit 1
fi


# ─── Sal Only, Open Mode ──────────────────────────────────────────────────────

# Sal's persona is named "default" inside Persona.
curl -sf -X POST "$HUB/persona/default/load" > /dev/null

# Everyone else in the room leaves.
others="$(curl -sf "$HUB/state" | python3 -c '
import json, sys
loaded = json.load(sys.stdin)["loaded_personas"]
for name in loaded:
    if name != "default":
        print(name)
')"

for name in $others; do
    curl -sf -X POST "$HUB/persona/$name/unload" > /dev/null
    echo "$name left the room."
done

curl -sf -X POST "$HUB/mode/open" > /dev/null

echo "Sal mode is on: Sal only, open mode, mic at $SAL_MIC_LEVEL."
echo "Say \"be quiet\" to go back to named mode."
echo "Run ./persona_sal.sh --restore to put the mic back."
