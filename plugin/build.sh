#!/usr/bin/env bash
# Copyright 2026 Feifei
# SPDX-License-Identifier: GPL-3.0-only
#
# Build the VST3. Everything lands in plugin/build, and JUCE copies the finished
# plugin to ~/.vst3 for you.
#
#   ./plugin/build.sh              build + install to ~/.vst3
#   ./plugin/build.sh --package    ...and write dist/<name>-<version>-linux-x86_64.zip
set -euo pipefail

cd "$(dirname "$0")"

PACKAGE=0
[[ "${1:-}" == "--package" ]] && PACKAGE=1

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

PLUGIN="$HOME/.vst3/Beautiful Singing Voice.vst3"
echo
echo "plugin:  $PLUGIN"
echo "host:    $(pwd)/build/BSVHost_artefacts/Release/BSVHost"
echo "verify:  .venv/bin/python plugin/verify.py"

if [[ $PACKAGE -eq 1 ]]; then
    VERSION="$(git describe --tags --abbrev=0 2>/dev/null | sed 's/^v//' || true)"
    VERSION="${VERSION:-0.0.0}"
    ZIP_NAME="Beautiful-Singing-Voice-${VERSION}-linux-x86_64.zip"

    STAGE="$(mktemp -d)"
    trap 'rm -rf "$STAGE"' EXIT
    cp -r "$PLUGIN" "$STAGE/"
    cp INSTALL.txt "$STAGE/安装说明.txt"

    mkdir -p ../dist
    (cd "$STAGE" && zip -r -q - .) > "../dist/$ZIP_NAME"
    (cd ../dist && sha256sum "$ZIP_NAME" > "$ZIP_NAME.sha256")

    echo
    echo "package: $(cd ../dist && pwd)/$ZIP_NAME"
    cat "../dist/$ZIP_NAME.sha256"
fi
