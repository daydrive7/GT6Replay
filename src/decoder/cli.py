"""Command-line interface for GT6Replay Decoder."""

import argparse
import json
import sys
from pathlib import Path

from version import VERSION


def main(arguments=None):
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(prog="GT6ReplayDecoderCLI")
    parser.add_argument("--version", action="version", version=f"GT6Replay Decoder {VERSION}")
    parser.add_argument("--capabilities", action="store_true")
    parser.add_argument("--input", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--keys", type=Path, help="Local savedata key configuration.")
    parser.add_argument("--format", choices=("rply", "report", "motion"), default=None)
    parser.add_argument(
        "--inspect", action="store_true", help="Print race information without exporting."
    )
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args(arguments)
    from .operations import CAPABILITIES, export_input, inspect_input, MotionUnavailableError
    from .bitstream import DecodeError

    if args.capabilities:
        print(json.dumps({"program": "GT6Replay Decoder", "version": VERSION, **CAPABILITIES}))
        return 0
    if not args.input:
        parser.error("--input is required unless --capabilities or --version is used")
    try:
        if args.inspect:
            if args.output or args.format:
                parser.error("--inspect does not take --output or --format")
            _, report = inspect_input(args.input, args.keys)
            print(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False))
        else:
            if not args.output:
                parser.error("--output is required for an export")
            mode = args.format or (
                "motion"
                if args.output.suffix.lower() in (".gt6r", ".part")
                else "report" if args.output.suffix.lower() == ".json" else "rply"
            )
            export_input(
                args.input,
                args.output,
                mode,
                args.keys,
                args.overwrite,
                lambda message: print(message, file=sys.stderr, flush=True),
            )
            print(f"Exported {args.output}")
        return 0
    except MotionUnavailableError as error:
        print(str(error), file=sys.stderr)
        return 3
    except (DecodeError, ValueError, OSError) as error:
        print(str(error), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
