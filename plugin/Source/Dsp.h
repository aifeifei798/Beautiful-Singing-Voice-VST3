// Copyright 2026 Feifei
// SPDX-License-Identifier: AGPL-3.0-or-later
//
// The plugin-side DSP. It mirrors bsv/dsp.py and bsv/filters.py, with the same
// RBJ/prewarped biquad constructions, so a plugin instance on a stem sounds like
// the desktop app does on the same stem.
//
// Two things are deliberately different:
//   * no stem separation — a plugin cannot run Demucs inside a DAW block;
//   * no loudness normalisation — the DAW owns the master level, so the plugin
//     only offers an output trim and a true-peak ceiling.
//
// Doubling is the other difference. The app reads a detuned copy at a fixed
// rate, which drifts and then simply ends with the file. A plugin plays forever,
// so each double rides a slow triangle-modulated delay instead: same ±0.45 %
// pitch offset, but bounded, and it never runs out of buffer.

#pragma once

#include <algorithm>
#include <cmath>
#include <cstddef>
#include <cstdint>
#include <deque>
#include <vector>

namespace bsv
{
constexpr double kPi = 3.14159265358979323846;

inline float dbToGain (float db) noexcept { return std::pow (10.0f, db * 0.05f); }
inline float gainToDb (float g) noexcept { return 20.0f * std::log10 (std::max (g, 1.0e-12f)); }

// ---------------------------------------------------------------------------
// biquads — coefficients follow bsv/filters.py exactly
// ---------------------------------------------------------------------------
struct Biquad
{
    double b0 = 1.0, b1 = 0.0, b2 = 0.0, a1 = 0.0, a2 = 0.0;

    static double prewarp (double hz, double sr) noexcept
    {
        return std::tan (kPi * std::clamp (hz, 1.0, sr * 0.49) / sr);
    }

    void setHighpass1 (double hz, double sr) noexcept
    {
        const double k = prewarp (hz, sr);
        b0 = 1.0 / (1.0 + k);
        b1 = -b0;
        b2 = 0.0;
        a1 = (k - 1.0) / (1.0 + k);
        a2 = 0.0;
    }

    void setLowpass1 (double hz, double sr) noexcept
    {
        const double k = prewarp (hz, sr);
        b0 = k / (1.0 + k);
        b1 = b0;
        b2 = 0.0;
        a1 = (k - 1.0) / (1.0 + k);
        a2 = 0.0;
    }

    void setPeak (double hz, double q, double gainDb, double sr) noexcept
    {
        if (std::abs (gainDb) < 1.0e-9)
        {
            b0 = 1.0; b1 = b2 = a1 = a2 = 0.0;
            return;
        }

        const double k = prewarp (hz, sr);
        const double zeta = 1.0 / (2.0 * std::max (q, 0.1));
        const double a = std::pow (10.0, gainDb / 20.0);
        const double kk = k * k;

        const double nb0 = 1.0 + 2.0 * zeta * k * a + kk;
        const double nb1 = 2.0 * (kk - 1.0);
        const double nb2 = 1.0 - 2.0 * zeta * k * a + kk;
        const double na0 = 1.0 + 2.0 * zeta * k + kk;
        const double na1 = 2.0 * (kk - 1.0);
        const double na2 = 1.0 - 2.0 * zeta * k + kk;

        b0 = nb0 / na0; b1 = nb1 / na0; b2 = nb2 / na0;
        a1 = na1 / na0; a2 = na2 / na0;
    }

    // One first-order shelf section. The Python code cascades two of them to
    // reach the full gain, so callers add this twice with a = sqrt(gain).
    static Biquad lowShelfSection (double hz, double a, double sr) noexcept
    {
        const double k = prewarp (hz, sr);
        Biquad bq;
        bq.b0 = (1.0 + a * k) / (1.0 + k);
        bq.b1 = (a * k - 1.0) / (1.0 + k);
        bq.a1 = (k - 1.0) / (1.0 + k);
        return bq;
    }

    static Biquad highShelfSection (double hz, double a, double sr) noexcept
    {
        const double k = prewarp (hz, sr);
        Biquad bq;
        bq.b0 = (a + k) / (1.0 + k);
        bq.b1 = (k - a) / (1.0 + k);
        bq.a1 = (k - 1.0) / (1.0 + k);
        return bq;
    }

    inline float process (float x, double& s1, double& s2) const noexcept
    {
        const double v = static_cast<double> (x);
        const double y = b0 * v + s1;
        s1 = b1 * v - a1 * y + s2;
        s2 = b2 * v - a2 * y;
        return static_cast<float> (y);
    }
};

class StereoFilter
{
public:
    static constexpr int kMaxSections = 8;

    StereoFilter() { reset(); }

    void clear()
    {
        count = 0;
        reset();
    }

    void add (const Biquad& b)
    {
        if (count < kMaxSections)
            sections[count++] = b;
    }

    void addPeak (double hz, double q, double gainDb, double sr)
    {
        if (std::abs (gainDb) > 1.0e-9)
        {
            Biquad b;
            b.setPeak (hz, q, gainDb, sr);
            add (b);
        }
    }

    void addLowShelf (double hz, double gainDb, double sr)
    {
        if (std::abs (gainDb) > 1.0e-9)
        {
            const double a = std::pow (10.0, gainDb / 40.0);
            add (Biquad::lowShelfSection (hz, a, sr));
            add (Biquad::lowShelfSection (hz, a, sr));
        }
    }

    void addHighShelf (double hz, double gainDb, double sr)
    {
        if (std::abs (gainDb) > 1.0e-9)
        {
            const double a = std::pow (10.0, gainDb / 40.0);
            add (Biquad::highShelfSection (hz, a, sr));
            add (Biquad::highShelfSection (hz, a, sr));
        }
    }

    void reset()
    {
        for (auto& v : s1)
            v = 0.0;
        for (auto& v : s2)
            v = 0.0;
    }

    void prepare (double) { reset(); }

    inline float process (int ch, float x) noexcept
    {
        for (int i = 0; i < count; ++i)
            x = sections[i].process (x, s1[i * 2 + ch], s2[i * 2 + ch]);

        return x;
    }

    void process (float* l, float* r, int n) noexcept
    {
        for (int i = 0; i < n; ++i)
        {
            l[i] = process (0, l[i]);
            r[i] = process (1, r[i]);
        }
    }

private:
    Biquad sections[kMaxSections];
    int count = 0;
    double s1[kMaxSections * 2] {}, s2[kMaxSections * 2] {};
};

// ---------------------------------------------------------------------------
// soft de-clip: round off flat-topped clipping instead of squaring it off
// ---------------------------------------------------------------------------
inline float softDeclip (float x, float knee) noexcept
{
    const float ax = std::abs (x);
    if (ax <= knee)
        return x;

    const float span = 1.0f - knee;
    const float scaled = (ax - knee) / span;
    return (x < 0.0f ? -1.0f : 1.0f) * (knee + span * std::tanh (scaled));
}

inline void softDeclip (float* l, float* r, int n, float knee) noexcept
{
    for (int i = 0; i < n; ++i)
    {
        l[i] = softDeclip (l[i], knee);
        r[i] = softDeclip (r[i], knee);
    }
}

// A parameter ramp that never allocates and cannot zipper: small enough to keep
// Dsp.h free of JUCE includes.
struct LinearRamp
{
    void prepare (double sampleRate, float seconds = 0.02f)
    {
        rampSamples = std::max (1, (int) std::lround (sampleRate * seconds));
        current = target = 1.0f;
        step = 0.0f;
        remaining = 0;
    }

    void setTarget (float t) noexcept
    {
        target = t;
        step = (target - current) / (float) rampSamples;
        remaining = rampSamples;
    }

    inline float next() noexcept
    {
        if (remaining > 0)
        {
            current += step;
            --remaining;
        }
        return current;
    }

    float current = 1.0f, target = 1.0f, step = 0.0f;
    int rampSamples = 1, remaining = 0;
};

// ---------------------------------------------------------------------------
// de-esser: only the 6.5 kHz band is turned down, and only when it spikes
// ---------------------------------------------------------------------------
class DeEsser
{
public:
    void prepare (double sampleRate)
    {
        sr = sampleRate;
        band.clear();
        Biquad hp, lp;
        hp.setHighpass1 (5900.0, sr);
        lp.setLowpass1 (7100.0, sr);
        band.add (hp);
        band.add (lp);
        band.reset();
        bandEnv = coreEnv = 0.0f;
        reductionDb = 0.0f;
    }

    void setAmount (float a) { amount = std::max (a, 0.0f); }
    void setOffsetDb (float o) { offsetDb = o; }

    void process (float* l, float* r, int n) noexcept
    {
        if (amount <= 0.0001f)
            return;

        const float coreAtk = envCoeff (30.0f);
        const float coreRel = envCoeff (300.0f);
        const float bandAtk = envCoeff (2.0f);
        const float bandRel = envCoeff (40.0f);
        const float gainAtk = envCoeff (4.0f);
        const float gainRel = envCoeff (40.0f);

        for (int i = 0; i < n; ++i)
        {
            const float corePeak = std::max (std::abs (l[i]), std::abs (r[i]));
            coreEnv = follow (coreEnv, corePeak, coreAtk, coreRel);

            const float bl = band.process (0, l[i]);
            const float br = band.process (1, r[i]);
            const float bandPeak = std::max (std::abs (bl), std::abs (br));
            bandEnv = follow (bandEnv, bandPeak, bandAtk, bandRel);

            const float over = gainToDb (bandEnv) - (gainToDb (coreEnv) + offsetDb);
            const float target = -amount * std::max (0.0f, over);
            reductionDb = follow (reductionDb, target, gainAtk, gainRel);

            const float g = dbToGain (reductionDb) - 1.0f; // apply to the band only
            l[i] += bl * g;
            r[i] += br * g;
        }
    }

private:
    static float follow (float state, float target, float atk, float rel) noexcept
    {
        const float c = target > state ? atk : rel;
        return c * state + (1.0f - c) * target;
    }

    float envCoeff (float ms) const noexcept
    {
        return std::exp (-1.0f / std::max (1.0f, (float) sr * ms * 0.001f));
    }

    double sr = 44100.0;
    float amount = 0.0f, offsetDb = -5.0f;
    float bandEnv = 0.0f, coreEnv = 0.0f, reductionDb = 0.0f;
    StereoFilter band;
};

// ---------------------------------------------------------------------------
// gentle compressor, stereo-linked, 6 dB soft knee
// ---------------------------------------------------------------------------
class Compressor
{
public:
    void prepare (double sampleRate) { sr = sampleRate; env = 0.0f; }

    void setRatio (float r) { ratio = std::clamp (r, 1.0f, 10.0f); }
    void setThreshold (float db) { thresholdDb = db; }

    void process (float* l, float* r, int n) noexcept
    {
        const float atk = coeff (20.0f);
        const float rel = coeff (120.0f);
        const float slope = 1.0f - 1.0f / ratio;
        constexpr float knee = 6.0f;

        for (int i = 0; i < n; ++i)
        {
            const float peak = std::max (std::abs (l[i]), std::abs (r[i]));
            env = peak > env ? atk * env + (1.0f - atk) * peak
                             : rel * env + (1.0f - rel) * peak;

            const float over = gainToDb (env) - thresholdDb;
            float reduction = 0.0f;

            if (over > knee * 0.5f)
                reduction = slope * over;
            else if (over > -knee * 0.5f)
                reduction = slope * (over + knee * 0.5f) * (over + knee * 0.5f) / (2.0f * knee);

            const float g = dbToGain (-reduction);
            l[i] *= g;
            r[i] *= g;
        }
    }

private:
    float coeff (float ms) const noexcept
    {
        return std::exp (-1.0f / std::max (1.0f, (float) sr * ms * 0.001f));
    }

    double sr = 44100.0;
    float ratio = 1.6f, thresholdDb = -20.0f, env = 0.0f;
};

// ---------------------------------------------------------------------------
// doubling: three band-limited copies, each on a slow triangle delay
// ---------------------------------------------------------------------------
class Doubler
{
public:
    void prepare (double sampleRate)
    {
        sr = sampleRate;
        const int size = (int) std::ceil (sr * 0.12) + 4; // 120 ms of headroom
        buffer[0].assign ((size_t) size, 0.0f);
        buffer[1].assign ((size_t) size, 0.0f);
        writePos = 0;
        phases[0] = 0.0f;
        phases[1] = 0.37f;
        phases[2] = 0.71f;

        band.clear();
        Biquad hp, lp;
        hp.setHighpass1 (220.0, sr);
        lp.setLowpass1 (7500.0, sr);
        band.add (hp);
        band.add (lp);
        band.reset();
    }

    void reset()
    {
        std::fill (buffer[0].begin(), buffer[0].end(), 0.0f);
        std::fill (buffer[1].begin(), buffer[1].end(), 0.0f);
        writePos = 0;
        phases[0] = 0.0f;
        phases[1] = 0.37f;
        phases[2] = 0.71f;
        band.reset();
    }

    // `levelDb` is the level of each double, exactly like the app.
    void setParams (float levelDb, float delayMs) noexcept
    {
        level = levelDb <= -60.0f ? 0.0f : dbToGain (levelDb);
        baseDelayMs[0] = delayMs * 0.72f;
        baseDelayMs[1] = delayMs;
        baseDelayMs[2] = delayMs * 1.45f;
    }

    void process (float* l, float* r, int n) noexcept
    {
        if (level <= 0.0f)
            return;

        const int size = (int) buffer[0].size();
        const float srF = (float) sr;
        constexpr float detune = 0.0045f;   // ±0.45 %, same as the app
        const float lfoHz[3] = { 0.29f, 0.37f, 0.43f };

        for (int i = 0; i < n; ++i)
        {
            const float inL = band.process (0, l[i]);
            const float inR = band.process (1, r[i]);
            buffer[0][(size_t) writePos] = inL;
            buffer[1][(size_t) writePos] = inR;

            float dl = l[i], dr = r[i];

            for (int tap = 0; tap < 3; ++tap)
            {
                // amplitude of the triangle that produces a 0.45 % read-rate
                // offset: slope = 4A/T, so A = detune * T / 4
                const float period = 1.0f / lfoHz[tap];
                const float depth = detune * period * 0.25f * srF;

                phases[tap] += lfoHz[tap] / srF;
                if (phases[tap] >= 1.0f)
                    phases[tap] -= 1.0f;

                const float tri = 4.0f * std::abs (phases[tap] - 0.5f) - 1.0f; // -1..1
                const float delay = baseDelayMs[tap] * 0.001f * srF + depth * tri;

                float read = (float) writePos - delay;
                while (read < 0.0f)
                    read += (float) size;
                while (read >= (float) size)
                    read -= (float) size;

                const int i0 = (int) read;
                const float frac = read - (float) i0;
                const int i1 = (i0 + 1) % size;

                dl += level * ((1.0f - frac) * buffer[0][(size_t) i0] + frac * buffer[0][(size_t) i1]);
                dr += level * ((1.0f - frac) * buffer[1][(size_t) i0] + frac * buffer[1][(size_t) i1]);
            }

            l[i] = dl;
            r[i] = dr;

            if (++writePos >= size)
                writePos = 0;
        }
    }

private:
    double sr = 44100.0;
    float level = 0.0f;
    float baseDelayMs[3] { 18.0f, 25.0f, 36.0f };
    float phases[3] { 0.0f, 0.37f, 0.71f };
    int writePos = 0;
    std::vector<float> buffer[2];
    StereoFilter band;
};

// ---------------------------------------------------------------------------
// sidechain duck: only the 250–4 kHz body of the music makes room
// ---------------------------------------------------------------------------
class Ducker
{
public:
    void prepare (double sampleRate)
    {
        sr = sampleRate;
        band.clear();
        Biquad hp, lp;
        hp.setHighpass1 (250.0, sr);
        lp.setLowpass1 (4000.0, sr);
        band.add (hp);
        band.add (lp);
        band.reset();
        env = 0.0f;
    }

    void reset() { band.reset(); env = 0.0f; }

    // sidechain may be null: the host has no second input wired up
    void process (float* l, float* r, const float* scl, const float* scr, int n, float amountDb) noexcept
    {
        if (scl == nullptr || scr == nullptr || amountDb <= 0.0f)
            return;

        const float atk = coeff (40.0f);
        const float rel = coeff (260.0f);
        constexpr float thresholdDb = -28.0f;

        for (int i = 0; i < n; ++i)
        {
            const float peak = std::max (std::abs (scl[i]), std::abs (scr[i]));
            env = peak > env ? atk * env + (1.0f - atk) * peak
                             : rel * env + (1.0f - rel) * peak;

            const float active = std::clamp ((gainToDb (env) - thresholdDb) / 8.0f, 0.0f, 1.0f);
            const float g = dbToGain (-amountDb * active);

            const float ml = band.process (0, l[i]);
            const float mr = band.process (1, r[i]);
            l[i] -= ml * (1.0f - g);
            r[i] -= mr * (1.0f - g);
        }
    }

private:
    float coeff (float ms) const noexcept
    {
        return std::exp (-1.0f / std::max (1.0f, (float) sr * ms * 0.001f));
    }

    double sr = 44100.0;
    float env = 0.0f;
    StereoFilter band;
};

// ---------------------------------------------------------------------------
// lookahead brickwall limiter (5 ms lookahead, 120 ms release)
// ---------------------------------------------------------------------------
class Limiter
{
public:
    void prepare (double sampleRate)
    {
        sr = sampleRate;
        lookahead = std::max (1, (int) std::lround (sr * 0.005));
        delay[0].assign ((size_t) lookahead, 0.0f);
        delay[1].assign ((size_t) lookahead, 0.0f);
        pos = 0;
        gain = 1.0f;
        release = std::exp (-1.0f / (float) (sr * 0.12));
        peaks.clear();
        index = 0;
    }

    void setCeilingDb (float db) { ceiling = dbToGain (db); }
    int latencySamples() const noexcept { return lookahead; }

    void process (float* l, float* r, int n) noexcept
    {
        for (int i = 0; i < n; ++i)
        {
            const float mono = std::max (std::abs (l[i]), std::abs (r[i]));

            while (! peaks.empty() && peaks.back().second <= mono)
                peaks.pop_back();
            peaks.emplace_back (index, mono);
            while (! peaks.empty() && index - peaks.front().first >= lookahead)
                peaks.pop_front();
            ++index;

            const float windowPeak = peaks.empty() ? 0.0f : peaks.front().second;
            const float target = windowPeak > ceiling ? ceiling / windowPeak : 1.0f;

            if (target < gain)
                gain = target;
            else
                gain = release * gain + (1.0f - release) * target;

            const float outL = delay[0][(size_t) pos] * gain;
            const float outR = delay[1][(size_t) pos] * gain;

            delay[0][(size_t) pos] = l[i];
            delay[1][(size_t) pos] = r[i];

            l[i] = outL;
            r[i] = outR;

            if (++pos >= lookahead)
                pos = 0;
        }
    }

private:
    double sr = 44100.0;
    int lookahead = 220, pos = 0;
    // 64-bit: an int overflows after ~12 hours of continuous playback, and the
    // comparison against the deque would then silently stop limiting.
    std::int64_t index = 0;
    float ceiling = 0.891f; // -1 dB
    float gain = 1.0f, release = 0.9998f;
    std::vector<float> delay[2];
    std::deque<std::pair<std::int64_t, float>> peaks;
};

// ---------------------------------------------------------------------------
// the three modes
// ---------------------------------------------------------------------------
enum class Mode
{
    master = 0,
    vocal = 1,
    music = 2
};

struct ChainParams
{
    Mode mode = Mode::master;
    float mudDb = -2.0f;
    float presenceDb = 2.0f;
    float airDb = 1.5f;
    float deessAmount = 0.7f;
    float compRatio = 1.3f;
    float doublingDb = -14.0f;
    float duckDb = 3.0f;
    float outputDb = 0.0f;
    float ceilingDb = -1.0f;

    bool operator== (const ChainParams& o) const noexcept
    {
        return mode == o.mode
               && mudDb == o.mudDb && presenceDb == o.presenceDb && airDb == o.airDb
               && deessAmount == o.deessAmount && compRatio == o.compRatio
               && doublingDb == o.doublingDb && duckDb == o.duckDb
               && outputDb == o.outputDb && ceilingDb == o.ceilingDb;
    }

    bool operator!= (const ChainParams& o) const noexcept { return ! (*this == o); }
};

class Chain
{
public:
    void prepare (double sampleRate)
    {
        sr = sampleRate;
        hp.prepare (sr);
        mud.prepare (sr);
        mud2.prepare (sr);
        warmth.prepare (sr);
        presence.prepare (sr);
        air.prepare (sr);
        deesser.prepare (sr);
        comp.prepare (sr);
        doubler.prepare (sr);
        ducker.prepare (sr);
        limiter.prepare (sr);
        outputGain.prepare (sr, 0.02f);
        lastParams = ChainParams {};
        rebuild (lastParams);
    }

    void reset()
    {
        for (auto* f : { &hp, &mud, &mud2, &warmth, &presence, &air })
            f->reset();
        deesser.prepare (sr);
        comp.prepare (sr);
        doubler.reset();
        ducker.reset();
        limiter.prepare (sr);
    }

    // Constant across modes on purpose: a latency that changes when a parameter
    // moves makes hosts re-allocate their delay compensation mid-playback.
    int latencySamples() const noexcept { return limiter.latencySamples(); }

    void setParams (const ChainParams& p)
    {
        // Rebuilding resets every filter state, so it must not happen per block:
        // a 40 Hz highpass restarting every 11 ms never settles, which shows up
        // as a phantom low cut.
        if (p == lastParams)
            return;

        lastParams = p;
        rebuild (p);
    }

    void process (float* l, float* r, const float* scl, const float* scr, int n) noexcept
    {
        const auto mode = lastParams.mode;

        softDeclip (l, r, n, 0.94f);

        hp.process (l, r, n);
        mud.process (l, r, n);
        if (mode == Mode::vocal)
        {
            mud2.process (l, r, n);
            warmth.process (l, r, n);
        }
        // The music bus gets the app's music chain: low-end cleanup only. Its
        // presence/air belong to the vocal, and boosting them here would just
        // fight the vocal and add headroom problems.
        if (mode != Mode::music)
        {
            presence.process (l, r, n);
            air.process (l, r, n);
        }

        if (mode == Mode::vocal)
        {
            deesser.process (l, r, n);
            comp.process (l, r, n);
            doubler.process (l, r, n);
        }
        else if (mode == Mode::master)
        {
            comp.process (l, r, n);
        }

        if (mode == Mode::music)
            ducker.process (l, r, scl, scr, n, lastParams.duckDb);

        for (int i = 0; i < n; ++i)
        {
            const float g = outputGain.next();
            l[i] *= g;
            r[i] *= g;
        }

        // A DAW renders the master from all the tracks at once, so the brickwall
        // belongs on the master only. Limiting a vocal or a music bus here would
        // squash it before it ever meets the mix. It still runs on the stem
        // modes with a ceiling nothing reaches, because that keeps its lookahead
        // delay — and therefore the reported latency — identical in every mode.
        limiter.process (l, r, n);
    }

private:
    void rebuild (const ChainParams& p)
    {
        hp.clear();
        mud.clear();
        mud2.clear();
        warmth.clear();
        presence.clear();
        air.clear();

        // The master runs the same shapes at ~60 % depth: on a whole mix the
        // full vocal amount reads as "someone messed with my master".
        const bool master = p.mode == Mode::master;
        const float depth = master ? 0.6f : 1.0f;

        Biquad h;
        h.setHighpass1 (master ? 30.0 : 40.0, sr);
        hp.add (h);

        mud.addPeak (320.0, 1.2, p.mudDb * depth, sr);

        if (p.mode == Mode::vocal)
        {
            mud2.addPeak (470.0, 1.0, p.mudDb * 0.65f, sr);
            warmth.addLowShelf (180.0, 1.0, sr);
        }

        presence.addPeak (2500.0, 0.8, p.presenceDb * depth, sr);
        air.addHighShelf (8000.0, p.airDb * depth, sr);

        deesser.setAmount (p.mode == Mode::vocal ? p.deessAmount : 0.0f);
        comp.setRatio (master ? std::min (p.compRatio, 1.4f) : p.compRatio);
        comp.setThreshold (master ? -16.0f : -20.0f);
        doubler.setParams (p.mode == Mode::vocal ? p.doublingDb : -60.0f, 25.0f);
        limiter.setCeilingDb (master ? p.ceilingDb : 24.0f);
        outputGain.setTarget (dbToGain (p.outputDb));
    }

    double sr = 44100.0;
    StereoFilter hp, mud, mud2, warmth, presence, air;
    DeEsser deesser;
    Compressor comp;
    Doubler doubler;
    Ducker ducker;
    Limiter limiter;
    LinearRamp outputGain;
    ChainParams lastParams;
};
} // namespace bsv
