from pathlib import Path
import os

os.environ["QT_QPA_PLATFORM"] = "offscreen"
from PySide6.QtWidgets import QApplication
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtGui import QImage, QPainter

ROOT = Path(__file__).resolve().parents[1]
application = QApplication([])
image = QImage(256, 256, QImage.Format_ARGB32)
image.fill(0)
painter = QPainter(image)
QSvgRenderer(str(ROOT / "src/assets/icon.svg")).render(painter)
painter.end()
assert image.save(str(ROOT / "src/assets/icon.ico"), "ICO")
