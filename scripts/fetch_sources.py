"""Fetch matching unmodified Qt/PySide sources and preserve their notices."""

from pathlib import Path
import hashlib, json, urllib.request, urllib.parse, html.parser, tarfile

ROOT = Path(__file__).resolve().parents[1]


class Links(html.parser.HTMLParser):
    def __init__(self):
        super().__init__()
        self.links = []

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            for key, value in attrs:
                if key == "href":
                    self.links.append(value)


def main():
    output = ROOT / "release/third-party-sources"
    output.mkdir(parents=True, exist_ok=True)
    base = "https://download.qt.io/official_releases/qt/6.11/6.11.0/submodules/"
    urls = [
        base + module + "-everywhere-src-6.11.0.tar.xz"
        for module in ("qtbase", "qtsvg", "qtimageformats")
    ]
    pyside = "https://download.qt.io/official_releases/QtForPython/pyside6/PySide6-6.11.0-src/"
    parser = Links()
    parser.feed(urllib.request.urlopen(pyside, timeout=30).read().decode("utf-8"))
    source = next(
        link for link in parser.links if link.endswith(".tar.xz") and "pyside" in link.lower()
    )
    urls.append(urllib.parse.urljoin(pyside, source))
    records = []
    for url in urls:
        name = url.rsplit("/", 1)[-1]
        path = output / name
        if not path.exists():
            pending = path.with_suffix(".part")
            with urllib.request.urlopen(url, timeout=60) as response, pending.open("wb") as stream:
                total = 0
                for data in iter(lambda: response.read(1024**2), b""):
                    total += len(data)
                    if total > 100 * 1024**2:
                        raise ValueError("Unexpected source archive size.")
                    stream.write(data)
            pending.replace(path)
        with path.open("rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
        records.append({"file": name, "url": url, "sha256": digest, "bytes": path.stat().st_size})
        count = 0
        with tarfile.open(path) as archive:
            for member in archive.getmembers():
                if not member.isfile() or member.size > 2 * 1024**2:
                    continue
                relative = Path(member.name)
                if ".." in relative.parts or relative.is_absolute():
                    continue
                if not relative.name.upper().startswith(
                    ("LICENSE", "COPYING", "COPYRIGHT", "NOTICE")
                ):
                    continue
                target = ROOT / "LICENSES/Qt-Sources" / name.removesuffix(".tar.xz") / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(archive.extractfile(member).read())
                count += 1
        print(name, path.stat().st_size, "bytes;", count, "notices", flush=True)
    (ROOT / "third-party-sources.json").write_text(
        json.dumps(
            {"qt_version": "6.11.0", "pyside_version": "6.11.0", "sources": records}, indent=2
        )
        + "\n"
    )


if __name__ == "__main__":
    main()
