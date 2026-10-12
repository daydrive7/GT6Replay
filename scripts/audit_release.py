from pathlib import Path
import argparse, re

ROOT = Path(__file__).resolve().parents[1]
FORBIDDEN_SUFFIX = {".gt6r", ".rply", ".self", ".elf", ".pfd", ".sfo", ".bin"}
PATTERNS = [
    r"C:\\Users\\[^\\\s]+",
    r"192\.168\.\d+\.\d+",
    r"\b_SYSCON_KEY\b",
    r"\b_SECURE_FILE_ID\b",
]


def source_files():
    for directory in ("src", "tests", "scripts", "docs", ".github", "LICENSES"):
        for path in (ROOT / directory).rglob("*"):
            if path.is_file() and "__pycache__" not in path.parts and path.name != "icon.ico":
                yield path
    for path in ROOT.iterdir():
        if path.is_file():
            yield path


def audit_source():
    errors = []
    count = 0
    for path in source_files():
        count += 1
        if path.suffix.lower() in FORBIDDEN_SUFFIX:
            errors.append(str(path.relative_to(ROOT)))
        if (
            "LICENSES" in path.parts
            or path.name.endswith("LICENSE.txt")
            or path.name == "audit_release.py"
        ):
            continue
        if path.suffix.lower() in (".py", ".md", ".yml", ".yaml", ".txt", ".json", ".toml", ".ps1"):
            for pattern in PATTERNS:
                if re.search(pattern, path.read_text(encoding="utf-8")):
                    errors.append(str(path.relative_to(ROOT)) + ": private content pattern")
    if errors:
        raise ValueError("\n".join(errors))
    print("Source audit passed:", count, "files")


def audit_package(directory):
    allowed_qt = {
        "qt6core.dll",
        "qt6gui.dll",
        "qt6widgets.dll",
        "qt6network.dll",
        "qt6opengl.dll",
        "qt6svg.dll",
    }
    errors = []
    count = 0
    for path in Path(directory).rglob("*"):
        if not path.is_file():
            continue
        count += 1
        if path.suffix.lower() in FORBIDDEN_SUFFIX or re.fullmatch(r"REPLAY\.\d+", path.name, re.I):
            errors.append(str(path))
        if (
            path.name.lower().startswith("qt6")
            and path.suffix.lower() == ".dll"
            and path.name.lower() not in allowed_qt
        ):
            errors.append("Unexpected Qt module: " + path.name)
        if any(
            part in ("Native", "Captures", "Downloads")
            for part in path.relative_to(directory).parts
        ):
            errors.append("User data directory: " + str(path))
    if errors:
        raise ValueError("\n".join(errors))
    print("Package audit passed:", count, "files")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--package", type=Path)
    args = parser.parse_args()
    audit_source()
    if args.package:
        audit_package(args.package.resolve())


if __name__ == "__main__":
    main()
