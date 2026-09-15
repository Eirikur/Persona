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

# ─── ReSpeaker LED ring: systemd unit ─────────────────────────────────────────

DIR="$(cd "$(dirname "$0")" && pwd)"
LED_RING_UNIT="$HOME/.config/systemd/user/persona-led-ring.service"
LED_RING_UNIT_WANT="persona-led-ring.service"

chmod +x "$DIR/persona_led_ring.py"

NEEDS_RELOAD=0

DESIRED_UNIT="[Unit]
Description=Persona LED Ring Service
After=persona-hub.service network.target
PartOf=persona.target

[Service]
SuccessExitStatus=143
ExecStart=$DIR/persona_led_ring.py
WorkingDirectory=$DIR
Restart=always
StandardOutput=append:$DIR/logs/led-ring.log
StandardError=append:$DIR/logs/led-ring.log

[Install]
WantedBy=default.target"

if [ "$(cat "$LED_RING_UNIT" 2>/dev/null)" = "$DESIRED_UNIT" ]; then
    echo "LED ring systemd unit already installed."
else
    echo "Installing LED ring systemd unit..."
    mkdir -p "$(dirname "$LED_RING_UNIT")"
    echo "$DESIRED_UNIT" > "$LED_RING_UNIT"
    NEEDS_RELOAD=1
fi

PERSONA_TARGET="$HOME/.config/systemd/user/persona.target"
if [ -f "$PERSONA_TARGET" ] && ! grep -q "$LED_RING_UNIT_WANT" "$PERSONA_TARGET"; then
    echo "Adding LED ring to persona.target..."
    sed -i "s/^Wants=.*/& $LED_RING_UNIT_WANT/" "$PERSONA_TARGET"
    NEEDS_RELOAD=1
fi

if [ "$NEEDS_RELOAD" -eq 1 ]; then
    systemctl --user daemon-reload
fi

echo "Done."
