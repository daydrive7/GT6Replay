"""Standalone desktop and command-line entry point."""

from pathlib import Path
import sys


def main():
    arguments = sys.argv[1:]
    if "--cli" in arguments:
        arguments.remove("--cli")
        from decoder.cli import main as cli_main

        return cli_main(arguments)
    if (
        arguments
        and "--gui" not in arguments
        or Path(sys.executable).stem.casefold().endswith("decodercli")
    ):
        from decoder.cli import main as cli_main

        return cli_main(arguments if arguments else ["--help"])
    if "--gui" in arguments:
        arguments.remove("--gui")
    from decoder.gui import main as gui_main

    return gui_main(arguments)


if __name__ == "__main__":
    sys.exit(main())
