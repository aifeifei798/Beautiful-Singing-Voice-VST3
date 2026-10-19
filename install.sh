#!/usr/bin/env bash
# Beautiful Singing Voice — 一键安装
#
#   ./install.sh                       # 建 venv + 装依赖 + 预下载分轨模型 + 自检
#   ./install.sh --python 3.12         # 指定 Python 版本（需要 uv 或该版本已安装）
#   ./install.sh --model htdemucs      # 用更小/更快的模型（84 MB，单文件）
#   ./install.sh --no-models           # 只装依赖，不下载模型（首次运行时再下）
#   ./install.sh --no-tests            # 跳过测试
#   ./install.sh --clean               # 删除 .venv 重新装
set -euo pipefail

cd "$(dirname "$0")"

VENV=.venv
MODEL=htdemucs_ft
PYTHON=""
GET_MODELS=1
RUN_TESTS=1

usage() { sed -n '2,8p' "$0" | sed 's/^#\s\{0,1\}//'; }

while [ $# -gt 0 ]; do
    arg="$1"; shift
    case "$arg" in
        --python)     PYTHON="${1:-}"; shift ;;
        --python=*)   PYTHON="${arg#--python=}" ;;
        --model)      MODEL="${1:-htdemucs_ft}"; shift ;;
        --model=*)    MODEL="${arg#--model=}" ;;
        --no-models)  GET_MODELS=0 ;;
        --no-tests)   RUN_TESTS=0 ;;
        --clean)      rm -rf "$VENV" ;;
        -h|--help)    usage; exit 0 ;;
        *)            echo "unknown option: $arg"; usage; exit 2 ;;
    esac
done

echo "== Beautiful Singing Voice install =="

# ---------------------------------------------------------------- 1. tools ----
if ! command -v ffmpeg >/dev/null; then
    echo "!! ffmpeg not found — install it first:  sudo apt install ffmpeg"
    exit 1
fi

HAS_UV=0
if command -v uv >/dev/null 2>&1; then
    HAS_UV=1
    echo "using uv ($(uv --version))"
else
    echo "uv not found, falling back to python3 -m venv + pip"
    if ! command -v python3 >/dev/null 2>&1; then
        echo "!! python3 not found"
        exit 1
    fi
fi

# ---------------------------------------------------------------- 2. venv ----
if [ ! -d "$VENV" ]; then
    if [ "$HAS_UV" = 1 ]; then
        if [ -n "$PYTHON" ]; then uv venv "$VENV" --python "$PYTHON"; else uv venv "$VENV"; fi
    else
        py="${PYTHON:-python3}"
        "$py" -m venv "$VENV"
    fi
    echo "created $VENV ($( "$VENV/bin/python" -V ))"
else
    echo "$VENV already exists ($( "$VENV/bin/python" -V ))"
fi

PY="$VENV/bin/python"

# ---------------------------------------------------------------- 3. deps ----
EXTRAS=".[separate]"
if [ "$GET_MODELS" = 0 ]; then EXTRAS="."; fi

if [ "$HAS_UV" = 1 ]; then
    uv pip install --python "$PY" -e "$EXTRAS" pytest
else
    "$PY" -m pip install --upgrade pip
    "$PY" -m pip install -e "$EXTRAS" pytest
fi
echo "dependencies installed"

# ---------------------------------------------------------------- 4. models --
if [ "$GET_MODELS" = 1 ]; then
    echo "prefetching demucs weights ($MODEL)…"
    if "$PY" scripts/download_models.py --model "$MODEL"; then
        echo "model weights cached in ~/.cache/torch/hub/checkpoints"
    else
        echo "!! model download failed (proxy?). Retry later: scripts/download_models.py --model $MODEL"
        echo "   the app still works in whole-mix fallback mode without separation."
    fi
fi

# ---------------------------------------------------------------- 5. verify --
"$PY" - <<'PYCODE'
import sys
print(f"python {sys.version.split()[0]}")
import numpy, scipy, soundfile, pedalboard
print(f"numpy {numpy.__version__}, scipy {scipy.__version__}, pedalboard {pedalboard.__version__}")
try:
    import torch
    print(f"torch {torch.__version__}  CUDA: {torch.cuda.is_available()}"
          + (f"  ({torch.cuda.get_device_name(0)})" if torch.cuda.is_available() else "  (cpu only)"))
except ImportError:
    print("torch not installed -> stem separation unavailable")
try:
    import demucs
    print("demucs ok")
except ImportError:
    print("demucs not installed -> separation unavailable")
try:
    from bsv.separate import plan_separation, _free_vram_mib
    device, segment = plan_separation("htdemucs_ft")
    free = _free_vram_mib()
    where = f"free VRAM {free} MiB" if free is not None else "VRAM unknown"
    extra = f", segment {segment:g}s" if segment else ""
    print(f"separation plan: {device}{extra}  ({where})")
except Exception as exc:
    print(f"separation plan: unknown ({exc})")
try:
    import PyQt6, pyqtgraph
    print(f"PyQt6 + pyqtgraph {pyqtgraph.__version__} ok")
except ImportError:
    print("!! GUI deps missing")
import sounddevice
print("audio devices:", len(sounddevice.query_devices()))
PYCODE

if [ "$RUN_TESTS" = 1 ]; then
    "$PY" -m pytest -q tests
fi

echo
echo "done. run:"
echo "    ./run.sh                 # GUI"
echo "    ./run.sh cli song.flac --preset 中文流行"
echo "or  .venv/bin/python -m bsv.ui.app"
