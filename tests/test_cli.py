# Copyright 2026 Feifei
# SPDX-License-Identifier: GPL-3.0-only

"""CLI parsing: preset names and the argument combinations people actually type."""

from __future__ import annotations

import pytest

from bsv.cli import build_parser, resolve_preset
from bsv.presets import PRESETS


def test_list_presets_needs_no_input_file(capsys):
    from bsv.cli import main

    assert main(["--list-presets"]) == 0
    printed = capsys.readouterr().out.split()
    assert printed  # one name per line
    assert "中性" in printed[0]


def test_resolve_preset_accepts_full_name():
    for name in PRESETS:
        assert resolve_preset(name) == name


def test_resolve_preset_accepts_short_name():
    assert resolve_preset("中性") == "中性 (只修问题)"
    assert resolve_preset("EDM") == "EDM / 电子流行"
    assert resolve_preset("lo-fi") == "Lo-fi / 氛围"


def test_resolve_preset_rejects_unknown_and_ambiguous():
    assert resolve_preset("nope") is None


def test_missing_input_is_an_error(capsys):
    from bsv.cli import main

    with pytest.raises(SystemExit) as exc:
        main(["--preset", "中性"])
    assert exc.value.code == 2
    assert "inputs" in capsys.readouterr().err


def test_inputs_are_optional_at_parse_time():
    args = build_parser().parse_args(["--list-presets"])
    assert args.inputs == []
