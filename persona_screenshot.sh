#!/bin/bash

# Screenshots the Persona Chat UI without touching the live window or the hub.
#
# Launches a throwaway headless Chromium against the same URL and window
# size as persona_ui_launcher.sh, using its own --user-data-dir so it can
# never collide with the live window's browser profile.
#
# The page's unload handler POSTs /shutdown so that closing the real chat
# window takes down the hub -- and headless Chromium fires that same
# handler when it exits after grabbing the screenshot. The no_shutdown=1
# query flag (see persona_chat.html) tells the page to skip that beacon.
#
# Usage: ./persona_screenshot.sh [output.png]

OUT="${1:-/tmp/persona_screenshot.png}"
PROFILE_DIR=$(mktemp -d /tmp/persona-screenshot-profile.XXXXXX)

# Same page and dimensions as the real launcher, so sizing checks are apples-to-apples.
chromium --headless=new --disable-gpu --hide-scrollbars --no-sandbox \
    --screenshot="$OUT" \
    --window-size=1200,2100 \
    --user-data-dir="$PROFILE_DIR" \
    "http://localhost:8400/ui/persona_chat.html?no_shutdown=1"

rm -rf "$PROFILE_DIR"

echo "Saved: $OUT"
