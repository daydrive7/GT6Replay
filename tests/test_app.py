"""UI integration tests use synthetic motion; no demo is shipped as a real replay."""

import os

os.environ["QT_QPA_PLATFORM"] = "offscreen"
import sys
import unittest
from pathlib import Path
from unittest.mock import patch
from types import SimpleNamespace
import numpy as np
from PySide6.QtCore import Qt, QPoint, QPointF
from PySide6.QtTest import QTest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from app import QApplication, MainWindow, STYLE, load_replay
from native_motion import NativeReplay


class AppTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.application = QApplication.instance() or QApplication([])
        cls.application.setStyleSheet(STYLE)

    def setUp(self):
        self.window = MainWindow()

    def tearDown(self):
        self.window.dirty_capture = False
        self.window.close()

    def frames(self):
        return [
            {
                "time_seconds": i / 60,
                "x": i * 1.2,
                "y": 3,
                "z": i * 0.8,
                "speed_kmh": 200,
                "rpm": 7000,
                "gear": 4,
                "lap": 1,
                "throttle": 0.8,
                "brake": 0,
            }
            for i in range(120)
        ]

    def test_play_seek_and_end(self):
        self.window.set_frames(self.frames())
        self.assertTrue(self.window.play_button.isEnabled())
        self.window.seek(5000)
        self.assertAlmostEqual(self.window.play_time, 119 / 120)
        self.window.toggle_play()
        self.assertTrue(self.window.playing)
        self.window.last_tick -= 10
        self.window.tick()
        self.assertFalse(self.window.playing)
        self.assertEqual(self.window.index, 119)
        self.window.restart()
        self.assertEqual(self.window.index, 0)

    def test_race_labels_render_untrusted_text_as_plain_text(self):
        replay = {
            "metadata": {"track": "<b>Track</b>", "event": '<img src="invalid">'},
            "entries": [{"slot": 0, "name": "DriverA", "position": 1}],
        }
        self.window.save_loaded(replay)
        self.assertEqual(self.window.track_label.textFormat(), Qt.PlainText)
        self.assertEqual(self.window.event_label.textFormat(), Qt.PlainText)
        self.assertEqual(self.window.track_label.text(), "<b>Track</b>")

    def test_reopening_native_replay_restores_selected_driver_and_playback(self):
        replay = {
            "source_path": "sample",
            "metadata": {"driver": "TestDriver", "total_frames": 120},
            "entries": [{"slot": 0, "name": "TestDriver", "position": 1}],
            "decode_reason": "Decoded native motion",
        }
        frames = self.frames()
        native = SimpleNamespace(
            metadata={"frame_count": 120, "fps": 60, "slots": [0], "native_sha256": "a" * 64},
            replay=replay,
            path=Path("sample.gt6r"),
            frames_for_slot=lambda *args: frames,
        )
        for _ in range(2):
            self.window.save_loaded(replay, native)
            self.assertEqual(len(self.window.frames), 120)
            self.assertTrue(self.window.play_button.isEnabled())
            self.window.seek(5000)
            self.window.toggle_play()
            self.assertTrue(self.window.playing)

    def test_all_cars_share_race_clock_and_retired_car_disappears(self):
        replay = {
            "source_path": "sample",
            "metadata": {"driver": "LiveDriver", "total_frames": 5},
            "entries": [
                {"slot": 0, "name": "LiveDriver", "position": 1},
                {"slot": 1, "name": "RetiredDriver", "position": 2},
            ],
            "decode_reason": "Decoded native motion",
        }
        motion = np.zeros((5, 2, 13), np.float32)
        motion[:, :, 9] = 1
        motion[:, :, 10] = 800
        motion[:, :, 11] = 2
        motion[:, 0, 0] = np.arange(5)
        motion[:, 1, 0] = np.arange(5) + 10
        motion[2:, 1, :] = np.nan
        native = NativeReplay(
            "sample.gt6r",
            motion,
            {"frame_count": 5, "fps": 60, "slots": [0, 1], "native_sha256": "a" * 64},
            replay,
        )
        self.window.save_loaded(replay, native)
        self.assertTrue(self.window.all_cars.isChecked())
        self.assertEqual(len(self.window.map_view.visible_cars()), 2)
        self.window.seek(7500)
        time = self.window.play_time
        self.window.entries_table.selectRow(1)
        self.assertAlmostEqual(self.window.play_time, time)
        self.assertAlmostEqual(self.window.duration, 4 / 60)
        visible = self.window.map_view.visible_cars()
        self.assertEqual([car[0]["slot"] for car in visible], [0])
        self.assertEqual(self.window.instruments["rpm"].text(), "—")
        self.window.all_cars.setChecked(False)
        self.assertFalse(self.window.map_view.visible_cars())
        self.window.all_cars.setChecked(True)
        self.assertEqual(len(self.window.view3d.visible_cars()), 1)

    def test_pan_zoom_anchor_and_fit_in_both_views(self):
        self.window.set_frames(self.frames())
        self.window.show()
        for tab, view in [(0, self.window.map_view), (1, self.window.view3d)]:
            self.window.tabs.setCurrentIndex(tab)
            self.application.processEvents()
            before = view.project(12, 3, 8)
            QTest.mousePress(view, Qt.LeftButton, pos=QPoint(100, 100))
            QTest.mouseMove(view, QPoint(160, 140))
            QTest.mouseRelease(view, Qt.LeftButton, pos=QPoint(160, 140))
            after = view.project(12, 3, 8)
            self.assertAlmostEqual(after.x() - before.x(), 60)
            self.assertAlmostEqual(after.y() - before.y(), 40)
            view.zoom_at(2, after)
            zoomed = view.project(12, 3, 8)
            self.assertAlmostEqual(zoomed.x(), after.x())
            self.assertAlmostEqual(zoomed.y(), after.y())
            self.assertEqual(view.zoom, 2)
            view.reset_camera()
            self.assertEqual(view.pan, QPointF())
            self.assertEqual(view.zoom, 1)
            if view.perspective:
                yaw = view.yaw
                pan = QPointF(view.pan)
                QTest.mousePress(view, Qt.RightButton, pos=QPoint(100, 100))
                QTest.mouseMove(view, QPoint(140, 120))
                QTest.mouseRelease(view, Qt.RightButton, pos=QPoint(140, 120))
                self.assertNotEqual(view.yaw, yaw)
                self.assertEqual(view.pan, pan)

    def test_capture_validation(self):
        data = {"format": "gt6-telemetry-v1", "frames": self.frames()}
        self.assertEqual(len(MainWindow.validate_capture(data)), 120)
        data["frames"][10]["time_seconds"] = -1
        with self.assertRaises(ValueError):
            MainWindow.validate_capture(data)
        data["frames"][10]["time_seconds"] = 10 / 60
        data["frames"][4]["x"] = float("nan")
        with self.assertRaises(ValueError):
            MainWindow.validate_capture(data)

    def test_record_status_and_incremental_capture(self):
        class Recorder:
            def status(self):
                return {"error": None, "packets": 20, "last_packet": {"loading": True}}

            def snapshot(self, since=0):
                return {"frames": []}

        self.window.recorder = Recorder()
        self.window.tick()
        self.assertIn("Connected", self.window.status_label.text())
        self.window.recorder = None

    def test_live_motion_matches_recorder_contract(self):
        frames = self.frames()

        class Recorder:
            def status(self):
                return {"error": None, "packets": len(frames), "last_packet": frames[-1]}

            def snapshot(self, since=0):
                return {"frames": frames[since:]}

        self.window.recorder = Recorder()
        self.window.tick()
        self.assertEqual(len(self.window.frames), 120)
        self.window.last_live_refresh = 0
        self.window.tick()
        self.assertEqual(len(self.window.frames), 120)
        self.assertEqual(self.window.index, 119)
        self.window.recorder = None

    def test_render_synthetic_3d(self):
        self.window.set_frames(self.frames())
        self.window.tabs.setCurrentIndex(1)
        self.window.show()
        self.application.processEvents()
        pixmap = self.window.grab()
        self.assertFalse(pixmap.isNull())
        self.assertGreater(pixmap.width(), 1000)

    def test_motion_background_reused_for_playback_and_invalidated_for_view_changes(self):
        self.window.set_frames(self.frames())
        view = self.window.map_view
        background = view._static_background()
        view.index = 60
        self.assertIs(view._static_background(), background)
        view.zoom = 2
        zoomed = view._static_background()
        self.assertIsNot(zoomed, background)
        view.resize(view.width() + 15, view.height())
        resized = view._static_background()
        self.assertIsNot(resized, zoomed)
        view.set_frames([])
        cleared = view._static_background()
        self.assertIsNot(cleared, resized)
        self.assertFalse(cleared.isNull())

    def test_trace_updates_after_recorder_extends_same_list(self):
        frames = self.frames()
        trace = self.window.trace
        trace.frames = frames
        background = trace._static_background()
        trace.index = 60
        self.assertIs(trace._static_background(), background)
        frames.append(dict(frames[-1], time_seconds=2.1, speed_kmh=310))
        extended = trace._static_background()
        self.assertIsNot(extended, background)
        self.assertEqual(trace._maximum, 310)
        self.assertEqual(trace._duration, 2.1)
        trace.resize(trace.width() + 15, trace.height())
        self.assertIsNot(trace._static_background(), extended)
        trace.frames = []
        self.assertFalse(trace._static_background().isNull())
        self.assertFalse(trace._points)

    def test_long_static_path_sampling_retains_full_motion(self):
        frames = [dict(self.frames()[0], time_seconds=index / 60, x=index) for index in range(4000)]
        view = self.window.map_view
        view.set_frames(frames)
        self.assertIs(view.frames, frames)
        self.assertLessEqual(len(view.path), 1800)
        self.assertEqual(len(view.frames), 4000)


if __name__ == "__main__":
    unittest.main()
