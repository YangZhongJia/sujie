"""截图编辑器图像操作自检。"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from PySide6.QtCore import QPointF  # noqa: E402
from PySide6.QtGui import QColor, QGuiApplication, QImage  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

import sujie.editor as editor_module  # noqa: E402
from sujie.editor import RESULT_COPY, RESULT_SAVE, ScreenshotEditor, _Canvas  # noqa: E402


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

    dialog_demo(app)
    print("editor self-check passed")


def dialog_demo(app) -> None:
    small = QImage(64, 48, QImage.Format_ARGB32)
    small.fill(QColor("#336699"))

    # 复制按钮：剪贴板拿到图像，结果码是 RESULT_COPY
    editor = ScreenshotEditor(small)
    editor._copy_and_close()
    clip = QGuiApplication.clipboard().image()
    assert not clip.isNull() and (clip.width(), clip.height()) == (64, 48), "复制后剪贴板应为 64x48"
    assert editor.result() == RESULT_COPY, "复制应以 RESULT_COPY 关闭"

    # 保存按钮：伪造保存对话框，验证落盘和结果码
    editor = ScreenshotEditor(small)
    target = Path(tempfile.mkdtemp(prefix="sujie_editor_")) / "saved-shot.png"
    real_dialog = editor_module.QFileDialog

    class _FakeDialog:
        @staticmethod
        def getSaveFileName(*_args, **_kwargs):
            return (str(target), "PNG 图片 (*.png)")

    editor_module.QFileDialog = _FakeDialog
    try:
        editor._save_and_close()
    finally:
        editor_module.QFileDialog = real_dialog
    assert target.exists() and target.stat().st_size > 100, "保存后应有非空 PNG"
    saved = QImage(str(target))
    assert not saved.isNull() and (saved.width(), saved.height()) == (64, 48), "保存的图应为 64x48"
    assert editor.result() == RESULT_SAVE, "保存应以 RESULT_SAVE 关闭"

    # 保存对话框被取消：编辑器不能被关掉
    editor = ScreenshotEditor(small)

    class _CancelDialog:
        @staticmethod
        def getSaveFileName(*_args, **_kwargs):
            return ("", "")

    editor_module.QFileDialog = _CancelDialog
    try:
        editor._save_and_close()
    finally:
        editor_module.QFileDialog = real_dialog
    assert editor.result() == 0, "取消保存时对话框不应结束"

    print("editor dialog checks passed")


if __name__ == "__main__":
    sys.path.insert(0, "src")
    demo()
