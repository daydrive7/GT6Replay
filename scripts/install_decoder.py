"""Include the standalone utility in a freshly built viewer folder."""

from pathlib import Path
import argparse
import shutil

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("distpath", type=Path)
    args = parser.parse_args()
    distribution = args.distpath.resolve()
    if not distribution.is_relative_to(ROOT) or distribution == ROOT:
        raise ValueError("Distribution must be a directory inside the project.")
    source = distribution / "GT6ReplayDecoder"
    target = distribution / "GT6Replay" / "Decoder"
    if (
        not (source / "GT6ReplayDecoder.exe").is_file()
        or not (target.parent / "GT6Replay.exe").is_file()
    ):
        raise ValueError("Build both programs before installing the decoder.")
    shutil.copytree(source, target, dirs_exist_ok=True)
    print("Standalone decoder included in viewer folder.")


if __name__ == "__main__":
    main()
