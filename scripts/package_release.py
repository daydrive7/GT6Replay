from pathlib import Path
import json, zipfile, hashlib, shutil, sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from version import VERSION
from audit_release import audit_source, audit_package, source_files


def main():
    program = ROOT / "dist/GT6Replay"
    audit_source()
    audit_package(program)
    sources = json.loads((ROOT / "third-party-sources.json").read_text())["sources"]
    for record in sources:
        path = ROOT / "release/third-party-sources" / record["file"]
        with path.open("rb") as stream:
            assert hashlib.file_digest(stream, "sha256").hexdigest() == record["sha256"]
    for name in ("README.md", "LICENSE", "THIRD_PARTY.md", "PRIVACY.md", "RELEASE_NOTES.md"):
        shutil.copy2(ROOT / name, program / name)
    output = ROOT / "release"
    output.mkdir(exist_ok=True)
    windows = output / f"GT6Replay-{VERSION}-windows-x64.zip"
    with zipfile.ZipFile(windows, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for path in program.rglob("*"):
            if path.is_file():
                archive.write(path, Path("GT6Replay") / path.relative_to(program))
    source = output / f"GT6Replay-{VERSION}-source.zip"
    with zipfile.ZipFile(source, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in source_files():
            archive.write(path, Path("GT6Replay") / path.relative_to(ROOT))
    lines = []
    for path in [windows, source] + [
        ROOT / "release/third-party-sources" / r["file"] for r in sources
    ]:
        with path.open("rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
        lines.append(digest + "  " + path.name)
    (output / "SHA256SUMS.txt").write_text("\n".join(lines) + "\n")
    print(windows)
    print(source)


if __name__ == "__main__":
    main()
