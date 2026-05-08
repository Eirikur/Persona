#!/bin/bash

SESSION="persona"
DIR="$(cd "$(dirname "$0")" && pwd)"

# Kill any existing session
tmux kill-session -t "$SESSION" 2>/dev/null

# Kill anything still holding the ports
for port in 8400 8401 8402 8403; do
    fuser -k ${port}/tcp 2>/dev/null
done

sleep 1

# Create session with first window for LLM
tmux new-session -d -s "$SESSION" -n llm -c "$DIR"
tmux send-keys -t "$SESSION:llm" './persona_llm.py' Enter

# Speech output (slow — loads Chatterbox)
tmux new-window -t "$SESSION" -n speech-out -c "$DIR"
tmux send-keys -t "$SESSION:speech-out" './persona_speech_output.py' Enter

# Hub
tmux new-window -t "$SESSION" -n hub -c "$DIR"
tmux send-keys -t "$SESSION:hub" './persona_hub.py' Enter

# Speech input (slow — loads Whisper)
tmux new-window -t "$SESSION" -n speech-in -c "$DIR"
tmux send-keys -t "$SESSION:speech-in" './persona_speech_input.py' Enter

# Land on the hub window
tmux select-window -t "$SESSION:hub"

tmux attach -t "$SESSION"
