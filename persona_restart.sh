#!/bin/bash

DIR="$(cd "$(dirname "$0")" && pwd)"

# Announce before the session dies
curl -sf -X POST "http://127.0.0.1:8402/speak" \
    -H "Content-Type: application/json" \
    -d '{"text": "Restarting."}' >/dev/null 2>&1

sleep 1.5

# setsid detaches from the current process group so this survives tmux kill-session
setsid "$DIR/persona_start.sh" --no-attach &
