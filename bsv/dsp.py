# Copyright 2026 Feifei
# SPDX-License-Identifier: Apache-2.0

"""DSP primitives: soft de-clip, EQ, de-esser, sidechain duck, limiter, loudness.

All functions take numpy arrays shaped (n_samples, 2) float32 and a sample rate.
EQ is done with the scipy biquads in bsv.filters — pedalboard's IIR plugins are
~30x slower on a full track (a 230 s song: ~45 s of filtering vs ~1.5 s here),
and the responses were matched against pedalboard to within a fraction of a dB.
"""

from __future__ import annotations

import numpy as np
from pedalboard import BrickwallLimiter, Compressor, Reverb

from .filters import (
    band_filter,
    high_shelf_sos,
    highpass_sos,
    k_weighting_sos,
    lowpass_sos,
    low_shelf_sos,
    peak_sos,
    Filter,
)

LOG10_20 = np.log(10.0) / 20.0
EPS = 1e-12
# Sample blocks used by the element-wise stages. A 230 s track is ~80 MB per
# array, and on a machine already carrying a local LLM the kernel starts swapping
# when a stage needs several full-track temporaries at once. Working in 262k
# sample blocks (about 6 s) keeps those temporaries in cache and the render flat
# no matter what else is resident.
BLOCK = 1 << 18


def _db_to_linear(db: float) -> float:
    return 10.0 ** (db / 20.0)


# --------------------------------------------------------------------------
# repair
# --------------------------------------------------------------------------
def soft_declip(x: np.ndarray, knee: float = 0.94) -> np.ndarray:
    """Round off flat-topped clipping instead of hard-clipping it again."""
    x = np.asarray(x, dtype=np.float32)
    abs_x = np.abs(x)
    over = abs_x > knee
    if not over.any():
        return x
    out = x.copy()
    span = 1.0 - knee
    scaled = (abs_x[over] - knee) / span
    out[over] = np.sign(x[over]) * (knee + span * np.tanh(scaled))
    return out


# --------------------------------------------------------------------------
# envelope helpers (block-based, vectorised)
# --------------------------------------------------------------------------
def _block_size(sr: int, block_ms: float) -> int:
    return max(1, int(sr * block_ms / 1000.0))


def block_rms_db(x: np.ndarray, sr: int, block_ms: float = 4.0) -> np.ndarray:
    """RMS level in dB per block, shape (n_blocks, channels)."""
    block = _block_size(sr, block_ms)
    n = x.shape[0]
    n_blocks = (n + block - 1) // block
    padded = np.pad(x, ((0, n_blocks * block - n), (0, 0)))
    blocks = padded.reshape(n_blocks, block, x.shape[1])
    rms = np.sqrt(np.mean(blocks * blocks, axis=1))
    return 20.0 * np.log10(np.maximum(rms, EPS))


def block_peak_db(x: np.ndarray, sr: int, block_ms: float = 1.0) -> np.ndarray:
    block = _block_size(sr, block_ms)
    n = x.shape[0]
    n_blocks = (n + block - 1) // block
    padded = np.pad(x, ((0, n_blocks * block - n), (0, 0)))
    peaks = np.max(np.abs(padded.reshape(n_blocks, block, x.shape[1])), axis=1)
    return 20.0 * np.log10(np.maximum(peaks, EPS))


def smooth_blocks(values: np.ndarray, sr: int, attack_ms: float, release_ms: float,
                  block_ms: float = 4.0) -> np.ndarray:
    """One-pole smoothing with separate attack/release on block values."""
    block = _block_size(sr, block_ms)
    attack = np.exp(-block / (sr * max(attack_ms, 0.1) / 1000.0))
    release = np.exp(-block / (sr * max(release_ms, 0.1) / 1000.0))
    out = np.empty_like(values)
    prev = values[0].copy()
    for i in range(values.shape[0]):
        target = values[i]
        coeff = np.where(target < prev, attack, release)  # deeper attenuation = fast
        prev = prev + coeff * (target - prev)
        out[i] = prev
    return out


# --------------------------------------------------------------------------
# EQ
# --------------------------------------------------------------------------
def band(x: np.ndarray, sr: int, lo_hz: float, hi_hz: float) -> np.ndarray:
    """Approximate band isolation with cascaded highpass + lowpass."""
    return band_filter(lo_hz, hi_hz, sr)(x, sr)


def deesser(
    x: np.ndarray,
    sr: int,
    center_hz: float,
    threshold_db: float,
    amount: float,
    attack_ms: float = 4.0,
    release_ms: float = 40.0,
    half_width_hz: float = 1200.0,
) -> np.ndarray:
    """Attenuate a sibilance band only when it spikes above threshold."""
    if amount <= 0.0:
        return x
    lo = max(200.0, center_hz - half_width_hz / 2.0)
    hi = min(sr / 2.0 - 100.0, center_hz + half_width_hz / 2.0)
    targeted = band(x, sr, lo, hi)

    block_ms = 2.0
    env_db = block_rms_db(targeted, sr, block_ms)
    gain_blocks = smooth_blocks(
        -amount * np.maximum(0.0, env_db - threshold_db), sr, attack_ms, release_ms, block_ms
    )

    block = _block_size(sr, block_ms)
    out = x.copy()
    n = x.shape[0]
    for i in range(0, n, BLOCK):
        j = min(i + BLOCK, n)
        linear = np.exp(gain_blocks[np.arange(i, j) // block] * LOG10_20) - 1.0
        out[i:j] += targeted[i:j] * linear
    return out.astype(np.float32, copy=False)


# --------------------------------------------------------------------------
# sidechain ducking driven by the vocal stem
# --------------------------------------------------------------------------
def duck(
    music: np.ndarray,
    vocal: np.ndarray,
    sr: int,
    duck_db: float,
    lo_hz: float = 250.0,
    hi_hz: float = 4000.0,
    threshold_db: float = -28.0,
    attack_ms: float = 40.0,
    release_ms: float = 260.0,
) -> np.ndarray:
    """Push the accompaniment down inside the vocal band while the vocal is active."""
    if duck_db <= 0.0:
        return music

    block_ms = 5.0
    env_db = block_rms_db(vocal, sr, block_ms)
    active = np.clip((env_db - threshold_db) / 8.0, 0.0, 1.0)
    active = smooth_blocks(active, sr, attack_ms, release_ms, block_ms)
    gain_blocks = -duck_db * active

    block = _block_size(sr, block_ms)
    mid = band(music, sr, lo_hz, hi_hz)
    out = music.copy()
    n = music.shape[0]
    for i in range(0, n, BLOCK):
        j = min(i + BLOCK, n)
        linear = np.exp(gain_blocks[np.arange(i, j) // block] * LOG10_20)
        out[i:j] -= mid[i:j] * (1.0 - linear)
    return out.astype(np.float32, copy=False)


# --------------------------------------------------------------------------
# loudness
# --------------------------------------------------------------------------
def _block_powers(weighted: np.ndarray, sr: int, block: int, lo: np.ndarray, hi: np.ndarray,
                  gains: np.ndarray) -> np.ndarray:
    """Mean square per gating block, summed over channels with BS.1770 gains."""
    total = np.zeros(lo.shape[0], dtype=np.float64)
    for ch in range(weighted.shape[1]):
        c = np.empty(weighted.shape[0] + 1, dtype=np.float64)
        c[0] = 0.0
        np.cumsum(np.square(weighted[:, ch].astype(np.float64)), out=c[1:])
        total += gains[ch] * (c[hi] - c[lo]) / block
    return total


def lufs(x: np.ndarray, sr: int, block_size: float = 0.4, overlap: float = 0.75) -> float:
    """Integrated gated loudness (ITU-R BS.1770-4), vectorised.

    pyloudnorm does the same maths but loops over every 400 ms block in Python,
    which costs ~30 s and ~500 MB on a four-minute track. Gating is done with a
    cumulative sum instead, so a 230 s track measures in well under a second.
    """
    x = np.asarray(x, dtype=np.float32)
    if x.ndim == 1:
        x = x[:, None]
    n, channels = x.shape

    weighted = Filter(k_weighting_sos(sr))(x, sr)
    gains = np.array([1.0, 1.0, 1.0, 1.41, 1.41])[:channels]

    block = int(round(block_size * sr))
    step_fraction = 1.0 - overlap
    if n < block:
        return -0.691 + 10.0 * np.log10(max(float(np.mean(np.square(weighted.astype(np.float64)) * gains)), EPS))

    num_blocks = int(round(((n / sr - block_size) / (block_size * step_fraction)))) + 1
    if num_blocks <= 1:
        return -0.691 + 10.0 * np.log10(max(float(np.mean(np.square(weighted.astype(np.float64)) * gains)), EPS))

    j = np.arange(num_blocks, dtype=np.float64)
    lo = (block_size * (j * step_fraction) * sr).astype(np.int64)
    hi = (block_size * (j * step_fraction + 1.0) * sr).astype(np.int64)
    np.clip(hi, 0, n, out=hi)

    power = _block_powers(weighted, sr, block, lo, hi, gains)
    loud = -0.691 + 10.0 * np.log10(np.maximum(power, EPS))

    above_absolute = loud > -70.0
    if not above_absolute.any():
        return -70.0

    relative = -0.691 + 10.0 * np.log10(max(float(np.mean(power[above_absolute])), EPS)) - 10.0
    gated = above_absolute & (loud > relative)
    if not gated.any():
        return -70.0

    return -0.691 + 10.0 * np.log10(max(float(np.mean(power[gated])), EPS))


def normalize_loudness(x: np.ndarray, sr: int, target_lufs: float, ceiling_db: float = -1.0) -> np.ndarray:
    ln10 = np.log(10.0) / 20.0
    measured = lufs(x, sr)
    delta = float(np.clip(target_lufs - measured, -24.0, 24.0))
    out = x * np.exp(delta * ln10)
    out = BrickwallLimiter(ceiling_db=ceiling_db, release_ms=120.0, lookahead_ms=5.0)(out, sr)

    # second pass: the limiter can shave a little, so correct once more
    err = target_lufs - lufs(out, sr)
    if abs(err) > 0.4:
        out = out * np.exp(np.clip(err, -6.0, 6.0) * ln10)
        out = BrickwallLimiter(ceiling_db=ceiling_db, release_ms=120.0, lookahead_ms=5.0)(out, sr)
    return out


def peak_db(x: np.ndarray) -> float:
    return 20.0 * np.log10(max(float(np.max(np.abs(x))), EPS))


def rms_db(x: np.ndarray) -> float:
    return 20.0 * np.log10(max(float(np.sqrt(np.mean(np.square(x)))), EPS))


# --------------------------------------------------------------------------
# chain builders
# --------------------------------------------------------------------------
def _vocal_eq(params, sr: int) -> Filter:
    sections = [highpass_sos(params.vocal_hp_hz, sr)]
    sections.append(peak_sos(params.mud_hz, 1.2, params.mud_db, sr))
    sections.append(peak_sos(params.mud2_hz, 1.0, params.mud2_db, sr))
    if params.warmth_db != 0.0:
        sections.append(low_shelf_sos(params.warmth_hz, params.warmth_db, sr))
    if params.presence_db != 0.0:
        sections.append(peak_sos(params.presence_hz, 0.8, params.presence_db, sr))
    if params.air_db != 0.0:
        sections.append(high_shelf_sos(params.air_hz, params.air_db, sr))
    return Filter(sections)


def _music_eq(params, sr: int) -> Filter:
    sections = [highpass_sos(params.music_hp_hz, sr)]
    if params.music_mud_db != 0.0:
        sections.append(peak_sos(320.0, 1.2, params.music_mud_db, sr))
    return Filter(sections)


def vocal_chain(params, sr: int) -> list:
    return [_vocal_eq(params, sr), Compressor(
        threshold_db=params.comp_threshold_db,
        ratio=params.comp_ratio,
        attack_ms=params.comp_attack_ms,
        release_ms=params.comp_release_ms,
    )]


def music_chain(params, sr: int) -> list:
    return [_music_eq(params, sr)]


def reverb(x: np.ndarray, sr: int, room: float, wet: float, damping: float) -> np.ndarray:
    if wet <= 0.0:
        return x
    wet_signal = Reverb(room_size=room, damping=damping, wet_level=1.0, dry_level=0.0)(x, sr)
    # keep the reverberation out of the muddy low band so the vocal stays close
    wet_signal = Filter([highpass_sos(250.0, sr)])(wet_signal, sr)
    dry = x * (1.0 - wet)
    return dry + wet_signal * wet


def add_doubling(x: np.ndarray, sr: int, level_db: float, delay_ms: float,
                 count: int = 3, detune: float = 0.0045,
                 block: int | None = None) -> np.ndarray:
    """Layer band-limited, slightly detuned copies behind the lead vocal.

    One slap copy is just an echo. Real thickness comes from a few doubles at
    ~20-45 ms, detuned by a few tenths of a percent and missing the low end —
    the same thing three session singers would do on a reel. `level_db` is the
    level of *each* double.

    Measured on a real vocal stem (60 s of 夜南京), relative to the dry lead:

        level      RMS      body 200-900 Hz   air 4-8 kHz   correlation
        -20 dB    +0.04 dB       +0.06 dB       +0.09 dB      0.989
        -16 dB    +0.16 dB       +0.20 dB       +0.21 dB      0.973
        -14 dB    +0.27 dB       +0.33 dB       +0.32 dB      0.958
        -12 dB    +0.45 dB       +0.54 dB       +0.50 dB      0.935
        -10 dB    +0.73 dB       +0.85 dB       +0.76 dB      0.901

    So -14 dB reads as body without touching the level much, which is why the
    neutral preset sits there. The correlation column is the honest measure of
    "is it still the same voice" — it stays above 0.95 up to -14 dB.
    """
    if level_db <= -60.0:
        return x
    n = x.shape[0]
    level = _db_to_linear(level_db)
    doubles = band_filter(220.0, 7500.0, sr)(x, sr)
    out = x.copy()
    block = block or BLOCK
    fade = max(1, int(0.008 * sr))  # 8 ms: keep the tail from ending on a step

    multipliers = (0.72, 1.0, 1.45)[:count]
    detunes = (-detune, detune * 0.9, -detune * 1.7)[:count]
    for mul, scale in zip(multipliers, detunes):
        scale = 1.0 + scale
        delay = int(round(delay_ms * mul / 1000.0 * sr))
        if delay <= 0 or delay >= n:
            continue
        # a detuned copy reads slightly past its own position, so it runs out of
        # source before the signal does; stop there instead of holding the last sample
        span = min(n - delay, int((n - 1) / scale) + 1)
        if span <= 0:
            continue
        tail = span - min(fade, span // 2)
        for i in range(0, span, block):
            j = min(i + block, span)
            lo = max(0, int(i * scale) - 1)
            hi = min(n, int(j * scale) + 2)
            idx = np.arange(i, j, dtype=np.float64) * scale
            src = np.arange(lo, hi, dtype=np.float64)
            for ch in range(x.shape[1]):
                shifted = np.interp(idx, src, doubles[lo:hi, ch])
                if j > tail:
                    k = max(0, tail - i)
                    shifted[k:] *= np.linspace(1.0, 0.0, len(shifted) - k)
                out[i + delay:j + delay, ch] += shifted * level
    return out.astype(np.float32, copy=False)
