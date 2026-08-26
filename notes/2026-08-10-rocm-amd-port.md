# ROCm / AMD port — decisions from the Typist and Speak port

2026-08-10. Persona itself was **not** touched. Typist and Speak (both broken
out of this project) were ported to AMD ROCm on the new box, and the host is now
configured for Persona to follow. This note records what was decided and why, so
the Persona port does not re-derive it.

## The machine

Beelink GTR9 Pro — Ryzen AI MAX+ 395, Radeon 8060S (**gfx1151**), 128 GB RAM
split **96 GB VRAM / 32 GB system** by BIOS UMA. Linux Mint 22.3 (Ubuntu noble
base), kernel 7.0.0-28-generic, **inbox amdgpu driver, no DKMS**. `rocminfo`
also enumerates the NPU (`aie2p`) as a DSP agent; nothing uses it.

## Host setup already done (Persona inherits this)

- ROCm **7.2.2** from `repo.radeon.com`, `noble` repo, pin priority 600.
- Installed `rocm-hip-libraries` + `miopen-hip` (14 GB) — **not** the full
  `rocm` metapackage (26 GB, adds only compiler/SDK material). `miopen-hip` is
  not part of `rocm-hip-libraries` and is required; PyTorch routes convolutions
  through it.
- **Linker fix, required.** Neither metapackage ships an ldconfig entry or the
  `/opt/rocm` symlink; those come from `amdgpu-install`. Without them torch dies
  at import with `ImportError: libroctx64.so.4`. Created `/opt/rocm ->
  /opt/rocm-7.2.2`, added `/etc/ld.so.conf.d/rocm.conf`, ran `ldconfig`.
  (Checked first: none of the 89 libraries in `/opt/rocm/lib` collide with a
  system library.)
- User is in the `render` and `video` groups.
- Build deps for audio: `python3-dev`, `portaudio19-dev`, `libasound2-dev`.

## Decisions

**Vulkan was considered and rejected.** Neither CTranslate2 nor PyTorch has a
production Vulkan compute backend. Vulkan would mean swapping engines
(whisper.cpp for STT; nothing at all for Chatterbox), not changing dependencies.
Revisit only if ROCm support for gfx1151 regresses.

**Two settings layers, not one.** Both Typist and Speak expose:

- `*_EXTRA` — which torch gets *installed* (`auto|rocm|cuda|cpu`)
- `*_DEVICE` — which device the model *runs on* (`auto|cuda|cpu`)

Changing device needs no reinstall, because the ROCm builds carry CPU kernels
too. Persona's speech services should adopt the same split rather than inventing
a third scheme. Defaults live in an editable `settings` block at the top of each
launcher script.

**Dependencies live in `pyproject.toml`, not a `# /// script` block.** uv rejects
extras in inline script metadata ("Extras are not supported for Python scripts
with inline metadata"), and extras are the only way to express a CUDA-or-ROCm
choice. Alternate *indexes* do work inline — this was tested, not assumed.

## uv gotchas that will bite Persona too

- AMD's wheel URL is a **flat HTML directory listing**, not a PEP 503 index
  (`/simple/` and `/torch/` both 404). `[[tool.uv.index]]` needs
  `format = "flat"` or resolution fails with a misleading "package not found".
- **`[tool.uv.sources]` only redirects *direct* dependencies.** ROCm torch needs
  `triton==3.6.0+rocm7.2.0...`, which exists only on AMD's index; as a
  transitive dep it gets looked up on PyPI and fails. List `triton` explicitly.
- **`override-dependencies` breaks extra-conditional sources.** It collapses the
  requirement into a single unconditional one, detaching it from the extra, so
  the index redirect stops matching and torch silently resolves from PyPI. The
  lockfile looks fine; you just get the wrong torch. Use
  `[[tool.uv.dependency-metadata]]` to restate a package's requires-dist instead.
- **`setuptools<81`** wherever `perth` is involved — 81 removed `pkg_resources`,
  and perth swallows the resulting ImportError, failing much later as
  `TypeError: 'NoneType' object is not callable`.

## Benchmarks — the GPU is not always the fast path

Same install both arms; only `device=` changed.

| Workload | ROCm | CPU | Winner |
|---|---|---|---|
| faster-whisper `small.en`, 1.6 s clip | 0.197 s | 0.551 s | **GPU, 2.8x** |
| faster-whisper `small.en`, 10.5 s clip | 0.528 s | 0.861 s | **GPU, 1.63x** |
| Chatterbox TTS | 0.337x realtime | 0.517x realtime | **CPU, 1.5x** |

Chatterbox is *slower* on the iGPU. On an APU the iGPU shares the same LPDDR5X
memory as the CPU, so it gains no bandwidth advantage, and Chatterbox's T3 stage
is a batch-1 autoregressive loop — latency-bound, thousands of small matmuls,
which penalises per-kernel launch and sync overhead. Whisper's encoder is one
large dense batched pass, which is what a GPU is for.

MIOpen tuning does not rescue the Chatterbox GPU arm:
`torch.backends.cudnn.benchmark = True` and `MIOPEN_FIND_MODE=NORMAL` were both
tried, with no effect. Convolutions are not the bottleneck.

**Implication for `persona_speech_output.py`:** run Chatterbox on the CPU on this
box. It is faster *and* it leaves the GPU free for the LLM — which matters here,
because speech output and LLM inference would otherwise contend for the same
device.

## Open

- Persona not ported. `persona_speech_input.py` (Whisper) and
  `persona_speech_output.py` (Chatterbox) are the two GPU touchpoints.
- Root filesystem is tight — it hit 100% during this work. There is a 4 TB USB
  SSD labeled `USB4TB` (in `/etc/fstab` with `nofail`) that also holds a
  bootable system clone.
