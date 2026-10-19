// Copyright 2026 Feifei
// SPDX-License-Identifier: AGPL-3.0-or-later

#pragma once

#include <juce_gui_basics/juce_gui_basics.h>

#include "PluginProcessor.h"

class BSVAudioProcessorEditor : public juce::AudioProcessorEditor,
                                 private juce::Timer
{
public:
    explicit BSVAudioProcessorEditor (BSVAudioProcessor&);
    ~BSVAudioProcessorEditor() override;

    void paint (juce::Graphics&) override;
    void resized() override;

private:
    void timerCallback() override;
    void updateModeDependent();

    struct Knob
    {
        juce::Label name;
        juce::Slider slider;
        std::unique_ptr<juce::AudioProcessorValueTreeState::SliderAttachment> attachment;
    };

    void addKnob (Knob& knob, const char* paramId, const char* label,
                  juce::Range<double> range, double defaultValue, const char* suffix);

    BSVAudioProcessor& processor;

    juce::Label title, subtitle, modeLabel, hintLabel, scLabel;
    juce::ComboBox presetBox;
    std::unique_ptr<juce::AudioProcessorValueTreeState::ComboBoxAttachment> presetAttachment;

    juce::TextButton modeButtons[3];
    int lastMode = -1;

    Knob mudKnob, presenceKnob, airKnob, deessKnob, compKnob, doublingKnob, duckKnob,
         outputKnob, ceilingKnob;

    JUCE_DECLARE_NON_COPYABLE_WITH_LEAK_DETECTOR (BSVAudioProcessorEditor)
};
