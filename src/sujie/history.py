"""最近记录：把每次发送/录制的结果记一份，方便回头找、重新发。

存两处：
* ``%APPDATA%\\速截\\history.jsonl`` —— 一行一条记录（新版在前）
* ``%LOCALAPPDATA%\\速截\\sent\\`` —— 实际文件的本地副本（图片）与缩略图
"""

from __future__ import annotations

import io
import json
import os
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from . import APP_NAME, bootstrap, paths, win32util

HISTORY_NAME = "history.jsonl"
THUMB_SIZE = 160
KIND_LABELS = {"image": "截图", "video": "录屏"}


def history_path() -> Path:
    return paths.app_data_dir() / HISTORY_NAME


def sent_dir() -> Path:
    return paths.local_data_dir() / "sent"


def thumbs_dir() -> Path:
    return paths.local_data_dir() / "thumbs"


def format_size(size: int) -> str:
    value = float(size or 0)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            if unit == "B":
                return f"{int(value)} B"
            return f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} GB"


def format_time(ts: float) -> str:
    try:
        return time.strftime("%m-%d %H:%M", time.localtime(float(ts)))
    except (ValueError, OSError):
        return ""


@dataclass
class HistoryEntry:
    ts: float = field(default_factory=time.time)
    name: str = ""
    kind: str = "image"
    size: int = 0
    ok: bool = True
    targets: List[str] = field(default_factory=list)
    remote_path: str = ""
    local_path: str = ""
    thumb: str = ""
    message: str = ""

    def to_dict(self) -> Dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict) -> Optional["HistoryEntry"]:
        if not isinstance(data, dict) or not data.get("name"):
            return None
        try:
            return cls(
                ts=float(data.get("ts") or 0.0),
                name=str(data.get("name") or ""),
                kind=str(data.get("kind") or "image"),
                size=int(data.get("size") or 0),
                ok=bool(data.get("ok", True)),
                targets=[str(item) for item in (data.get("targets") or [])],
                remote_path=str(data.get("remote_path") or ""),
                local_path=str(data.get("local_path") or ""),
                thumb=str(data.get("thumb") or ""),
                message=str(data.get("message") or ""),
            )
        except (TypeError, ValueError):
            return None

    def kind_label(self) -> str:
        return KIND_LABELS.get(self.kind, self.kind)

    def exists(self) -> bool:
        return bool(self.local_path) and os.path.isfile(self.local_path)


class History:
    """history.jsonl 的读写。"""

    def __init__(self, limit: int = 200):
        self.limit = max(1, int(limit or 200))

    # ------------------------------------------------------------------ 写入
    def add(self, entry: HistoryEntry) -> HistoryEntry:
        path = history_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with open(path, "a", encoding="utf-8") as handle:
                handle.write(json.dumps(entry.to_dict(), ensure_ascii=False) + "\n")
        except OSError as exc:
            bootstrap.log(f"写入历史记录失败：{exc}")
            return entry
        self._trim()
        return entry

    def add_image(self, filename: str, data: bytes, targets: List[str],
                  ok: bool, remote_path: str = "", message: str = "") -> HistoryEntry:
        local = self._store_copy(filename, data)
        thumb = self._make_thumb_from_bytes(filename, data) if local else ""
        entry = HistoryEntry(
            name=filename, kind="image", size=len(data or b""), ok=ok,
            targets=list(targets), remote_path=remote_path, local_path=local,
            thumb=thumb, message=message,
        )
        return self.add(entry)

    def add_video(self, path, targets: List[str], ok: bool,
                  remote_path: str = "", message: str = "") -> HistoryEntry:
        local = str(path) if path and Path(path).exists() else ""
        try:
            size = Path(path).stat().st_size if local else 0
        except OSError:
            size = 0
        entry = HistoryEntry(
            name=Path(path).name if path else "", kind="video", size=size, ok=ok,
            targets=list(targets), remote_path=remote_path, local_path=local,
            message=message,
        )
        return self.add(entry)

    # ------------------------------------------------------------------ 读取
    def entries(self, limit: int = 60) -> List[HistoryEntry]:
        path = history_path()
        if not path.exists():
            return []
        result: List[HistoryEntry] = []
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as handle:
                for line in handle:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entry = HistoryEntry.from_dict(json.loads(line))
                    except (ValueError, TypeError):
                        continue        # 坏行跳过，不允许一行损坏导致整段历史打不开
                    if entry is not None:
                        result.append(entry)
        except OSError:
            return []
        result.reverse()
        return result[:limit]

    def count(self) -> int:
        return len(self.entries(limit=10 ** 6))

    def clear(self) -> None:
        # 先读出来再删文件：如果先 unlink，下面的 entries() 就读不到任何记录了，
        # 留在 sent/ 和 thumbs/ 里的副本会永远攒着。
        existing = self.entries(limit=10 ** 6)
        try:
            history_path().unlink()
        except OSError:
            pass
        for entry in existing:
            self._remove_files(entry)

    # ------------------------------------------------------------------ 内部
    def _trim(self) -> None:
        all_entries = self.entries(limit=10 ** 6)
        if len(all_entries) <= self.limit:
            return
        keep = all_entries[: self.limit]
        drop = all_entries[self.limit:]
        for entry in drop:
            self._remove_files(entry)
        path = history_path()
        tmp = path.with_suffix(".jsonl.tmp")
        try:
            with open(tmp, "w", encoding="utf-8") as handle:
                for entry in reversed(keep):
                    handle.write(json.dumps(entry.to_dict(), ensure_ascii=False) + "\n")
            os.replace(tmp, path)
        except OSError as exc:
            bootstrap.log(f"裁剪历史记录失败：{exc}")

    def _store_copy(self, filename: str, data: bytes) -> str:
        if not data:
            return ""
        directory = sent_dir()
        try:
            directory.mkdir(parents=True, exist_ok=True)
            target = directory / filename
            index = 1
            while target.exists():
                target = directory / f"{Path(filename).stem}-{index}{Path(filename).suffix}"
                index += 1
            target.write_bytes(data)
            return str(target)
        except OSError as exc:
            bootstrap.log(f"保存本地副本失败：{exc}")
            return ""

    def _make_thumb_from_bytes(self, filename: str, data: bytes) -> str:
        try:
            from PIL import Image

            with Image.open(io.BytesIO(data)) as image:
                image = image.convert("RGB")
                image.thumbnail((THUMB_SIZE, THUMB_SIZE))
                directory = thumbs_dir()
                directory.mkdir(parents=True, exist_ok=True)
                target = directory / f"{Path(filename).stem}.png"
                image.save(target, "PNG")
                return str(target)
        except Exception as exc:  # 缩略图失败不影响主流程
            bootstrap.log(f"生成缩略图失败：{exc!r}")
            return ""

    @staticmethod
    def _remove_files(entry: HistoryEntry) -> None:
        # 图片条目的 local_path 是 sent/ 里应用自管的副本，可以删；
        # 录屏条目指向用户视频目录里的原始录像文件，只清记录、不动原件。
        items = [entry.thumb]
        if entry.kind != "video":
            items.append(entry.local_path)
        for item in items:
            if not item:
                continue
            try:
                Path(item).unlink()
            except OSError:
                pass


class HistoryDialog(QDialog):
    """最近记录面板。"""

    def __init__(self, history: History, parent=None):
        super().__init__(parent)
        self._history = history
        self._entries: List[HistoryEntry] = []
        self.resendRequested = None  # 由 client 赋值：callable(entry) -> None

        self.setWindowTitle(f"{APP_NAME} · 最近记录")
        self.setMinimumSize(620, 600)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 18, 22, 18)
        layout.setSpacing(12)
        title = QLabel("最近记录")
        title.setProperty("role", "title")
        layout.addWidget(title)
        self.summary = QLabel("共 0 条")
        self.summary.setProperty("role", "subtitle")
        layout.addWidget(self.summary)

        self.content = QStackedWidget(self)
        self.empty_page = QWidget(self)
        empty_layout = QVBoxLayout(self.empty_page)
        empty_layout.setAlignment(Qt.AlignCenter)
        empty_title = QLabel("暂无记录")
        empty_title.setProperty("role", "sectionTitle")
        empty_hint = QLabel("截图或录制发送后会显示在这里。")
        empty_hint.setProperty("role", "subtitle")
        empty_layout.addWidget(empty_title, 0, Qt.AlignCenter)
        empty_layout.addWidget(empty_hint, 0, Qt.AlignCenter)

        self.list = QListWidget(self)
        self.list.setIconSize(QSize(72, 72))
        self.list.setSelectionMode(QAbstractItemView.SingleSelection)
        self.list.itemDoubleClicked.connect(lambda _item: self._open_selected())
        self.list.currentRowChanged.connect(lambda _row: self._sync_buttons())
        self.content.addWidget(self.empty_page)
        self.content.addWidget(self.list)
        layout.addWidget(self.content, 1)

        buttons = QHBoxLayout()
        buttons.setSpacing(8)
        self.open_button = QPushButton("打开")
        self.open_button.setProperty("primary", True)
        self.open_button.clicked.connect(self._open_selected)
        self.resend_button = QPushButton("重新发送")
        self.resend_button.clicked.connect(self._resend_selected)
        self.folder_button = QPushButton("所在文件夹")
        self.folder_button.clicked.connect(self._open_folder)
        self.clear_button = QPushButton("清空")
        self.clear_button.setProperty("destructive", True)
        self.clear_button.clicked.connect(self._clear)
        close_button = QPushButton("关闭")
        close_button.clicked.connect(self.accept)
        for button in (self.open_button, self.resend_button, self.folder_button):
            buttons.addWidget(button)
        buttons.addStretch(1)
        buttons.addWidget(self.clear_button)
        buttons.addWidget(close_button)
        layout.addLayout(buttons)

        self.reload()

    # ---------------------------------------------------------------- 数据
    def reload(self) -> None:
        self._entries = self._history.entries(limit=200)
        self.list.clear()
        for entry in self._entries:
            item = QListWidgetItem(self._item_text(entry))
            icon = self._icon_for(entry)
            if icon is not None:
                item.setIcon(icon)
            item.setData(Qt.UserRole, entry)
            self.list.addItem(item)
        self.content.setCurrentWidget(self.list if self._entries else self.empty_page)
        self.summary.setText(f"共 {len(self._entries)} 条")
        self._sync_buttons()

    def _item_text(self, entry: HistoryEntry) -> str:
        targets = "、".join(entry.targets) if entry.targets else "（未发送）"
        state = "" if entry.ok else "  ⚠ 失败"
        return (f"{format_time(entry.ts)}  {entry.kind_label()}  "
                f"{format_size(entry.size)}{state}\n{entry.name}  →  {targets}")

    def _icon_for(self, entry: HistoryEntry) -> Optional[QIcon]:
        if entry.thumb and os.path.isfile(entry.thumb):
            pixmap = QPixmap(entry.thumb)
            if not pixmap.isNull():
                return QIcon(pixmap)
        if entry.exists():
            pixmap = QPixmap(entry.local_path)
            if not pixmap.isNull():
                return QIcon(pixmap.scaled(64, 64, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        return None

    def _selected(self) -> Optional[HistoryEntry]:
        item = self.list.currentItem()
        return item.data(Qt.UserRole) if item is not None else None

    def _sync_buttons(self) -> None:
        entry = self._selected()
        has_file = bool(entry and entry.exists())
        self.open_button.setEnabled(has_file)
        self.resend_button.setEnabled(has_file and callable(self.resendRequested))
        self.folder_button.setEnabled(bool(entry and entry.local_path))
        self.clear_button.setEnabled(bool(self._entries))

    # ---------------------------------------------------------------- 动作
    def _open_selected(self) -> None:
        entry = self._selected()
        if entry is None or not entry.exists():
            return
        win32util.open_path(entry.local_path)

    def _open_folder(self) -> None:
        entry = self._selected()
        if entry is None or not entry.local_path:
            return
        folder = os.path.dirname(entry.local_path)
        win32util.open_path(folder if folder else entry.local_path)

    def _resend_selected(self) -> None:
        entry = self._selected()
        if entry is None or not callable(self.resendRequested):
            return
        self.resendRequested(entry)

    def _clear(self) -> None:
        answer = QMessageBox.question(
            self,
            "清空最近记录",
            "这会删除记录和对应的本地副本。要继续吗？",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return
        self._history.clear()
        self.reload()

    def current_entries(self) -> List[HistoryEntry]:
        return list(self._entries)
