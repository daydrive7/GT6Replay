import unittest, tempfile, json, sys
from pathlib import Path
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from native_motion import COLUMNS, load_native_replay, find_native_replay


class NativeMotionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "test.gt6r"
        self.meta = {
            "format": "gt6-native-motion-v1",
            "native_sha256": "a" * 64,
            "fps": 60,
            "frame_count": 3,
            "columns": list(COLUMNS),
            "slots": [0, 5],
        }
        self.replay = {
            "native_sha256": "a" * 64,
            "metadata": {"total_frames": 3},
            "entries": [{"slot": 0, "name": "DriverA"}, {"slot": 5, "name": "DriverB"}],
        }
        self.data = np.zeros((3, 2, len(COLUMNS)), np.float32)
        self.data[:, :, 9] = 1
        self.data[:, 0, 0] = [0, 1, 2]
        self.data[:, 0, 3] = 10
        self.data[:, :, 10] = 800
        self.data[:, :, 11] = 2

    def tearDown(self):
        self.tmp.cleanup()

    def write(self):
        with self.path.open("wb") as f:
            np.savez_compressed(
                f,
                motion=self.data,
                metadata=np.array(json.dumps(self.meta)),
                replay=np.array(json.dumps(self.replay)),
            )

    def test_real_time_velocity_and_orientation_fields(self):
        self.write()
        frames = load_native_replay(self.path, "a" * 64).frames_for_slot(0, 744)
        self.assertEqual(len(frames), 3)
        self.assertEqual(frames[1]["packet_id"], 1)
        self.assertAlmostEqual(frames[1]["time_seconds"], 1 / 60)
        self.assertEqual(frames[1]["speed_kmh"], 36)
        self.assertEqual(frames[1]["qw"], 1)
        self.assertEqual(frames[1]["car_code"], 744)
        self.assertNotIn("throttle", frames[1])
        self.assertEqual(frames.coordinate_bounds, (0, 2, 0, 0, 0, 0))

    def test_source_fingerprint_prevents_wrong_replay_attachment(self):
        self.write()
        with self.assertRaisesRegex(ValueError, "different native replay"):
            load_native_replay(self.path, "b" * 64)
        self.assertIsNone(find_native_replay({"native_sha256": "b" * 64}, self.tmp.name))

    def test_missing_car_frames_keep_original_frame_clock(self):
        self.data[1, 0, :] = np.nan
        self.write()
        frames = load_native_replay(self.path).frames_for_slot(0)
        self.assertEqual(len(frames), 2)
        self.assertEqual(frames[1]["packet_id"], 2)
        self.assertAlmostEqual(frames[1]["time_seconds"], 2 / 60)
        self.assertEqual(frames[-1], frames[1])
        self.assertEqual(len(frames[:]), 2)

    def test_wrong_shape_is_rejected(self):
        self.data = self.data[:2]
        self.write()
        with self.assertRaisesRegex(ValueError, "layout"):
            load_native_replay(self.path)

    def test_invalid_instrument_is_rejected(self):
        self.data[1, 0, 10] = np.nan
        self.write()
        with self.assertRaisesRegex(ValueError, "instrument"):
            load_native_replay(self.path)

    def test_repeated_driver_slots_are_rejected(self):
        self.meta["slots"] = [0, 0]
        self.write()
        with self.assertRaisesRegex(ValueError, "slots"):
            load_native_replay(self.path)

    def test_metadata_frame_count_is_verified(self):
        self.replay["metadata"]["total_frames"] = 4
        self.write()
        with self.assertRaisesRegex(ValueError, "race metadata"):
            load_native_replay(self.path)

    def test_unknown_slot_has_no_invented_motion(self):
        self.write()
        self.assertEqual(load_native_replay(self.path).frames_for_slot(4), [])

    def test_missing_entrants_are_rejected_before_ui_load(self):
        self.replay.pop("entries")
        self.write()
        with self.assertRaisesRegex(ValueError, "entrants"):
            load_native_replay(self.path)

    def test_byte_string_metadata_is_supported(self):
        with self.path.open("wb") as stream:
            np.savez_compressed(
                stream,
                motion=self.data,
                metadata=np.array(json.dumps(self.meta).encode()),
                replay=np.array(json.dumps(self.replay).encode()),
            )
        self.assertEqual(len(load_native_replay(self.path).frames_for_slot(0)), 3)


if __name__ == "__main__":
    unittest.main()
