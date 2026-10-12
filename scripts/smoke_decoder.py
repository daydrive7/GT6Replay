"""Verify standalone executables with synthetic protected data and no Python PATH."""

from pathlib import Path
import argparse
import json
import os
import struct
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))
from test_decoder import encryption_fixture, pfd_fixture


def replay_fixture():
    data = bytearray(0xA00)
    data[:4] = b"RPLY"
    for offset, value in (
        (8, 115),
        (0x210, 0),
        (0x214, 0x400),
        (0x240, 1),
        (0x244, 0x300),
        (0x248, 3),
        (0x264, 0x500),
        (0x27C, 1),
        (0x28C, 2),
        (0x294, 0x480),
        (0x304, 0x380),
        (0x380, 109),
    ):
        struct.pack_into(">I", data, offset, value)
    struct.pack_into(">3I", data, 0x10, 21, 17, 49)
    struct.pack_into(">H", data, 0x282, 0x74)
    struct.pack_into(">4I", data, 0x480, 0x7D2, 0, 0x900, 3)
    data[0x360:0x370] = b"Synthetic driver"
    data[0x500] = 1
    data[0x7D2] = 0x80
    return bytes(data)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("program", type=Path)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    program = args.program.resolve()
    cli, gui = program / "GT6ReplayDecoderCLI.exe", program / "GT6ReplayDecoder.exe"
    with tempfile.TemporaryDirectory(prefix="gt6-decoder-check-") as temporary:
        directory = Path(temporary)
        export = directory / "original"
        export.mkdir()
        plaintext = replay_fixture()
        keys, encrypted, record = encryption_fixture(plaintext)
        (export / "REPLAY.0").write_bytes(encrypted)
        (export / "PARAM.PFD").write_bytes(pfd_fixture([record]))
        config = directory / "keys.json"
        config.write_text(
            json.dumps(
                {"portability_key": keys.portability.hex(), "secure_file_id": keys.file_id.hex()}
            )
        )
        environment = os.environ.copy()
        environment["PATH"] = str(Path(os.environ.get("SystemRoot", "C:/Windows")) / "System32")
        environment["LOCALAPPDATA"] = str(directory / "settings")
        for name in ("PYTHONPATH", "PYTHONHOME", "GT6REPLAY_KEY_FILE", "GT6REPLAY_DECODER"):
            environment.pop(name, None)

        def invoke(executable, *arguments):
            return subprocess.run(
                [str(executable), *map(str, arguments)],
                cwd=directory,
                env=environment,
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=60,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )

        capabilities = invoke(cli, "--capabilities")
        assert capabilities.returncode == 0, capabilities.stderr
        assert json.loads(capabilities.stdout)["motion_archive"] is False
        output = directory / "decoded.rply"
        decoded = invoke(cli, "--input", export, "--keys", config, "--output", output)
        assert decoded.returncode == 0, decoded.stderr
        assert output.read_bytes() == plaintext
        inspect = invoke(cli, "--input", output, "--inspect")
        assert inspect.returncode == 0, inspect.stderr
        report = json.loads(inspect.stdout)
        assert report["motion_index"]["seek_segments"] == 1
        assert report["replay"]["entries"][0]["name"] == "Synthetic driver"
        archive = directory / "unsupported.gt6r"
        unsupported = invoke(cli, "--input", export, "--keys", config, "--output", archive)
        assert unsupported.returncode == 3 and not archive.exists(), unsupported.stderr
        preview = directory / "gui.json"
        desktop = invoke(gui, "--gui", "--verify-gui", preview)
        assert desktop.returncode == 0 and preview.is_file(), desktop.stderr
        assert json.loads(preview.read_text())["standalone_gui"]
        assert (export / "REPLAY.0").read_bytes() == encrypted
        assert (export / "PARAM.PFD").read_bytes() == pfd_fixture([record])
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(
            json.dumps(
                {
                    "standalone_gui": True,
                    "cli_capabilities": True,
                    "encrypted_export_exact": True,
                    "metadata_inspection": True,
                    "original_files_unchanged": True,
                    "motion_request_rejected": True,
                    "no_python_on_path": True,
                },
                indent=2,
            )
        )
        import shutil

        shutil.copyfile(preview.with_suffix(".png"), args.report.with_suffix(".png"))
    print("Standalone decoder executable checks passed.")


if __name__ == "__main__":
    main()
