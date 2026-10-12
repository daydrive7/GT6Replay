import os, sys, unittest

os.environ["QT_QPA_PLATFORM"] = "offscreen"
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import numpy as np
from app import QApplication, MainWindow
from native_motion import NativeReplay
from PySide6.QtCore import Qt
from PySide6.QtCore import QPoint
from PySide6.QtTest import QTest


class ResultTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.application = QApplication.instance() or QApplication([])

    def setUp(self):
        self.window = MainWindow()
        entries = [
            dict(
                slot=i, name=name, position=pos, best_lap_ms=best, total_time_ms=race, car_name=car
            )
            for i, (name, pos, best, race, car) in enumerate(
                [
                    ("driver2", 2, 61000, 150000, "Car B"),
                    ("Driver10", 10, 60000, 160000, "Car A"),
                    ("Driver1", 1, None, 140000, "Car C"),
                    ("No result", None, 75000, None, None),
                ]
            )
        ]
        replay = {
            "source_path": "fixture",
            "metadata": {"driver": "Driver10", "total_frames": 10},
            "entries": entries,
            "decode_reason": "Decoded motion",
        }
        data = np.zeros((10, 4, 13), np.float32)
        data[:, :, 9] = 1
        data[:, :, 10] = 800
        data[:, :, 11] = 2
        data[:, :, 0] = np.arange(10)[:, None]
        data[:, :, 2] = np.arange(4)[None, :]
        native = NativeReplay(
            "fixture.gt6r",
            data,
            dict(frame_count=10, fps=60, slots=[0, 1, 2, 3], native_sha256="a" * 64),
            replay,
        )
        self.window.save_loaded(replay, native)

    def tearDown(self):
        self.window.close()

    def values(self, column):
        return [self.window.entries_table.item(r, column).value for r in range(4)]

    def test_numeric_sort_and_missing_values_both_directions(self):
        table = self.window.entries_table
        for column, ascending, descending in [
            (0, [1, 2, 10, None], [10, 2, 1, None]),
            (2, [60000, 61000, 75000, None], [75000, 61000, 60000, None]),
            (4, [0, 10000, 20000, None], [20000, 10000, 0, None]),
        ]:
            table.sortItems(column, Qt.AscendingOrder)
            self.assertEqual(self.values(column), ascending)
            table.sortItems(column, Qt.DescendingOrder)
            self.assertEqual(self.values(column), descending)

    def test_name_sort_and_driver_selection_remain_stable(self):
        self.window.seek(5000)
        before = self.window.play_time
        self.window.entries_table.sortItems(1, Qt.AscendingOrder)
        self.assertEqual(self.values(1), ["driver1", "driver10", "driver2", "no result"])
        self.assertEqual(self.window.frames.slot, 1)
        self.assertEqual(self.window.play_time, before)
        self.window.entries_table.selectRow(2)
        self.assertEqual(self.window.frames.slot, 0)
        self.assertEqual(self.window.play_time, before)

    def test_reload_preserves_sort_but_restores_default_driver(self):
        self.window.entries_table.sortItems(0, Qt.DescendingOrder)
        self.window.save_loaded(self.window.replay, self.window.native_document)
        self.assertEqual(self.values(0), [10, 2, 1, None])
        self.assertEqual(self.window.frames.slot, 1)

    def test_clicking_header_toggles_sort_direction(self):
        self.window.show()
        self.application.processEvents()
        header = self.window.entries_table.horizontalHeader()
        point = QPoint(
            header.sectionViewportPosition(0) + header.sectionSize(0) // 2, header.height() // 2
        )
        QTest.mouseClick(header.viewport(), Qt.LeftButton, pos=point)
        self.assertEqual(self.values(0), [10, 2, 1, None])
        QTest.mouseClick(header.viewport(), Qt.LeftButton, pos=point)
        self.assertEqual(self.values(0), [1, 2, 10, None])


if __name__ == "__main__":
    unittest.main()
