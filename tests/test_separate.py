# Copyright 2026 Feifei
# SPDX-License-Identifier: GPL-3.0-only

from __future__ import annotations

from pathlib import Path

import pytest

from bsv import separate


@pytest.fixture(autouse=True)
def _no_env_override(monkeypatch):
    monkeypatch.delenv("BSV_DEVICE", raising=False)


def _fake_gpu(monkeypatch, free_mib: int | None):
    monkeypatch.setattr(separate, "_gpu_available", lambda: True)
    monkeypatch.setattr(separate, "_free_vram_mib", lambda: free_mib)


def test_cpu_when_there_is_no_gpu(monkeypatch):
    monkeypatch.setattr(separate, "_gpu_available", lambda: False)
    monkeypatch.setattr(separate, "_free_vram_mib", lambda: 30000)
    assert separate.plan_separation("htdemucs_ft") == ("cpu", None)


def test_gpu_probe_is_cached(monkeypatch):
    """torch.cuda.is_available() pulls in torch (~1.3 s); ask it only once."""
    monkeypatch.setattr(separate, "_GPU_AVAILABLE", None)
    calls = []

    class FakeCuda:
        @staticmethod
        def is_available():
            calls.append(1)
            return True

    class FakeTorch:
        cuda = FakeCuda

    monkeypatch.setitem(__import__("sys").modules, "torch", FakeTorch)
    assert separate._gpu_available() is True
    assert separate._gpu_available() is True
    assert len(calls) == 1


def test_cuda_with_default_segment_when_the_card_is_free(monkeypatch):
    _fake_gpu(monkeypatch, 30000)
    assert separate.plan_separation("htdemucs_ft") == ("cuda", None)


def test_a_shared_card_still_uses_cuda(monkeypatch):
    """The LLM server holds most of the card; demucs only needs ~2.2 GB."""
    _fake_gpu(monkeypatch, 4000)
    assert separate.plan_separation("htdemucs_ft") == ("cuda", None)


def test_small_segment_when_vram_is_tight(monkeypatch):
    _fake_gpu(monkeypatch, 1600)
    assert separate.plan_separation("htdemucs_ft") == ("cuda", separate.SEGMENT_TIGHT)


def test_cpu_when_vram_is_hopeless(monkeypatch):
    _fake_gpu(monkeypatch, 900)
    assert separate.plan_separation("htdemucs_ft") == ("cpu", None)


def test_single_model_needs_less_vram(monkeypatch):
    _fake_gpu(monkeypatch, 1550)
    assert separate.plan_separation("htdemucs") == ("cuda", None)
    assert separate.plan_separation("htdemucs_ft") == ("cuda", separate.SEGMENT_TIGHT)


def test_explicit_device_wins_even_without_a_gpu(monkeypatch):
    monkeypatch.setattr(separate, "_gpu_available", lambda: False)
    monkeypatch.setattr(separate, "_free_vram_mib", lambda: 0)
    assert separate.plan_separation("htdemucs_ft", "cuda") == ("cuda", None)
    assert separate.plan_separation("htdemucs_ft", "cpu") == ("cpu", None)


def test_env_override_wins(monkeypatch):
    _fake_gpu(monkeypatch, 30000)
    monkeypatch.setenv("BSV_DEVICE", "cpu")
    assert separate.plan_separation("htdemucs_ft") == ("cpu", None)


def test_fallback_ladder_tries_small_segment_then_cpu():
    assert separate._attempts("cuda", None) == [
        ("cuda", None),
        ("cuda", separate.SEGMENT_TIGHT),
        ("cpu", None),
    ]
    assert separate._attempts("cuda", separate.SEGMENT_TIGHT) == [
        ("cuda", separate.SEGMENT_TIGHT),
        ("cpu", None),
    ]
    assert separate._attempts("cpu", None) == [("cpu", None)]


def test_command_keeps_full_precision_and_honours_the_plan(tmp_path: Path):
    cmd = separate._demucs_command(
        tmp_path / "song.wav", tmp_path / "out", "htdemucs_ft", "cuda", None
    )
    assert "--float32" in cmd, "16-bit stems lose detail before the DSP chain"
    assert cmd[cmd.index("-d") + 1] == "cuda"
    assert "--segment" not in cmd
    assert cmd[-1].endswith("song.wav")

    tight = separate._demucs_command(
        tmp_path / "song.wav", tmp_path / "out", "htdemucs_ft", "cuda", 4.0
    )
    assert tight[tight.index("--segment") + 1] == "4"
    assert tight[-1].endswith("song.wav")


def test_stem_cache_is_tagged_by_format(tmp_path: Path):
    song = tmp_path / "song.wav"
    song.write_bytes(b"not really audio")
    path = separate.stem_dir(song, "htdemucs_ft")
    assert path.name == f"htdemucs_ft-{separate.CACHE_TAG}"


def test_stale_staging_dirs_are_cleaned(tmp_path: Path):
    leftover = tmp_path / "demucs-abc123"
    (leftover / "htdemucs_ft" / "song").mkdir(parents=True)
    (leftover / "htdemucs_ft" / "song" / "vocals.wav").write_bytes(b"x")
    keep = tmp_path / "htdemucs_ft-f32"
    keep.mkdir()

    separate._clean_stale_staging(tmp_path)

    assert not leftover.exists()
    assert keep.exists()


def test_broken_cache_is_ignored(tmp_path: Path, monkeypatch):
    """A half-written cache (crash mid-move) must not be mistaken for stems."""
    monkeypatch.setattr(separate, "CACHE_DIR", tmp_path)
    song = tmp_path / "song.wav"
    song.write_bytes(b"not really audio")
    broken = separate.stem_dir(song, "htdemucs_ft") / "song"
    broken.mkdir(parents=True)
    (broken / "vocals.wav").write_bytes(b"")

    assert separate.load_cached_stems(song, "htdemucs_ft") is None
