#!/usr/bin/env bash
# Copyright 2026 Feifei
# SPDX-License-Identifier: GPL-3.0-only
#
# Build the VST3. Everything lands in plugin/build, and JUCE copies the finished
# plugin to ~/.vst3 for you.
set -euo pipefail

cd "$(dirname "$0")"

JUCE_VERSION="${JUCE_VERSION:-8.0.12}"
JUCE_DIR="${JUCE_DIR:-$HOME/develop/JUCE}"

if [[ ! -f "$JUCE_DIR/CMakeLists.txt" ]]; then
    echo "JUCE not found at $JUCE_DIR, cloning $JUCE_VERSION ..."
    mkdir -p "$(dirname "$JUCE_DIR")"
    git clone --depth 1 --branch "$JUCE_VERSION" \
        https://github.com/juce-framework/JUCE.git "$JUCE_DIR"
fi

GENERATOR=()
if command -v ninja >/dev/null 2>&1; then
    GENERATOR=(-G Ninja)
fi

cmake -B build "${GENERATOR[@]}" -DCMAKE_BUILD_TYPE=Release -DJUCE_DIR="$JUCE_DIR"
cmake --build build --parallel "$(nproc)"

echo
echo "plugin:  $HOME/.vst3/Beautiful Singing Voice.vst3"
echo "host:    plugin/build/BSVHost_artefacts/Release/BSVHost"
echo "verify:  .venv/bin/python plugin/verify.py"
