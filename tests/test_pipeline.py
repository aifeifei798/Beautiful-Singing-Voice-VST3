# Copyright 2026 Feifei
# SPDX-License-Identifier: GPL-3.0-only

from __future__ import annotations

import numpy as np

from bsv.pipeline import Project, open_project
from bsv.presets import PRESETS

SR = 44100


def _synthetic_song(seconds: float = 6.0) -> np.ndarray:
    n = int(SR * seconds)
    t = np.arange(n) / SR
    # "vocal": 400 Hz fundamental with vibrato + a sibilance burst at 2.5 s
    vib = 1.0 + 0.02 * np.sin(2 * np.pi * 5.0 * t)
    vocal = (
        0.25 * np.sin(2 * np.pi * 400 * vib * t)
        + 0.12 * np.sin(2 * np.pi * 1200 * t)
        + 0.05 * np.sin(2 * np.pi * 6800 * t) * (t > 2.0)
    )
    # "music": bass + broadband noise
    music = 0.3 * np.sin(2 * np.pi * 80 * t) + 0.15 * np.random.randn(n)
    mix = np.stack([vocal + music, vocal * 0.9 + music], axis=1)
    # hard clip like a hot Suno export
    mix = np.clip(mix, -1.0, 1.0)
    return mix.astype(np.float32)


def test_render_is_stable_and_loudness_matched():
    mix = _synthetic_song()
    project = Project(source="synthetic.wav", sr=SR, original=mix)
    for name, params in PRESETS.items():
        result = project.render(params)
        assert result.mix.shape == mix.shape
        assert np.all(np.isfinite(result.mix))
        assert abs(result.lufs_after - params.target_lufs) < 1.5
        assert result.peak_after_db <= -0.5


def test_open_project_without_demucs_still_produces_output(tmp_path):
    from bsv.audio import save_audio

    path = tmp_path / "song.wav"
    save_audio(path, _synthetic_song(4.0), SR, "wav")
    project = open_project(path, force_separate=False)
    result = project.render(PRESETS["中文流行"])
    assert np.all(np.isfinite(result.mix))
    assert not project.has_stems


def test_48k_input_is_resampled_to_the_project_clock(tmp_path):
    """A 48 kHz file must not end up remixed against 44.1 kHz stems — that is the
    "the fixed version plays faster / sounds detuned" bug."""
    from bsv.audio import load_audio, save_audio

    sr = 48000
    n = int(3.0 * sr)
    t = np.arange(n) / sr
    data = np.stack([0.2 * np.sin(2 * np.pi * 440 * t)] * 2, axis=1).astype(np.float32)
    path = tmp_path / "song48.wav"
    save_audio(path, data, sr, "wav")

    project = open_project(path, force_separate=False)
    assert project.sr == 44100
    assert abs(project.original.shape[0] - int(3.0 * 44100)) <= 2


def test_stems_are_resampled_when_demucs_rate_differs():
    from bsv.separate import _match_rate

    v = np.ones((44100, 2), dtype=np.float32)
    o = np.ones((44100, 2), dtype=np.float32)
    v48, o48 = _match_rate(v, o, 44100, 48000)
    assert abs(v48.shape[0] - 48000) <= 1
    v_same, _ = _match_rate(v, o, 44100, 44100)
    assert v_same.shape[0] == 44100


def test_demucs_stem_names_are_resolved(tmp_path):
    """--two-stems=vocals writes vocals.wav + no_vocals.wav, not other.wav."""
    from bsv.separate import _stem_paths

    run = tmp_path / "htdemucs_ft" / "song"
    run.mkdir(parents=True)
    (run / "vocals.wav").write_bytes(b"x")
    (run / "no_vocals.wav").write_bytes(b"y")
    vocals, other = _stem_paths(tmp_path / "htdemucs_ft", "song")
    assert vocals.name == "vocals.wav"
    assert other.name == "no_vocals.wav"
