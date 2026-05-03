#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11,<3.14"
# dependencies = [
#     "kokoro",
#     "torch",
# ]
# ///
#
# Blend two or more Kokoro voices into a new voice .pt file.
#
# Usage:
#   ./blend_voice.py output_name voice1[:weight] voice2[:weight] ...
#
# Examples:
#   ./blend_voice.py my_voice af_heart af_bella          # equal blend
#   ./blend_voice.py my_voice af_heart:0.7 af_bella:0.3  # weighted blend
#   ./blend_voice.py my_voice af_heart:1 am_michael:1    # unnormalized (will normalize)
#
# The output file is saved as <output_name>.pt in the current directory.
# Use it in speak_kokoro.py by passing the full path as the voice argument.

import sys
import torch
from kokoro import KPipeline

REPO_ID = 'hexgrad/Kokoro-82M'

def parse_args(args):
    if len(args) < 3:
        print("Usage: blend_voice.py output_name voice1[:weight] voice2[:weight] ...")
        sys.exit(1)
    output_name = args[1]
    voices = []
    weights = []
    for token in args[2:]:
        if ':' in token:
            name, w = token.rsplit(':', 1)
            voices.append(name)
            weights.append(float(w))
        else:
            voices.append(token)
            weights.append(1.0)
    total = sum(weights)
    weights = [w / total for w in weights]
    return output_name, voices, weights

def main():
    output_name, voices, weights = parse_args(sys.argv)

    pipeline = KPipeline(lang_code='a', repo_id=REPO_ID)

    print(f"Loading and blending {len(voices)} voice(s):")
    packs = []
    for name, w in zip(voices, weights):
        print(f"  {name:20s}  weight={w:.3f}")
        pack = pipeline.load_single_voice(name)
        packs.append(pack)

    # Weighted sum — all packs must have same shape [N, 256]
    shapes = [p.shape for p in packs]
    if len(set(shapes)) > 1:
        # Trim to the smallest common N
        min_n = min(s[0] for s in shapes)
        print(f"Warning: voice shapes differ {shapes}, trimming to [{min_n}, 256]")
        packs = [p[:min_n] for p in packs]

    blended = sum(w * p for w, p in zip(weights, packs))
    blended = blended.to(torch.float32)

    out_path = f"{output_name}.pt"
    torch.save(blended, out_path)
    print(f"\nSaved: {out_path}  shape={list(blended.shape)}")
    print(f"Use in speak_kokoro.py: speak(text, voice='{out_path}')")

if __name__ == '__main__':
    main()
