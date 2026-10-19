from __future__ import annotations

import numpy as np

from bsv.dsp import add_doubling, band, deesser, duck, reverb, rms_db, soft_declip
from bsv.presets import PRESETS

SR = 44100


def _stereo(x: np.ndarray) -> np.ndarray:
    return np.stack([x, x], axis=1).astype(np.float32)


def test_soft_declip_rounds_flat_tops():
    clipped = np.clip(np.sin(np.linspace(0, 200 * np.pi, 20000)), -1.0, 1.0)
    before = _stereo(clipped)
    out = soft_declip(before, knee=0.94)
    assert np.max(np.abs(out)) < 1.0
    assert rms_db(out) < rms_db(before)  # flat tops carried excess energy


def test_deesser_attenuates_a_sibilance_burst_only():
    t = np.arange(SR * 4) / SR
    burst = np.sin(2 * np.pi * 6800 * t) * (t > 2.0)
    before = _stereo(0.3 * np.sin(2 * np.pi * 500 * t) + 0.25 * burst)
    targeted = band(before, SR, 6200, 8000)
    after = deesser(before, SR, center_hz=6800, threshold_db=-24.0, amount=1.0)

    region = slice(int(3 * SR), int(4 * SR))
    band_before = rms_db(targeted[region])
    band_after = rms_db((after - before + targeted)[region])  # what the de-esser left in the band
    assert band_after < band_before - 3.0
    assert band_after <= -24.0 + 1.5  # clamped down to the threshold

    core_before = rms_db(band(before, SR, 300, 900))
    core_after = rms_db(band(after, SR, 300, 900))
    assert abs(core_after - core_before) < 1.0


def test_duck_loweres_accompaniment_only_while_vocal_is_active():
    t = np.arange(SR * 6) / SR
    vocal = _stereo(np.where(t < 3.0, 0.5 * np.sin(2 * np.pi * 500 * t), 0.001))
    music = _stereo(0.4 * np.sin(2 * np.pi * 1200 * t))
    out = duck(
        music, vocal, SR,
        duck_db=6.0, lo_hz=250.0, hi_hz=4000.0,
        threshold_db=-30.0, attack_ms=30.0, release_ms=200.0,
    )

    mid_before = band(music, SR, 250.0, 4000.0)
    mid_after = band(out, SR, 250.0, 4000.0)

    active = slice(int(2.0 * SR), int(3.0 * SR))
    idle = slice(int(4.5 * SR), int(5.5 * SR))

    assert rms_db(mid_after[active]) < rms_db(mid_before[active]) - 4.0
    assert abs(rms_db(mid_after[idle]) - rms_db(mid_before[idle])) < 1.0


def test_duck_depth_matches_the_requested_db():
    """`duck_db` is dB, not a raw exponent: 4 dB must be ~4 dB, not ~35 dB."""
    t = np.arange(SR * 4) / SR
    vocal = _stereo(0.5 * np.sin(2 * np.pi * 500 * t))
    music = _stereo(0.4 * np.sin(2 * np.pi * 1200 * t))

    steady = slice(int(3.0 * SR), int(4.0 * SR))
    for depth in (3.0, 4.0, 6.0):
        out = duck(music, vocal, SR, duck_db=depth, threshold_db=-30.0,
                   attack_ms=30.0, release_ms=200.0)
        drop = rms_db(out[steady]) - rms_db(music[steady])
        assert abs(drop + depth) < 1.0, (depth, drop)


def test_reverb_is_off_by_default():
    """Presets keep the space the mix already has — reverb must be dialled in."""
    x = _stereo(np.sin(2 * np.pi * 500 * np.arange(SR * 2) / SR))
    assert np.array_equal(reverb(x, SR, 0.45, 0.0, 0.4), x)
    for params in PRESETS.values():
        assert params.reverb_wet == 0.0, params


def test_doubling_is_on_by_default_but_bounded():
    """Every preset thickens the lead a little; none of it is a slap echo."""
    for name, params in PRESETS.items():
        assert -20.0 <= params.doubling_db <= -8.0, (name, params.doubling_db)
        assert 10.0 <= params.doubling_ms <= 60.0, (name, params.doubling_ms)


def test_doubling_off_is_a_no_op():
    x = _stereo(np.sin(2 * np.pi * 500 * np.arange(SR * 2) / SR))
    assert np.array_equal(add_doubling(x, SR, -60.0, 25.0), x)


def test_doubling_adds_body_without_changing_pitch_or_length():
    t = np.arange(SR * 6) / SR
    x = _stereo(0.4 * np.sin(2 * np.pi * 260 * t) + 0.2 * np.sin(2 * np.pi * 520 * t))
    y = add_doubling(x, SR, -12.0, 25.0)

    assert y.shape == x.shape
    assert y.dtype == x.dtype

    body = rms_db(y) - rms_db(x)
    assert 0.2 < body < 2.0, body  # thickening, not a volume bump

    def peak_freq(sig: np.ndarray) -> float:
        window = sig[:, 0] * np.hanning(len(sig))
        spectrum = np.abs(np.fft.rfft(window))
        freqs = np.fft.rfftfreq(len(window), 1.0 / SR)
        return float(freqs[int(np.argmax(spectrum))])

    assert abs(peak_freq(y) - 260.0) < 1.0


def test_doubling_does_not_leave_a_tail():
    """A detuned copy runs out of source before the signal ends; it must fade out."""
    t = np.arange(SR * 3) / SR
    x = _stereo(0.3 * np.sin(2 * np.pi * 300 * t))
    y = add_doubling(x, SR, -9.0, 18.0)

    assert np.all(np.isfinite(y))
    # by the final sample the doubles have faded out, leaving just the dry lead
    assert abs(float(y[-1, 0] - x[-1, 0])) < 1e-3
    # and the last jump is the tone's own slope, not a click
    slope = abs(float(x[-1, 0] - x[-2, 0]))
    assert abs(float(y[-1, 0] - y[-2, 0])) < 1.5 * slope


def test_doubling_is_chunk_exact():
    """Blocked processing must equal one-pass processing (no seams, no drift)."""
    t = np.arange(SR * 5) / SR
    rng = np.random.default_rng(11)
    x = _stereo(0.35 * np.sin(2 * np.pi * 180 * t) + 0.1 * rng.uniform(-1, 1, len(t)))
    whole = add_doubling(x, SR, -12.0, 25.0, block=len(x) + 1)
    blocked = add_doubling(x, SR, -12.0, 25.0, block=4096)
    assert np.array_equal(whole, blocked)


def test_space_can_still_be_dialled_in():
    x = _stereo(np.sin(2 * np.pi * 500 * np.arange(SR * 2) / SR))
    with_reverb = reverb(x, SR, 0.45, 0.15, 0.4)
    assert not np.array_equal(with_reverb, x)
    assert rms_db(with_reverb) > rms_db(x) - 6.0
