# Copyright 2026 Feifei
# SPDX-License-Identifier: GPL-3.0-only

"""The one-click pipeline: convert -> separate -> per-stem chains -> remix -> loudness."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from .analysis import analyze
from .audio import load_audio, save_audio
from .dsp import (
    add_doubling,
    band,
    block_rms_db,
    deesser,
    duck,
    lufs,
    music_chain,
    normalize_loudness,
    peak_db,
    reverb,
    rms_db,
    soft_declip,
    vocal_chain,
)
from .presets import Params
from .separate import DEFAULT_MODEL, demucs_available, separate


@dataclass
class RenderResult:
    mix: np.ndarray
    vocal: np.ndarray
    music: np.ndarray
    lufs_before: float
    lufs_after: float
    peak_before_db: float
    peak_after_db: float
    vocal_ratio_db: float
    offset_sec: float = 0.0
    duration_sec: float = 0.0


@dataclass
class Project:
    source: Path
    sr: int
    original: np.ndarray
    vocal: np.ndarray | None = None
    music: np.ndarray | None = None
    model: str = DEFAULT_MODEL
    separated: bool = False
    stats: dict = field(default_factory=dict)

    @property
    def has_stems(self) -> bool:
        return self.separated and self.vocal is not None and self.music is not None

    def render(self, params: Params, start: float | None = None, end: float | None = None,
               preroll: float = 2.0) -> RenderResult:
        """Render the whole track, or a time window (start/end in seconds).

        A window is used for fast audition while tweaking knobs; exporting renders
        the full track. The preroll lets filters and reverb settle before the window
        so the preview does not start with a transient.
        """
        sr = self.sr
        n = self.original.shape[0]
        if start is None:
            i0, i1 = 0, n
            window_start = 0.0
        else:
            i0 = int(max(0.0, start - preroll) * sr)
            i1 = int(min(float(end) if end is not None else n / sr, n / sr) * sr)
            window_start = float(start)
            i1 = max(i1, i0 + 1)

        original = soft_declip(self.original[i0:i1], params.declip_knee)

        if self.has_stems:
            vocal = soft_declip(self.vocal[i0:i1], params.declip_knee)
            music = soft_declip(self.music[i0:i1], params.declip_knee)

            for plugin in vocal_chain(params, sr):
                vocal = plugin(vocal, sr)
            vocal = deesser_wrap(vocal, sr, params)
            vocal = reverb(vocal, sr, params.reverb_room, params.reverb_wet, params.reverb_damping)
            vocal = add_doubling(vocal, sr, params.doubling_db, params.doubling_ms)
            vocal = vocal * np.exp(params.vocal_gain_db * np.log(10) / 20.0)

            for plugin in music_chain(params, sr):
                music = plugin(music, sr)
            music = duck(music, vocal, sr, params.duck_db, params.duck_lo_hz,
                         params.duck_hi_hz, params.duck_threshold_db,
                         params.duck_attack_ms, params.duck_release_ms)
            music = music * np.exp(params.music_gain_db * np.log(10) / 20.0)
        else:
            # fallback: no separation available, polish the whole mix
            mix = original
            for plugin in vocal_chain(params, sr):
                mix = plugin(mix, sr)
            mix = deesser_wrap(mix, sr, params)
            mix = reverb(mix, sr, params.reverb_room * 0.6, params.reverb_wet * 0.5, params.reverb_damping)
            vocal, music = mix, mix

        mix = vocal + music
        lufs_before = lufs(original, sr)
        mix = normalize_loudness(mix, sr, params.target_lufs)

        return RenderResult(
            mix=mix,
            vocal=vocal,
            music=music,
            lufs_before=lufs_before,
            lufs_after=lufs(mix, sr),
            peak_before_db=peak_db(original),
            peak_after_db=peak_db(mix),
            vocal_ratio_db=rms_db(vocal) - rms_db(music),
            offset_sec=i0 / sr,
            duration_sec=(i1 - i0) / sr,
        )


def deesser_wrap(x: np.ndarray, sr: int, params: Params) -> np.ndarray:
    """Adaptive de-esser: the threshold follows the track's own vocal level, so a
    quiet mix does not get over-treated and a hot one still gets cleaned."""
    core_level = float(np.mean(block_rms_db(band(x, sr, 300.0, 3000.0), sr, 50.0)))
    threshold = float(np.clip(core_level + params.deesser_offset_db, -40.0, -12.0))

    out = deesser(x, sr, params.deesser_hz, threshold, params.deesser_amount)
    out = deesser(out, sr, params.deesser_hz2, threshold + 3.0, params.deesser_amount * 0.7)
    return out


def open_project(path: Path, model: str = DEFAULT_MODEL, device: str | None = None,
                 progress_cb=None, force_separate: bool = True) -> Project:
    """Load a file and (when possible) separate it into stems."""
    original, sr = load_audio(path, sr=44100)
    project = Project(source=Path(path), sr=sr, original=original, model=model)

    if force_separate and demucs_available():
        try:
            vocal, music = separate(
                Path(path), model=model, device=device,
                progress_cb=progress_cb, target_sr=sr,
            )
            # Demucs runs at 44.1 kHz; keep stems and original on the same clock and length
            n = min(original.shape[0], vocal.shape[0], music.shape[0])
            project.original = original[:n]
            project.vocal, project.music = vocal[:n], music[:n]
            project.separated = True
        except Exception as exc:  # keep the tool usable even without a working model
            if progress_cb:
                progress_cb(0.0, f"分离失败，退回整轨模式: {exc}")
            project.separated = False
    return project


def export(result: RenderResult, path: Path, sr: int, fmt: str = "wav") -> Path:
    return save_audio(path, result.mix, sr, fmt)
