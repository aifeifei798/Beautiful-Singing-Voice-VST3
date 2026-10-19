"""Audio I/O: normalise any Suno export (.mp3/.flac/.wav/.webm/...) to 44.1 kHz stereo WAV."""

from __future__ import annotations

import hashlib
import os
import subprocess
from pathlib import Path

import numpy as np
import soundfile as sf

TARGET_SR = 44100

CACHE_DIR = Path(os.environ.get("BSV_CACHE", str(Path.home() / ".cache" / "bsv")))
AUDIO_EXTS = {
    ".wav", ".mp3", ".flac", ".ogg", ".opus", ".m4a", ".aac",
    ".webm", ".webp", ".mp4", ".aiff", ".aif", ".m4b",
}


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def ensure_wav(path: Path, sr: int = TARGET_SR) -> Path:
    """Convert any supported input into a cached stereo WAV at `sr`.

    The sample rate is always forced: Demucs outputs 44.1 kHz no matter what goes in,
    so keeping a 48 kHz original in the cache would make the stems and the remix
    disagree about the clock (that plays back like a tape speed-up).
    """
    path = Path(path)
    out = CACHE_DIR / "wav" / f"{sha256(path)}_{sr}.wav"
    if out.exists():
        return out
    out.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            "ffmpeg", "-hide_banner", "-loglevel", "error",
            "-i", str(path), "-ac", "2", "-ar", str(sr), str(out),
        ],
        check=True,
    )
    return out


def load_audio(path: Path, sr: int = TARGET_SR) -> tuple[np.ndarray, int]:
    """Return (samples float32 shaped (n, 2), sample_rate)."""
    wav = ensure_wav(path, sr)
    data, file_sr = sf.read(wav, dtype="float32", always_2d=True)
    if data.shape[1] == 1:
        data = np.repeat(data, 2, axis=1)
    return np.ascontiguousarray(data), file_sr


def save_audio(path: Path, data: np.ndarray, sr: int, fmt: str = "wav") -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = np.asarray(data, dtype="float32")
    if fmt == "wav":
        sf.write(path, data, sr, format="wav", subtype="PCM_24")
    elif fmt in {"flac", "mp3"}:
        tmp = path.with_suffix(".tmp.wav")
        sf.write(tmp, data, sr, format="wav")
        subprocess.run(
            ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
             "-i", str(tmp), str(path)],
            check=True,
        )
        tmp.unlink()
    else:
        raise ValueError(f"unsupported export format: {fmt}")
    return path
