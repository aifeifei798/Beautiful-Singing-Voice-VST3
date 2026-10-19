#!/usr/bin/env python3
"""Prefetch Demucs weights into the torch hub cache.

Useful when the network/proxy is flaky: torch.hub fails with a hash mismatch on a
partially downloaded file, and demucs then aborts. This script retries with curl and
verifies each file against the signature in its filename.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import pathlib
import subprocess
import sys

BASE = "https://dl.fbaipublicfiles.com/demucs/hybrid_transformer/"

MODELS = {
    "htdemucs": ["955717e8-8726e21a.th"],
    "htdemucs_ft": [
        "f7e0c4bc-ba3fe64a.th",
        "d12395a8-e57c48e6.th",
        "92cfc3b6-ef3bcb9c.th",
        "04573f0d-f3cf25b2.th",
    ],
    "htdemucs_6s": ["5c90dfd2-34c22ccb.th"],
}


def cache_dir() -> pathlib.Path:
    root = pathlib.Path(os.environ.get("TORCH_HOME", str(pathlib.Path.home() / ".cache" / "torch")))
    return root / "hub" / "checkpoints"


def fetch(name: str, retries: int = 60) -> bool:
    dest = cache_dir() / name
    # demucs names files <signature>-<sha256 prefix>.th
    expected = name.split("-")[1].split(".")[0]
    if dest.exists():
        digest = hashlib.sha256(dest.read_bytes()).hexdigest()
        if digest.startswith(expected):
            print(f"  {name}: already cached, hash ok")
            return True

    # Resumable: proxies often truncate large downloads, so keep the partial file
    # and continue from the byte offset until the hash matches.
    for attempt in range(1, retries + 1):
        argv = ["curl", "-sL", "-C", "-", "--max-time", "120", "-o", str(dest), BASE + name]
        if attempt == 1:
            argv.insert(1, "--noproxy")
            argv.insert(2, "*")  # this CDN is reachable directly; the local proxy truncates large files
        result = subprocess.run(argv, capture_output=True)
        size = dest.stat().st_size if dest.exists() else 0
        digest = hashlib.sha256(dest.read_bytes()).hexdigest() if size else ""
        if digest.startswith(expected):
            print(f"  {name}: ok ({size / 1e6:.0f} MB)")
            return True
        print(f"  {name}: attempt {attempt}, got {size / 1e6:.1f} MB (curl exit {result.returncode})")
    return False


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", default="htdemucs_ft", choices=list(MODELS))
    args = parser.parse_args(argv)

    cache_dir().mkdir(parents=True, exist_ok=True)
    ok = all(fetch(name) for name in MODELS[args.model])
    if not ok:
        print("download failed — retry, or point --model at a smaller model")
        return 1
    print(f"{args.model} weights ready in {cache_dir()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
