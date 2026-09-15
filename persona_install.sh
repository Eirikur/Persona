#!/bin/bash

# Persona installer -- one-time system-level setup that a plain `uv run`
# can't handle on its own (udev rules, group membership, etc). Safe to
# re-run: each step checks whether it's already done before changing
# anything.

# ─── ReSpeaker LED ring: USB access without sudo ─────────────────────────────

RESPEAKER_RULE_FILE="/etc/udev/rules.d/99-persona-respeaker.rules"
RESPEAKER_RULE_LINE='SUBSYSTEM=="usb", ATTR{idVendor}=="2886", ATTR{idProduct}=="001a", MODE="0660", GROUP="plugdev"'

if [ -f "$RESPEAKER_RULE_FILE" ] && grep -qF "$RESPEAKER_RULE_LINE" "$RESPEAKER_RULE_FILE"; then
    echo "ReSpeaker udev rule already installed."
else
    echo "Installing ReSpeaker udev rule (needs sudo)..."
    echo "$RESPEAKER_RULE_LINE" | sudo tee "$RESPEAKER_RULE_FILE" > /dev/null
    sudo udevadm control --reload-rules
    sudo udevadm trigger
    echo "Installed. Unplug and replug the ReSpeaker for the new permissions to take effect."
fi

if ! groups "$USER" | grep -qw plugdev; then
    echo "Warning: $USER is not in the 'plugdev' group -- the udev rule above won't grant access."
    echo "Run: sudo usermod -aG plugdev $USER   (then log out and back in)"
fi

echo "Done."
