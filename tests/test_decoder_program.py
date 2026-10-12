import contextlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

os.environ["QT_QPA_PLATFORM"] = "offscreen"
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))
from decoder.cli import main as cli_main
from decoder.operations import export_input, inspect_input, MotionUnavailableError
from decoder.settings import configure_key_file, load_keys, key_file_path, clear_key_file
from decoder.gui import DecoderWindow
from PySide6.QtWidgets import QApplication
from local_converter import find_decoder_program, launch_decoder, has_motion_converter
from smoke_decoder import replay_fixture
from audit_release import contains_key_configuration
from test_decoder import encryption_fixture, pfd_fixture


class ProgramTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.application = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.directory = Path(self.temporary.name)
        self.environment = patch.dict(
            os.environ,
            {
                "LOCALAPPDATA": str(self.directory / "local"),
                "GT6REPLAY_KEY_FILE": "",
                "GT6REPLAY_DECODER": "",
            },
        )
        self.environment.start()
        self.source = self.directory / "original"
        self.source.mkdir()
        self.plaintext = replay_fixture()
        keys, ciphertext, record = encryption_fixture(self.plaintext)
        (self.source / "REPLAY.0").write_bytes(ciphertext)
        (self.source / "PARAM.PFD").write_bytes(pfd_fixture([record]))
        self.keys = self.directory / "keys.json"
        self.keys.write_text(
            json.dumps(
                {"portability_key": keys.portability.hex(), "secure_file_id": keys.file_id.hex()}
            )
        )
        self.key_values = keys

    def tearDown(self):
        self.environment.stop()
        self.temporary.cleanup()

    def test_shared_settings_contain_only_key_file_location(self):
        configure_key_file(self.keys)
        self.assertEqual(key_file_path(), self.keys.resolve())
        self.assertEqual(load_keys(), self.key_values)
        text = (self.directory / "local/GT6Replay/settings.json").read_text()
        self.assertNotIn(self.key_values.file_id.hex(), text)
        self.assertNotIn(self.key_values.portability.hex(), text)
        clear_key_file()
        self.assertIsNone(key_file_path())
        self.assertTrue(self.keys.is_file())

    def test_package_audit_detects_key_files(self):
        self.assertTrue(contains_key_configuration(self.keys))
        ordinary = self.directory / "ordinary.json"
        ordinary.write_text(json.dumps({"version": "test"}))
        self.assertFalse(contains_key_configuration(ordinary))

    def test_key_validation_does_not_echo_secret_values(self):
        self.keys.write_text(
            json.dumps({"portability_key": "private-secret", "secure_file_id": "abc"})
        )
        with self.assertRaises(ValueError) as error:
            load_keys(self.keys)
        self.assertNotIn("private-secret", str(error.exception))

    def test_real_program_exports_rply_and_reports_without_touching_sources(self):
        original = {path.name: path.read_bytes() for path in self.source.iterdir()}
        output = self.directory / "replay.rply"
        report = export_input(self.source, output, key_file=self.keys)
        self.assertEqual(output.read_bytes(), self.plaintext)
        self.assertFalse(report["capabilities"]["motion_archive"])
        self.assertEqual(report["motion_index"]["encoding_slots"], 1)
        json_output = self.directory / "race.json"
        export_input(output, json_output, "report")
        self.assertEqual(
            json.loads(json_output.read_text())["replay"]["entries"][0]["name"], "Synthetic driver"
        )
        self.assertEqual(original, {path.name: path.read_bytes() for path in self.source.iterdir()})

    def test_original_folder_and_existing_outputs_are_protected(self):
        with self.assertRaises(ValueError):
            export_input(self.source, self.source / "export.rply", key_file=self.keys)
        output = self.directory / "export.rply"
        output.write_bytes(b"keep this file")
        with self.assertRaises(ValueError):
            export_input(self.source, output, key_file=self.keys)
        self.assertEqual(output.read_bytes(), b"keep this file")
        export_input(self.source, output, key_file=self.keys, overwrite=True)
        self.assertEqual(output.read_bytes(), self.plaintext)
        self.assertEqual(list(self.directory.glob(".gt6-export-*")), [])

    def test_motion_failure_creates_no_archive(self):
        output = self.directory / "race.gt6r"
        with self.assertRaises(MotionUnavailableError):
            export_input(self.source, output, "motion", self.keys)
        self.assertFalse(output.exists())

    def test_cli_reports_capabilities_and_unsupported_conversion(self):
        stream = io.StringIO()
        with contextlib.redirect_stdout(stream):
            self.assertEqual(cli_main(["--capabilities"]), 0)
        self.assertFalse(json.loads(stream.getvalue())["motion_archive"])
        errors = io.StringIO()
        with contextlib.redirect_stderr(errors):
            code = cli_main(
                ["--input", str(self.source), "--output", str(self.directory / "race.gt6r")]
            )
        self.assertEqual(code, 3)
        self.assertIn("not available", errors.getvalue())

    def test_cli_entry_point_exports_a_protected_folder(self):
        output = self.directory / "race.rply"
        result = subprocess.run(
            [
                sys.executable,
                str(ROOT / "src/decoder_program.py"),
                "--cli",
                "--input",
                str(self.source),
                "--keys",
                str(self.keys),
                "--output",
                str(output),
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(output.read_bytes(), self.plaintext)

    def test_desktop_preview_and_available_formats(self):
        window = DecoderWindow()
        report = inspect_input(self.source, self.keys)[1]
        window.show_report(report)
        self.assertEqual(window.table.item(0, 1).text(), "Synthetic driver")
        self.assertEqual(
            [window.format.itemData(i) for i in range(window.format.count())], ["rply", "report"]
        )
        window.close()

    def test_decoder_discovery_and_launch_from_viewer_package(self):
        directory = self.directory / "viewer"
        helper = directory / "Decoder/GT6ReplayDecoder.exe"
        helper.parent.mkdir(parents=True)
        helper.write_bytes(b"synthetic executable name only")
        self.assertEqual(find_decoder_program(directory), [str(helper)])
        with patch("local_converter.subprocess.Popen") as popen:
            launch_decoder(directory)
            self.assertEqual(popen.call_args.args[0], [str(helper)])
        self.assertFalse(has_motion_converter())

    def test_source_launch_requires_no_built_viewer(self):
        command = find_decoder_program(ROOT / "src")
        self.assertEqual(command, [sys.executable, str(ROOT / "src/decoder_program.py"), "--gui"])


if __name__ == "__main__":
    unittest.main()
