#!/usr/bin/env bash
# One-command launch: create the venv on first run, then open the GUI.
set -euo pipefail
cd "$(dirname "$0")"

if [ ! -d .venv ]; then
    uv venv .venv
    uv pip install --python .venv/bin/python -e ".[separate]"
fi

PY=.venv/bin/python
if [ "${1:-}" = "cli" ]; then
    shift
    exec "$PY" -m bsv.cli "$@"
fi

if [ ! -f "$HOME/.cache/torch/hub/checkpoints/f7e0c4bc-ba3fe64a.th" ]; then
    echo "prefetching demucs weights (proxy-flaky networks need this)…"
    "$PY" scripts/download_models.py --model htdemucs_ft || true
fi

exec "$PY" -m bsv.ui.app "$@"
