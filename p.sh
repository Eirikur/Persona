#!/bin/bash



# LISTENING state. RED solid. It's a red-for-recording light.
sudo /home/eh/.local/bin/uv run xvf_host.py LED_EFFECT --values 3
sudo /home/eh/.local/bin/uv run xvf_host.py LED_COLOR --values 0x880000
sleep 2

# Transcribing state. Blue for ordinary computer activity.
sudo /home/eh/.local/bin/uv run xvf_host.py LED_EFFECT --values 3
sudo /home/eh/.local/bin/uv run xvf_host.py LED_COLOR --values 0x0000cd
sleep 2

# Inference state. White for "hottest" activity. White breathing.
sudo /home/eh/.local/bin/uv run xvf_host.py LED_SPEED --values  3
sudo /home/eh/.local/bin/uv run xvf_host.py LED_EFFECT --values 1
sudo /home/eh/.local/bin/uv run xvf_host.py LED_COLOR --values 0xffffff
sleep 2

# Speaking state. Green for "All done/ things are good."
sudo /home/eh/.local/bin/uv run xvf_host.py LED_EFFECT --values 3
sudo /home/eh/.local/bin/uv run xvf_host.py LED_COLOR --values 0x00aa00
sleep 2


# Restore DOA (angle of arrival) standard mode.
sudo /home/eh/.local/bin/uv run xvf_host.py LED_EFFECT --values 4


# ReSpeaker Mic LED Ring

# HEARING state is represented by DOA state of LED ring.

# LISTENIING state is represented by solid color 0x880000, pulsed by event that pulses the HEARING indicator on the UI.
# Red indicating recording, pulsed to so live activity.
# # TRANSCRIBING is represented by beathing blue 0x008800 speed 3
# # INFERENCE is represented by breathing white 0xffffff speed 3
# sudo /home/eh/.local/bin/uv run xvf_host.py LED_SPEED --values  3
# sudo /home/eh/.local/bin/uv run xvf_host.py LED_EFFECT --values 1
# sudo /home/eh/.local/bin/uv run xvf_host.py LED_COLOR --values 0xffffff
# sleep 2


