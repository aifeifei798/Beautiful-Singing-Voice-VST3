# Copyright 2026 Feifei
# SPDX-License-Identifier: GPL-3.0-only

"""Fast EQ: second-order sections built with scipy instead of pedalboard plugins.

pedalboard's IIR plugins walk the signal sample by sample in its own wrapper.
On a 230 s stereo track a single PeakFilter costs ~20 s, and a vocal chain is
seven of them. scipy.signal.sosfilt is the same biquad maths, C-implemented,
and roughly 30x faster. The coefficients come from the standard RBJ Audio EQ
Cookbook construction (bilinear transform with frequency pre-warping).
"""

from __future__ import annotations

import numpy as np
from scipy.signal import butter, sosfilt

def _linear_gain(gain_db: float) -> float:
    return 10.0 ** (gain_db / 20.0)


def _prewarped(cf_hz: float, sr: int) -> float:
    """tan(pi f / sr): the bilinear-transform warping for a corner at cf_hz."""
    return float(np.tan(np.pi * float(cf_hz) / sr))


def _normalise(sos: np.ndarray) -> np.ndarray:
    return sos / sos[:, 3]


def highpass_sos(cf_hz: float, sr: int, order: int = 1) -> np.ndarray:
    """First-order Butterworth by default — pedalboard's HighpassFilter is first
    order, and matching it keeps the result identical to what was auditioned."""
    if order == 1:
        k = _prewarped(cf_hz, sr)
        return np.array([[1.0 / (1.0 + k), -1.0 / (1.0 + k), 0.0, 1.0, (k - 1.0) / (1.0 + k), 0.0]])
    nyquist = sr / 2.0
    w = min(max(cf_hz, 1.0) / nyquist, 0.999)
    return butter(order, w, btype="highpass", output="sos")


def lowpass_sos(cf_hz: float, sr: int, order: int = 1) -> np.ndarray:
    if order == 1:
        k = _prewarped(cf_hz, sr)
        return np.array([[k / (1.0 + k), k / (1.0 + k), 0.0, 1.0, (k - 1.0) / (1.0 + k), 0.0]])
    nyquist = sr / 2.0
    w = min(max(cf_hz, 1.0) / nyquist, 0.999)
    return butter(order, w, btype="lowpass", output="sos")


def peak_sos(cf_hz: float, q: float, gain_db: float, sr: int) -> np.ndarray:
    """Peaking EQ: gain gain_db at cf_hz, Q controls the bandwidth."""
    if gain_db == 0.0:
        return np.array([[1.0, 0.0, 0.0, 1.0, 0.0, 0.0]])
    k = _prewarped(cf_hz, sr)
    zeta = 1.0 / (2.0 * max(q, 0.1))
    a = _linear_gain(gain_db)

    b = [1.0 + 2.0 * zeta * k * a + k * k, 2.0 * (k * k - 1.0), 1.0 - 2.0 * zeta * k * a + k * k]
    d = [1.0 + 2.0 * zeta * k + k * k, 2.0 * (k * k - 1.0), 1.0 - 2.0 * zeta * k + k * k]
    return _normalise(np.array([[b[0], b[1], b[2], d[0], d[1], d[2]]], dtype=np.float64))


def _shelf_section(a: float, k: float, low: bool) -> list[float]:
    """First-order shelving section with gain `a` on the boosted side.

    H(z) = [(1 + a k) + (a k - 1) z^-1] / [(1 + k) + (k - 1) z^-1]  (low shelf)
    H(z) = [(a + k) + (k - a) z^-1] / [(1 + k) + (k - 1) z^-1]      (high shelf)
    """
    if low:  # boost below the corner, unity above
        b0, b1 = (1.0 + a * k) / (1.0 + k), (a * k - 1.0) / (1.0 + k)
    else:  # boost above the corner, unity below
        b0, b1 = (a + k) / (1.0 + k), (k - a) / (1.0 + k)
    return [b0, b1, 0.0, 1.0, (k - 1.0) / (1.0 + k), 0.0]


def low_shelf_sos(cf_hz: float, gain_db: float, sr: int) -> np.ndarray:
    if gain_db == 0.0:
        return np.array([[1.0, 0.0, 0.0, 1.0, 0.0, 0.0]])
    a = _linear_gain(gain_db) ** 0.5  # two cascaded sections give the full gain
    k = _prewarped(cf_hz, sr)
    return np.array([_shelf_section(a, k, True), _shelf_section(a, k, True)])


def high_shelf_sos(cf_hz: float, gain_db: float, sr: int) -> np.ndarray:
    if gain_db == 0.0:
        return np.array([[1.0, 0.0, 0.0, 1.0, 0.0, 0.0]])
    a = _linear_gain(gain_db) ** 0.5
    k = _prewarped(cf_hz, sr)
    return np.array([_shelf_section(a, k, False), _shelf_section(a, k, False)])


class Filter:
    """A chain of second-order sections, callable like a pedalboard plugin.

    The sections are packed into one SOS matrix so scipy runs the whole EQ in a
    single pass over the signal instead of allocating a new array per stage.
    """

    def __init__(self, sections: list[np.ndarray]):
        parts = [np.asarray(s, dtype=np.float64) for s in sections if s is not None]
        if not parts:
            parts = [np.array([[1.0, 0.0, 0.0, 1.0, 0.0, 0.0]])]
        self.sections = np.vstack(parts)

    def __call__(self, x: np.ndarray, sr: int) -> np.ndarray:
        return np.asarray(sosfilt(self.sections, x, axis=0), dtype=np.float32)

    def response_db(self, sr: int, freqs: np.ndarray) -> np.ndarray:
        """Magnitude response in dB at `freqs` — handy for tests and plotting."""
        return 20.0 * np.log10(np.abs(self.transfer_function(sr, freqs)) + 1e-12)

    def transfer_function(self, sr: int, freqs: np.ndarray) -> np.ndarray:
        """Complex response (magnitude and phase) — the exact IIR evaluation."""
        z = np.exp(-2j * np.pi * freqs / sr)
        total = np.ones_like(freqs, dtype=np.complex128)
        for b0, b1, b2, a0, a1, a2 in self.sections:
            total *= (b0 + b1 * z + b2 * z * z) / (a0 + a1 * z + a2 * z * z)
        return total


def band_filter(lo_hz: float, hi_hz: float, sr: int) -> Filter:
    return Filter([highpass_sos(lo_hz, sr), lowpass_sos(hi_hz, sr)])


# --------------------------------------------------------------------------
# ITU-R BS.1770 K-weighting (the filter LUFS meters use)
# --------------------------------------------------------------------------
def _rbj_section(filter_type: str, gain_db: float, q: float, cf_hz: float, sr: int) -> np.ndarray:
    """RBJ cookbook biquad, matching the coefficients pyloudnorm uses."""
    a = 10.0 ** (gain_db / 40.0)
    w0 = 2.0 * np.pi * (cf_hz / sr)
    alpha = np.sin(w0) / (2.0 * q)
    cos_w = np.cos(w0)

    if filter_type == "high_shelf":
        b = [
            a * ((a + 1) + (a - 1) * cos_w + 2 * np.sqrt(a) * alpha),
            -2 * a * ((a - 1) + (a + 1) * cos_w),
            a * ((a + 1) + (a - 1) * cos_w - 2 * np.sqrt(a) * alpha),
        ]
        d = [
            (a + 1) - (a - 1) * cos_w + 2 * np.sqrt(a) * alpha,
            2 * ((a - 1) - (a + 1) * cos_w),
            (a + 1) - (a - 1) * cos_w - 2 * np.sqrt(a) * alpha,
        ]
    elif filter_type == "low_shelf":
        b = [
            a * ((a + 1) - (a - 1) * cos_w + 2 * np.sqrt(a) * alpha),
            2 * a * ((a - 1) - (a + 1) * cos_w),
            a * ((a + 1) - (a - 1) * cos_w - 2 * np.sqrt(a) * alpha),
        ]
        d = [
            (a + 1) + (a - 1) * cos_w + 2 * np.sqrt(a) * alpha,
            -2 * ((a - 1) + (a + 1) * cos_w),
            (a + 1) + (a - 1) * cos_w - 2 * np.sqrt(a) * alpha,
        ]
    elif filter_type == "high_pass":
        b = [(1 + cos_w) / 2, -(1 + cos_w), (1 + cos_w) / 2]
        d = [1 + alpha, -2 * cos_w, 1 - alpha]
    elif filter_type == "low_pass":
        b = [(1 - cos_w) / 2, 1 - cos_w, (1 - cos_w) / 2]
        d = [1 + alpha, -2 * cos_w, 1 - alpha]
    else:  # peaking
        b = [1 + alpha * a, -2 * cos_w, 1 - alpha * a]
        d = [1 + alpha / a, -2 * cos_w, 1 - alpha / a]

    return _normalise(np.array([b + d], dtype=np.float64))


def k_weighting_sos(sr: int) -> list[np.ndarray]:
    """K-weighting: +4 dB high shelf at 1500 Hz then a 38 Hz highpass."""
    return [
        _rbj_section("high_shelf", 4.0, 1 / np.sqrt(2), 1500.0, sr),
        _rbj_section("high_pass", 0.0, 0.5, 38.0, sr),
    ]
