#!/bin/bash

# Usage: ./persona_start.sh [--no-voice] [--setup NAME]
#
# --setup NAME starts Persona from a saved setup (made by saying
# "system persist as NAME"). The current state.json is kept first as
# state-before-setup.json, so nothing is lost.

DIR="$(cd "$(dirname "$0")" && pwd)"
CONFIG_DIR="$HOME/.config/persona"

NO_VOICE=0
SETUP=""
while [ $# -gt 0 ]; do
    case "$1" in
        --no-voice)  NO_VOICE=1 ;;
        --setup)
            SETUP="$2"
            if [ -z "$SETUP" ]; then
                echo "--setup needs a name."
                exit 1
            fi
            shift
            ;;
    esac
    shift
done

# Check the setup exists before stopping anything
if [ -n "$SETUP" ] && [ ! -f "$CONFIG_DIR/setups/$SETUP.json" ]; then
    echo "No setup named '$SETUP'. Saved setups:"
    ls "$CONFIG_DIR/setups" 2>/dev/null | sed 's/\.json$//' | sed 's/^/  /'
    exit 1
fi

# Ensure systemd knows about the units
systemctl --user daemon-reload

# Kill anything still holding the ports to ensure a clean start
for port in 8400 8401 8402 8403; do
    fuser -k ${port}/tcp 2>/dev/null
done

sleep 1

# Put the chosen setup in place now that the hub is stopped
if [ -n "$SETUP" ]; then
    cp "$CONFIG_DIR/state.json" "$CONFIG_DIR/state-before-setup.json" 2>/dev/null
    cp "$CONFIG_DIR/setups/$SETUP.json" "$CONFIG_DIR/state.json"
    echo "Starting from setup: $SETUP"
fi

# Start Core Services
systemctl --user restart persona-llm.service
systemctl --user restart persona-hub.service

if [ "$NO_VOICE" -eq 0 ]; then
    systemctl --user restart persona-speech-out.service
    systemctl --user restart persona-speech-in.service
    systemctl --user restart persona-led-ring.service
else
    systemctl --user stop persona-speech-out.service
    systemctl --user stop persona-speech-in.service
    systemctl --user stop persona-led-ring.service
fi

# Open chat window via systemd
systemctl --user restart persona-ui.service

echo "Persona services started via systemd."
echo "Logs are available in $DIR/logs/"
echo "Use 'systemctl --user status persona-*' to check health."
