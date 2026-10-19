# Copyright 2026 Feifei
# SPDX-License-Identifier: GPL-3.0-only

"""Preset definitions: every preset is a parameter vector over the same processing chain."""

from __future__ import annotations

from dataclasses import dataclass, asdict, field


@dataclass
class Params:
    # ---- global ----
    target_lufs: float = -14.0
    declip_knee: float = 0.94

    # ---- vocals ----
    vocal_gain_db: float = 0.0
    vocal_hp_hz: float = 40.0
    mud_hz: float = 320.0
    mud_db: float = -3.0
    mud2_hz: float = 470.0
    mud2_db: float = -2.0
    warmth_hz: float = 180.0
    warmth_db: float = 1.0
    presence_hz: float = 2500.0
    presence_db: float = 3.0
    air_hz: float = 8000.0
    air_db: float = 2.0

    # ---- de-esser (two bands) ----
    deesser_hz: float = 6500.0
    deesser_hz2: float = 9200.0
    deesser_offset_db: float = -5.0  # threshold = vocal core level + this offset
    deesser_amount: float = 0.8

    # ---- vocal dynamics ----
    comp_threshold_db: float = -20.0
    comp_ratio: float = 1.6
    comp_attack_ms: float = 20.0
    comp_release_ms: float = 120.0

    # ---- vocal space ----
    # Reverb is off by default: the mixes already carry their own space, and a
    # reverb on top of it reads as "回响太重". Doubling is on by default — a
    # band-limited, slightly detuned double is body, not an effect.
    reverb_room: float = 0.45
    reverb_wet: float = 0.0
    reverb_damping: float = 0.4
    doubling_db: float = -12.0  # level of EACH double; -60 = off
    doubling_ms: float = 25.0

    # ---- arrangement / accompaniment ----
    music_gain_db: float = -1.0
    music_hp_hz: float = 30.0
    music_mud_db: float = -2.0
    duck_db: float = 4.0
    duck_lo_hz: float = 250.0
    duck_hi_hz: float = 4000.0
    duck_threshold_db: float = -28.0
    duck_attack_ms: float = 40.0
    duck_release_ms: float = 260.0

    def to_dict(self) -> dict:
        return asdict(self)

    @staticmethod
    def from_dict(values: dict) -> "Params":
        return Params(**{k: v for k, v in values.items() if k in Params.__dataclass_fields__})


def _off(x: float) -> bool:
    return x is None or x <= -80.0


PRESETS: dict[str, Params] = {
    # No preset adds reverb. Doubling is dialled per style: how much body the
    # lead vocal should have. -60 = off.
    "中性 (只修问题)": Params(
        vocal_gain_db=0.0, mud_db=-2.5, presence_db=2.0, air_db=1.5,
        deesser_amount=0.7, comp_ratio=1.3, duck_db=3.0, doubling_db=-14.0,
    ),
    "中文流行": Params(
        vocal_gain_db=+1.0, mud_db=-3.5, mud2_db=-2.5, warmth_db=1.2,
        presence_db=3.2, air_db=2.2, deesser_amount=0.9, comp_ratio=1.7,
        duck_db=4.5, music_gain_db=-1.5, doubling_db=-12.0,
    ),
    "K-pop ballad": Params(
        vocal_gain_db=+1.5, mud_db=-4.0, warmth_db=1.5, presence_db=2.8,
        air_db=2.6, deesser_amount=1.0, deesser_offset_db=-4.0, comp_ratio=1.9,
        reverb_room=0.55, duck_db=5.0, music_gain_db=-2.0, doubling_db=-10.0,
    ),
    "EDM / 电子流行": Params(
        vocal_gain_db=+0.8, vocal_hp_hz=60.0, mud_db=-4.0, warmth_db=0.0,
        presence_db=3.6, air_db=2.8, deesser_amount=1.1, deesser_offset_db=-4.0,
        comp_ratio=2.2, comp_attack_ms=12.0, reverb_room=0.3,
        duck_db=6.0, music_gain_db=0.0, music_hp_hz=25.0, doubling_db=-9.0,
    ),
    "Rock": Params(
        vocal_gain_db=+0.5, mud_db=-3.0, warmth_db=1.8, presence_db=3.4,
        air_db=1.6, deesser_amount=0.8, comp_ratio=2.0, reverb_room=0.35,
        duck_db=3.5, music_gain_db=+0.5, doubling_db=-12.0, doubling_ms=18.0,
    ),
    "Lo-fi / 氛围": Params(
        vocal_gain_db=0.0, mud_db=-2.0, warmth_db=2.2, presence_db=2.0,
        air_db=1.0, deesser_amount=0.6, deesser_offset_db=-7.0, comp_ratio=1.4,
        reverb_room=0.6, duck_db=3.0, music_gain_db=-0.5,
        target_lufs=-16.0, doubling_db=-16.0, doubling_ms=35.0,
    ),
    "美式流行": Params(
        vocal_gain_db=+1.2, mud_db=-3.8, warmth_db=0.8, presence_db=3.5,
        air_db=2.4, deesser_amount=1.0, comp_ratio=1.8, reverb_room=0.42,
        duck_db=5.0, music_gain_db=-1.0, doubling_db=-11.0,
    ),
}


def preset_names() -> list[str]:
    return list(PRESETS.keys())
