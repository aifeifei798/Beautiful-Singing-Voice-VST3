# Copyright 2026 Feifei
# SPDX-License-Identifier: GPL-3.0-only

from __future__ import annotations

import numpy as np

from bsv.analysis import analyze, rms_db

SR = 44100


def _stems(seconds: float = 4.0):
    n = int(SR * seconds)
    t = np.arange(n) / SR
    # vocal: silent intro, then a 400 Hz "singing" burst, silent outro
    singing = (t > 2.0) & (t < 3.0)
    vocal = 0.25 * np.sin(2 * np.pi * 400 * t) * singing
    # sibilance spike inside the burst
    vocal += 0.25 * np.sin(2 * np.pi * 7000 * t) * ((t > 2.4) & (t < 2.6))
    # music: continuous bass + noise, loud everywhere
    music = 0.3 * np.sin(2 * np.pi * 120 * t) + 0.1 * np.random.randn(n)
    return np.stack([vocal, vocal], axis=1).astype(np.float32), music.astype(np.float32)


def test_levels_use_true_rms_not_a_mean_of_dbs():
    vocal, music = _stems()
    stats = analyze(vocal, music, SR)
    assert abs(stats["vocal_level_db"] - rms_db(vocal)) < 0.01
    assert abs(stats["vocal_music_ratio_db"] - (rms_db(vocal) - rms_db(music))) < 0.01
    # a mean of per-block dB values would report the vocal ~40 dB lower here
    assert stats["vocal_level_db"] > -30.0


def test_overlap_hotspots_only_where_the_vocal_is_present():
    vocal, music = _stems()
    stats = analyze(vocal, music, SR)
    for region in stats["regions"]["overlap"]:
        assert 2.0 <= region["time"] <= 3.2, region


def test_sibilance_hotspot_is_found():
    vocal, music = _stems()
    stats = analyze(vocal, music, SR)
    # the 7 kHz burst is only present for 200 ms, so it reads a few dB below the core
    assert stats["sibilance_max_db"] > -6.0
    times = [r["time"] for r in stats["regions"]["sibilance"]]
    assert any(2.3 <= t <= 2.7 for t in times)
