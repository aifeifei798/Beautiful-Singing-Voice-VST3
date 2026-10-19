# Copyright 2026 Feifei
# SPDX-License-Identifier: Apache-2.0

"""Small seekable playback wrapper around sounddevice, for A/B audition.

The audio handed to the player is always the *preview region* only, so every
index here is relative to that slice. Looping, seeking and A/B switching are all
safe no matter how the array changes underneath.
"""

from __future__ import annotations

import threading

import numpy as np

try:
    import sounddevice as sd
except Exception:  # pragma: no cover - only when no audio device exists
    sd = None


class Player:
    def __init__(self, sample_rate: int = 44100):
        self.sr = int(sample_rate)
        self.data: np.ndarray | None = None
        self.pos = 0
        self.loop_start = 0
        self.loop_end: int | None = None
        self.playing = False
        self.lock = threading.Lock()
        self.stream = None
        self.available = False
        self.error = ""
        self._open_stream(self.sr)

    # ------------------------------------------------------------ stream ----
    def _open_stream(self, sample_rate: int) -> bool:
        """(Re)open an output stream. sounddevice streams are inactive until
        start() is called — without it the callback never fires and nothing
        plays, which is why the audition buttons used to be dead."""
        if sd is None:
            self.error = "sounddevice 未安装，无法试听"
            return False
        if self.stream is not None:
            try:
                self.stream.stop()
                self.stream.close()
            except Exception:
                pass
            self.stream = None
        try:
            self.stream = sd.OutputStream(
                samplerate=sample_rate,
                blocksize=2048,
                channels=2,
                dtype="float32",
                callback=self._callback,
            )
            self.stream.start()
            self.sr = int(sample_rate)
            self.available = True
            self.error = ""
            return True
        except Exception as exc:
            self.available = False
            self.error = f"音频设备不可用：{exc}"
            return False

    def set_samplerate(self, sample_rate: int) -> None:
        if int(sample_rate) != self.sr or self.stream is None:
            self._open_stream(sample_rate)

    # ------------------------------------------------------------- content ----
    def set_audio(self, data: np.ndarray | None) -> None:
        if data is None:
            with self.lock:
                self.data = None
            return
        data = np.asarray(data, dtype=np.float32)
        if data.ndim == 1:
            data = np.repeat(data[:, None], 2, axis=1)
        if data.shape[1] == 1:
            data = np.repeat(data, 2, axis=1)
        with self.lock:
            self.data = data
            self.pos = min(self.pos, max(0, len(data) - 1))

    def set_loop(self, start_sec: float, end_sec: float | None) -> None:
        with self.lock:
            self.loop_start = max(0, int(start_sec * self.sr))
            self.loop_end = int(end_sec * self.sr) if end_sec is not None else None

    def play(self, start_sec: float = 0.0) -> bool:
        if not self.available:
            return False
        with self.lock:
            if self.data is None or len(self.data) == 0:
                return False
            self.pos = int(max(0.0, start_sec) * self.sr)
            self.playing = True
        return True

    def stop(self) -> None:
        with self.lock:
            self.playing = False

    def toggle(self) -> bool:
        return self.play() if not self.playing else (self.stop(), False)[1]

    def position_sec(self) -> float:
        with self.lock:
            return self.pos / self.sr

    def duration_sec(self) -> float:
        return len(self.data) / self.sr if self.data is not None else 0.0

    def _callback(self, out, frames, *_rest):
        """sounddevice passes (buffer, frames, time, status) — accept them all."""
        with self.lock:
            data = self.data
            if not self.playing or data is None or len(data) == 0:
                out[:] = 0.0
                return

            n = len(data)
            start = min(max(self.loop_start, 0), n - 1)
            end = self.loop_end if self.loop_end is not None else n
            end = min(end, n)
            if end <= start:
                start, end = 0, n

            cursor = self.pos
            if not start <= cursor < end:
                cursor = start

            filled = 0
            while filled < frames:
                take = min(frames - filled, end - cursor)
                out[filled:filled + take] = data[cursor:cursor + take]
                cursor += take
                filled += take
                if cursor >= end:
                    cursor = start

            self.pos = cursor

    def close(self) -> None:
        self.stop()
        if self.stream is not None:
            try:
                self.stream.stop()
                self.stream.close()
            except Exception:
                pass
            self.stream = None
            self.available = False
