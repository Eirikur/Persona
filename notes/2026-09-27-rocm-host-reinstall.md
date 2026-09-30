ROCm host stack was gone — full reinstall recipe
==================================================

2026-09-27. While chasing "speech recognition drags on long utterances"
(affects both Persona and Typist), went to Typist to benchmark ROCm vs CPU
for faster-whisper and found the entire ROCm host setup described in
`notes/2026-08-10-rocm-amd-port.md` **missing**: no `/opt/rocm-7.2.2`, no
`repo.radeon.com` entry anywhere in `/etc/apt/sources.list.d/`, no real ROCm
compute packages in `dpkg -l` (only `rocm-smi`, a monitoring tool), and the
user not in the `render`/`video` groups. The USB4TB drive that note
mentions (held a bootable clone) also wasn't mounted. Cause unconfirmed --
most likely an OS reinstall/reimage sometime after 2026-08-10 that didn't
repeat this step. **If the OS gets reinstalled again, redo everything below.**

## Symptom that led here

`persona_speech_input.py` and Typist's actual running script both silently
fall back to CPU int8 for faster-whisper. Neither prints a loud warning,
because the fallback logic (`torch.cuda.is_available()` false, or
`detect_backend()` in Typist) only warns on a *mismatch* between torch and
CTranslate2 -- with no ROCm stack at all, both correctly agree "no GPU" and
say nothing.

## Reinstall recipe (what actually worked)

```
sudo mkdir --parents --mode=0755 /etc/apt/keyrings

wget https://repo.radeon.com/rocm/rocm.gpg.key -O - | \
  gpg --dearmor | sudo tee /etc/apt/keyrings/rocm.gpg > /dev/null

echo 'deb [arch=amd64 signed-by=/etc/apt/keyrings/rocm.gpg] https://repo.radeon.com/rocm/apt/7.2.2 noble main' \
  | sudo tee /etc/apt/sources.list.d/rocm.list

printf 'Package: *\nPin: release o=repo.radeon.com\nPin-Priority: 600\n' \
  | sudo tee /etc/apt/preferences.d/rocm-pin-600

sudo apt-get update
sudo apt-get install -y rocm-hip-libraries miopen-hip

sudo ln -s /opt/rocm-7.2.2 /opt/rocm
printf '/opt/rocm/lib\n/opt/rocm/lib64\n' | sudo tee /etc/ld.so.conf.d/rocm.conf
sudo ldconfig

sudo usermod -aG render,video eh
# then LOG OUT AND BACK IN (or reboot) -- group membership only takes
# effect for new login sessions, including systemd --user services.
```

Only the `rocm/apt/7.2.2` repo line was added, not the `graphics/7.2.4/...`
one some AMD docs also show -- the box uses the inbox amdgpu driver with no
DKMS (per the original note), and that second repo is for the
driver/DKMS side, not needed here.

Pinned to the exact `7.2.2` path (not the newer `7.2.4` current default) to
match the version already baked into the `/opt/rocm-7.2.2` symlink target
and Typist's vendored CTranslate2 wheel naming. `repo.radeon.com/rocm/apt/`
still serves every patch version back through the 7.x line as its own path,
so this exact version stays available even as AMD publishes newer ones.

Build deps (`python3-dev`, `portaudio19-dev`, `libasound2-dev`) were already
present, unaffected by whatever wiped the ROCm stack. Group membership
(`render`, `video`) was also gone -- add both back.

## Pitfall: don't chase missing .so files with plain `apt install libX`

Before finding the real cause, tried `sudo apt install libhiprand1` to fix
one `ImportError` at a time. That pulled in `libamdhip64-5`, `librocrand1`,
and `libhsa-runtime64-1` from Ubuntu's **universe** repo -- a ROCm-**5.7**-era
compat build, version-mismatched with the ROCm 7.2 CTranslate2 wheel, and
(once the real `rocm-hip-libraries` install ran) filename-colliding with the
correct libraries under `/opt/rocm/lib`. Had to `apt remove` all four plus
`apt autoremove` three more orphaned transitive deps
(`libamd-comgr2`, `libhsakmt1`, `libllvm17t64`) to get back to zero
collisions before wiring up `/opt/rocm` in `ld.so.conf.d`. If a `.so` is
missing, go straight to `repo.radeon.com`'s packages
(`hipblas`, `rocblas`, `hip-runtime-amd`, etc., all pulled in transitively by
`rocm-hip-libraries`) rather than patching one missing library at a time
from Ubuntu's repo.

One pre-existing collision, unrelated to any of this and not touched:
`librocm_smi64.so.1` exists both in `/usr/lib/x86_64-linux-gnu` (Ubuntu's
`librocm-smi64-1` package, already installed before this session) and now in
`/opt/rocm/lib`. Harmless (it's only the monitoring tool), left alone.

## Verification

```
sg render -c "sg video -c 'uv run --extra rocm python -c \"
import ctranslate2, torch
print(torch.__version__, torch.version.hip, torch.cuda.is_available())
print(ctranslate2.get_supported_compute_types(\\\"cuda\\\"))
\"'"
```
(`sg render`/`sg video` used only because this shell session predates the
`usermod`; a fresh login shell needs neither.)

Result: `torch 2.10.0+rocm7.2.0... hip 7.2.26015, cuda.is_available() True`,
device name `Radeon 8060S Graphics`, CTranslate2 GPU compute types include
`float16`.

## Fresh benchmark (faster-whisper `large-v3-turbo`, best of 5, warm-started)

| Clip | CPU int8 | ROCm iGPU | Speedup |
|---|---|---|---|
| 1.62s (`Typist/components/warmup_audio.wav`) | 4.865s | 0.599s | 8.1x |
| 10.45s (`Persona/audio/bird-dream.wav`) | 5.135s | 0.772s | 6.7x |

Matches `future/PERFORMANCE.md` in Typist (measured 2026-08-11) closely, so
the recipe is confirmed reproducible from a cold OS state, not a fluke of
the original install.

## What this doesn't fix yet

- **Typist's actual launcher (`typist.sh` -> `typist.py`) still doesn't use
  any of this.** It runs via `uv run --script typist.py`, an inline PEP 723
  metadata block with plain CUDA packages (`nvidia-cublas-cu12` etc.),
  completely disconnected from `components/pyproject.toml`'s ROCm setup.
  Root cause: commit `347ff20` ("Promote overlay Typist script", 2026-09-10)
  promoted the tkinter model-switcher overlay from `experiments/sep9/`,
  which was built on the pre-ROCm-port script, silently reverting the
  hardware-detecting launcher that commit `37c91df` (2026-08-11) had put in
  place. Not yet repaired -- separate task, owner's call on whether to fix
  the live app now or just bring the ROCm setup straight to Persona.
- `components/pyproject.toml` also had its own bug found and fixed today
  (uncommitted, in the Typist repo): `[tool.uv.sources]`'s vendored wheel
  path was `wheels/rocm/ctranslate2-...whl`, relative to `components/`, but
  the wheel actually lives one directory up, at the repo root
  (`Typist/wheels/rocm/`). Fixed to `../wheels/rocm/...`. `components/`
  had never actually been `uv sync`'d before today (no prior `.venv`), so
  this had never been caught.
- Persona's own `persona_speech_input.py` still hasn't been ported to use
  this (see `notes/2026-08-10-rocm-amd-port.md`'s "Open" section) -- this
  note just re-proves the host side works, on this exact machine, today.
