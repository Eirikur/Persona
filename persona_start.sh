#!/bin/bash

SESSION="persona"
DIR="$(cd "$(dirname "$0")" && pwd)"

NO_VOICE=0
NO_ATTACH=0
for arg in "$@"; do
    case "$arg" in
        --no-voice)  NO_VOICE=1 ;;
        --no-attach) NO_ATTACH=1 ;;
    esac
done

# Kill any existing session
tmux kill-session -t "$SESSION" 2>/dev/null

# Kill anything still holding the ports
for port in 8400 8401 8402 8403; do
    fuser -k ${port}/tcp 2>/dev/null
done

sleep 1

wait_and_speak() {
    local port=$1
    local message=$2
    until curl -sf "http://127.0.0.1:$port/openapi.json" >/dev/null 2>&1; do
        sleep 0.5
    done
    curl -sf -X POST "http://127.0.0.1:8402/speak" \
        -H "Content-Type: application/json" \
        -d "{\"text\": \"$message\"}" >/dev/null
}

if [ "$NO_VOICE" -eq 0 ]; then
    # Speech output first — slowest (Chatterbox GPU), and needed for announcements
    tmux new-session -d -s "$SESSION" -n speech-out -c "$DIR"
    tmux send-keys -t "$SESSION:speech-out" './persona_speech_output.py' Enter

    # LLM
    tmux new-window -t "$SESSION" -n llm -c "$DIR"
else
    tmux new-session -d -s "$SESSION" -n llm -c "$DIR"
fi

# LLM
tmux send-keys -t "$SESSION:llm" './persona_llm.py' Enter

# Hub
tmux new-window -t "$SESSION" -n hub -c "$DIR"
tmux send-keys -t "$SESSION:hub" './persona_hub.py' Enter

if [ "$NO_VOICE" -eq 0 ]; then
    # Speech input (loads Whisper)
    tmux new-window -t "$SESSION" -n speech-in -c "$DIR"
    tmux send-keys -t "$SESSION:speech-in" './persona_speech_input.py' Enter

    # Announce each service as it comes up, in sequence
    # Note: no announcement for speech-in (8403) — Whisper would transcribe it
fi

# Open chat window once the hub is up
(
    until curl -sf "http://127.0.0.1:8400/openapi.json" >/dev/null 2>&1; do
        sleep 0.5
    done
    timeout 2 xdotool search --name "Sal" windowclose 2>/dev/null || true
    pkill -TERM -f "persona_chat" 2>/dev/null
    sleep 0.5
    pkill -KILL -f "persona_chat" 2>/dev/null
    sleep 0.3
    chromium --app="http://localhost:8400/ui/persona_chat.html?v=$(date +%s)" --no-restore-last-session --window-size=1200,2000 &
) &

# Land on the hub window
tmux select-window -t "$SESSION:hub"

if [ "$NO_ATTACH" -eq 0 ]; then
    tmux attach -t "$SESSION"
fi
