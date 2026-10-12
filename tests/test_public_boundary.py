import sys, unittest, tempfile, struct, json, hashlib, io, zipfile
from pathlib import Path
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from replay_data import load_replay, ReplayError, EncryptedReplayError
from native_motion import COLUMNS, load_native_replay, find_native_for_input


def fixture():
    data = bytearray(0x800)
    data[:4] = b"RPLY"
    for offset, value in (
        (8, 115),
        (0x210, 0),
        (0x214, 0x600),
        (0x240, 1),
        (0x244, 0x300),
        (0x248, 3),
        (0x264, 0x700),
        (0x27C, 1),
        (0x304, 0x400),
        (0x400, 109),
    ):
        struct.pack_into(">I", data, offset, value)
    struct.pack_into(">H", data, 0x282, 0x74)
    data[0x360:0x367] = b"DriverA"
    return bytes(data)


class BoundaryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_plain_metadata_without_embedded_game_catalogue(self):
        path = self.root / "test.rply"
        path.write_bytes(fixture())
        replay = load_replay(path)
        self.assertEqual(replay["metadata"]["total_frames"], 3)
        self.assertEqual(replay["entries"][0]["name"], "DriverA")
        self.assertEqual(replay["entries"][0]["car_name"], "Car #0")

    def test_encrypted_savedata_requests_external_decoder(self):
        (self.root / "REPLAY.0").write_bytes(b"not a decrypted replay")
        with self.assertRaises(EncryptedReplayError):
            load_replay(self.root)

    def test_truncated_and_unsupported_plain_inputs_are_rejected(self):
        path = self.root / "test.rply"
        path.write_bytes(fixture()[:50])
        with self.assertRaises(ReplayError):
            load_replay(path)
        data = bytearray(fixture())
        struct.pack_into(">I", data, 8, 114)
        path.write_bytes(data)
        with self.assertRaises(ReplayError):
            load_replay(path)

    def test_cache_matches_chunks_in_a_different_folder_by_content(self):
        part = self.root / "REPLAY.0"
        part.write_bytes(b"encrypted fixture")
        digest = hashlib.sha256(part.read_bytes()).hexdigest()
        replay = {
            "native_sha256": "a" * 64,
            "metadata": {"total_frames": 3},
            "entries": [{"slot": 0, "name": "DriverA"}],
            "files": [{"name": "REPLAY.0", "sha256": digest}],
        }
        metadata = {
            "format": "gt6-native-motion-v1",
            "native_sha256": "a" * 64,
            "fps": 60,
            "frame_count": 3,
            "slots": [0],
            "columns": list(COLUMNS),
        }
        motion = np.zeros((3, 1, 13), np.float32)
        with (self.root / "test.gt6r").open("wb") as stream:
            np.savez_compressed(
                stream,
                motion=motion,
                metadata=np.array(json.dumps(metadata)),
                replay=np.array(json.dumps(replay)),
            )
        self.assertIsNotNone(find_native_for_input(part, [self.root]))
        part.write_bytes(b"different replay")
        self.assertIsNone(find_native_for_input(part, [self.root]))

    def test_forged_array_shape_is_rejected_before_allocation(self):
        stream = io.BytesIO()
        np.lib.format.write_array_header_1_0(
            stream, {"descr": "<f4", "fortran_order": False, "shape": (10**12, 1, 13)}
        )
        path = self.root / "bad.gt6r"
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr("motion.npy", stream.getvalue())
            archive.writestr("metadata.npy", b"x")
            archive.writestr("replay.npy", b"x")
        with self.assertRaisesRegex(ValueError, "size"):
            load_native_replay(path)

    def test_missing_input_is_not_resolved_to_a_neighbouring_save(self):
        (self.root / "REPLAY.0").write_bytes(b"fixture")
        self.assertIsNone(find_native_for_input(self.root / "missing.file", [self.root]))


if __name__ == "__main__":
    unittest.main()
