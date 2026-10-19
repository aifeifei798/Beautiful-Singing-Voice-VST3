# Copyright 2026 Feifei
# SPDX-License-Identifier: Apache-2.0

"""Analysis: find the time slots where Suno tracks actually need help.

Used by the UI to jump straight to the interesting comparisons instead of
scrubbing a 3-minute song by hand.
"""

from __future__ import annotations

import numpy as np

from .dsp import EPS, band, block_rms_db

_BLOCK_MS = 100.0


def rms_db(x: np.ndarray) -> float:
    """Level of the whole signal — averaging linear RMS, then converting once.

    Averaging per-block dB values is wrong: a stem with silent blocks drags the
    mean down by tens of dB.
    """
    x = np.asarray(x, dtype=np.float64)
    return float(20.0 * np.log10(max(np.sqrt(np.mean(x * x)), EPS)))


def _per_block_db(blocks: np.ndarray) -> np.ndarray:
    return blocks.mean(axis=1) if blocks.ndim > 1 else blocks


def _top_regions(values: np.ndarray, min_db: float, top: int = 4,
                 block_ms: float = _BLOCK_MS) -> list[dict]:
    n = values.shape[0]
    if n == 0:
        return []
    order = np.argsort(values)[::-1]
    picked: list[int] = []
    for idx in order:
        if values[idx] < min_db:
            break
        if any(abs(idx - p) < int(1000 / block_ms) for p in picked):
            continue
        picked.append(int(idx))
        if len(picked) >= top:
            break
    return [
        {"time": idx * block_ms / 1000.0, "value_db": float(values[idx])}
        for idx in picked
    ]


def analyze(vocal: np.ndarray, music: np.ndarray, sr: int) -> dict:
    """Return global balance stats plus the most problematic time regions."""
    if vocal.ndim == 1:
        vocal = vocal[:, None]
    if music.ndim == 1:
        music = music[:, None]

    vocal_core = band(vocal, sr, 300.0, 3000.0)
    vocal_high = band(vocal, sr, 5500.0, 9000.0)
    music_core = band(music, sr, 300.0, 3000.0)

    core_db = _per_block_db(block_rms_db(vocal_core, sr, _BLOCK_MS))
    music_db = _per_block_db(block_rms_db(music_core, sr, _BLOCK_MS))
    high_db = _per_block_db(block_rms_db(vocal_high, sr, _BLOCK_MS))

    # Only blocks where the vocal is actually singing count: in a silent block both
    # bands sit on the EPS floor and the ratio is meaningless (0 dB "sibilance").
    if core_db.size:
        present = core_db > np.max(core_db) - 12.0
    else:
        present = np.zeros_like(core_db, dtype=bool)

    sib_db = np.where(present, high_db - core_db, -np.inf)
    overlap = np.where(present, music_db - core_db, -np.inf)

    sib_max = float(np.max(sib_db)) if sib_db.size else -np.inf
    sib_peak = sib_max if np.isfinite(sib_max) else 0.0
    overlap_max = float(np.max(overlap)) if overlap.size else -np.inf
    overlap_peak = overlap_max if np.isfinite(overlap_max) else 0.0

    return {
        "vocal_level_db": rms_db(vocal),
        "music_level_db": rms_db(music),
        "vocal_music_ratio_db": rms_db(vocal) - rms_db(music),
        "sibilance_max_db": sib_peak,
        "overlap_max_db": overlap_peak,
        "regions": {
            "sibilance": _top_regions(sib_db, min_db=-6.0, top=4),
            "overlap": _top_regions(overlap, min_db=2.0, top=4),
        },
    }
