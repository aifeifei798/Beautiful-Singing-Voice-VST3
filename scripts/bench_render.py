# Copyright 2026 Feifei
# SPDX-License-Identifier: GPL-3.0-only

"""Render-time benchmark: how long a one-click fix takes, stage by stage.

    .venv/bin/python scripts/bench_render.py path/to/song.flac

Demucs separation is not timed here (it is cached per file and dominates the
first run); this measures the DSP pass the sliders re-run on every change.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

from bsv.pipeline import open_project
from bsv.presets import PRESETS


def main() -> None:
    src = Path(sys.argv[1] if len(sys.argv) > 1 else "demo/demo_30.wav")
    preset_name = sys.argv[2] if len(sys.argv) > 2 else "中性 (只修问题)"
    params = PRESETS[preset_name]

    t = time.time()
    project = open_project(src)
    print(f"load + separation      {time.time() - t:6.2f}s  stems={'yes' if project.has_stems else 'no'}")

    t = time.time()
    result = project.render(params)
    print(f"render ({src.name})    {time.time() - t:6.2f}s")
    print(f"  loudness {result.lufs_before:.1f} -> {result.lufs_after:.1f} LUFS")
    print(f"  peak     {result.peak_before_db:.1f} -> {result.peak_after_db:.1f} dBFS")


if __name__ == "__main__":
    main()
