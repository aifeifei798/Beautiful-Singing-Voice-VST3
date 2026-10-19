// Copyright 2026 Feifei
// SPDX-License-Identifier: AGPL-3.0-or-later

#include "PluginEditor.h"
#include "Text.h"

using namespace juce;

namespace
{
const Colour kBg (0xff14161a);
const Colour kPanel (0xff1d2026);
const Colour kText (0xffe6e8ec);
const Colour kDim (0xff8b919c);
const Colour kAccent (0xff28be78);   // the app's "B" green
const Colour kWarm (0xffff7830);     // the app's playhead orange

class StudioLookAndFeel : public LookAndFeel_V4
{
public:
    StudioLookAndFeel()
    {
        setColour (Label::textColourId, kText);
        setColour (Label::backgroundColourId, Colours::transparentBlack);
        setColour (Label::outlineColourId, Colours::transparentBlack);
        setColour (TextEditor::backgroundColourId, Colours::transparentBlack);
        setColour (TextEditor::outlineColourId, Colours::transparentBlack);
        setColour (TextEditor::focusedOutlineColourId, kAccent.withAlpha (0.6f));
        setColour (TextEditor::highlightColourId, kAccent.withAlpha (0.3f));
        setColour (Slider::textBoxHighlightColourId, kAccent.withAlpha (0.3f));
        setColour (Slider::textBoxTextColourId, kText);
        setColour (Slider::textBoxOutlineColourId, Colours::transparentBlack);
        setColour (Slider::textBoxBackgroundColourId, Colour (0xff22262e));
        setColour (ComboBox::backgroundColourId, kPanel);
        setColour (ComboBox::textColourId, kText);
        setColour (ComboBox::outlineColourId, Colour (0xff2c313a));
        setColour (ComboBox::arrowColourId, kDim);
        setColour (PopupMenu::backgroundColourId, kPanel);
        setColour (PopupMenu::textColourId, kText);
        setColour (PopupMenu::highlightedBackgroundColourId, kAccent.withAlpha (0.35f));
        setColour (TextButton::buttonColourId, kPanel);
        setColour (TextButton::buttonOnColourId, kAccent);
        setColour (TextButton::textColourOffId, kText);
        setColour (TextButton::textColourOnId, Colour (0xff0d0f12));
    }

    void drawRotarySlider (Graphics& g, int x, int y, int width, int height,
                           float pos, float startAngle, float endAngle,
                           Slider&) override
    {
        const auto bounds = Rectangle<int> (x, y, width, height).toFloat().reduced (6.0f);
        const auto radius = jmin (bounds.getWidth(), bounds.getHeight()) / 2.0f;
        const auto centre = bounds.getCentre();
        const auto angle = startAngle + pos * (endAngle - startAngle);
        const auto thickness = jmax (2.0f, radius * 0.16f);

        g.setColour (Colour (0xff2a2f37));
        g.fillEllipse (centre.x - radius, centre.y - radius, radius * 2.0f, radius * 2.0f);

        g.setColour (Colour (0xff111317));
        g.fillEllipse (centre.x - radius * 0.82f, centre.y - radius * 0.82f,
                       radius * 1.64f, radius * 1.64f);

        Path track;
        track.addCentredArc (centre.x, centre.y, radius - thickness * 0.5f,
                             radius - thickness * 0.5f, 0.0f, startAngle, endAngle, true);
        g.setColour (Colour (0xff313742));
        g.strokePath (track, PathStrokeType (thickness, PathStrokeType::curved, PathStrokeType::rounded));

        Path value;
        value.addCentredArc (centre.x, centre.y, radius - thickness * 0.5f,
                             radius - thickness * 0.5f, 0.0f, startAngle, angle, true);
        g.setColour (kAccent);
        g.strokePath (value, PathStrokeType (thickness, PathStrokeType::curved, PathStrokeType::rounded));

        const auto pointerLength = radius * 0.55f;
        g.setColour (kText);
        g.drawLine (centre.x + pointerLength * 0.45f * std::sin (angle),
                    centre.y - pointerLength * 0.45f * std::cos (angle),
                    centre.x + pointerLength * std::sin (angle),
                    centre.y - pointerLength * std::cos (angle),
                    2.0f);
    }
};
} // namespace

BSVAudioProcessorEditor::BSVAudioProcessorEditor (BSVAudioProcessor& p)
    : AudioProcessorEditor (&p), processor (p)
{
    setLookAndFeel (new StudioLookAndFeel()); // owned by the component tree
    setResizable (true, true);
    setResizeLimits (680, 400, 1100, 720);
    setSize (760, 470);

    title.setText ("Beautiful Singing Voice", dontSendNotification);
    title.setFont (Font (22.0f, Font::bold));
    title.setColour (Label::textColourId, kText);
    addAndMakeVisible (title);

    subtitle.setText (u8 ("VST3 · 一键修复人声 / 配乐 / 整轨"), dontSendNotification);
    subtitle.setFont (Font (12.0f));
    subtitle.setColour (Label::textColourId, kDim);
    addAndMakeVisible (subtitle);

    modeLabel.setText (u8 ("模式"), dontSendNotification);
    modeLabel.setFont (Font (12.0f));
    modeLabel.setColour (Label::textColourId, kDim);
    addAndMakeVisible (modeLabel);

    for (int i = 0; i < 3; ++i)
    {
        auto& b = modeButtons[i];
        b.setButtonText (BSVAudioProcessor::modeName (i));
        b.setClickingTogglesState (false);
        b.onClick = [this, i]
        {
            if (auto* param = processor.apvts.getParameter (BSVAudioProcessor::kMode))
                param->setValueNotifyingHost (param->convertTo0to1 ((float) i));

            updateModeDependent();
        };
        addAndMakeVisible (b);
    }

    presetBox.addItemList (BSVAudioProcessor::presetChoices(), 1);
    addAndMakeVisible (presetBox);
    presetAttachment = std::make_unique<AudioProcessorValueTreeState::ComboBoxAttachment> (
        processor.apvts, BSVAudioProcessor::kPreset, presetBox);

    addKnob (mudKnob, BSVAudioProcessor::kMud, "低频清理", { -6.0, 0.0 }, -2.0, " dB");
    addKnob (presenceKnob, BSVAudioProcessor::kPresence, "临场感", { 0.0, 6.0 }, 2.0, " dB");
    addKnob (airKnob, BSVAudioProcessor::kAir, "空气感", { 0.0, 4.0 }, 1.5, " dB");
    addKnob (deessKnob, BSVAudioProcessor::kDeess, "齿音抑制", { 0.0, 1.2 }, 0.7, "");
    addKnob (compKnob, BSVAudioProcessor::kComp, "压缩比", { 1.0, 3.0 }, 1.3, " : 1");
    addKnob (doublingKnob, BSVAudioProcessor::kDoubling, "加厚", { -60.0, -6.0 }, -20.0, " dB");
    doublingKnob.slider.setTooltip (u8 ("耳机监听建议调低加厚；外放 / 现场感建议拉满。"));
    addKnob (duckKnob, BSVAudioProcessor::kDuck, "闪避", { 0.0, 10.0 }, 3.0, " dB");
    addKnob (outputKnob, BSVAudioProcessor::kOutput, "输出增益", { -12.0, 12.0 }, 0.0, " dB");
    addKnob (ceilingKnob, BSVAudioProcessor::kCeiling, "峰值上限", { -6.0, 0.0 }, -1.0, " dB");

    hintLabel.setFont (Font (12.0f));
    hintLabel.setColour (Label::textColourId, kDim);
    addAndMakeVisible (hintLabel);

    scLabel.setFont (Font (11.0f));
    scLabel.setColour (Label::textColourId, kDim);
    addAndMakeVisible (scLabel);

    updateModeDependent();
    startTimerHz (8);
}

BSVAudioProcessorEditor::~BSVAudioProcessorEditor()
{
    setLookAndFeel (nullptr);
}

void BSVAudioProcessorEditor::addKnob (Knob& knob, const char* paramId, const char* label,
                                       Range<double> range, double defaultValue,
                                       const char* suffix)
{
    knob.name.setText (u8 (label), dontSendNotification);
    knob.name.setFont (Font (12.0f));
    knob.name.setJustificationType (Justification::centred);
    knob.name.setColour (Label::textColourId, kDim);
    addAndMakeVisible (knob.name);

    auto& s = knob.slider;
    // Add it first: setTextBoxStyle() builds the value Label with the slider's
    // current LookAndFeel, and before this point it would fall back to JUCE's
    // default (white box, white outline).
    addAndMakeVisible (s);
    s.setSliderStyle (Slider::RotaryHorizontalVerticalDrag);
    s.setRotaryParameters (MathConstants<float>::pi * 1.2f,
                           MathConstants<float>::pi * 2.8f, true);
    s.setTextBoxStyle (Slider::TextBoxBelow, false, 76, 18);
    s.setColour (Slider::textBoxTextColourId, kText);
    s.setRange (range.getStart(), range.getEnd(), 0.01);
    s.setValue (defaultValue, dontSendNotification);
    s.setDoubleClickReturnValue (true, defaultValue);
    s.setTextValueSuffix (suffix);
    s.setNumDecimalPlacesToDisplay (1);

    knob.attachment = std::make_unique<AudioProcessorValueTreeState::SliderAttachment> (
        processor.apvts, paramId, s);
}

void BSVAudioProcessorEditor::paint (Graphics& g)
{
    g.fillAll (kBg);

    // header rule
    g.setColour (Colour (0xff2a2f37));
    g.fillRect (0, 84, getWidth(), 1);
    g.fillRect (0, getHeight() - 44, getWidth(), 1);

    // a quiet accent strip on the left edge
    g.setColour (kAccent.withAlpha (0.55f));
    g.fillRect (0, 0, 3, getHeight());
}

void BSVAudioProcessorEditor::resized()
{
    auto area = getLocalBounds().reduced (18, 14);

    auto header = area.removeFromTop (56);
    auto headerLeft = header.removeFromLeft (header.getWidth() - 240);
    title.setBounds (headerLeft.removeFromTop (28));
    subtitle.setBounds (headerLeft.removeFromTop (20));

    auto presetArea = header.withTrimmedTop (4);
    presetBox.setBounds (presetArea.removeFromRight (220).withHeight (30));

    area.removeFromTop (14);

    auto modeRow = area.removeFromTop (54);
    modeLabel.setBounds (modeRow.removeFromLeft (36).withTrimmedTop (22).withHeight (18));
    const int gap = 8;
    const int buttonWidth = (modeRow.getWidth() - gap * 2) / 3;
    for (auto& b : modeButtons)
        b.setBounds (modeRow.removeFromLeft (buttonWidth).reduced (0, 12));

    area.removeFromTop (10);

    auto footer = area.removeFromBottom (40);
    hintLabel.setBounds (footer.removeFromTop (20));
    scLabel.setBounds (footer.removeFromTop (18));

    area.removeFromBottom (6);

    // 3 x 3 knobs
    Knob* grid[3][3] = {
        { &mudKnob, &presenceKnob, &airKnob },
        { &deessKnob, &compKnob, &doublingKnob },
        { &duckKnob, &outputKnob, &ceilingKnob },
    };

    const int cellW = area.getWidth() / 3;
    const int cellH = area.getHeight() / 3;

    for (int row = 0; row < 3; ++row)
    {
        for (int col = 0; col < 3; ++col)
        {
            auto cell = Rectangle<int> (area.getX() + col * cellW, area.getY() + row * cellH, cellW, cellH);
            auto* knob = grid[row][col];
            knob->name.setBounds (cell.removeFromTop (18));
            knob->slider.setBounds (cell.reduced (6, 2));
        }
    }
}

void BSVAudioProcessorEditor::timerCallback()
{
    if (auto* modeParam = processor.apvts.getParameter (BSVAudioProcessor::kMode))
    {
        const int mode = (int) std::lround (modeParam->getValue() * 2.0f);
        if (mode != lastMode)
            updateModeDependent();
    }

    if (processor.sidechainConnected())
        scLabel.setColour (Label::textColourId, kAccent);
    else
        scLabel.setColour (Label::textColourId, kDim);

    scLabel.setText (u8 (processor.sidechainConnected()
                                    ? "侧链：已连接"
                                    : "侧链：未连接（配乐模式下闪避不生效）"),
                     dontSendNotification);
}

void BSVAudioProcessorEditor::updateModeDependent()
{
    int mode = 0;
    if (auto* modeParam = processor.apvts.getParameter (BSVAudioProcessor::kMode))
        mode = jlimit (0, 2, (int) std::lround (modeParam->getValue() * 2.0f));

    if (mode == lastMode)
        return;

    lastMode = mode;

    for (int i = 0; i < 3; ++i)
        modeButtons[i].setToggleState (i == mode, dontSendNotification);

    const bool vocal = mode == 1;
    const bool music = mode == 2;
    const bool master = mode == 0;

    ceilingKnob.slider.setEnabled (master);
    ceilingKnob.name.setAlpha (master ? 1.0f : 0.35f);

    deessKnob.slider.setEnabled (vocal);
    doublingKnob.slider.setEnabled (vocal);
    duckKnob.slider.setEnabled (music);

    // dim the labels of the knobs that this mode ignores, so it is obvious why
    // turning them does nothing
    deessKnob.name.setAlpha (vocal ? 1.0f : 0.35f);
    doublingKnob.name.setAlpha (vocal ? 1.0f : 0.35f);
    duckKnob.name.setAlpha (music ? 1.0f : 0.35f);
    mudKnob.name.setAlpha (master ? 0.75f : 1.0f);
    presenceKnob.name.setAlpha (master ? 0.75f : 1.0f);
    airKnob.name.setAlpha (master ? 0.75f : 1.0f);
    compKnob.name.setAlpha (music ? 0.35f : 1.0f);
    compKnob.slider.setEnabled (! music);

    hintLabel.setText (BSVAudioProcessor::modeHint (mode), dontSendNotification);

    repaint();
}
