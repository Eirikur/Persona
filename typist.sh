#!/bin/bash
HF_HUB_OFFLINE=1 /home/eh/Proj/Persona/typist.py --echo 2>&1 | grep -v -e Jack -e ALSA -e server -e NNPACK -e Downloading
