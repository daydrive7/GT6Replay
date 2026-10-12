"""Preserve notices for the decoder's additional runtime dependencies."""

from pathlib import Path
import importlib.metadata
import re
import shutil
import ssl
import urllib.request

from cryptography.hazmat.backends.openssl.backend import backend

ROOT = Path(__file__).resolve().parents[1]


def main():
    for name in ("cryptography", "cffi", "pycparser"):
        distribution = importlib.metadata.distribution(name)
        for relative in distribution.files or ():
            if ".dist-info/licenses/" not in str(relative):
                continue
            source = Path(distribution.locate_file(relative))
            if source.is_file():
                target = ROOT / "LICENSES" / name / source.name
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, target)
    versions = {backend.openssl_version_text().split()[1], ssl.OPENSSL_VERSION.split()[1]}
    for version in sorted(versions):
        if not re.fullmatch(r"\d+\.\d+\.\d+", version):
            raise ValueError("Unrecognized OpenSSL runtime version.")
        target = ROOT / "LICENSES" / "OpenSSL" / version / "LICENSE.txt"
        if not target.exists():
            url = f"https://raw.githubusercontent.com/openssl/openssl/openssl-{version}/LICENSE.txt"
            with urllib.request.urlopen(url, timeout=30) as response:
                content = response.read(100001)
            if len(content) > 100000 or b"Apache License" not in content:
                raise ValueError("Unexpected OpenSSL license file.")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)
    print("Decoder dependency notices collected; OpenSSL", ", ".join(sorted(versions)))


if __name__ == "__main__":
    main()
