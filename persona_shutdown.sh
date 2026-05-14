#!/bin/bash

SESSION="persona"

# Announce before killing speech output
curl -sf -X POST "http://127.0.0.1:8402/speak" \
    -H "Content-Type: application/json" \
    -d '{"text": "Shutting down."}' >/dev/null 2>&1

sleep 1.5

tmux kill-session -t "$SESSION" 2>/dev/null

for port in 8400 8401 8402 8403; do
    fuser -k ${port}/tcp 2>/dev/null
done
