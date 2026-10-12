"""GT6Replay. Native replay and captured telemetry playback."""

from __future__ import annotations
import bisect
import csv
import json
import math
import os
from pathlib import Path
import sys
import time
import traceback
import shutil
from datetime import datetime
from ftplib import FTP
from PySide6.QtCore import Qt, QTimer, QThread, Signal, QPointF, QRectF
from PySide6.QtGui import (
    QColor,
    QPainter,
    QPen,
    QPolygonF,
    QFont,
    QFontDatabase,
    QKeySequence,
    QShortcut,
    QImage,
    QIcon,
)
from PySide6.QtWidgets import (
    QApplication,
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QComboBox,
    QSlider,
    QFileDialog,
    QMessageBox,
    QLineEdit,
    QDialog,
    QFormLayout,
    QDialogButtonBox,
    QTableWidget,
    QTableWidgetItem,
    QHeaderView,
    QSplitter,
    QTabWidget,
    QProgressBar,
    QCheckBox,
    QMenu,
)
from replay_data import load_replay, EncryptedReplayError
from telemetry import GT6TelemetryRecorder
from native_motion import load_native_replay, find_native_replay, find_native_for_input
from local_converter import (
    convert_local_replay,
    find_local_converter,
    convert_path,
    cache_directory,
)
from version import APP_NAME, VERSION
from results import ResultItem, HEADERS, result_values

TEAL = QColor("#53e0bf")
PALETTE = ["#53e0bf", "#6fa8ff", "#ffbc69", "#ef84ac", "#b6a0ff"]
CAR_COLORS = [
    "#53e0bf",
    "#6fa8ff",
    "#ffbc69",
    "#ef84ac",
    "#b6a0ff",
    "#f1e674",
    "#75d5f3",
    "#e68d69",
    "#9ee087",
    "#e6b4ee",
]


def app_directory():
    return Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).parent


def fmt_time(seconds):
    if seconds is None or seconds < 0:
        return "—"
    milliseconds = round(seconds * 1000)
    return f"{milliseconds // 60000}:{milliseconds // 1000 % 60:02d}.{milliseconds % 1000:03d}"


def fmt_ms(milliseconds):
    return fmt_time(None if milliseconds is None else milliseconds / 1000)


class Worker(QThread):
    done = Signal(object)
    failed = Signal(str)
    progress = Signal(str)

    def __init__(self, action, parent=None):
        super().__init__(parent)
        self.action = action

    def run(self):
        try:
            self.done.emit(self.action(self.progress.emit))
        except Exception as exc:
            self.failed.emit(f"{type(exc).__name__}: {exc}")


class RaceView(QWidget):
    """Schematic views of measured coordinates, never invented save frames."""

    def __init__(self, perspective=False):
        super().__init__()
        self.perspective = perspective
        self.frames = []
        self.path = []
        self.index = 0
        self.bounds = None
        self.yaw = -0.6
        self.pitch = 0.65
        self.zoom = 1.0
        self.pan = QPointF()
        self.time_seconds = 0
        self.racers = []
        self.race_bounds = None
        self.race_path = []
        self.selected_slot = None
        self.show_all = True
        self.mouse_mode = None
        self.mouse_start = None
        self._frame_generation = 0
        self._background_key = None
        self._background = None
        self.setMinimumSize(430, 310)
        self.setCursor(Qt.OpenHandCursor)

    @staticmethod
    def frame_bounds(frames):
        if hasattr(frames, "coordinate_bounds"):
            return frames.coordinate_bounds
        if not frames:
            return None
        xs = [f["x"] for f in frames]
        ys = [f.get("y", 0) for f in frames]
        zs = [f["z"] for f in frames]
        return (min(xs), max(xs), min(ys), max(ys), min(zs), max(zs))

    def set_race(self, native, entries):
        self.racers = []
        self.race_bounds = None
        self.race_path = []
        if native:
            for i, entry in enumerate(entries):
                frames = native.frames_for_slot(entry["slot"], entry.get("car_code"))
                if not frames:
                    continue
                times = (
                    frames.times
                    if hasattr(frames, "times")
                    else [f["time_seconds"] for f in frames]
                )
                self.racers.append(
                    dict(
                        slot=entry["slot"],
                        name=entry["name"],
                        frames=frames,
                        times=times,
                        fps=native.metadata["fps"],
                        color=QColor(CAR_COLORS[i % len(CAR_COLORS)]),
                    )
                )
            bounds = [self.frame_bounds(r["frames"]) for r in self.racers]
            if bounds:
                self.race_bounds = tuple(
                    ((min if i % 2 == 0 else max)((b[i] for b in bounds)) for i in range(6))
                )
                reference = self.racers[0]["frames"]
                self.race_path = reference[:: max(1, math.ceil(len(reference) / 1800))]
        self._frame_generation += 1
        self.reset_camera()
        self.bounds = (
            self.race_bounds if self.show_all and self.racers else self.frame_bounds(self.frames)
        )

    def set_show_all(self, enabled):
        self.show_all = enabled
        self.bounds = (
            self.race_bounds if enabled and self.racers else self.frame_bounds(self.frames)
        )
        self.update()

    def visible_cars(self):
        if self.racers:
            visible = []
            for racer in self.racers:
                if not self.show_all and racer["slot"] != self.selected_slot:
                    continue
                frames = racer["frames"]
                index = bisect.bisect_right(racer["times"], self.time_seconds + 1e-07) - 1
                if index < 0:
                    continue
                frame_id = (
                    int(frames.frame_ids[index])
                    if hasattr(frames, "frame_ids")
                    else round(racer["times"][index] * racer["fps"])
                )
                if frame_id != int((self.time_seconds + 1e-07) * racer["fps"]):
                    continue
                visible.append((racer, frames, index))
            return visible
        if self.frames:
            return [
                (
                    dict(slot=None, name="", color=TEAL),
                    self.frames,
                    min(self.index, len(self.frames) - 1),
                )
            ]
        return []

    def set_frames(self, frames):
        self.frames = frames
        self.index = 0
        self.path = frames[:: max(1, math.ceil(len(frames) / 1800))]
        self._frame_generation += 1
        self._background_key = None
        self.bounds = (
            self.race_bounds if self.show_all and self.racers else self.frame_bounds(frames)
        )
        self.update()

    def project(self, x, y, z):
        x0, x1, y0, y1, z0, z1 = self.bounds
        x -= (x0 + x1) / 2
        z -= (z0 + z1) / 2
        y -= (y0 + y1) / 2
        if self.perspective:
            xx = x * math.cos(self.yaw) - z * math.sin(self.yaw)
            zz = x * math.sin(self.yaw) + z * math.cos(self.yaw)
            yy = -y * math.cos(self.pitch) + zz * math.sin(self.pitch)
            depth = y * math.sin(self.pitch) + zz * math.cos(self.pitch)
            span = max(x1 - x0, z1 - z0, 30)
            perspective = 1.0 / max(0.45, 1 + depth / (span * 3))
            scale = min(self.width(), self.height()) * 0.74 / span * self.zoom
            return QPointF(
                self.width() / 2 + self.pan.x() + xx * scale * perspective,
                self.height() / 2 + self.pan.y() + yy * scale * perspective,
            )
        scale = (
            min((self.width() - 90) / max(x1 - x0, 20), (self.height() - 100) / max(z1 - z0, 20))
            * self.zoom
        )
        return QPointF(
            self.width() / 2 + self.pan.x() + x * scale,
            self.height() / 2 + self.pan.y() + z * scale,
        )

    def _static_background(self):
        dpr = self.devicePixelRatioF()
        key = (
            self.width(),
            self.height(),
            dpr,
            self.perspective,
            self.yaw,
            self.pitch,
            self.zoom,
            self.pan.x(),
            self.pan.y(),
            self.bounds,
            self.show_all,
            self._frame_generation,
        )
        if key == self._background_key:
            return self._background
        image = QImage(
            max(1, round(self.width() * dpr)),
            max(1, round(self.height() * dpr)),
            QImage.Format_ARGB32_Premultiplied,
        )
        image.setDevicePixelRatio(dpr)
        image.fill(QColor("#101a29"))
        p = QPainter(image)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(QPen(QColor("#1b293a"), 1))
        for x in range(0, self.width(), 40):
            p.drawLine(x, 0, x, self.height())
        for y in range(0, self.height(), 40):
            p.drawLine(0, y, self.width(), y)
        p.setPen(QColor("#a9b9cd"))
        p.setFont(QFont("Segoe UI", 9))
        title = "3D MOTION · SCHEMATIC" if self.perspective else "TRACK MAP · MEASURED PATH"
        p.drawText(QRectF(20, 12, self.width() - 40, 25), Qt.AlignLeft, title)
        if not self.frames and (not self.racers):
            p.setFont(QFont("Segoe UI", 16, QFont.DemiBold))
            p.setPen(QColor("#e9f2fc"))
            p.drawText(
                QRectF(45, self.height() / 2 - 65, self.width() - 90, 50),
                Qt.AlignCenter,
                "Ready for recorded motion",
            )
            p.setFont(QFont("Segoe UI", 10))
            p.setPen(QColor("#a9b9cd"))
            p.drawText(
                QRectF(45, self.height() / 2 - 5, self.width() - 90, 95),
                Qt.AlignCenter | Qt.TextWordWrap,
                "Open a decoded local replay or a telemetry capture.\nChoose a replay file or a save folder.",
            )
        else:
            path = self.race_path if self.racers and self.show_all else self.path
            line = QPolygonF([self.project(f["x"], f.get("y", 0), f["z"]) for f in path])
            p.setPen(QPen(QColor("#26394f"), 11, Qt.SolidLine, Qt.RoundCap, Qt.BevelJoin))
            p.drawPolyline(line)
            p.setPen(QPen(QColor("#7d90a7"), 2, Qt.SolidLine, Qt.RoundCap, Qt.BevelJoin))
            p.drawPolyline(line)
        p.end()
        self._background, self._background_key = (image, key)
        return image

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.drawImage(QPointF(0, 0), self._static_background())
        if not self.frames and (not self.racers):
            return
        cars = self.visible_cars()
        for racer, frames, index in sorted(
            cars, key=lambda car: car[0]["slot"] == self.selected_slot
        ):
            self.draw_car(p, frames, index, racer["color"], racer["slot"] == self.selected_slot)
        p.setPen(QColor("#a9b9cd"))
        p.setFont(QFont("Segoe UI", 9))
        if self.racers:
            p.drawText(
                QRectF(20, 12, self.width() - 40, 25),
                Qt.AlignRight,
                f"{len(cars)} cars visible" if self.show_all else "Selected car",
            )

    def draw_car(self, p, frames, index, color, selected):
        f = frames[index]
        pos = self.project(f["x"], f.get("y", 0), f["z"])
        trail = frames[max(0, index - 60) : index + 1 : 3]
        p.setPen(QPen(color, 2 if selected else 1, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        p.drawPolyline(QPolygonF([self.project(v["x"], v.get("y", 0), v["z"]) for v in trail]))
        p.setPen(Qt.NoPen)
        halo = QColor(color)
        halo.setAlpha(45 if selected else 25)
        p.setBrush(halo)
        p.drawEllipse(pos, 8 if selected else 5, 8 if selected else 5)
        if self.perspective:
            before = frames[max(0, index - 3)]
            after = frames[min(len(frames) - 1, index + 3)]
            dx, dz = (after["x"] - before["x"], after["z"] - before["z"])
            length = math.hypot(dx, dz)
            dx, dz = (dx / length, dz / length) if length > 0.01 else (1.0, 0.0)
            span = max(self.bounds[1] - self.bounds[0], self.bounds[5] - self.bounds[4], 30)
            length = max(4.6, span / 110)
            width = length * 0.43
            height = length * 0.27
            corners = []
            for along, side in [(-0.5, -0.5), (0.5, -0.5), (0.5, 0.5), (-0.5, 0.5)]:
                corners.append(
                    (
                        f["x"] + dx * along * length - dz * side * width,
                        f.get("y", 0),
                        f["z"] + dz * along * length + dx * side * width,
                    )
                )
            roof = [(x, y + height, z) for x, y, z in corners]
            p.setPen(QPen(QColor("#f2f8ff") if selected else color.lighter(130), 0.8))
            for i in range(4):
                j = (i + 1) % 4
                p.setBrush(color.darker(145))
                p.drawPolygon(
                    QPolygonF(
                        [
                            self.project(*corners[i]),
                            self.project(*corners[j]),
                            self.project(*roof[j]),
                            self.project(*roof[i]),
                        ]
                    )
                )
            p.setBrush(color)
            p.drawPolygon(QPolygonF([self.project(*v) for v in roof]))
            windshield = []
            for along, side in [(-0.05, -0.4), (0.28, -0.4), (0.28, 0.4), (-0.05, 0.4)]:
                windshield.append(
                    self.project(
                        f["x"] + dx * along * length - dz * side * width,
                        f.get("y", 0) + height * 1.01,
                        f["z"] + dz * along * length + dx * side * width,
                    )
                )
            p.setBrush(QColor("#132c3b"))
            p.drawPolygon(QPolygonF(windshield))
        else:
            p.setPen(QPen(QColor("#f2f8ff") if selected else color.darker(150), 1))
            p.setBrush(color)
            p.drawEllipse(pos, 3.5 if selected else 2.5, 3.5 if selected else 2.5)

    def mousePressEvent(self, event):
        if event.button() in (Qt.LeftButton, Qt.MiddleButton, Qt.RightButton):
            self.mouse_start = event.position()
            self.mouse_mode = (
                "orbit" if self.perspective and event.button() == Qt.RightButton else "pan"
            )
            self.setCursor(Qt.ClosedHandCursor)
            event.accept()

    def mouseMoveEvent(self, event):
        if self.mouse_start is not None:
            delta = event.position() - self.mouse_start
            if self.mouse_mode == "orbit":
                self.yaw += delta.x() * 0.008
                self.pitch = max(0.15, min(1.45, self.pitch + delta.y() * 0.005))
            else:
                self.pan += delta
            self.mouse_start = event.position()
            self.update()

    def mouseReleaseEvent(self, event):
        self.mouse_start = None
        self.mouse_mode = None
        self.setCursor(Qt.OpenHandCursor)

    def zoom_at(self, factor, position=None):
        center = QPointF(self.width() / 2, self.height() / 2)
        position = position if position is not None else center
        zoom = max(0.2, min(40, self.zoom * factor))
        ratio = zoom / self.zoom
        self.pan = position - center - (position - center - self.pan) * ratio
        self.zoom = zoom
        self.update()

    def wheelEvent(self, event):
        delta = event.angleDelta().y() or event.pixelDelta().y()
        if delta:
            self.zoom_at(1.15 ** (delta / 120), event.position())
        event.accept()

    def reset_camera(self):
        self.yaw, self.pitch, self.zoom, self.pan = (-0.6, 0.65, 1, QPointF())
        self.update()

    def mouseDoubleClickEvent(self, event):
        self.reset_camera()


class TraceView(QWidget):

    def __init__(self):
        super().__init__()
        self._frames, self.index = ([], 0)
        self._frame_generation = 0
        self._series_key = None
        self._background_key = None
        self._background = None
        self._points = []
        self._duration, self._maximum = (0.001, 1)
        self._chart_box = QRectF()
        self.setMinimumHeight(160)

    @property
    def frames(self):
        return self._frames

    @frames.setter
    def frames(self, frames):
        self._frames = frames
        self._frame_generation += 1
        self._series_key = None
        self._background_key = None

    def set_frames(self, frames):
        self.frames = frames
        self.index = 0
        self.update()

    def _static_background(self):
        series_key = (
            id(self.frames),
            self._frame_generation,
            len(self.frames),
            self.frames[-1]["time_seconds"] if self.frames else None,
        )
        if series_key != self._series_key:
            self._duration = max(self.frames[-1]["time_seconds"], 0.001) if self.frames else 0.001
            self._maximum = (
                max(1, self.frames.max_speed)
                if hasattr(self.frames, "max_speed")
                else max(1, max((f.get("speed_kmh", 0) for f in self.frames))) if self.frames else 1
            )
            self._points = self.frames[:: max(1, math.ceil(len(self.frames) / 1800))]
            self._series_key = series_key
        dpr = self.devicePixelRatioF()
        key = (self.width(), self.height(), dpr, series_key)
        if key == self._background_key:
            return self._background
        image = QImage(
            max(1, round(self.width() * dpr)),
            max(1, round(self.height() * dpr)),
            QImage.Format_ARGB32_Premultiplied,
        )
        image.setDevicePixelRatio(dpr)
        image.fill(QColor("#101a29"))
        p = QPainter(image)
        p.setRenderHint(QPainter.Antialiasing)
        p.setFont(QFont("Segoe UI", 9))
        p.setPen(QColor("#a9b9cd"))
        native = hasattr(self.frames, "native_slot") or hasattr(self.frames, "slot")
        p.drawText(
            18,
            24,
            (
                "NATIVE TELEMETRY  /  SPEED  ·  RPM"
                if native
                else "TELEMETRY  /  SPEED  ·  THROTTLE  ·  BRAKE"
            ),
        )
        if not self.frames:
            p.drawText(
                QRectF(0, 45, self.width(), 90),
                Qt.AlignCenter,
                "Open a local replay to see its telemetry.",
            )
        else:
            box = QRectF(48, 42, self.width() - 68, self.height() - 70)
            self._chart_box = box
            p.setPen(QPen(QColor("#25364a"), 1))
            for i in range(5):
                yy = box.top() + box.height() * i / 4
                p.drawLine(QPointF(box.left(), yy), QPointF(box.right(), yy))
            channels = [("speed_kmh", self._maximum, "#53e0bf")]
            if native:
                channels.append(
                    ("rpm", max(1, max((f.get("rpm", 0) for f in self._points))), "#6fa8ff")
                )
            else:
                channels.extend([("throttle", 1, "#6fa8ff"), ("brake", 1, "#ef84ac")])
            for field, limit, color in channels:
                p.setPen(QPen(QColor(color), 1.6))
                p.drawPolyline(
                    QPolygonF(
                        [
                            QPointF(
                                box.left() + f["time_seconds"] / self._duration * box.width(),
                                box.bottom()
                                - min(1, max(0, f.get(field, 0) / limit)) * box.height(),
                            )
                            for f in self._points
                        ]
                    )
                )
            p.setPen(QColor("#a9b9cd"))
            p.drawText(8, 50, f"{self._maximum:.0f}")
            p.drawText(25, int(box.bottom()), "0")
            p.drawText(
                QRectF(box.left(), box.bottom() + 6, box.width(), 22),
                Qt.AlignRight,
                fmt_time(self._duration),
            )
        p.end()
        self._background, self._background_key = (image, key)
        return image

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.drawImage(QPointF(0, 0), self._static_background())
        if not self.frames:
            return
        box = self._chart_box
        f = self.frames[min(self.index, len(self.frames) - 1)]
        xx = box.left() + f["time_seconds"] / self._duration * box.width()
        p.setPen(QPen(QColor("#ffffff"), 1, Qt.DashLine))
        p.drawLine(QPointF(xx, box.top()), QPointF(xx, box.bottom()))


class CaptureDialog(QDialog):

    def __init__(self, host, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Record a PS3 replay")
        self.setMinimumWidth(470)
        layout = QVBoxLayout(self)
        description = QLabel(
            "Start recording here, then play your saved replay in GT6 on the PS3.\nThe telemetry feed supplies one car's motion.\nThe recorded path and available instruments will play back on the PC."
        )
        description.setWordWrap(True)
        layout.addWidget(description)
        form = QFormLayout()
        self.host = QLineEdit(host)
        self.label = QLineEdit("GT6 replay capture")
        form.addRow("PS3 address", self.host)
        form.addRow("Capture name", self.label)
        layout.addLayout(form)
        note = QLabel(
            "UDP 33339 → PC 33340. Allow the app through Windows Firewall on your private network.\nIf no packets arrive, verify GT6 is running and the PC and PS3 share the same LAN."
        )
        note.setWordWrap(True)
        note.setObjectName("muted")
        layout.addWidget(note)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("Start recording")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)


class FTPDialog(QDialog):

    def __init__(self, host, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Read replays from PS3 FTP")
        self.resize(630, 420)
        self.worker = None
        self.result_path = None
        self.replays = []
        layout = QVBoxLayout(self)
        note = QLabel("Browse exported replay saves on your PS3. Downloads are local copies.")
        note.setWordWrap(True)
        layout.addWidget(note)
        form = QFormLayout()
        self.host = QLineEdit(host)
        self.user = QLineEdit("anonymous")
        self.password = QLineEdit()
        self.password.setEchoMode(QLineEdit.Password)
        form.addRow("Address", self.host)
        form.addRow("FTP user", self.user)
        form.addRow("Password", self.password)
        layout.addLayout(form)
        self.scan_button = QPushButton("Find replay saves")
        self.scan_button.clicked.connect(self.scan)
        layout.addWidget(self.scan_button)
        self.list = QComboBox()
        layout.addWidget(self.list)
        self.status = QLabel("Enter the console address to browse saved replays.")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.download_button = QPushButton("Download and open")
        self.download_button.setEnabled(False)
        self.download_button.clicked.connect(self.download)
        layout.addWidget(self.download_button)
        close = QPushButton("Close")
        close.clicked.connect(self.reject)
        layout.addWidget(close)

    def connection(self):
        f = FTP(encoding="latin1")
        f.connect(self.host.text().strip(), 21, timeout=15)
        f.login(self.user.text().strip() or "anonymous", self.password.text() or "anonymous@")
        return f

    def run_worker(self, action, handler):
        self.scan_button.setEnabled(False)
        self.download_button.setEnabled(False)
        self.worker = Worker(action, self)
        self.worker.progress.connect(self.status.setText)
        self.worker.done.connect(handler)
        self.worker.failed.connect(self.error)
        self.worker.start()

    def scan(self):
        host, user, password = (
            self.host.text().strip(),
            self.user.text().strip(),
            self.password.text(),
        )

        def action(progress):
            progress("Connecting to PS3…")
            with FTP(encoding="latin1") as f:
                f.connect(host, 21, timeout=15)
                f.login(user or "anonymous", password or "anonymous@")
                paths = []
                for user_id in f.nlst("/dev_hdd0/home"):
                    user_id = user_id.rsplit("/", 1)[-1]
                    if not user_id.isdigit():
                        continue
                    savedata = f"/dev_hdd0/home/{user_id}/savedata"
                    try:
                        names = f.nlst(savedata)
                    except Exception:
                        continue
                    for name in names:
                        name = name.rsplit("/", 1)[-1]
                        if "-RPLY" in name and name.startswith(
                            ("BCJS37016", "BCES01893", "BCUS98296")
                        ):
                            paths.append(f"{savedata}/{name}")
                return paths

        self.run_worker(action, self.found)

    def found(self, paths):
        self.replays = paths
        self.list.clear()
        self.list.addItems(paths)
        self.status.setText(f"{len(paths)} GT6 replay save(s) found.")
        self.scan_button.setEnabled(True)
        self.download_button.setEnabled(bool(paths))

    def download(self):
        remote = self.list.currentText()
        host, user, password = (
            self.host.text().strip(),
            self.user.text().strip(),
            self.password.text(),
        )
        target = (
            cache_directory().parent
            / "Downloads"
            / (remote.rsplit("/", 1)[-1] + "_" + datetime.now().strftime("%Y%m%d_%H%M%S"))
        )

        def action(progress):
            target.mkdir(parents=True, exist_ok=False)
            with FTP(encoding="latin1") as f:
                f.connect(host, 21, timeout=20)
                f.login(user or "anonymous", password or "anonymous@")
                f.cwd(remote)
                names = [v.rsplit("/", 1)[-1] for v in f.nlst()]
                allowed = [
                    v
                    for v in names
                    if v in ("PARAM.SFO", "PARAM.PFD", "ICON0.PNG", "PIC1.PNG")
                    or (v.startswith("REPLAY.") and v[7:].isdigit())
                ]
                if "REPLAY.0" not in allowed:
                    raise ValueError("This save has no REPLAY.0 file.")
                for name in allowed:
                    progress(f"Downloading {name}…")
                    with (target / name).open("wb") as out:
                        f.retrbinary("RETR " + name, out.write, blocksize=262144)
            return target

        self.run_worker(action, self.downloaded)

    def downloaded(self, path):
        self.result_path = path
        self.accept()

    def error(self, message):
        self.status.setText(message)
        self.scan_button.setEnabled(True)
        self.download_button.setEnabled(bool(self.replays))

    def reject(self):
        if self.worker and self.worker.isRunning():
            self.status.setText("Please wait for the current FTP operation to finish.")
            return
        super().reject()


class MainWindow(QMainWindow):

    def __init__(self):
        super().__init__()
        if not QFontDatabase.families():
            for name in ("segoeui.ttf", "segoeuib.ttf", "seguisym.ttf"):
                QFontDatabase.addApplicationFont(
                    str(Path(os.environ.get("WINDIR", "C:\\Windows")) / "Fonts" / name)
                )
        self.setWindowTitle(f"{APP_NAME} {VERSION}")
        self.setWindowIcon(QIcon(str(Path(__file__).parent / "assets/icon.svg")))
        help_menu = self.menuBar().addMenu("Help")
        help_menu.addAction(
            "About GT6Replay",
            lambda: QMessageBox.about(
                self,
                "About GT6Replay",
                f"<b>GT6Replay {VERSION}</b><p>Independent replay viewer.</p><p>Application: MIT license.<br>Uses Qt/PySide6 under LGPLv3.<br>Notices and corresponding source accompany the release.</p>",
            ),
        )
        self.resize(1550, 940)
        self.setMinimumSize(1250, 720)
        self.replay = None
        self.native_document = None
        self.frames = []
        self.times = []
        self.capture_metadata = {}
        self.index = 0
        self.playing = False
        self.recorder = None
        self.capture_started = 0
        self.worker = None
        self.host = ""
        self.last_tick = time.monotonic()
        self.play_time = 0
        self.last_live_refresh = 0
        self.capture_label = ""
        self.dirty_capture = False
        self._build()
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.tick)
        self.timer.start(33)
        QShortcut(QKeySequence("Space"), self, activated=self.toggle_play)
        QShortcut(QKeySequence("Ctrl+O"), self, activated=self.open_capture)
        QShortcut(QKeySequence("Home"), self, activated=self.restart)

    def _build(self):
        root = QWidget()
        self.setCentralWidget(root)
        layout = QVBoxLayout(root)
        layout.setContentsMargins(22, 18, 22, 14)
        header = QHBoxLayout()
        title = QLabel("GT6<span style='color:#53e0bf'>Replay</span>")
        title.setObjectName("brand")
        header.addWidget(title)
        header.addStretch()
        self.open_button = QPushButton("Open save folder")
        self.open_button.clicked.connect(self.open_save)
        header.addWidget(self.open_button)
        self.ftp_button = QPushButton("PS3 FTP")
        self.ftp_button.clicked.connect(self.open_ftp)
        header.addWidget(self.ftp_button)
        self.telemetry_button = QPushButton("Open replay")
        self.telemetry_button.setObjectName("primary")
        self.telemetry_button.clicked.connect(self.open_capture)
        header.addWidget(self.telemetry_button)
        self.record_button = QPushButton("Record")
        self.record_button.clicked.connect(self.toggle_record)
        header.addWidget(self.record_button)
        layout.addLayout(header)
        self.banner = QLabel("Open a replay to begin.")
        self.banner.setWordWrap(True)
        self.banner.setObjectName("banner")
        layout.addWidget(self.banner)
        splitter = QSplitter(Qt.Horizontal)
        left = QWidget()
        left.setMinimumWidth(430)
        left.setMaximumWidth(740)
        side = QVBoxLayout(left)
        side.setContentsMargins(0, 0, 14, 0)
        self.track_label = QLabel("No replay opened")
        self.track_label.setObjectName("track")
        self.track_label.setWordWrap(True)
        self.track_label.setTextFormat(Qt.PlainText)
        side.addWidget(self.track_label)
        self.event_label = QLabel("Your replay library")
        self.event_label.setWordWrap(True)
        self.event_label.setTextFormat(Qt.PlainText)
        self.event_label.setObjectName("muted")
        side.addWidget(self.event_label)
        self.metadata_label = QLabel(
            "Open a GT6 save folder or a decoded .gt6r replay.\nLocal playback includes recorded motion and race results."
        )
        self.metadata_label.setWordWrap(True)
        self.metadata_label.setTextFormat(Qt.PlainText)
        side.addWidget(self.metadata_label)
        side.addSpacing(12)
        result_heading = QHBoxLayout()
        result_heading.addWidget(QLabel("RACE RESULTS"))
        result_heading.addStretch(1)
        columns_button = QPushButton("Columns")
        columns_button.setMaximumWidth(85)
        columns_button.clicked.connect(
            lambda: self.result_columns_menu(
                self.entries_table.horizontalHeader().rect().topRight()
            )
        )
        result_heading.addWidget(columns_button)
        side.addLayout(result_heading)
        self.entries_table = QTableWidget(0, len(HEADERS))
        self.entries_table.setHorizontalHeaderLabels(HEADERS)
        self.entries_table.verticalHeader().hide()
        self.entries_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.entries_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        for column in range(2, len(HEADERS)):
            self.entries_table.horizontalHeader().setSectionResizeMode(
                column, QHeaderView.ResizeToContents
            )
        self.entries_table.setSortingEnabled(True)
        self.entries_table.sortItems(0, Qt.AscendingOrder)
        self.entries_table.setColumnHidden(7, True)
        self.entries_table.horizontalHeaderItem(4).setToolTip(
            "Race time minus the winner's race time."
        )
        self.entries_table.horizontalHeaderItem(5).setToolTip(
            "Highest recorded lap number, including the current lap."
        )
        self.entries_table.horizontalHeader().setContextMenuPolicy(Qt.CustomContextMenu)
        self.entries_table.horizontalHeader().customContextMenuRequested.connect(
            self.result_columns_menu
        )
        self.entries_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.entries_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.entries_table.setSelectionMode(QTableWidget.SingleSelection)
        self.entries_table.itemSelectionChanged.connect(self.driver_selected)
        side.addWidget(self.entries_table, 1)
        self.car_label = QLabel("")
        self.car_label.setTextFormat(Qt.PlainText)
        self.car_label.setWordWrap(True)
        self.car_label.setObjectName("muted")
        side.addWidget(self.car_label)
        self.export_button = QPushButton("Export race report…")
        self.export_button.setEnabled(False)
        self.export_button.clicked.connect(self.export_report)
        side.addWidget(self.export_button)
        self.save_button = QPushButton("Save capture…")
        self.save_button.setEnabled(False)
        self.save_button.clicked.connect(self.save_capture)
        side.addWidget(self.save_button)
        self.csv_button = QPushButton("Export telemetry CSV…")
        self.csv_button.setEnabled(False)
        self.csv_button.clicked.connect(self.export_csv)
        side.addWidget(self.csv_button)
        splitter.addWidget(left)
        right = QWidget()
        content = QVBoxLayout(right)
        content.setContentsMargins(0, 0, 0, 0)
        self.tabs = QTabWidget()
        self.map_view = RaceView()
        self.view3d = RaceView(perspective=True)
        self.tabs.addTab(self.map_view, "Track map")
        self.tabs.addTab(self.view3d, "3D motion")
        view_controls = QHBoxLayout()
        self.all_cars = QCheckBox("Show all cars")
        self.all_cars.setChecked(True)
        self.all_cars.setEnabled(False)
        self.all_cars.toggled.connect(self.show_all_cars)
        view_controls.addWidget(self.all_cars)
        view_controls.addStretch(1)
        hint = QLabel("Drag to pan · wheel to zoom")
        hint.setObjectName("muted")
        view_controls.addWidget(hint)
        self.tabs.currentChanged.connect(
            lambda i: hint.setText(
                "Drag to pan · right-drag to orbit · wheel to zoom"
                if i == 1
                else "Drag to pan · wheel to zoom"
            )
        )
        for label, factor in [("−", 1 / 1.3), ("+", 1.3)]:
            button = QPushButton(label)
            button.setToolTip("Zoom out" if factor < 1 else "Zoom in")
            button.clicked.connect(lambda checked=False, f=factor: self.active_view().zoom_at(f))
            view_controls.addWidget(button)
        fit = QPushButton("Fit view")
        fit.clicked.connect(lambda: self.active_view().reset_camera())
        view_controls.addWidget(fit)
        content.addLayout(view_controls)
        content.addWidget(self.tabs, 1)
        instruments = QHBoxLayout()
        self.instruments = {}
        for key, caption, initial in [
            ("speed_kmh", "SPEED · KM/H", "—"),
            ("rpm", "ENGINE · RPM", "—"),
            ("gear", "GEAR", "—"),
            ("lap", "LAP", "—"),
            ("throttle", "THROTTLE", "—"),
            ("brake", "BRAKE", "—"),
        ]:
            box = QWidget()
            box.setObjectName("instrument")
            instrument_layout = QVBoxLayout(box)
            label = QLabel(caption)
            label.setObjectName("caption")
            value = QLabel(initial)
            value.setObjectName("value")
            instrument_layout.addWidget(label)
            instrument_layout.addWidget(value)
            self.instruments[key] = value
            instruments.addWidget(box)
        content.addLayout(instruments)
        self.trace = TraceView()
        content.addWidget(self.trace)
        transport = QHBoxLayout()
        self.restart_button = QPushButton("↺")
        self.restart_button.clicked.connect(self.restart)
        self.restart_button.setToolTip("Restart (Home)")
        transport.addWidget(self.restart_button)
        self.play_button = QPushButton("▶ Play")
        self.play_button.clicked.connect(self.toggle_play)
        self.play_button.setToolTip("Play / pause (Space)")
        transport.addWidget(self.play_button)
        self.clock_label = QLabel("0:00.000 / 0:00.000")
        self.clock_label.setMinimumWidth(175)
        transport.addWidget(self.clock_label)
        self.slider = QSlider(Qt.Horizontal)
        self.slider.setRange(0, 10000)
        self.slider.valueChanged.connect(self.seek)
        transport.addWidget(self.slider, 1)
        self.rate = QComboBox()
        self.rate.addItems(["0.25×", "0.5×", "1×", "2×", "4×"])
        self.rate.setCurrentIndex(2)
        transport.addWidget(self.rate)
        self.loop = QCheckBox("Loop")
        transport.addWidget(self.loop)
        content.addLayout(transport)
        splitter.addWidget(right)
        splitter.setSizes([530, 1020])
        layout.addWidget(splitter, 1)
        self.status_label = QLabel("")
        self.status_label.setObjectName("muted")
        layout.addWidget(self.status_label)
        self.status_label.hide()
        self.notice_timer = QTimer(self)
        self.notice_timer.setSingleShot(True)
        self.notice_timer.timeout.connect(self.status_label.hide)
        self.set_transport_enabled(False)

    def notify(self, message):
        self.status_label.setText(message)
        self.status_label.show()
        self.notice_timer.start(4000)

    def result_columns_menu(self, position):
        menu = QMenu(self)
        for column, title in enumerate(HEADERS):
            action = menu.addAction(title)
            action.setCheckable(True)
            action.setChecked(not self.entries_table.isColumnHidden(column))
            if column == 1:
                action.setEnabled(False)
            action.toggled.connect(
                lambda checked, c=column: self.entries_table.setColumnHidden(c, not checked)
            )
        menu.exec(self.entries_table.horizontalHeader().mapToGlobal(position))

    def busy(self):
        return self.recorder is not None or (self.worker and self.worker.isRunning())

    def active_view(self):
        return self.view3d if self.tabs.currentWidget() is self.view3d else self.map_view

    def show_all_cars(self, enabled):
        self.map_view.set_show_all(enabled)
        self.view3d.set_show_all(enabled)

    @property
    def duration(self):
        if self.native_document:
            return (
                self.native_document.metadata["frame_count"] - 1
            ) / self.native_document.metadata["fps"]
        return self.times[-1] if self.times else 0

    def open_save(self):
        if self.busy():
            return
        path = QFileDialog.getExistingDirectory(
            self, "Choose the folder containing REPLAY.0 and PARAM.PFD"
        )
        if path:
            self.load_save(path)

    def load_save(self, path):
        if self.busy() or not self.confirm_unsaved():
            return
        self.playing = False
        self.banner.setText("Loading replay…")
        self.banner.show()
        self.set_loading(True)

        def read(progress):
            directories = [app_directory() / "Native", cache_directory()]
            native = find_native_for_input(path, directories)
            if native:
                replay = dict(native.replay)
                replay["source_path"] = str(Path(path).resolve())
                return (replay, native)
            try:
                replay = load_replay(path)
            except EncryptedReplayError:
                native = convert_path(path, progress)
                return (native.replay, native)
            native = next(
                (n for directory in directories if (n := find_native_replay(replay, directory))),
                None,
            )
            if native is None and find_local_converter():
                native = convert_local_replay(replay, app_directory(), progress)
            return (replay, native)

        self.worker = Worker(read, self)
        self.worker.done.connect(lambda value: self.save_loaded(*value))
        self.worker.failed.connect(self.load_failed)
        self.worker.progress.connect(self.banner.setText)
        self.worker.start()

    def set_loading(self, loading):
        for button in [
            self.open_button,
            self.ftp_button,
            self.telemetry_button,
            self.record_button,
        ]:
            button.setEnabled(not loading)

    def load_failed(self, message):
        self.set_loading(False)
        self.banner.setText("Could not open replay.")
        self.banner.show()
        QMessageBox.warning(self, "Replay could not be opened", message)

    def save_loaded(self, replay, native=None):
        self.set_loading(False)
        self.replay = replay
        self.native_document = native
        self.set_frames([])
        self.capture_metadata = {}
        metadata = replay["metadata"]
        self.track_label.setText(metadata.get("track") or "Replay")
        self.event_label.setText(metadata.get("event") or metadata.get("race_type") or "")
        self.metadata_label.setText(
            f"{metadata.get('recorded_at') or ''}\n{len(replay['entries'])} drivers · {fmt_time(metadata.get('duration_seconds', self.duration))}"
        )
        entries = sorted(replay["entries"], key=lambda e: e.get("position") or 999)
        selected_slot = next(
            (e["slot"] for e in entries if e["name"] == metadata.get("driver")),
            entries[0]["slot"] if entries else None,
        )
        winner = next((e for e in entries if e.get("position") == 1), None)
        leader_time = winner.get("total_time_ms") if winner else None
        header = self.entries_table.horizontalHeader()
        sort_column = header.sortIndicatorSection()
        sort_order = header.sortIndicatorOrder()
        signals = self.entries_table.blockSignals(True)
        self.entries_table.setSortingEnabled(False)
        self.entries_table.clearContents()
        self.entries_table.setRowCount(len(entries))
        for row, entry in enumerate(entries):
            lap = None
            if native:
                frames = native.frames_for_slot(entry["slot"], entry.get("car_code"))
                if frames:
                    lap = (
                        int(frames.data[:, 12].max())
                        if hasattr(frames, "data")
                        else max((f.get("lap", 0) for f in frames))
                    )
            values = result_values(entry, leader_time, lap)
            for column, value in enumerate(values):
                if column in (2, 3):
                    label = fmt_ms(value)
                elif column == 4:
                    label = (
                        "—"
                        if value is None
                        else ("+" if value > 0 else "−" if value < 0 else "") + fmt_ms(abs(value))
                    )
                else:
                    label = str(value) if value is not None else "—"
                cell = ResultItem(
                    label, value.casefold() if isinstance(value, str) else value, entry
                )
                if column not in (1, 7):
                    cell.setTextAlignment(Qt.AlignCenter)
                if native and column == 1:
                    cell.setForeground(QColor(CAR_COLORS[row % len(CAR_COLORS)]))
                self.entries_table.setItem(row, column, cell)
        self.entries_table.setSortingEnabled(True)
        self.entries_table.sortItems(sort_column, sort_order)
        self.all_cars.setEnabled(bool(native))
        if native:
            self.all_cars.setChecked(True)
        self.map_view.set_race(native, entries)
        self.view3d.set_race(native, entries)
        for row in range(len(entries)):
            if self.entries_table.item(row, 0).data(Qt.UserRole)["slot"] == selected_slot:
                self.entries_table.selectRow(row)
                break
        self.entries_table.blockSignals(signals)
        if entries:
            self.driver_selected()
        self.export_button.setEnabled(True)
        self.save_button.setText("Save replay…" if native else "Save recording…")
        if native:
            self.banner.hide()
        else:
            self.banner.setText("Race results loaded. Motion requires a decoded replay.")
            self.banner.show()
        self.status_label.hide()

    def driver_selected(self):
        row = self.entries_table.currentRow()
        item = self.entries_table.item(row, 0)
        if not item:
            return
        entry = item.data(Qt.UserRole)
        self.car_label.setText(
            entry.get("car_name")
            or ("Car #" + str(entry["car_code"]) if entry.get("car_code") is not None else "")
        )
        if self.native_document:
            previous_time = self.play_time
            playing = self.playing
            self.map_view.selected_slot = self.view3d.selected_slot = entry["slot"]
            self.set_frames(
                self.native_document.frames_for_slot(entry["slot"], entry.get("car_code"))
            )
            if self.frames or self.native_document:
                self.play_time = min(previous_time, self.duration)
                self.index = max(0, bisect.bisect_right(self.times, self.play_time) - 1)
                self.playing = playing
                self.play_button.setText("Pause" if playing else "Play")
                self.update_frame()

    def open_ftp(self):
        if self.busy():
            return
        dialog = FTPDialog(self.host, self)
        if dialog.exec() == QDialog.Accepted and dialog.result_path:
            self.host = dialog.host.text().strip()
            self.load_save(dialog.result_path)

    def set_frames(self, frames):
        self.frames = frames
        self.times = (
            frames.times.tolist()
            if hasattr(frames, "times")
            else [f["time_seconds"] for f in frames]
        )
        self.index, self.play_time = (0, 0)
        self.playing = False
        self.play_button.setText("Play")
        if not self.native_document:
            self.all_cars.setEnabled(False)
            if self.map_view.racers:
                self.map_view.set_race(None, [])
            if self.view3d.racers:
                self.view3d.set_race(None, [])
        self.map_view.set_frames(frames)
        self.view3d.set_frames(frames)
        self.trace.frames, self.trace.index = (frames, 0)
        self.trace.update()
        self.set_transport_enabled(bool(frames) or bool(self.native_document))
        self.save_button.setEnabled(bool(frames))
        self.csv_button.setEnabled(bool(frames))
        self.update_frame()

    def set_transport_enabled(self, enabled):
        for control in [self.play_button, self.restart_button, self.slider, self.rate, self.loop]:
            control.setEnabled(enabled)

    @staticmethod
    def validate_capture(data):
        if not isinstance(data, dict) or (
            data.get("format") != "gt6-telemetry-v1" and data.get("schema") != "gt6-pc-trace-1"
        ):
            raise ValueError("Choose a GT6Replay telemetry capture (gt6-telemetry-v1 JSON).")
        frames = data.get("frames")
        if not isinstance(frames, list) or not frames:
            raise ValueError("This capture contains no frames.")
        required = ["time_seconds", "x", "y", "z"]
        numeric = required + ["speed_kmh", "rpm", "throttle", "brake", "gear", "lap"]
        last = -1
        for frame in frames:
            if not isinstance(frame, dict) or any((k not in frame for k in required)):
                raise ValueError("A capture frame is missing time or position coordinates.")
            if any(
                (
                    k in frame
                    and (not isinstance(frame[k], (float, int)) or not math.isfinite(frame[k]))
                    for k in numeric
                )
            ):
                raise ValueError("A capture contains invalid numeric data.")
            if frame["time_seconds"] < 0 or frame["time_seconds"] < last:
                raise ValueError("Capture timestamps must be nonnegative and in order.")
            last = frame["time_seconds"]
        start = frames[0]["time_seconds"]
        return [dict(frame, time_seconds=frame["time_seconds"] - start) for frame in frames]

    def open_capture(self):
        if self.busy() or not self.confirm_unsaved():
            return
        path, _ = QFileDialog.getOpenFileName(
            self, "Open replay", str(Path.home()), "Replays (*.gt6r *.json *.rply)"
        )
        if not path:
            return
        if Path(path).suffix.lower() == ".gt6r":
            self.load_native_file(path)
            return
        if Path(path).suffix.lower() == ".rply":
            self.load_save(path)
            return
        self.load_capture_file(path)

    def load_capture_file(self, path):
        if self.busy() or not self.confirm_unsaved():
            return
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
            frames = self.validate_capture(data)
            self.native_document = None
            self.save_button.setText("Save capture…")
            if data.get("replay"):
                self.save_loaded(data["replay"])
            else:
                self.replay = None
                self.entries_table.setRowCount(0)
                self.export_button.setEnabled(False)
                self.track_label.setText("Recorded driving path")
                self.event_label.setText("PS3 telemetry capture")
                self.metadata_label.setText(
                    f'{len(frames):,} frames · {fmt_time(frames[-1]["time_seconds"])}'
                )
                self.car_label.setText("")
            self.capture_metadata = data.get("metadata", {})
            self.set_frames(frames)
            self.dirty_capture = False
            self.banner.hide()
            self.status_label.hide()
        except Exception as exc:
            QMessageBox.warning(self, "Capture could not be opened", str(exc))

    def load_native_file(self, path):
        if self.busy():
            return
        self.playing = False
        self.set_loading(True)
        self.banner.show()
        self.banner.setText("Opening decoded native motion…")
        self.worker = Worker(lambda progress: load_native_replay(path), self)
        self.worker.done.connect(lambda native: self.save_loaded(native.replay, native))
        self.worker.failed.connect(self.load_failed)
        self.worker.start()

    def toggle_record(self):
        if self.recorder:
            self.finish_recording()
            return
        if self.busy() or not self.confirm_unsaved():
            return
        dialog = CaptureDialog(self.host, self)
        if dialog.exec() != QDialog.Accepted:
            return
        self.host = dialog.host.text().strip()
        self.capture_label = dialog.label.text().strip() or "GT6 replay capture"
        try:
            self.recorder = GT6TelemetryRecorder(self.host)
            self.recorder.start()
        except Exception as exc:
            self.recorder = None
            QMessageBox.warning(self, "Recording could not start", str(exc))
            return
        self.native_document = None
        self.set_frames([])
        self.capture_started = time.monotonic()
        self.save_button.setText("Save capture…")
        self.last_live_refresh = 0
        self.record_button.setText("■ Stop recording")
        for button in [self.open_button, self.ftp_button, self.telemetry_button]:
            button.setEnabled(False)
        self.banner.setText("Recording from PS3. Start the saved replay in GT6.")
        self.capture_metadata = {
            "name": self.capture_label,
            "host": self.host,
            "recorded_at": datetime.now().astimezone().isoformat(),
        }

    def finish_recording(self):
        recorder = self.recorder
        if not recorder:
            return
        recorder.stop()
        document = recorder.snapshot()
        frames = document["frames"]
        self.capture_metadata["recorder_status"] = recorder.status()
        self.recorder = None
        self.record_button.setText("Record")
        self.set_loading(False)
        self.set_frames(frames)
        self.dirty_capture = bool(frames)
        if frames:
            self.banner.setText(
                f"Capture complete · {len(frames):,} frames · {fmt_time(frames[-1]['time_seconds'])}. Save it to keep this recording."
            )
            self.save_capture()
        else:
            self.banner.setText(
                "No GT6 telemetry packets arrived. Verify GT6 is running, check the PS3 address and allow UDP 33340 through Windows Firewall."
            )

    def tick(self):
        now = time.monotonic()
        delta = now - self.last_tick
        self.last_tick = now
        if self.recorder:
            if now - self.last_live_refresh >= 0.5:
                self.last_live_refresh = now
                status = self.recorder.status()
                incoming = self.recorder.snapshot(since=len(self.frames))["frames"]
                self.frames.extend(incoming)
                frames = self.frames
                if frames:
                    self.times = [f["time_seconds"] for f in frames]
                    self.index = len(frames) - 1
                    self.map_view.set_frames(frames)
                    self.view3d.set_frames(frames)
                    self.trace.frames = frames
                    self.update_frame()
                    self.set_transport_enabled(False)
                    self.notify(
                        f"RECORDING · {len(frames):,} frames · {fmt_time(frames[-1]['time_seconds'])} · {self.host}"
                    )
                else:
                    if status["error"]:
                        message = status["error"]
                    elif status["packets"]:
                        packet = status["last_packet"] or {}
                        state = (
                            "loading"
                            if packet.get("loading")
                            else "paused" if packet.get("paused") else "off track"
                        )
                        message = f"Connected · {status['packets']:,} packets · GT6 reports {state}. Start replay playback."
                    else:
                        message = f"Waiting for GT6 telemetry from {self.host} · {now - self.capture_started:.0f}s"
                    self.notify(message)
            return
        if (
            self.playing
            and (self.frames or self.native_document)
            and (not self.slider.isSliderDown())
        ):
            rate = [0.25, 0.5, 1, 2, 4][self.rate.currentIndex()]
            self.play_time += delta * rate
            duration = self.duration
            if self.play_time >= duration:
                if self.loop.isChecked() and duration > 0:
                    self.play_time %= duration
                else:
                    self.play_time = duration
                    self.playing = False
            self.index = max(
                0,
                min(
                    len(self.frames) - 1,
                    max(0, bisect.bisect_right(self.times, self.play_time) - 1),
                ),
            )
            self.update_frame()

    def update_frame(self):
        self.play_button.setText("❚❚ Pause" if self.playing else "▶ Play")
        if not self.frames and (not self.native_document):
            self.clock_label.setText("0:00.000 / 0:00.000")
            self.slider.setValue(0)
            for label in self.instruments.values():
                label.setText("—")
            return
        f = self.frames[self.index] if self.frames else {}
        if self.native_document and self.frames and hasattr(self.frames, "frame_ids"):
            if int(self.frames.frame_ids[self.index]) != int(
                (self.play_time + 1e-07) * self.native_document.metadata["fps"]
            ):
                f = {}
        if self.recorder:
            self.play_time = f.get("time_seconds", 0)
        self.clock_label.setText(f"{fmt_time(self.play_time)} / {fmt_time(self.duration)}")
        if not self.slider.isSliderDown():
            blocked = self.slider.blockSignals(True)
            self.slider.setValue(round(self.play_time / max(self.duration, 0.001) * 10000))
            self.slider.blockSignals(blocked)
        for key, label in self.instruments.items():
            value = f.get(key)
            if value is None:
                label.setText("—")
            elif key in ("throttle", "brake"):
                label.setText(f"{value * 100:.0f}%")
            elif key == "gear":
                label.setText("R" if value == 0 else "N" if value == 15 else str(int(value)))
            else:
                label.setText(f"{value:.0f}")
        self.map_view.index = self.view3d.index = self.trace.index = self.index
        self.map_view.time_seconds = self.view3d.time_seconds = self.play_time
        self.map_view.update()
        self.view3d.update()
        self.trace.update()

    def toggle_play(self):
        if not (self.frames or self.native_document) or self.recorder:
            return
        if self.play_time >= self.duration:
            self.play_time = 0
        self.playing = not self.playing
        self.last_tick = time.monotonic()
        self.update_frame()

    def restart(self):
        if self.recorder:
            return
        self.play_time, self.index = (0, 0)
        self.update_frame()

    def seek(self, value):
        if not (self.frames or self.native_document) or self.recorder:
            return
        self.play_time = value / 10000 * self.duration
        self.index = max(
            0,
            min(len(self.frames) - 1, max(0, bisect.bisect_right(self.times, self.play_time) - 1)),
        )
        self.update_frame()

    def capture_data(self):
        return {
            "format": "gt6-telemetry-v1",
            "metadata": self.capture_metadata,
            "replay": self.replay,
            "frames": list(self.frames),
        }

    def save_capture(self):
        if not self.frames or self.recorder:
            return False
        if self.native_document:
            path, _ = QFileDialog.getSaveFileName(
                self,
                "Save decoded native replay",
                self.native_document.path.name,
                "Native GT6 replay (*.gt6r)",
            )
            if not path:
                return False
            target = Path(path)
            if target.resolve() != self.native_document.path.resolve():
                shutil.copyfile(self.native_document.path, target)
            self.notify(f"Replay saved.")
            return True
        directory = cache_directory().parent / "Captures"
        directory.mkdir(parents=True, exist_ok=True)
        proposed = directory / (datetime.now().strftime("GT6_%Y%m%d_%H%M%S") + ".json")
        path, _ = QFileDialog.getSaveFileName(
            self, "Save telemetry capture", str(proposed), "GT6 capture (*.json)"
        )
        if not path:
            return False
        try:
            target = Path(path)
            temporary = target.with_name(target.name + ".tmp")
            temporary.write_text(
                json.dumps(
                    self.capture_data(), ensure_ascii=False, separators=(",", ":"), allow_nan=False
                ),
                encoding="utf-8",
            )
            temporary.replace(target)
            self.dirty_capture = False
            self.notify(f"Recording saved.")
            return True
        except Exception as exc:
            QMessageBox.warning(self, "Capture could not be saved", str(exc))
            return False

    def export_csv(self):
        if not self.frames:
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Export telemetry", "GT6_telemetry.csv", "CSV (*.csv)"
        )
        if not path:
            return
        try:
            fields = [
                "time_seconds",
                "x",
                "y",
                "z",
                "speed_kmh",
                "rpm",
                "gear",
                "lap",
                "throttle",
                "brake",
                "packet_id",
                "car_code",
            ]
            with Path(path).open("w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fields, extrasaction="ignore")
                writer.writeheader()
                writer.writerows(self.frames)
            self.notify(f"CSV exported.")
        except Exception as exc:
            QMessageBox.warning(self, "Export failed", str(exc))

    def export_report(self):
        if not self.replay:
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Export real replay metadata", "GT6_race_report.json", "JSON (*.json)"
        )
        if path:
            try:
                Path(path).write_text(
                    json.dumps(self.replay, ensure_ascii=False, indent=2), encoding="utf-8"
                )
                self.notify(f"Race report exported.")
            except Exception as exc:
                QMessageBox.warning(self, "Export failed", str(exc))

    def confirm_unsaved(self):
        if not self.dirty_capture:
            return True
        result = QMessageBox.question(
            self,
            "Unsaved capture",
            "Save the current capture before replacing it?",
            QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel,
        )
        if result == QMessageBox.Save:
            return self.save_capture()
        if result == QMessageBox.Discard:
            self.dirty_capture = False
            return True
        return False

    def closeEvent(self, event):
        if self.worker and self.worker.isRunning():
            QMessageBox.information(
                self, "Operation in progress", "Please wait for the replay operation to finish."
            )
            event.ignore()
            return
        if self.recorder:
            self.finish_recording()
        if not self.confirm_unsaved():
            event.ignore()
            return
        event.accept()


STYLE = "\nQWidget { background: #0b1320; color: #e6edf7; font-family: 'Segoe UI'; font-size: 12px; }\nQLabel#brand { font-size: 25px; font-weight: 700; }\nQLabel#track { font-size: 23px; font-weight: 600; }\nQLabel#muted, QLabel#caption { color: #9aadc5; }\nQLabel#banner { background: #172d38; color: #a5efdf; padding: 11px; border-radius: 6px; }\nQLabel#value { font-size: 28px; font-weight: 600; color: #f2f8ff; }\nQWidget#instrument { background: #142033; border-radius: 5px; }\nQWidget#instrument QLabel { background: transparent; }\nQPushButton { background: #1c2b40; border: 1px solid #31445e; padding: 8px 12px; border-radius: 5px; }\nQPushButton:hover { background: #2c4059; border-color: #7291b0; }\nQPushButton:disabled { background: #101b2b; color: #586b83; border-color: #223044; }\nQPushButton#primary { background: #206b5c; border-color: #359c84; color: #e6fff8; font-weight: 600; }\nQPushButton#primary:hover { background: #2a8973; }\nQTableWidget { background: #101a29; alternate-background-color: #142135; border: 1px solid #26374d; gridline-color: #23334a; }\nQTableWidget::item { padding: 6px 2px; }\nQTableWidget::item:selected { background: #245249; color: white; }\nQHeaderView::section { background: #1b2b3e; color: #a9b9cd; padding: 7px 3px; border: 0; }\nQTabWidget::pane { border: 1px solid #26374d; }\nQTabBar::tab { background: #142033; color: #a9b9cd; padding: 9px 18px; }\nQTabBar::tab:selected { color: #75ebcc; background: #1b2e3d; }\nQLineEdit, QComboBox { background: #142033; border: 1px solid #31445e; padding: 7px; border-radius: 4px; }\nQComboBox QAbstractItemView { background: #1c2b40; selection-background-color: #245249; }\nQSlider::groove:horizontal { height: 4px; background: #26374d; }\nQSlider::sub-page:horizontal { background: #53e0bf; }\nQSlider::handle:horizontal { background: #9bf4dc; width: 12px; margin: -5px 0; border-radius: 6px; }\nQSplitter::handle { background: #223044; width: 1px; }\nQScrollBar:vertical { background: #142033; width: 9px; }\nQScrollBar::handle:vertical { background: #354861; min-height: 25px; }\nQScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }\n"


def main():
    if len(sys.argv) == 4 and sys.argv[1] == "--verify-playback":
        os.environ["QT_QPA_PLATFORM"] = "offscreen"
        from playback_check import run

        return run(sys.argv[2], sys.argv[3])
    if len(sys.argv) == 4 and sys.argv[1] == "--verify-save":
        Path(sys.argv[3]).write_text(
            json.dumps(load_replay(sys.argv[2]), ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return 0
    if len(sys.argv) == 4 and sys.argv[1] == "--verify-native":
        native = load_native_replay(sys.argv[2])
        Path(sys.argv[3]).write_text(json.dumps(native.metadata, indent=2), encoding="utf-8")
        return 0
    import argparse

    parser = argparse.ArgumentParser(prog=APP_NAME)
    parser.add_argument("replay", nargs="?")
    parser.add_argument(
        "--decoder", type=Path, help="External decoder to execute when opening an unconverted save."
    )
    parser.add_argument("--version", action="version", version=f"{APP_NAME} {VERSION}")
    args = parser.parse_args()
    if args.decoder:
        os.environ["GT6REPLAY_DECODER"] = str(args.decoder.resolve())
    application = QApplication(sys.argv)
    application.setApplicationName(APP_NAME)
    application.setApplicationVersion(VERSION)
    application.setStyle("Fusion")
    application.setStyleSheet(STYLE)
    window = MainWindow()
    window.show()
    if args.replay:
        action = (
            window.load_native_file
            if Path(args.replay).suffix.lower() == ".gt6r"
            else (
                window.load_capture_file
                if Path(args.replay).suffix.lower() == ".json"
                else window.load_save
            )
        )
        QTimer.singleShot(0, lambda: action(args.replay))
    return application.exec()


if __name__ == "__main__":
    sys.exit(main())
