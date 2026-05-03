#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11,<3.14"
# dependencies = [
#     "torch",
#     "torchaudio",
#     "soundfile",
#     "huggingface_hub",
# ]
# ///
#
# Create a Kokoro voice .pt from a WAV file using the StyleTTS2 style encoder.
# The checkpoint is downloaded automatically from HuggingFace on first run (~774 MB).
#
# Usage:
#   ./make_voice.py input.wav output_name
#   ./make_voice.py bird-dream.wav bird_dream   → saves bird_dream.pt
#
# Compatibility note: Kokoro was derived from StyleTTS2. The LibriTTS checkpoint
# style encoder should produce compatible embeddings, but results may vary —
# experiment with different reference clips if the voice sounds off.

import math
import sys
import torch
import torch.nn as nn
import torch.nn.functional as F
from torch.nn.utils import spectral_norm
import soundfile as sf
import torchaudio
from huggingface_hub import hf_hub_download

# ── StyleEncoder (inlined from yl4579/StyleTTS2/models.py) ───────────────────

class DownSample(nn.Module):
    def __init__(self, layer_type):
        super().__init__()
        self.layer_type = layer_type

    def forward(self, x):
        if self.layer_type == 'none':
            return x
        elif self.layer_type == 'timepreserve':
            return F.avg_pool2d(x, (2, 1))
        elif self.layer_type == 'half':
            if x.shape[-1] % 2 != 0:
                x = torch.cat([x, x[..., -1].unsqueeze(-1)], dim=-1)
            return F.avg_pool2d(x, 2)
        raise RuntimeError(f'Unknown downsample type: {self.layer_type}')


class LearnedDownSample(nn.Module):
    def __init__(self, layer_type, dim_in):
        super().__init__()
        self.layer_type = layer_type
        if layer_type == 'none':
            self.conv = nn.Identity()
        elif layer_type == 'timepreserve':
            self.conv = spectral_norm(nn.Conv2d(
                dim_in, dim_in, kernel_size=(3, 1), stride=(2, 1),
                groups=dim_in, padding=(1, 0)))
        elif layer_type == 'half':
            self.conv = spectral_norm(nn.Conv2d(
                dim_in, dim_in, kernel_size=(3, 3), stride=(2, 2),
                groups=dim_in, padding=1))
        else:
            raise RuntimeError(f'Unknown downsample type: {layer_type}')

    def forward(self, x):
        return self.conv(x)


class ResBlk(nn.Module):
    def __init__(self, dim_in, dim_out, actv=nn.LeakyReLU(0.2),
                 normalize=False, downsample='none'):
        super().__init__()
        self.actv = actv
        self.normalize = normalize
        self.downsample = DownSample(downsample)
        self.downsample_res = LearnedDownSample(downsample, dim_in)
        self.learned_sc = dim_in != dim_out
        self.conv1 = spectral_norm(nn.Conv2d(dim_in, dim_in, 3, 1, 1))
        self.conv2 = spectral_norm(nn.Conv2d(dim_in, dim_out, 3, 1, 1))
        if normalize:
            self.norm1 = nn.InstanceNorm2d(dim_in, affine=True)
            self.norm2 = nn.InstanceNorm2d(dim_in, affine=True)
        if self.learned_sc:
            self.conv1x1 = spectral_norm(nn.Conv2d(dim_in, dim_out, 1, 1, 0, bias=False))

    def _shortcut(self, x):
        if self.learned_sc:
            x = self.conv1x1(x)
        return self.downsample(x)

    def _residual(self, x):
        if self.normalize:
            x = self.norm1(x)
        x = self.actv(x)
        x = self.conv1(x)
        x = self.downsample_res(x)
        if self.normalize:
            x = self.norm2(x)
        x = self.actv(x)
        x = self.conv2(x)
        return x

    def forward(self, x):
        return (self._shortcut(x) + self._residual(x)) / math.sqrt(2)


class StyleEncoder(nn.Module):
    def __init__(self, dim_in=64, style_dim=128, max_conv_dim=512):
        super().__init__()
        blocks = [spectral_norm(nn.Conv2d(1, dim_in, 3, 1, 1))]
        for _ in range(4):
            dim_out = min(dim_in * 2, max_conv_dim)
            blocks.append(ResBlk(dim_in, dim_out, downsample='half'))
            dim_in = dim_out
        blocks += [
            nn.LeakyReLU(0.2),
            spectral_norm(nn.Conv2d(dim_out, dim_out, 5, 1, 0)),
            nn.AdaptiveAvgPool2d(1),
            nn.LeakyReLU(0.2),
        ]
        self.shared = nn.Sequential(*blocks)
        self.unshared = nn.Linear(dim_out, style_dim)

    def forward(self, x):
        h = self.shared(x).view(x.size(0), -1)
        return self.unshared(h)


# ── Audio preprocessing ───────────────────────────────────────────────────────

to_mel = torchaudio.transforms.MelSpectrogram(
    sample_rate=24000, n_mels=80, n_fft=2048,
    win_length=1200, hop_length=300)
MEL_MEAN, MEL_STD = -4, 4


def preprocess(wav: torch.Tensor) -> torch.Tensor:
    """wav: 1D float32 tensor at 24kHz → [1, 80, T] normalized mel"""
    mel = to_mel(wav.unsqueeze(0))
    return (torch.log(1e-5 + mel) - MEL_MEAN) / MEL_STD


def load_audio(path: str) -> torch.Tensor:
    """Load, convert to mono, resample to 24kHz, trim silence."""
    data, sr = sf.read(path, dtype='float32')
    wav = torch.from_numpy(data)
    if wav.ndim == 2:
        wav = wav.mean(1)   # stereo → mono
    if sr != 24000:
        print(f"  Resampling from {sr} Hz to 24000 Hz")
        wav = torchaudio.functional.resample(wav, sr, 24000)
    # Trim leading/trailing silence
    threshold = 0.03
    mask = wav.abs() > threshold
    if mask.any():
        first = mask.nonzero(as_tuple=False)[0].item()
        last  = mask.nonzero(as_tuple=False)[-1].item()
        wav = wav[first:last + 1]
    duration = len(wav) / 24000
    print(f"  Audio: {duration:.2f}s after trimming")
    return wav


# ── Checkpoint loading ────────────────────────────────────────────────────────

REPO_ID   = 'yl4579/StyleTTS2-LibriTTS'
CKPT_FILE = 'Models/LibriTTS/epochs_2nd_00020.pth'
PACK_SIZE = 510   # max phoneme sequence length in Kokoro
DEVICE    = 'cuda' if torch.cuda.is_available() else 'cpu'


def strip_module_prefix(state_dict: dict) -> dict:
    """Remove 'module.' prefix added by DataParallel."""
    return {(k[7:] if k.startswith('module.') else k): v
            for k, v in state_dict.items()}


def load_encoders():
    print(f"Fetching checkpoint from HuggingFace ({REPO_ID}) ...")
    ckpt_path = hf_hub_download(repo_id=REPO_ID, filename=CKPT_FILE)
    print("Loading ...")
    ckpt = torch.load(ckpt_path, map_location='cpu', weights_only=False)

    net = ckpt.get('net', ckpt)   # handle flat or nested checkpoints

    def build_encoder(key):
        enc = StyleEncoder().to(DEVICE).eval()
        sd = strip_module_prefix(net[key])
        enc.load_state_dict(sd)
        return enc

    style_enc = build_encoder('style_encoder')
    pred_enc  = build_encoder('predictor_encoder')
    print(f"Encoders loaded (device={DEVICE})")
    return style_enc, pred_enc


# ── Voice pack creation ───────────────────────────────────────────────────────

def wav_to_pack(wav_path: str, style_enc: nn.Module, pred_enc: nn.Module) -> torch.Tensor:
    print(f"Loading {wav_path} ...")
    wav = load_audio(wav_path).to(DEVICE)
    mel = preprocess(wav).to(DEVICE)   # [1, 80, T]
    mel4d = mel.unsqueeze(1)           # [1, 1, 80, T]

    with torch.no_grad():
        ref_s = style_enc(mel4d)       # [1, 128]
        ref_p = pred_enc(mel4d)        # [1, 128]

    style_vec = torch.cat([ref_s, ref_p], dim=1).cpu().float()   # [1, 256]
    # pack[i] must return a 2D [1, 256] tensor (Kokoro does ref_s[:, 128:])
    pack = style_vec.unsqueeze(0).expand(PACK_SIZE, 1, 256).clone()  # [510, 1, 256]
    return pack


def main():
    if len(sys.argv) < 3:
        print("Usage: make_voice.py input.wav output_name")
        print("  Saves output_name.pt in the current directory.")
        print("  Use the .pt path as the voice= argument in speak_kokoro.py.")
        sys.exit(1)

    wav_path    = sys.argv[1]
    output_name = sys.argv[2]
    out_path    = f"{output_name}.pt"

    style_enc, pred_enc = load_encoders()
    pack = wav_to_pack(wav_path, style_enc, pred_enc)
    torch.save(pack, out_path)
    print(f"\nSaved: {out_path}  shape={list(pack.shape)}")
    print(f"Test: ./speak_kokoro.py bird-dream.wav some_text.txt")
    print(f"      (edit VOICE in speak_kokoro.py or pass voice='{out_path}')")


if __name__ == '__main__':
    main()
