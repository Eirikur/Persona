#!/bin/bash

# Ensure DISPLAY is set
export DISPLAY=:0

# Wait for Hub to be ready
until curl -sf http://127.0.0.1:8400/openapi.json >/dev/null 2>&1; do
    sleep 0.5
done

# Cleanup existing windows/processes
timeout 2 xdotool search --name 'Sal' windowclose 2>/dev/null || true
pkill -TERM -f 'persona_chat' 2>/dev/null
sleep 0.5
pkill -KILL -f 'persona_chat' 2>/dev/null
sleep 0.3

# Launch Chromium
# We use exec so that chromium becomes PID 1 of the service
exec chromium --app="http://localhost:8400/ui/persona_chat.html?v=$(date +%s)" \
    --no-restore-last-session \
    --window-size=1200,2000
