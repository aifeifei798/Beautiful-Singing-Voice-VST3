// Copyright 2026 Feifei
// SPDX-License-Identifier: AGPL-3.0-or-later
//
// juce::String(const char*) goes through the platform's 8-bit charset, which
// turns UTF-8 literals into mojibake on Linux. Every non-ASCII string in this
// plugin must go through u8().

#pragma once

#include <juce_core/juce_core.h>

inline juce::String u8 (const char* text)
{
    return juce::String::fromUTF8 (text);
}
