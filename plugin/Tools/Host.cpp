// Copyright 2026 Feifei
// SPDX-License-Identifier: AGPL-3.0-or-later
//
// A headless VST3 host used to verify the plugin without a DAW: it lists the
// parameters a real host sees and can push a WAV through the plugin offline, so
// the DSP can be compared against the Python chain sample by sample.

#include <juce_audio_processors/juce_audio_processors.h>
#include <juce_audio_formats/juce_audio_formats.h>
#include <juce_audio_utils/juce_audio_utils.h>
#include <juce_graphics/juce_graphics.h>

using namespace juce;

static AudioPluginInstance* instantiate (AudioPluginFormatManager& formats, const String& path)
{
    VST3PluginFormat vst3;
    OwnedArray<PluginDescription> types;
    vst3.findAllTypesForFile (types, path);

    if (types.isEmpty())
    {
        std::cerr << "no plugin types in " << path << "\n";
        return nullptr;
    }

    String error;
    auto instance = formats.createPluginInstance (*types[0], 44100.0, 512, error);
    if (instance == nullptr)
        std::cerr << "createPluginInstance failed: " << error << "\n";

    return instance.release();
}

static void listParameters (AudioPluginInstance& plugin)
{
    std::cout << "parameters: " << plugin.getParameters().size() << "\n";
    int i = 0;
    for (auto* p : plugin.getParameters())
        std::cout << "  [" << (i++) << "] " << p->getName (128).toRawUTF8() << "\t"
                  << p->getText (p->getValue(), 32).toRawUTF8() << "\n";

    std::cout << "latency: " << plugin.getLatencySamples() << " samples\n";
    std::cout << "buses: " << plugin.getBusCount (true) << " in, "
              << plugin.getBusCount (false) << " out\n";
    for (int i = 0; i < plugin.getBusCount (true); ++i)
        if (auto* b = plugin.getBus (true, i))
            std::cout << "  in[" << i << "] " << b->getName() << " "
                      << b->getNumberOfChannels() << "ch "
                      << (b->isEnabled() ? "enabled" : "disabled") << "\n";
}

// VALUE is the normalised 0..1 value. A host only ever sees normalised values
// through VST3, and the plugin exposes no range metadata to a wrapper, so
// callers convert from real units themselves (see plugin/verify.py).
static int setParameter (AudioPluginInstance& plugin, const String& name, float normalized)
{
    for (auto* p : plugin.getParameters())
    {
        if (p->getName (128) == name)
        {
            p->setValueNotifyingHost (jlimit (0.0f, 1.0f, normalized));
            return 1;
        }
    }

    std::cerr << "no parameter named " << name << "\n";
    return 0;
}

static int processFile (AudioPluginInstance& plugin, const File& in, const File& out, int blockSize,
                        const File& sidechain)
{
    AudioFormatManager formats;
    formats.registerBasicFormats();

    std::unique_ptr<AudioFormatReader> reader (formats.createReaderFor (in));
    if (reader == nullptr)
    {
        std::cerr << "cannot read " << in.getFullPathName() << "\n";
        return 1;
    }

    const double sr = reader->sampleRate;
    const int channels = 2;

    if (sidechain.existsAsFile())
    {
        AudioProcessor::BusesLayout layout;
        layout.inputBuses.add (AudioChannelSet::stereo());
        layout.inputBuses.add (AudioChannelSet::stereo());
        layout.outputBuses.add (AudioChannelSet::stereo());
        if (! plugin.setBusesLayout (layout))
            std::cerr << "plugin refused the sidechain layout\n";
    }

    plugin.prepareToPlay (sr, blockSize);
    plugin.setRateAndBufferSizeDetails (sr, blockSize);
    std::cout << "reported latency: " << plugin.getLatencySamples() << " samples @ "
              << sr << " Hz\n";

    std::unique_ptr<AudioFormatReader> scReader;
    AudioBuffer<float> scBuffer (2, (int) reader->lengthInSamples);
    scBuffer.clear();
    if (sidechain.existsAsFile())
    {
        scReader.reset (formats.createReaderFor (sidechain));
        if (scReader == nullptr)
        {
            std::cerr << "cannot read sidechain " << sidechain.getFullPathName() << "\n";
            return 1;
        }
        scBuffer.setSize (2, (int) scReader->lengthInSamples);
        scBuffer.clear();
        scReader->read (&scBuffer, 0, (int) scReader->lengthInSamples, 0, true, true);
    }

    const int totalIn = plugin.getTotalNumInputChannels();
    AudioBuffer<float> buffer (jmax (channels, totalIn), blockSize);
    AudioBuffer<float> file (channels, (int) reader->lengthInSamples);
    file.clear();
    reader->read (&file, 0, (int) reader->lengthInSamples, 0, true, true);

    const int total = file.getNumSamples();
    for (int pos = 0; pos < total; pos += blockSize)
    {
        const int n = jmin (blockSize, total - pos);
        buffer.clear();
        for (int ch = 0; ch < channels; ++ch)
            buffer.copyFrom (ch, 0, file, ch, pos, n);

        // sidechain bus (when enabled) is the next pair of channels
        for (int ch = channels; ch < totalIn; ++ch)
            if (ch - channels < scBuffer.getNumChannels())
                buffer.copyFrom (ch, 0, scBuffer, ch - channels, pos, n);

        MidiBuffer midi;
        plugin.processBlock (buffer, midi);

        for (int ch = 0; ch < channels; ++ch)
            file.copyFrom (ch, pos, buffer, ch, 0, n);
    }

    WavAudioFormat wav;
    out.deleteFile();
    std::unique_ptr<FileOutputStream> stream (out.createOutputStream());
    if (stream == nullptr)
        return 1;

    std::unique_ptr<AudioFormatWriter> writer (
        wav.createWriterFor (stream.get(), sr, channels, 32, {}, 0));
    if (writer == nullptr)
        return 1;

    stream.release();
    writer->writeFromAudioSampleBuffer (file, 0, total);
    writer.reset();
    std::cout << "wrote " << out.getFullPathName() << " (" << total << " samples @ " << sr << ")\n";
    return 0;
}

int main (int argc, char** argv)
{
    ScopedJuceInitialiser_GUI gui;
    if (argc < 2)
    {
        std::cerr << "usage: bsv-host plugin.vst3 [--list] [--set NAME=NORM]... "
                     "[--in in.wav --out out.wav [--sidechain sc.wav]] [--block N] "
                     "[--snapshot ui.png]\n";
        return 2;
    }

    AudioPluginFormatManager formats;
    formats.addFormat (std::make_unique<VST3PluginFormat>());

    std::unique_ptr<AudioPluginInstance> plugin (instantiate (formats, String::fromUTF8 (argv[1])));
    if (plugin == nullptr)
        return 1;

    File in, out, sidechain;
    int blockSize = 512;
    File snapshot;
    int waitMs = 0;
    bool listAfter = false;
    File saveState, loadState;

    for (int i = 2; i < argc; ++i)
    {
        const String arg = String::fromUTF8 (argv[i]);
        if (arg == "--list")
        {
            listParameters (*plugin);
        }
        else if (arg == "--save-state" && i + 1 < argc)
        {
            saveState = File (String::fromUTF8 (argv[++i]));
        }
        else if (arg == "--load-state" && i + 1 < argc)
        {
            loadState = File (String::fromUTF8 (argv[++i]));
        }
        else if (arg == "--list-after")
        {
            listAfter = true;
        }
        else if (arg == "--set" && i + 1 < argc)
        {
            const String pair = String::fromUTF8 (argv[++i]);
            const int eq = pair.indexOfChar ('=');
            if (eq <= 0)
                continue;
            setParameter (*plugin, pair.substring (0, eq), pair.substring (eq + 1).getFloatValue());
        }
        else if (arg == "--in" && i + 1 < argc)
        {
            in = File (String::fromUTF8 (argv[++i]));
        }
        else if (arg == "--out" && i + 1 < argc)
        {
            out = File (String::fromUTF8 (argv[++i]));
        }
        else if (arg == "--block" && i + 1 < argc)
        {
            blockSize = String::fromUTF8 (argv[++i]).getIntValue();
        }
        else if (arg == "--sidechain" && i + 1 < argc)
        {
            sidechain = File (String::fromUTF8 (argv[++i]));
        }
        else if (arg == "--wait" && i + 1 < argc)
        {
            waitMs = String::fromUTF8 (argv[++i]).getIntValue();
        }
        else if (arg == "--snapshot" && i + 1 < argc)
        {
            snapshot = File (String::fromUTF8 (argv[++i]));
        }
    }

    // let AsyncUpdater / timer work run, e.g. a preset change that has to write
    // the other parameters through the message thread. JUCE 8 has no modal
    // loop, so run the real dispatch loop and stop it from a timer.
    if (waitMs > 0)
    {
        struct StopAfter : Timer
        {
            void timerCallback() override { MessageManager::getInstance()->stopDispatchLoop(); }
        } stopper;

        stopper.startTimer (waitMs);
        MessageManager::getInstance()->runDispatchLoop();
    }

    if (loadState.existsAsFile())
    {
        MemoryBlock state;
        if (! loadState.loadFileAsData (state))
        {
            std::cerr << "cannot read state " << loadState.getFullPathName() << "\n";
            return 1;
        }

        plugin->setStateInformation (state.getData(), (int) state.getSize());
        std::cout << "loaded state " << loadState.getFullPathName() << "\n";
    }

    if (saveState != File())
    {
        MemoryBlock state;
        plugin->getStateInformation (state);
        saveState.replaceWithData (state.getData(), state.getSize());
        std::cout << "saved state " << saveState.getFullPathName() << "\n";
    }

    if (snapshot != File())
    {
        std::unique_ptr<AudioProcessorEditor> editor (plugin->createEditorIfNeeded());
        if (editor == nullptr)
        {
            std::cerr << "plugin has no editor\n";
            return 1;
        }

        editor->setSize (760, 470);
        std::cout << "editor " << editor->getWidth() << "x" << editor->getHeight()
                  << " visible=" << (int) editor->isVisible()
                  << " alpha=" << editor->getAlpha()
                  << " children=" << editor->getNumChildComponents() << "\n";
        editor->setVisible (true);
        auto image = editor->createComponentSnapshot (editor->getLocalBounds(), true, 2.0f);
        std::cout << "snapshot " << image.getWidth() << "x" << image.getHeight()
                  << " valid=" << (int) image.isValid() << "\n";
        FileOutputStream stream (snapshot);
        PNGImageFormat png;
        if (! png.writeImageToStream (image, stream))
        {
            std::cerr << "could not write " << snapshot.getFullPathName() << "\n";
            return 1;
        }

        std::cout << "wrote " << snapshot.getFullPathName() << "\n";
        return 0;
    }

    if (in.existsAsFile() && out != File())
    {
        const int result = processFile (*plugin, in, out, blockSize, sidechain);
        if (waitMs > 0)
        {
            struct StopAfter : Timer
            {
                void timerCallback() override { MessageManager::getInstance()->stopDispatchLoop(); }
            } stopper;
            stopper.startTimer (waitMs);
            MessageManager::getInstance()->runDispatchLoop();
        }
        if (listAfter)
            listParameters (*plugin);
        return result;
    }

    return 0;
}
