#!/usr/bin/env python3
# Copyright 2026 Feifei
# SPDX-License-Identifier: GPL-3.0-only
"""Verify the built VST3 against the Python DSP, without a DAW.

The plugin is pushed through the same EQ settings the desktop app uses, and the
measured transfer function is compared with bsv.filters' predicted response.
That catches the mistakes that matter in a port — a wrong Q, a missing section,
a shelf applied in the wrong direction — without needing the two implementations
to be sample-identical.

    ./plugin/verify.py
    ./plugin/verify.py --host path/to/bsv-host --plugin path/to/plugin.vst3
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np
import soundfile as sf
from scipy.signal import csd, welch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from bsv.filters import (  # noqa: E402
    Filter,
    high_shelf_sos,
    highpass_sos,
    low_shelf_sos,
    peak_sos,
)
from bsv.presets import Params  # noqa: E402


# The plugin's real ranges, exactly as declared in PluginProcessor.cpp. A host
# only speaks normalised values, so the script converts here.
RANGES = {
    "预设": (0, 7),
    "低频清理": (-6, 0),
    "临场感": (0, 6),
    "空气感": (0, 4),
    "齿音抑制": (0, 1.2),
    "压缩比": (1, 3),
    "加厚": (-60, -6),
    "闪避": (0, 10),
    "输出增益": (-12, 12),
    "峰值上限": (-6, 0),
}


def normalise(name: str, value: float) -> float:
    if name == "模式":
        return value / 2.0
    lo, hi = RANGES[name]
    if hi == lo:
        return 0.0
    return (value - lo) / (hi - lo)


def run_host(host: Path, plugin: Path, source: Path, target: Path, sets: dict[str, float],
             block: int = 512, sidechain: Path | None = None) -> None:
    cmd = [str(host), str(plugin)]
    for name, value in sets.items():
        cmd += ["--set", f"{name}={normalise(name, value):.6f}"]
    cmd += ["--in", str(source), "--out", str(target), "--block", str(block)]
    if sidechain is not None:
        cmd += ["--sidechain", str(sidechain)]
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL)


def peak_frequency(x: np.ndarray, sr: int) -> float:
    """Interpolated FFT peak, accurate to a small fraction of a cent."""
    n = 1 << 18
    window = np.hanning(len(x))
    spec = np.abs(np.fft.rfft(x * window, n))
    k = int(np.argmax(spec))
    a, b, c = np.log(spec[k - 1:k + 2] + 1e-30)
    delta = 0.5 * (a - c) / (a - 2.0 * b + c)
    return (k + delta) * sr / n


def transfer_db(path_in: Path, path_out: Path, sr: int, nperseg: int = 8192):
    """Measured H(f) = Sxy / Sxx, which cancels the noise spectrum."""
    x, _ = sf.read(path_in, dtype="float64", always_2d=True)
    y, _ = sf.read(path_out, dtype="float64", always_2d=True)
    f, sxx = welch(x[:, 0], fs=sr, nperseg=nperseg)
    _, sxy = csd(x[:, 0], y[:, 0], fs=sr, nperseg=nperseg)
    return f, 20.0 * np.log10(np.maximum(np.abs(sxy / np.maximum(sxx, 1e-30)), 1e-12))


def python_vocal_response(sr: int, freqs: np.ndarray, mud: float, presence: float,
                          air: float) -> np.ndarray:
    sections = [
        highpass_sos(40.0, sr),
        peak_sos(320.0, 1.2, mud, sr),
        peak_sos(470.0, 1.0, mud * 0.65, sr),
        low_shelf_sos(180.0, 1.0, sr),
        peak_sos(2500.0, 0.8, presence, sr),
        high_shelf_sos(8000.0, air, sr),
    ]
    return Filter(sections).response_db(sr, freqs)


def python_master_response(sr: int, freqs: np.ndarray, mud: float, presence: float,
                           air: float) -> np.ndarray:
    # the plugin runs the master at 60 % depth, and without mud2/warmth
    sections = [
        highpass_sos(30.0, sr),
        peak_sos(320.0, 1.2, mud * 0.6, sr),
        peak_sos(2500.0, 0.8, presence * 0.6, sr),
        high_shelf_sos(8000.0, air * 0.6, sr),
    ]
    return Filter(sections).response_db(sr, freqs)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default=str(ROOT / "plugin/build/BSVHost_artefacts/Release/BSVHost"))
    parser.add_argument("--plugin", default=os.path.expanduser(
        "~/.vst3/Beautiful Singing Voice.vst3"))
    parser.add_argument("--sr", type=int, default=44100)
    args = parser.parse_args()

    host, plugin = Path(args.host), Path(args.plugin)
    if not host.exists():
        print(f"missing host: {host}\nbuild it with: cmake --build plugin/build")
        return 2
    if not plugin.exists():
        print(f"missing plugin: {plugin}\nbuild it with: cmake --build plugin/build")
        return 2

    sr = args.sr
    rng = np.random.default_rng(7)
    noise = (rng.standard_normal((sr * 8, 2)) * 0.03).astype(np.float32)

    failures = 0
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        source = tmp / "noise.wav"
        sf.write(source, noise, sr, subtype="FLOAT")

        for label, mode_norm, mud, presence, air, reference in [
            ("vocal", 1.0, -3.0, 3.0, 2.0, python_vocal_response),
            ("master", 0.0, -3.0, 3.0, 2.0, python_master_response),
        ]:
            target = tmp / f"{label}.wav"
            # de-ess off, ratio 1 (no gain reduction), doubling off, no trim:
            # what is left is exactly the EQ chain.
            run_host(host, plugin, source, target, {
                "模式": mode_norm,
                "低频清理": mud,
                "临场感": presence,
                "空气感": air,
                "齿音抑制": 0.0,
                "压缩比": 1.0,
                "加厚": -60.0,
                "输出增益": 0.0,
                "峰值上限": 0.0,
            })

            freqs, measured = transfer_db(source, target, sr)
            expected = reference(sr, freqs, mud, presence, air)
            band = (freqs >= 60) & (freqs <= 16000)
            error = np.abs(measured[band] - expected[band])
            worst = float(error.max())
            where = float(freqs[band][int(error.argmax())])
            ok = worst < 0.35
            print(f"{label:7s} EQ error: max {worst:.3f} dB at {where:.0f} Hz  "
                  f"[{'ok' if ok else 'FAIL'}]")
            failures += 0 if ok else 1

            # the chain must not shift the noise floor or add DC
            x, _ = sf.read(source, dtype="float64", always_2d=True)
            y, _ = sf.read(target, dtype="float64", always_2d=True)
            if not np.isfinite(y).all():
                print(f"{label:7s} output has NaN/Inf  [FAIL]")
                failures += 1
            if abs(float(np.mean(y))) > 1e-3:
                print(f"{label:7s} output has DC offset {np.mean(y):.4f}  [FAIL]")
                failures += 1

            del x

        # --- limiter: a hot sine must come out under the ceiling ---------------
        t = np.arange(sr * 2) / sr
        hot = (np.sin(2 * np.pi * 220 * t) * 1.4).astype(np.float32)
        hot = np.stack([hot, hot], axis=1)
        hot_path = tmp / "hot.wav"
        sf.write(hot_path, hot, sr, subtype="FLOAT")
        lim_path = tmp / "lim.wav"
        run_host(host, plugin, hot_path, lim_path, {"模式": 0.0, "峰值上限": -1.0})
        out, _ = sf.read(lim_path, dtype="float64", always_2d=True)
        peak = 20.0 * np.log10(max(float(np.max(np.abs(out))), 1e-12))
        ok = peak <= -0.9
        print(f"limiter peak {peak:.2f} dBFS at a -1 dB ceiling  [{'ok' if ok else 'FAIL'}]")
        failures += 0 if ok else 1

        # --- sidechain duck: music mode must dip while the vocal is active ----
        # The music is a 1 kHz tone, not noise: a first-order band filter leaks
        # enough out-of-band energy that a noise measurement can never see a
        # deep duck, and the test would pass on a broken duck.
        seconds = 3.0
        t2 = np.arange(int(sr * seconds)) / sr
        tone_music = (np.sin(2 * np.pi * 1000 * t2) * 0.05).astype(np.float32)
        music = np.stack([tone_music, tone_music], axis=1)
        music_path = tmp / "music.wav"
        sf.write(music_path, music, sr, subtype="FLOAT")

        vocal_sc = np.zeros_like(music)
        active = (t2 >= 1.0) & (t2 < 2.0)
        tone_sc = (np.sin(2 * np.pi * 900 * t2) * 0.4)[active]
        vocal_sc[active, 0] = tone_sc
        vocal_sc[active, 1] = tone_sc
        sc_path = tmp / "sc.wav"
        sf.write(sc_path, vocal_sc, sr, subtype="FLOAT")

        from bsv.filters import band_filter

        def band_rms(sig, lo, hi):
            band = band_filter(lo, hi, sr)(sig.astype(np.float32), sr)
            return float(np.sqrt(np.mean(band[:, 0].astype(np.float64) ** 2)))

        settings = {"模式": 2.0, "闪避": 8.0, "低频清理": 0.0, "临场感": 0.0,
                    "空气感": 0.0, "峰值上限": 0.0}

        ducked_path = tmp / "ducked.wav"
        run_host(host, plugin, music_path, ducked_path, settings, sidechain=sc_path)
        plain_path = tmp / "plain.wav"
        run_host(host, plugin, music_path, plain_path, settings)

        window = slice(int(1.2 * sr), int(1.8 * sr))
        y_duck, _ = sf.read(ducked_path, dtype="float64", always_2d=True)
        y_plain, _ = sf.read(plain_path, dtype="float64", always_2d=True)
        during_duck = band_rms(y_duck[window], 250, 4000)
        during_plain = band_rms(y_plain[window], 250, 4000)
        drop = 20.0 * np.log10(max(during_duck, 1e-9) / max(during_plain, 1e-9))
        ok = drop <= -6.0
        print(f"sidechain duck {drop:+.1f} dB in 250-4k while the vocal plays  "
              f"[{'ok' if ok else 'FAIL'}]")
        failures += 0 if ok else 1

        # --- and without a sidechain the same mode must not duck ---------------
        after_plain = band_rms(y_plain[slice(int(2.3 * sr), int(2.9 * sr))], 250, 4000)
        drift = 20.0 * np.log10(max(during_plain, 1e-9) / max(after_plain, 1e-9))
        ok = abs(drift) < 1.0
        print(f"no sidechain, no duck: {drift:+.1f} dB  [{'ok' if ok else 'FAIL'}]")
        failures += 0 if ok else 1

        # --- the doubling must not move the fundamental ------------------------
        tone = (np.sin(2 * np.pi * 440 * t) * 0.1).astype(np.float32)
        tone = np.stack([tone, tone], axis=1)
        tone_path = tmp / "tone.wav"
        sf.write(tone_path, tone, sr, subtype="FLOAT")
        dbl_path = tmp / "dbl.wav"
        run_host(host, plugin, tone_path, dbl_path, {
            "模式": 1.0, "加厚": -14.0, "齿音抑制": 0.0, "压缩比": 1.0,
            "低频清理": 0.0, "临场感": 0.0, "空气感": 0.0, "峰值上限": 0.0,
        })
        a, _ = sf.read(tone_path, dtype="float64", always_2d=True)
        b, _ = sf.read(dbl_path, dtype="float64", always_2d=True)
        fa = peak_frequency(a[8192:8192 + 32768, 0], sr)
        fb = peak_frequency(b[8192:8192 + 32768, 0], sr)
        drift_cents = 1200.0 * np.log2(fb / fa)
        ok = abs(drift_cents) < 2.0
        print(f"doubling pitch drift {drift_cents:+.1f} cents  [{'ok' if ok else 'FAIL'}]")
        failures += 0 if ok else 1

    print("PASS" if failures == 0 else f"{failures} check(s) failed")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
