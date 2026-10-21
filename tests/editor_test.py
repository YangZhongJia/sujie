"""截图编辑器图像操作自检。"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from PySide6.QtCore import QPointF  # noqa: E402
from PySide6.QtGui import QColor, QImage
from PySide6.QtWidgets import QApplication

from sujie.editor import _Canvas  # noqa: E402


def demo() -> None:
    app = QApplication.instance() or QApplication([])
    image = QImage(320, 240, QImage.Format_ARGB32)
    for y in range(image.height()):
        for x in range(image.width()):
            image.setPixelColor(x, y, QColor(x % 256, y % 256, (x + y) % 256))
    canvas = _Canvas(image)
    original = canvas.image

    canvas._add_action({"kind": "rect", "start": QPointF(20, 20), "end": QPointF(100, 100)})
    marked = canvas.image
    assert marked != original
    canvas.undo()
    assert canvas.image == original
    canvas.redo()
    assert canvas.image == marked

    canvas._add_action({"kind": "text", "point": QPointF(100, 130), "text": "test"})
    text_marked = canvas.image
    assert text_marked != marked
    canvas.undo()
    assert canvas.image == marked
    canvas.redo()
    assert canvas.image == text_marked

    canvas._add_action({"kind": "mosaic", "rect": image.rect()})
    pixelated = canvas.image
    assert pixelated.pixelColor(0, 0) == pixelated.pixelColor(1, 1)
    canvas.undo()
    assert canvas.image == text_marked
    print("editor self-check passed")


if __name__ == "__main__":
    sys.path.insert(0, "src")
    demo()
