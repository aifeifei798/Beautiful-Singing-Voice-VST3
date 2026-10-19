# Copyright 2026 Feifei
# SPDX-License-Identifier: Apache-2.0

"""Stem separation via Demucs, run in a subprocess so Qt and CUDA stay apart.

Results are cached per input file (sha256) so slider tweaks never re-run the model.

GPU notes (measured on a 32 GB RTX 5090 D, `htdemucs_ft`, two stems):

* the whole 234 s reference track separates in ~12.6 s (18x realtime);
* peak device memory is ~2.2 GB with demucs' default chunk and ~1.5 GB with
  ``--segment 4``, because most of it is the four sets of weights;
* so a card that a local LLM mostly owns still runs this on GPU — the old
  "6 GB free or bust" rule dropped to CPU (4 min/track) far too eagerly.

CUDA runs are not bit-identical between runs (cuDNN picks kernels per launch),
so a re-separation can differ by ~1e-2 in the stems. That is inaudible, and the
cache means it only happens once per file.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np
import soundfile as sf
from scipy.signal import resample_poly

from .audio import CACHE_DIR, sha256

DEFAULT_MODEL = "htdemucs_ft"
# Bump when the stem format/quality changes so stale caches are not reused.
# v2: stems are written as 32-bit float instead of demucs' default 16-bit PCM.
CACHE_TAG = "f32"

SEGMENT_TIGHT = 4.0

# Free VRAM demucs needs, measured by pinning the card with a dummy tensor:
#   default chunk  -> OK at 2.1 GB free, OOM at 1.3 GB
#   --segment 4    -> OK at 1.5 GB free, OOM at 1.2 GB
VRAM_FT_FULL_MIB = 2300
VRAM_FT_TIGHT_MIB = 1400
VRAM_SINGLE_FULL_MIB = 1500
VRAM_SINGLE_TIGHT_MIB = 1000

# demucs runs a "bag" of several models one after another; each one prints its
# own progress bar, so the raw percentages restart several times per track.
BAG_PASSES = {"htdemucs_ft": 4}

_PERCENT = re.compile(r"(\d+(?:\.\d+)?)%")


def demucs_available() -> bool:
    try:
        import demucs  # noqa: F401
        return True
    except ImportError:
        return False


def _free_vram_mib() -> int | None:
    """Free VRAM on GPU 0 (the device demucs uses), or None if nvidia-smi is absent."""
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.free", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=6,
        )
        values = [int(line.strip()) for line in out.stdout.splitlines() if line.strip().isdigit()]
        return values[0] if values else None
    except Exception:
        return None


_GPU_AVAILABLE: bool | None = None


def _gpu_available() -> bool:
    """torch.cuda.is_available() costs ~1.3 s of imports, so ask it once."""
    global _GPU_AVAILABLE
    if _GPU_AVAILABLE is None:
        try:
            import torch
            _GPU_AVAILABLE = bool(torch.cuda.is_available())
        except Exception:
            _GPU_AVAILABLE = False
    return _GPU_AVAILABLE


def plan_separation(model: str, device: str | None = None) -> tuple[str, float | None]:
    """Pick (device, segment) for demucs.

    htdemucs_ft is a bag of four models: most of its footprint is the weights,
    and the chunk size only moves that by a few hundred MB. So the card does not
    need to be empty — it needs a couple of GB of headroom. When it is tighter
    than that we shrink the segment (slower, same output), and only when even
    that will not fit do we fall back to CPU (about 1.4x realtime).
    ``BSV_DEVICE=cuda|cpu`` forces the device.
    """
    override = device or os.environ.get("BSV_DEVICE")
    if override:
        return override, None
    if not _gpu_available():
        return "cpu", None
    free = _free_vram_mib()
    if free is None:
        return "cuda", None
    if model.endswith("_ft"):
        full, tight = VRAM_FT_FULL_MIB, VRAM_FT_TIGHT_MIB
    else:
        full, tight = VRAM_SINGLE_FULL_MIB, VRAM_SINGLE_TIGHT_MIB
    if free >= full:
        return "cuda", None
    if free >= tight:
        return "cuda", SEGMENT_TIGHT
    return "cpu", None


def _demucs_command(source: Path, out_dir: Path, model: str, device: str,
                    segment: float | None) -> list[str]:
    cmd = [
        sys.executable, "-m", "demucs",
        "-o", str(out_dir),
        "--two-stems=vocals",
        "-n", model,
        "-d", device,
        # demucs defaults to 16-bit PCM; float keeps the stems at full precision
        "--float32",
    ]
    if segment is not None:
        cmd += ["--segment", f"{segment:g}"]
    cmd.append(str(source))
    return cmd


def _attempts(device: str, segment: float | None) -> list[tuple[str, float | None]]:
    """Fallback ladder for a CUDA run: full chunk -> small chunk -> CPU."""
    attempts: list[tuple[str, float | None]] = [(device, segment)]
    if device == "cuda":
        if segment is None:
            attempts.append(("cuda", SEGMENT_TIGHT))
        attempts.append(("cpu", None))
    return attempts


def stem_dir(source: Path, model: str) -> Path:
    return CACHE_DIR / "stems" / sha256(source) / f"{model}-{CACHE_TAG}"


def _clean_stale_staging(parent: Path) -> None:
    """Drop staging dirs left behind by an interrupted run (crash, Ctrl-C, OOM)."""
    for leftover in parent.glob("demucs-*"):
        if leftover.is_dir():
            shutil.rmtree(leftover, ignore_errors=True)


def _stem_paths(out_dir: Path, track: str) -> tuple[Path, Path]:
    """Demucs names the second stem `other.wav` or `no_vocals.wav` depending on the mode."""
    base = out_dir / track
    vocals = base / "vocals.wav"
    if not vocals.exists():
        found = sorted(out_dir.glob("**/vocals.wav"))
        if not found:
            raise RuntimeError("demucs produced no vocals.wav")
        base = found[0].parent
        vocals = found[0]
    for name in ("other.wav", "no_vocals.wav"):
        other = base / name
        if other.exists():
            return vocals, other
    raise RuntimeError(f"demucs produced vocals.wav but no companion stem in {base}")


def _read_stem(path: Path) -> tuple[np.ndarray, int]:
    data, sr = sf.read(path, dtype="float32", always_2d=True)
    if data.shape[0] == 0:
        raise RuntimeError(f"{path.name} is empty")
    return data, sr


def load_cached_stems(source: Path, model: str) -> tuple[np.ndarray, np.ndarray, int] | None:
    """Cached stems for this file, or None when missing/unreadable (half a run)."""
    d = stem_dir(source, model)
    try:
        vocals, other = _stem_paths(d, Path(source).stem)
        v, stem_sr = _read_stem(vocals)
        o, _ = _read_stem(other)
    except Exception:
        return None
    return v, o, stem_sr


def _run_once(source: Path, out_dir: Path, model: str, device: str,
              segment: float | None, progress_cb) -> None:
    """One demucs attempt, staged in a temp dir so a crash cannot poison the cache."""
    out_dir.parent.mkdir(parents=True, exist_ok=True)
    _clean_stale_staging(out_dir.parent)
    staging = Path(tempfile.mkdtemp(prefix="demucs-", dir=out_dir.parent))
    label = device if segment is None else f"{device}, {segment:g}s 分段"
    passes = BAG_PASSES.get(model, 1)
    try:
        cmd = _demucs_command(source, staging, model, device, segment)
        proc = subprocess.Popen(cmd, stderr=subprocess.PIPE, text=True, bufsize=1)
        assert proc.stderr is not None
        tail: list[str] = []
        last_pct = 0.0
        done = 0
        for line in proc.stderr:
            tail.append(line)
            if len(tail) > 20:
                tail.pop(0)
            match = _PERCENT.search(line)
            if not match:
                continue
            pct = float(match.group(1))
            if pct + 40.0 < last_pct and done + 1 < passes:
                done += 1  # a model finished and the next bar restarted from 0
            last_pct = pct
            if progress_cb:
                overall = (done + pct / 100.0) / passes
                detail = f"{label}, 第 {done + 1}/{passes} 段模型" if passes > 1 else label
                progress_cb(min(overall * 100.0, 99.0), f"分离人声 / 配乐 ({detail})")
        code = proc.wait()
        if code != 0:
            detail = "".join(tail[-6:]).strip()
            raise RuntimeError(f"demucs failed with exit code {code}: {detail}")

        produced = staging / model / source.stem
        if not produced.exists():
            found = sorted(staging.glob(f"**/{source.stem}"))
            if not found:
                raise RuntimeError("demucs produced no output directory")
            produced = found[0]
        _stem_paths(produced.parent, produced.name)  # validate before publishing

        # flat cache layout: <sha>/<model>-f32/<track>/{vocals,no_vocals}.wav
        dest = out_dir / source.stem
        shutil.rmtree(dest, ignore_errors=True)
        shutil.move(str(produced), str(dest))
    finally:
        shutil.rmtree(staging, ignore_errors=True)


def separate(
    source: Path,
    model: str = DEFAULT_MODEL,
    device: str | None = None,
    progress_cb=None,
    target_sr: int | None = None,
) -> tuple[np.ndarray, np.ndarray]:
    """Return (vocals, everything_else) as float32 (n, 2).

    Demucs always works at 44.1 kHz, so when the project runs at another rate the
    stems are resampled to `target_sr` before they are handed back — otherwise the
    remix plays back like a sped-up tape.
    """
    cached = load_cached_stems(source, model)
    if cached is not None:
        if progress_cb:
            progress_cb(100.0, "分轨已缓存")
        vocals, other, stem_sr = cached
    else:
        out_dir = stem_dir(source, model)
        out_dir.mkdir(parents=True, exist_ok=True)
        device, segment = plan_separation(model, device)

        attempts = _attempts(device, segment)
        for index, (dev, seg) in enumerate(attempts):
            try:
                _run_once(source, out_dir, model, dev, seg, progress_cb)
                break
            except RuntimeError as exc:
                if dev != "cuda" or "out of memory" not in str(exc).lower():
                    raise
                if index + 1 >= len(attempts):
                    raise
                if progress_cb:
                    progress_cb(0.0, "显存不足，缩小分段 / 改用 CPU 重试…")

        vocals_path, other_path = _stem_paths(out_dir, Path(source).stem)
        vocals, stem_sr = _read_stem(vocals_path)
        other, _ = _read_stem(other_path)
        if progress_cb:
            progress_cb(100.0, "分轨完成")

    return _match_rate(vocals, other, stem_sr, target_sr)


def _match_rate(vocals: np.ndarray, other: np.ndarray, stem_sr: int,
                target_sr: int | None) -> tuple[np.ndarray, np.ndarray]:
    """Demucs output is always 44.1 kHz; resample when the project clock differs."""
    if not target_sr or stem_sr == target_sr:
        return vocals, other
    vocals = resample_poly(vocals, target_sr, stem_sr).astype(np.float32)
    other = resample_poly(other, target_sr, stem_sr).astype(np.float32)
    return vocals, other
