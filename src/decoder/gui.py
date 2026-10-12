"""Desktop front end for the standalone decoder utility."""

from pathlib import Path
import argparse
import json
import os
import re
import sys

from PySide6.QtCore import Qt, QThread, Signal, QStandardPaths, QTimer
from PySide6.QtGui import QIcon, QFontDatabase
from PySide6.QtWidgets import (
    QApplication,
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QFormLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QComboBox,
    QFileDialog,
    QMessageBox,
    QProgressBar,
    QTableWidget,
    QTableWidgetItem,
    QHeaderView,
)

from version import VERSION
from .operations import inspect_input, export_input
from .settings import key_file_path, configure_key_file, clear_key_file

STYLE = """
QWidget { background: #0b1320; color: #e6edf7; font-family: 'Segoe UI'; font-size: 13px; }
QLabel#brand { font-size: 26px; font-weight: 700; }
QLabel#summary { font-size: 18px; font-weight: 600; }
QLabel#muted { color: #a0b3ca; }
QLineEdit, QComboBox { background: #142033; border: 1px solid #31445e; border-radius: 4px; padding: 8px; }
QPushButton { background: #1c2b40; border: 1px solid #31445e; border-radius: 5px; padding: 8px 14px; }
QPushButton:hover { background: #2c4059; }
QPushButton:disabled { color: #64768d; }
QPushButton#primary { background: #206b5c; border-color: #359c84; font-weight: 600; }
QTableWidget { background: #101a29; border: 1px solid #26374d; gridline-color: #23334a; }
QHeaderView::section { background: #1b2b3e; color: #b3c3d5; padding: 8px; border: 0; }
QProgressBar { border: 1px solid #31445e; border-radius: 3px; }
QProgressBar::chunk { background: #359c84; }
"""


class Operation(QThread):
    completed = Signal(object)
    failed = Signal(str)
    progress = Signal(str)

    def __init__(self, action, parent=None):
        super().__init__(parent)
        self.action = action

    def run(self):
        try:
            self.completed.emit(self.action(self.progress.emit))
        except Exception as error:
            self.failed.emit(str(error))


def format_ms(value):
    if value is None:
        return "—"
    return f"{value // 60000}:{value // 1000 % 60:02d}.{value % 1000:03d}"


class DecoderWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        if not QFontDatabase.families():
            fonts = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts"
            for name in ("segoeui.ttf", "segoeuib.ttf", "seguisym.ttf"):
                QFontDatabase.addApplicationFont(str(fonts / name))
        self.setWindowTitle(f"GT6Replay Decoder {VERSION}")
        self.setWindowIcon(QIcon(str(Path(__file__).resolve().parents[1] / "assets/icon.svg")))
        self.resize(980, 670)
        self.setMinimumSize(820, 560)
        self.worker = None
        self.report = None
        self.controls = []
        tools = self.menuBar().addMenu("Tools")
        tools.addAction("Choose savedata key file…", self.choose_keys)
        tools.addAction("Clear savedata key file", self.clear_keys)
        help_menu = self.menuBar().addMenu("Help")
        help_menu.addAction(
            "About",
            lambda: QMessageBox.about(
                self,
                "GT6Replay Decoder",
                f"GT6Replay Decoder {VERSION}\n\nExports decrypted RPLY files and race reports.\n"
                "Full motion conversion is not yet available.\n\n"
                "Application: MIT license. Dependency notices accompany the program.",
            ),
        )
        root = QWidget()
        self.setCentralWidget(root)
        layout = QVBoxLayout(root)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(14)
        brand = QLabel("GT6Replay Decoder")
        brand.setObjectName("brand")
        layout.addWidget(brand)
        note = QLabel(
            "Export decrypted replay data and race information. Full motion conversion is not yet available."
        )
        note.setObjectName("muted")
        note.setWordWrap(True)
        layout.addWidget(note)
        form = QFormLayout()
        self.input = QLineEdit()
        self.input.setPlaceholderText("Replay export folder or decrypted .rply file")
        input_row = QHBoxLayout()
        input_row.addWidget(self.input, 1)
        for label, action in (("Folder…", self.choose_folder), ("File…", self.choose_file)):
            button = QPushButton(label)
            button.clicked.connect(action)
            input_row.addWidget(button)
            self.controls.append(button)
        form.addRow("Input", input_row)
        self.format = QComboBox()
        self.format.addItem("Decrypted replay (.rply)", "rply")
        self.format.addItem("Race report (.json)", "report")
        self.format.currentIndexChanged.connect(self.suggest_output)
        form.addRow("Export", self.format)
        self.output = QLineEdit()
        self.output.setPlaceholderText("Choose an export filename outside the original save folder")
        output_row = QHBoxLayout()
        output_row.addWidget(self.output, 1)
        output_button = QPushButton("Save as…")
        output_button.clicked.connect(self.choose_output)
        output_row.addWidget(output_button)
        self.controls.append(output_button)
        form.addRow("Output", output_row)
        key_row = QHBoxLayout()
        self.key_label = QLabel()
        self.key_label.setTextFormat(Qt.PlainText)
        self.key_label.setObjectName("muted")
        key_row.addWidget(self.key_label, 1)
        key_button = QPushButton("Choose key file…")
        key_button.clicked.connect(self.choose_keys)
        key_row.addWidget(key_button)
        self.controls.append(key_button)
        form.addRow("Savedata", key_row)
        layout.addLayout(form)
        self.summary = QLabel("Choose a replay to inspect.")
        self.summary.setTextFormat(Qt.PlainText)
        self.summary.setObjectName("summary")
        self.summary.setWordWrap(True)
        layout.addWidget(self.summary)
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(("Pos", "Driver", "Best lap", "Race time", "Car"))
        self.table.verticalHeader().hide()
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        layout.addWidget(self.table, 1)
        bottom = QHBoxLayout()
        self.status = QLabel("")
        self.status.setTextFormat(Qt.PlainText)
        self.status.setObjectName("muted")
        self.status.setWordWrap(True)
        bottom.addWidget(self.status, 1)
        self.inspect_button = QPushButton("Inspect")
        self.inspect_button.clicked.connect(self.inspect)
        bottom.addWidget(self.inspect_button)
        self.export_button = QPushButton("Export")
        self.export_button.setObjectName("primary")
        self.export_button.clicked.connect(self.export)
        bottom.addWidget(self.export_button)
        layout.addLayout(bottom)
        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.hide()
        layout.addWidget(self.progress)
        self.controls += [
            self.input,
            self.output,
            self.format,
            self.inspect_button,
            self.export_button,
        ]
        self.refresh_key_label()

    def refresh_key_label(self):
        try:
            path = key_file_path()
            self.key_label.setText(path.name if path else "Key file required for encrypted exports")
        except ValueError:
            self.key_label.setText("Savedata settings need attention")

    def choose_keys(self):
        if self.worker and self.worker.isRunning():
            return
        path, _ = QFileDialog.getOpenFileName(
            self, "Choose savedata key configuration", "", "JSON (*.json)"
        )
        if path:
            try:
                configure_key_file(path)
                self.refresh_key_label()
            except (ValueError, OSError) as error:
                QMessageBox.warning(self, "Key file could not be used", str(error))

    def clear_keys(self):
        if self.worker and self.worker.isRunning():
            return
        try:
            clear_key_file()
            self.refresh_key_label()
        except OSError as error:
            QMessageBox.warning(self, "Settings could not be changed", str(error))

    def choose_folder(self):
        path = QFileDialog.getExistingDirectory(self, "Choose the GT6 replay export folder")
        if path:
            self.input.setText(path)
            self.suggest_output()

    def choose_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Choose replay data", "", "Replay data (*.rply);;All files (*)"
        )
        if path:
            self.input.setText(path)
            self.suggest_output()

    def suggest_output(self):
        current = self.output.text().strip()
        suffix = ".rply" if self.format.currentData() == "rply" else ".json"
        if current:
            self.output.setText(str(Path(current).with_suffix(suffix)))
            return
        source = Path(self.input.text().strip())
        name = source.stem if source.suffix.lower() == ".rply" else source.name
        name = re.sub(r'[<>:"/\\|?*]', "_", name).strip(". ") or "replay"
        documents = QStandardPaths.writableLocation(QStandardPaths.DocumentsLocation) or str(
            Path.home()
        )
        self.output.setText(str(Path(documents) / "GT6Replay Exports" / (name + suffix)))

    def choose_output(self):
        self.suggest_output()
        filter = "Replay data (*.rply)" if self.format.currentData() == "rply" else "JSON (*.json)"
        path, _ = QFileDialog.getSaveFileName(
            self, "Choose export filename", self.output.text(), filter
        )
        if path:
            self.output.setText(path)

    def run_operation(self, action, completed_message):
        if self.worker and self.worker.isRunning():
            return
        if not self.input.text().strip():
            QMessageBox.information(
                self, "Choose a replay", "Select a replay export folder or .rply file first."
            )
            return
        for control in self.controls:
            control.setEnabled(False)
        self.progress.show()
        self.status.setText("Reading replay…")
        self.worker = Operation(action, self)
        self.worker.progress.connect(self.status.setText)
        self.worker.completed.connect(lambda report: self.show_report(report, completed_message))
        self.worker.failed.connect(self.operation_failed)
        self.worker.finished.connect(self.operation_finished)
        self.worker.start()

    def inspect(self):
        path = self.input.text().strip()
        self.run_operation(
            lambda progress: inspect_input(path, progress=progress)[1], "Ready to export."
        )

    def export(self):
        source, output, mode = (
            self.input.text().strip(),
            self.output.text().strip(),
            self.format.currentData(),
        )
        if not output:
            self.suggest_output()
            output = self.output.text()
        overwrite = False
        if Path(output).exists():
            choice = QMessageBox.question(
                self,
                "Replace export?",
                "The selected output already exists. Replace it?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if choice != QMessageBox.Yes:
                return
            overwrite = True
        self.run_operation(
            lambda progress: export_input(
                source, output, mode, overwrite=overwrite, progress=progress
            ),
            "Export saved.",
        )

    def show_report(self, report, status="Ready to export."):
        self.report = report
        replay = report["replay"]
        metadata = replay["metadata"]
        self.summary.setText(
            f"{metadata.get('track') or 'Replay'} · {len(replay['entries'])} drivers · {metadata['total_frames'] / 60:.1f} seconds"
        )
        entries = sorted(replay["entries"], key=lambda entry: entry.get("position") or 999)
        self.table.setRowCount(len(entries))
        for row, entry in enumerate(entries):
            values = (
                entry.get("position") or "—",
                entry["name"],
                format_ms(entry.get("best_lap_ms")),
                format_ms(entry.get("total_time_ms")),
                entry.get("car_name") or "—",
            )
            for column, value in enumerate(values):
                self.table.setItem(row, column, QTableWidgetItem(str(value)))
        self.status.setText(status)

    def operation_failed(self, message):
        self.status.setText("Operation could not be completed.")
        QMessageBox.warning(self, "Replay operation failed", message)

    def operation_finished(self):
        self.progress.hide()
        for control in self.controls:
            control.setEnabled(True)

    def closeEvent(self, event):
        if self.worker and self.worker.isRunning():
            QMessageBox.information(
                self, "Operation in progress", "Please wait for the replay operation to finish."
            )
            event.ignore()
            return
        event.accept()


def main(arguments=None):
    parser = argparse.ArgumentParser(prog="GT6ReplayDecoder")
    parser.add_argument("--input", type=Path)
    parser.add_argument("--verify-gui", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args(arguments)
    if args.verify_gui:
        os.environ["QT_QPA_PLATFORM"] = "offscreen"
    application = QApplication.instance() or QApplication([])
    application.setStyleSheet(STYLE)
    window = DecoderWindow()
    if args.input:
        window.input.setText(str(args.input))
        window.suggest_output()
    window.show()
    if args.verify_gui:

        def verify():
            assert window.isVisible()
            args.verify_gui.parent.mkdir(parents=True, exist_ok=True)
            assert window.grab().save(str(args.verify_gui.with_suffix(".png")))
            args.verify_gui.write_text(
                json.dumps(
                    {
                        "title": window.windowTitle(),
                        "standalone_gui": True,
                        "export_formats": [
                            window.format.itemData(i) for i in range(window.format.count())
                        ],
                        "motion_conversion_available": False,
                    }
                )
            )
            window.close()
            application.quit()

        QTimer.singleShot(100, verify)
    return application.exec()
