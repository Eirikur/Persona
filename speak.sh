#!/bin/bash
/home/eh/Proj/Persona/speak.py 2>&1 "$@" | grep -v -e 'LoRACompatibleLinear' -e "Fetching 10" -e "PerthNet"
