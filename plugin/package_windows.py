# Copyright 2026 Feifei
# SPDX-License-Identifier: GPL-3.0-only

"""Zip a built VST3 bundle for distribution.

Used by the Windows CI job. PowerShell's Compress-Archive writes entry names
in the OEM code page, which mangles the Chinese install note on any system
that is not a Chinese one; Python's zipfile always writes UTF-8 and sets the
matching flag, so the name survives everywhere.

    python plugin/package_windows.py <bundle.vst3> <out.zip> [extra file] [name in archive]
"""

from __future__ import annotations

import hashlib
import pathlib
import sys
import zipfile


def package(bundle: pathlib.Path, out: pathlib.Path, extra: pathlib.Path | None = None,
            extra_name: str | None = None) -> str:
    if not bundle.is_dir():
        raise SystemExit(f"not a directory: {bundle}")

    out.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        # the bundle keeps its own folder in the archive, so unzipping gives
        # "Beautiful Singing Voice.vst3/Contents/..." instead of a bare Contents
        for path in sorted(bundle.rglob("*")):
            if path.is_file():
                zf.write(path, path.relative_to(bundle.parent))
        if extra is not None:
            zf.write(extra, extra_name or extra.name)

    digest = hashlib.sha256(out.read_bytes()).hexdigest()
    out.with_name(out.name + ".sha256").write_text(f"{digest}  {out.name}\n", encoding="ascii")
    return digest


def main() -> int:
    # Windows consoles default to a legacy code page, which cannot print the
    # Chinese file name.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    if len(sys.argv) < 3:
        print(__doc__)
        return 2
    bundle = pathlib.Path(sys.argv[1])
    out = pathlib.Path(sys.argv[2])
    extra = pathlib.Path(sys.argv[3]) if len(sys.argv) > 3 else None
    extra_name = sys.argv[4] if len(sys.argv) > 4 else None
    digest = package(bundle, out, extra, extra_name)
    print(f"{digest}  {out.name}")
    with zipfile.ZipFile(out) as zf:
        for info in zf.infolist():
            print(f"  {info.filename}  ({info.file_size} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
