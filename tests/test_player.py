from __future__ import annotations

import numpy as np

from bsv.ui import player as player_module
from bsv.ui.player import Player


def _player() -> Player:
    """A Player with the device layer stubbed out — the callback is driven
    manually so the test works on a machine with no sound card."""
    player_module.sd = None
    p = Player(44100)
    p.available = True
    return p


def test_mono_is_promoted_to_stereo():
    p = _player()
    p.set_audio(np.ones(100, dtype=np.float32))
    assert p.data.shape == (100, 2)


def test_callback_emits_the_next_frames():
    p = _player()
    data = np.arange(2000 * 2, dtype=np.float32).reshape(2000, 2)
    p.set_audio(data)
    p.play(0.0)
    out = np.zeros((512, 2), dtype=np.float32)
    p._callback(out, 512)
    assert np.array_equal(out, data[:512])
    assert p.pos == 512


def test_stop_silences_the_stream():
    p = _player()
    p.set_audio(np.ones((1000, 2), dtype=np.float32))
    p.play(0.0)
    p.stop()
    out = np.full((100, 2), 1.0, dtype=np.float32)
    p._callback(out, 100)
    assert out.max() == 0.0


def test_loop_wraps_at_the_end_of_the_region():
    p = _player()
    data = np.arange(1000 * 2, dtype=np.float32).reshape(1000, 2)
    p.set_audio(data)
    p.play(0.0)
    p.pos = 900
    p.set_loop(0.0, None)
    out = np.zeros((300, 2), dtype=np.float32)
    p._callback(out, 300)
    assert np.array_equal(out[:100], data[900:1000])
    assert np.array_equal(out[100:300], data[0:200])  # wrapped back to the start
    assert p.pos == 200


def test_out_of_range_position_is_clamped():
    p = _player()
    p.set_audio(np.ones((200, 2), dtype=np.float32))
    p.play(5.0)  # beyond the end of the array
    out = np.zeros((50, 2), dtype=np.float32)
    p._callback(out, 50)
    assert out.sum() == 100.0
