"""First-run mode selection and role process startup."""

from __future__ import annotations

import os
import subprocess
import sys
from typing import Optional

from . import bootstrap
from .config import AppModeConfig, MODE_CHOICES, MODE_LABELS

MANAGED_ENV = "SUJIE_MANAGED_MODE"

def _command(role: str) -> list[str]:
    if getattr(sys, "frozen", False):
        return [sys.executable, f"--{role}"]
    return [sys.executable, os.path.abspath(sys.argv[0]), f"--{role}"]


def launch_mode(mode: str, current_role: Optional[str] = None, app=None) -> None:
    """Start missing roles and stop this role when the selected mode excludes it."""
    if mode not in MODE_CHOICES:
        return
    config = AppModeConfig.load()
    config.mode = mode
    config.save()

    wanted = {
        "screenshot": ("client",),
        "receiver": ("receiver",),
        "both": ("client", "receiver"),
    }[mode]
    env = os.environ.copy()
    env[MANAGED_ENV] = "1"
    for role in wanted:
        if role == current_role:
            continue
        try:
            subprocess.Popen(_command(role), env=env, close_fds=True)
        except OSError as exc:
            bootstrap.log(f"启动{MODE_LABELS[mode]}中的{role}角色失败：{exc}")

    if app is not None and current_role not in wanted:
        app.quit()


def _choose_mode(current_mode: Optional[str] = None) -> str:
    from PySide6.QtWidgets import (
        QApplication, QDialog, QDialogButtonBox, QFrame, QHBoxLayout, QLabel,
        QButtonGroup, QRadioButton, QVBoxLayout,
    )
    from .theme import apply_theme

    app = QApplication.instance() or QApplication([])
    apply_theme(app)
    dialog = QDialog()
    dialog.setObjectName("modeDialog")
    dialog.setWindowTitle("选择工作模式 · 速截")
    dialog.setMinimumWidth(500)
    layout = QVBoxLayout(dialog)
    layout.setContentsMargins(24, 22, 24, 20)
    layout.setSpacing(12)
    title = QLabel("这台电脑如何使用速截？")
    title.setProperty("role", "title")
    layout.addWidget(title)
    subtitle = QLabel("之后可在开始菜单中随时更改。")
    subtitle.setProperty("role", "subtitle")
    layout.addWidget(subtitle)

    options = {}
    rows = {}
    group = QButtonGroup(dialog)
    group.setExclusive(True)
    descriptions = {
        "screenshot": "截取并编辑图片，再发送到其他电脑。",
        "receiver": "在后台接收截图，并保存到这台电脑。",
        "both": "这台电脑既能截图发送，也能接收图片。",
    }
    for mode in MODE_CHOICES:
        row = QFrame()
        row.setObjectName("modeOption")
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(14, 10, 14, 10)
        option = QRadioButton(MODE_LABELS[mode])
        option.setStyleSheet("font-weight: 600")
        text_layout = QVBoxLayout()
        text_layout.setSpacing(3)
        detail = QLabel(descriptions[mode])
        detail.setProperty("role", "subtitle")
        text_layout.addWidget(option)
        text_layout.addWidget(detail)
        row_layout.addLayout(text_layout, 1)
        layout.addWidget(row)
        group.addButton(option)
        options[mode] = option
        rows[mode] = row

        def update_row(checked: bool, target=row) -> None:
            target.setProperty("selected", checked)
            target.style().unpolish(target)
            target.style().polish(target)

        option.toggled.connect(update_row)

    selected = current_mode if current_mode in options else "screenshot"
    options[selected].setChecked(True)
    for key, row in rows.items():
        row.setProperty("selected", key == selected)

    layout.addSpacing(4)
    buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
    buttons.button(QDialogButtonBox.Ok).setText("继续")
    buttons.button(QDialogButtonBox.Cancel).setText("取消")
    buttons.button(QDialogButtonBox.Ok).setProperty("primary", True)
    buttons.accepted.connect(dialog.accept)
    buttons.rejected.connect(dialog.reject)
    layout.addWidget(buttons)
    if dialog.exec() != QDialog.Accepted:
        return ""
    return next(mode for mode, option in options.items() if option.isChecked())


def main(mode_arg: Optional[str] = None, force_choose: bool = False) -> int:
    if not bootstrap.acquire_single_instance("速截Launcher"):
        return 0
    config = AppModeConfig.load()
    mode = _choose_mode(config.mode) if force_choose else (mode_arg or config.mode)
    if mode not in MODE_CHOICES:
        mode = _choose_mode(config.mode)
    if mode not in MODE_CHOICES:
        return 0
    launch_mode(mode)
    return 0
