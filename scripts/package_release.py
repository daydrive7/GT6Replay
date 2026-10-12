from pathlib import Path
import argparse, json, zipfile, hashlib, shutil, sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from version import VERSION
from audit_release import audit_source, audit_package, source_files


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--distpath", type=Path, default=ROOT / "dist")
    parser.add_argument(
        "--outputpath", type=Path, default=ROOT / ("release-dev" if "-" in VERSION else "release")
    )
    parser.add_argument("--decoder-only", action="store_true")
    args = parser.parse_args()
    distribution, output = args.distpath.resolve(), args.outputpath.resolve()
    for target in (distribution, output):
        if not target.is_relative_to(ROOT) or target == ROOT:
            raise ValueError("Package paths must stay inside this project.")
    programs = ["GT6ReplayDecoder"] if args.decoder_only else ["GT6Replay", "GT6ReplayDecoder"]
    audit_source()
    sources = json.loads((ROOT / "third-party-sources.json").read_text())["sources"]
    for record in sources:
        path = ROOT / "release/third-party-sources" / record["file"]
        with path.open("rb") as stream:
            assert hashlib.file_digest(stream, "sha256").hexdigest() == record["sha256"]
    output.mkdir(exist_ok=True)
    source_assets = []
    for record in sources:
        original = ROOT / "release/third-party-sources" / record["file"]
        target = output / "third-party-sources" / record["file"]
        if original.resolve() != target.resolve():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(original, target)
        source_assets.append(target)
    artifacts = []
    for name in programs:
        program = distribution / name
        if not (program / (name + ".exe")).is_file():
            raise ValueError(f"Build {name} before packaging it.")
        audit_package(program)
        for notice in ("LICENSE", "THIRD_PARTY.md", "PRIVACY.md", "RELEASE_NOTES.md"):
            shutil.copy2(ROOT / notice, program / notice)
        shutil.copy2(
            ROOT / ("docs/decoder.md" if name == "GT6ReplayDecoder" else "README.md"),
            program / "README.md",
        )
        windows = output / f"{name}-{VERSION}-windows-x64.zip"
        with zipfile.ZipFile(windows, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
            for path in program.rglob("*"):
                if path.is_file():
                    archive.write(path, Path(name) / path.relative_to(program))
        artifacts.append(windows)
    source = output / f"GT6Replay-{VERSION}-source.zip"
    with zipfile.ZipFile(source, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in source_files():
            archive.write(path, Path("GT6Replay") / path.relative_to(ROOT))
    lines = []
    for path in artifacts + [source] + source_assets:
        with path.open("rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
        lines.append(digest + "  " + path.name)
    (output / "SHA256SUMS.txt").write_text("\n".join(lines) + "\n")
    for artifact in artifacts:
        print(artifact)
    print(source)


if __name__ == "__main__":
    main()
