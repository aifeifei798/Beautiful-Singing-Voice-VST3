# Copyright 2026 Feifei
# SPDX-License-Identifier: GPL-3.0-only

from __future__ import annotations

import numpy as np
from pedalboard import (
    HighpassFilter,
    HighShelfFilter,
    LowpassFilter,
    LowShelfFilter,
    PeakFilter,
)

from bsv.dsp import band, lufs, peak_db
from bsv.filters import (
    band_filter,
    Filter,
    high_shelf_sos,
    highpass_sos,
    lowpass_sos,
    low_shelf_sos,
    peak_sos,
)

SR = 44100


def _impulse(n: int = 1 << 14) -> np.ndarray:
    imp = np.zeros((n, 2), dtype=np.float32)
    imp[64, 0] = imp[64, 1] = 1.0
    return imp


def _measured(plugin, sr: int = SR) -> np.ndarray:
    imp = _impulse()
    return 20.0 * np.log10(np.abs(np.fft.rfft(plugin(imp, sr)[:, 0])) + 1e-12)


def _grid(sr: int = SR, n: int = 1 << 14) -> np.ndarray:
    return np.fft.rfftfreq(n, 1.0 / sr)[1:-1]  # skip DC and Nyquist, where every filter is 0 or exact


def test_eq_matches_pedalboard():
    imp_len = 1 << 14
    freqs = _grid(n=imp_len)
    cases = [
        (HighpassFilter(cutoff_frequency_hz=40.0), [highpass_sos(40.0, SR)]),
        (HighpassFilter(cutoff_frequency_hz=250.0), [highpass_sos(250.0, SR)]),
        (LowpassFilter(cutoff_frequency_hz=4000.0), [lowpass_sos(4000.0, SR)]),
        (PeakFilter(cutoff_frequency_hz=320.0, q=1.2, gain_db=-3.5), [peak_sos(320.0, 1.2, -3.5, SR)]),
        (PeakFilter(cutoff_frequency_hz=2500.0, q=0.8, gain_db=3.2), [peak_sos(2500.0, 0.8, 3.2, SR)]),
        (LowShelfFilter(cutoff_frequency_hz=180.0, gain_db=1.2), [low_shelf_sos(180.0, 1.2, SR)]),
        (HighShelfFilter(cutoff_frequency_hz=8000.0, gain_db=2.2), [high_shelf_sos(8000.0, 2.2, SR)]),
    ]
    for plugin, sections in cases:
        mine = Filter(sections).response_db(SR, freqs)
        theirs = _measured(plugin)[1:-1]  # same bins as freqs
        assert np.max(np.abs(mine - theirs)) < 1.0, f"{type(plugin).__name__} response differs by >1 dB"


def test_zero_gain_is_passthrough():
    x = np.random.RandomState(1).uniform(-1, 1, size=(2048, 2)).astype(np.float32)
    out = Filter([peak_sos(1000.0, 1.0, 0.0, SR), low_shelf_sos(500.0, 0.0, SR)])(x, SR)
    assert np.allclose(out, x, atol=1e-6)


def test_band_isolates_the_target_range():
    sr = SR
    n = 1 << 13
    t = np.arange(n) / sr
    sig = (np.sin(2 * np.pi * 7000 * t) + np.sin(2 * np.pi * 100 * t) + np.sin(2 * np.pi * 15000 * t))
    sig = sig[:, None]

    before = np.abs(np.fft.rfft(sig[:, 0]))
    after = np.abs(np.fft.rfft(band(sig, sr, 5500.0, 9000.0)[:, 0]))
    freqs = np.fft.rfftfreq(n, 1.0 / sr)

    def at(freq):
        i = int(np.argmin(np.abs(freqs - freq)))
        return i

    assert after[at(7000.0)] > 0.5 * before[at(7000.0)]
    assert after[at(100.0)] < 0.05 * before[at(100.0)]
    assert after[at(15000.0)] < 0.6 * before[at(15000.0)]


def test_lufs_matches_pyloudnorm():
    import pyloudnorm as pyln

    rng = np.random.default_rng(7)
    sr = SR
    tone = (0.2 * np.sin(2 * np.pi * 1000 * np.arange(sr * 6) / sr)).astype(np.float32)
    noise = (0.05 * rng.uniform(-1, 1, size=tone.shape)).astype(np.float32)
    x = np.stack([tone + noise, tone - noise], axis=1)

    assert abs(lufs(x, sr) - pyln.Meter(sr, block_size=0.4).integrated_loudness(x.astype(np.float64))) < 0.1
