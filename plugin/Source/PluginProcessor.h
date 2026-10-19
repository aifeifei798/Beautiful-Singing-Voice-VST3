// Copyright 2026 Feifei
// SPDX-License-Identifier: AGPL-3.0-or-later

#pragma once

#include <juce_audio_processors/juce_audio_processors.h>

#include "Dsp.h"

class BSVAudioProcessor : public juce::AudioProcessor,
                          private juce::AudioProcessorValueTreeState::Listener
{
public:
    // Parameter ids are also the automation labels, so keep them stable.
    static constexpr const char* kMode = "mode";
    static constexpr const char* kPreset = "preset";
    static constexpr const char* kMud = "mud";
    static constexpr const char* kPresence = "presence";
    static constexpr const char* kAir = "air";
    static constexpr const char* kDeess = "deess";
    static constexpr const char* kComp = "comp";
    static constexpr const char* kDoubling = "doubling";
    static constexpr const char* kDuck = "duck";
    static constexpr const char* kOutput = "output";
    static constexpr const char* kCeiling = "ceiling";

    BSVAudioProcessor();
    ~BSVAudioProcessor() override = default;

    void prepareToPlay (double sampleRate, int samplesPerBlock) override;
    void releaseResources() override;

    bool isBusesLayoutSupported (const BusesLayout& layouts) const override;

    void processBlock (juce::AudioBuffer<float>& buffer, juce::MidiBuffer& midi) override;

    juce::AudioProcessorEditor* createEditor() override;
    bool hasEditor() const override { return true; }

    const juce::String getName() const override { return "Beautiful Singing Voice"; }
    bool acceptsMidi() const override { return false; }
    bool producesMidi() const override { return false; }
    double getTailLengthSeconds() const override { return 0.4; }

    int getNumPrograms() override { return 1; }
    int getCurrentProgram() override { return 0; }
    void setCurrentProgram (int) override {}
    const juce::String getProgramName (int) override { return {}; }
    void changeProgramName (int, const juce::String&) override {}

    void getStateInformation (juce::MemoryBlock& destData) override;
    void setStateInformation (const void* data, int sizeInBytes) override;

    juce::AudioProcessorValueTreeState apvts;

    // ---- used by the editor ----
    bool sidechainConnected() const;
    static juce::String modeName (int index);
    static juce::String modeHint (int index);
    static juce::StringArray modeChoices();
    static juce::StringArray presetChoices();
    static int presetCount();

    static juce::AudioProcessorValueTreeState::ParameterLayout createLayout();

private:
    void parameterChanged (const juce::String& id, float newValue) override;
    void applyPreset (int index);
    void handleAsyncUpdate();

    struct PresetUpdater : public juce::AsyncUpdater
    {
        explicit PresetUpdater (BSVAudioProcessor& p) : owner (p) {}
        void handleAsyncUpdate() override { owner.handleAsyncUpdate(); }
        BSVAudioProcessor& owner;
    };

    bsv::Chain chain;
    PresetUpdater presetUpdater { *this };

    std::atomic<int> pendingPreset { 0 };
    std::atomic<int> activePreset { 0 };
    std::atomic<bool> restoringState { false };
    double currentSampleRate = 44100.0;
    bool sidechainWired = false;
    int maxBlockSize = 512;
    juce::AudioBuffer<float> monoScratch;

    JUCE_DECLARE_NON_COPYABLE_WITH_LEAK_DETECTOR (BSVAudioProcessor)
};
