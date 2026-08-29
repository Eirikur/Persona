#!/bin/bash

DIR="$(cd "$(dirname "$0")" && pwd)"

NO_VOICE=0
for arg in "$@"; do
    case "$arg" in
        --no-voice)  NO_VOICE=1 ;;
    esac
done

# Ensure systemd knows about the units
systemctl --user daemon-reload

# Kill anything still holding the ports to ensure a clean start
for port in 8400 8401 8402 8403; do
    fuser -k ${port}/tcp 2>/dev/null
done

sleep 1

# Start Core Services
systemctl --user restart persona-llm.service
systemctl --user restart persona-hub.service

if [ "$NO_VOICE" -eq 0 ]; then
    systemctl --user restart persona-speech-out.service
    systemctl --user restart persona-speech-in.service
else
    systemctl --user stop persona-speech-out.service
    systemctl --user stop persona-speech-in.service
fi

# Open chat window via systemd
systemctl --user restart persona-ui.service

echo "Persona services started via systemd."
echo "Logs are available in $DIR/logs/"
echo "Use 'systemctl --user status persona-*' to check health."
