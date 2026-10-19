"""Command line entry point: `bsv song.mp3 --preset 中文流行 -o out.wav`"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from bsv.analysis import analyze
from bsv.pipeline import export, open_project
from bsv.presets import PRESETS, Params
from bsv.separate import DEFAULT_MODEL


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="bsv",
        description="One-click Suno vocal & arrangement fix.",
    )
    parser.add_argument("inputs", nargs="*", help="audio files (.mp3/.flac/.wav/.webm/...)")
    parser.add_argument("--preset", default="中性 (只修问题)", help=f"one of: {', '.join(PRESETS)}")
    parser.add_argument("-o", "--output", default=None, help="output path (default: <name>_fixed.wav)")
    parser.add_argument("--format", default="wav", choices=["wav", "flac", "mp3"])
    parser.add_argument("--model", default=DEFAULT_MODEL, help="demucs model name")
    parser.add_argument("--device", default=None, help="cuda or cpu")
    parser.add_argument("--no-separate", action="store_true", help="skip stem separation")
    parser.add_argument("--lufs", type=float, default=None)
    parser.add_argument("--vocal-gain", type=float, default=None)
    parser.add_argument("--music-gain", type=float, default=None)
    parser.add_argument("--duck", type=float, default=None)
    parser.add_argument("--deesser", type=float, default=None)
    parser.add_argument("--space", type=float, default=None, help="reverb wet level 0.0-0.4 (0 = keep the original space)")
    parser.add_argument("--doubling", type=float, default=None, help="vocal doubling level in dB (-60 = off)")
    parser.add_argument("--list-presets", action="store_true")
    return parser


def apply_overrides(params: Params, args: argparse.Namespace) -> Params:
    if args.lufs is not None:
        params.target_lufs = args.lufs
    if args.vocal_gain is not None:
        params.vocal_gain_db = args.vocal_gain
    if args.music_gain is not None:
        params.music_gain_db = args.music_gain
    if args.duck is not None:
        params.duck_db = args.duck
    if args.deesser is not None:
        params.deesser_amount = args.deesser
    if args.space is not None:
        params.reverb_wet = args.space
    if args.doubling is not None:
        params.doubling_db = args.doubling
    return params


def resolve_preset(name: str) -> str | None:
    """Accept the full preset name or an unambiguous prefix (`中性` -> `中性 (只修问题)`)."""
    if name in PRESETS:
        return name
    matches = [key for key in PRESETS if key.startswith(name)]
    if len(matches) == 1:
        return matches[0]
    folded = name.casefold()
    matches = [key for key in PRESETS if key.casefold().startswith(folded)]
    return matches[0] if len(matches) == 1 else None


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.list_presets:
        for name in PRESETS:
            print(name)
        return 0

    preset = resolve_preset(args.preset)
    if preset is None:
        print(f"unknown preset: {args.preset} (use --list-presets)")
        return 2
    if not args.inputs:
        build_parser().error("the following arguments are required: inputs")

    params = apply_overrides(PRESETS[preset], args)

    for raw in args.inputs:
        path = Path(raw)
        if not path.exists():
            print(f"skip: {path} not found")
            continue

        print(f"== {path.name}")
        project = open_project(path, model=args.model, device=args.device,
                               force_separate=not args.no_separate,
                               progress_cb=lambda p, msg: print(f"  {msg} ({p:.0f}%)", flush=True))
        result = project.render(params)
        stats = analyze(project.vocal, project.music, project.sr) if project.has_stems else {}

        out = Path(args.output) if args.output and len(args.inputs) == 1 else path.with_name(f"{path.stem}_fixed.{args.format}")
        export(result, out, project.sr, args.format)

        print(f"  stems: {'yes' if project.has_stems else 'no (whole-mix fallback)'}")
        print(f"  loudness: {result.lufs_before:.1f} -> {result.lufs_after:.1f} LUFS")
        print(f"  peak:     {result.peak_before_db:.1f} -> {result.peak_after_db:.1f} dBFS")
        if stats:
            print(f"  vocal/music ratio: {stats['vocal_music_ratio_db']:.1f} dB "
                  f"(max sibilance {stats['sibilance_max_db']:.1f} dB, "
                  f"max band overlap {stats['overlap_max_db']:.1f} dB)")
            for kind, regions in stats["regions"].items():
                if regions:
                    spots = ", ".join(f"{r['time']:.1f}s" for r in regions)
                    print(f"  hot spots ({kind}): {spots}")
        print(f"  wrote: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
