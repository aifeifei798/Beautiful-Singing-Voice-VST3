// Copyright 2026 Feifei
// SPDX-License-Identifier: AGPL-3.0-or-later

#include "PluginProcessor.h"
#include "PluginEditor.h"
#include "Text.h"

using namespace juce;

namespace
{
struct PresetValues
{
    const char* name;
    float mud, presence, air, deess, comp, doubling, duck;
};

// Mirrors bsv/presets.py. Index 0 ("自定义") is not a preset: it means the knobs
// are whatever the user left them at.
const PresetValues kPresets[] = {
    { "自定义",     -2.0f, 2.0f, 1.5f, 0.7f, 1.3f, -20.0f, 3.0f },
    { "中性",       -2.5f, 2.0f, 1.5f, 0.7f, 1.3f, -20.0f, 3.0f },
    { "中文流行",   -3.5f, 3.2f, 2.2f, 0.9f, 1.7f, -18.0f, 4.5f },
    { "K-pop",      -4.0f, 2.8f, 2.6f, 1.0f, 1.9f, -16.0f, 5.0f },
    { "EDM",        -4.0f, 3.6f, 2.8f, 1.1f, 2.2f, -15.0f, 6.0f },
    { "Rock",       -3.0f, 3.4f, 1.6f, 0.8f, 2.0f, -18.0f, 3.5f },
    { "Lo-fi",      -2.0f, 2.0f, 1.0f, 0.6f, 1.4f, -22.0f, 3.0f },
    { "美式",       -3.8f, 3.5f, 2.4f, 1.0f, 1.8f, -17.0f, 5.0f },
};

constexpr int kNumPresets = (int) (sizeof (kPresets) / sizeof (kPresets[0]));

StringArray choiceList (std::initializer_list<const char*> items)
{
    StringArray a;
    for (auto* s : items)
        a.add (u8 (s));
    return a;
}
} // namespace

StringArray BSVAudioProcessor::modeChoices()
{
    return choiceList ({ "母带 / 整轨", "人声", "配乐" });
}

StringArray BSVAudioProcessor::presetChoices()
{
    StringArray a;
    for (int i = 0; i < kNumPresets; ++i)
        a.add (u8 (kPresets[i].name));
    return a;
}

int BSVAudioProcessor::presetCount() { return kNumPresets; }

String BSVAudioProcessor::modeName (int index)
{
    return modeChoices()[jlimit (0, 2, index)];
}

String BSVAudioProcessor::modeHint (int index)
{
    switch (jlimit (0, 2, index))
    {
        case 1:  return u8 ("放在人声轨：完整人声链 + 加厚");
        case 2:  return u8 ("放在伴奏总线：低频清理 + 侧链闪避（要接侧链）");
        default: return u8 ("放在 master：整轨温和打磨，不闪避、不加厚");
    }
}

BSVAudioProcessor::BSVAudioProcessor()
    : AudioProcessor (BusesProperties()
                          .withInput ("Input", AudioChannelSet::stereo(), true)
                          .withInput ("Sidechain", AudioChannelSet::stereo(), false)
                          .withOutput ("Output", AudioChannelSet::stereo(), true)),
      apvts (*this, nullptr, "PARAMS", createLayout())
{
    apvts.addParameterListener (kPreset, this);
}

AudioProcessorValueTreeState::ParameterLayout BSVAudioProcessor::createLayout()
{
    AudioProcessorValueTreeState::ParameterLayout layout;

    auto global = std::make_unique<AudioProcessorParameterGroup> ("global", u8 ("全局"), " / ");
    global->addChild (std::make_unique<AudioParameterChoice> (kMode, u8 ("模式"), modeChoices(), 0));
    global->addChild (std::make_unique<AudioParameterChoice> (kPreset, u8 ("预设"), presetChoices(), 1));
    layout.add (std::move (global));

    auto tone = std::make_unique<AudioProcessorParameterGroup> ("tone", u8 ("音色"), " / ");
    tone->addChild (std::make_unique<AudioParameterFloat> (
        kMud, u8 ("低频清理"), NormalisableRange<float> (-6.0f, 0.0f, 0.1f), -2.5f));
    tone->addChild (std::make_unique<AudioParameterFloat> (
        kPresence, u8 ("临场感"), NormalisableRange<float> (0.0f, 6.0f, 0.1f), 2.0f));
    tone->addChild (std::make_unique<AudioParameterFloat> (
        kAir, u8 ("空气感"), NormalisableRange<float> (0.0f, 4.0f, 0.1f), 1.5f));
    tone->addChild (std::make_unique<AudioParameterFloat> (
        kDeess, u8 ("齿音抑制"), NormalisableRange<float> (0.0f, 1.2f, 0.01f), 0.7f));
    layout.add (std::move (tone));

    auto dyn = std::make_unique<AudioProcessorParameterGroup> ("dyn", u8 ("动态"), " / ");
    dyn->addChild (std::make_unique<AudioParameterFloat> (
        kComp, u8 ("压缩比"), NormalisableRange<float> (1.0f, 3.0f, 0.05f), 1.3f));
    dyn->addChild (std::make_unique<AudioParameterFloat> (
        kDoubling, u8 ("加厚"), NormalisableRange<float> (-60.0f, -6.0f, 1.0f), -20.0f));
    dyn->addChild (std::make_unique<AudioParameterFloat> (
        kDuck, u8 ("闪避"), NormalisableRange<float> (0.0f, 10.0f, 0.1f), 3.0f));
    layout.add (std::move (dyn));

    auto out = std::make_unique<AudioProcessorParameterGroup> ("out", u8 ("输出"), " / ");
    out->addChild (std::make_unique<AudioParameterFloat> (
        kOutput, u8 ("输出增益"), NormalisableRange<float> (-12.0f, 12.0f, 0.1f), 0.0f));
    out->addChild (std::make_unique<AudioParameterFloat> (
        kCeiling, u8 ("峰值上限"), NormalisableRange<float> (-6.0f, 0.0f, 0.1f), -1.0f));
    layout.add (std::move (out));

    return layout;
}

void BSVAudioProcessor::prepareToPlay (double sampleRate, int samplesPerBlock)
{
    currentSampleRate = sampleRate;
    maxBlockSize = juce::jmax (16, samplesPerBlock);
    monoScratch.setSize (2, maxBlockSize, false, false, true);

    // Start from whatever preset the restored state carries. Without this, the
    // first block would "apply" it over the knobs the user had actually saved.
    if (auto* presetParam = apvts.getRawParameterValue (kPreset))
        activePreset.store ((int) presetParam->load());
    chain.prepare (sampleRate);
    setLatencySamples (chain.latencySamples());
    sidechainWired = getBus (true, 1) != nullptr && getBus (true, 1)->isEnabled();
}

void BSVAudioProcessor::releaseResources() {}

bool BSVAudioProcessor::isBusesLayoutSupported (const BusesLayout& layouts) const
{
    const auto mainIn = layouts.getChannelSet (true, 0);
    const auto mainOut = layouts.getChannelSet (false, 0);
    return mainIn == mainOut
           && (mainOut == AudioChannelSet::stereo() || mainOut == AudioChannelSet::mono());
}

bool BSVAudioProcessor::sidechainConnected() const
{
    const auto* bus = getBus (true, 1);
    return bus != nullptr && bus->isEnabled() && bus->getNumberOfChannels() > 0;
}

void BSVAudioProcessor::applyPreset (int index)
{
    if (index <= 0 || index >= kNumPresets)
        return;

    const auto& p = kPresets[index];
    auto set = [this] (const char* id, float value)
    {
        if (auto* param = apvts.getParameter (id))
            param->setValueNotifyingHost (param->convertTo0to1 (value));
    };

    set (kMud, p.mud);
    set (kPresence, p.presence);
    set (kAir, p.air);
    set (kDeess, p.deess);
    set (kComp, p.comp);
    set (kDoubling, p.doubling);
    set (kDuck, p.duck);
}

void BSVAudioProcessor::parameterChanged (const String& id, float newValue)
{
    // A preset is not a value of its own: picking one writes the other knobs,
    // which is only legal on the message thread, and this callback can arrive on
    // the audio thread (host automation). Hand it over and let it run there.
    if (id != kPreset || restoringState.load())
        return;

    const int index = (int) newValue;
    if (index <= 0 || index == activePreset.exchange (index))
        return;

    pendingPreset.store (index);
    presetUpdater.triggerAsyncUpdate();
}

void BSVAudioProcessor::handleAsyncUpdate()
{
    applyPreset (pendingPreset.exchange (0));
}

void BSVAudioProcessor::processBlock (AudioBuffer<float>& buffer, MidiBuffer&)
{
    ScopedNoDenormals noDenormals;

    if (buffer.getNumChannels() < 1)
        return;

    // Belt and braces: some hosts only deliver a parameter change with the next
    // process call, and the listener above is not guaranteed to see it. Catching
    // it here means a preset still lands while the transport is stopped.
    if (auto* presetParam = apvts.getRawParameterValue (kPreset))
    {
        const int wanted = (int) presetParam->load();
        if (wanted > 0 && wanted != activePreset.exchange (wanted))
        {
            pendingPreset.store (wanted);
            presetUpdater.triggerAsyncUpdate();
        }
    }

    bsv::ChainParams p;
    const int modeIndex = (int) apvts.getRawParameterValue (kMode)->load();
    p.mode = static_cast<bsv::Mode> (jlimit (0, 2, modeIndex));
    p.mudDb = apvts.getRawParameterValue (kMud)->load();
    p.presenceDb = apvts.getRawParameterValue (kPresence)->load();
    p.airDb = apvts.getRawParameterValue (kAir)->load();
    p.deessAmount = apvts.getRawParameterValue (kDeess)->load();
    p.compRatio = apvts.getRawParameterValue (kComp)->load();
    p.doublingDb = apvts.getRawParameterValue (kDoubling)->load();
    p.duckDb = apvts.getRawParameterValue (kDuck)->load();
    p.outputDb = apvts.getRawParameterValue (kOutput)->load();
    p.ceilingDb = apvts.getRawParameterValue (kCeiling)->load();
    chain.setParams (p);

    const int n = buffer.getNumSamples();

    // getBusBuffer returns a view over the same memory, but it is a temporary,
    // so keep it alive for the duration of the block.
    AudioBuffer<float> scBuffer;
    if (sidechainConnected() && buffer.getNumChannels() > 2)
        scBuffer = getBusBuffer (buffer, true, 1);

    const float* scl = nullptr;
    const float* scr = nullptr;
    if (scBuffer.getNumChannels() > 0)
    {
        scl = scBuffer.getReadPointer (0);
        scr = scBuffer.getNumChannels() > 1 ? scBuffer.getReadPointer (1) : scl;
    }

    if (buffer.getNumChannels() == 1)
    {
        // A mono track fed to a stereo plugin: process a real stereo copy rather
        // than passing the same pointer as both channels, which would run every
        // filter twice on one sample.
        monoScratch.setSize (2, n, false, false, true);
        monoScratch.copyFrom (0, 0, buffer, 0, 0, n);
        monoScratch.copyFrom (1, 0, buffer, 0, 0, n);
        chain.process (monoScratch.getWritePointer (0), monoScratch.getWritePointer (1), scl, scr, n);
        buffer.copyFrom (0, 0, monoScratch, 0, 0, n);
        return;
    }

    auto* l = buffer.getWritePointer (0);
    auto* r = buffer.getWritePointer (1);
    chain.process (l, r, scl, scr, n);
}

AudioProcessorEditor* BSVAudioProcessor::createEditor()
{
    return new BSVAudioProcessorEditor (*this);
}

void BSVAudioProcessor::getStateInformation (MemoryBlock& destData)
{
    if (auto xml = apvts.copyState().createXml())
        copyXmlToBinary (*xml, destData);
}

void BSVAudioProcessor::setStateInformation (const void* data, int sizeInBytes)
{
    if (auto xml = getXmlFromBinary (data, sizeInBytes))
    {
        if (xml->hasTagName (apvts.state.getType()))
        {
            // Restoring a preset index must not re-apply the preset: the saved
            // knobs are what the user actually left the plugin with.
            restoringState.store (true);
            apvts.replaceState (ValueTree::fromXml (*xml));
            restoringState.store (false);

            if (auto* presetParam = apvts.getRawParameterValue (kPreset))
                activePreset.store ((int) presetParam->load());
        }
    }
}

// This creates the plugin instance that the host loads.
juce::AudioProcessor* JUCE_CALLTYPE createPluginFilter()
{
    return new BSVAudioProcessor();
}
