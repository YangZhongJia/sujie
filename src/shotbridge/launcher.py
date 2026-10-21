"""First-run mode selection and role process startup."""

from __future__ import annotations

import os
import subprocess
import sys
from typing import Optional

from . import bootstrap
from .config import AppModeConfig, MODE_CHOICES, MODE_LABELS

MANAGED_ENV = "SHOTBRIDGE_MANAGED_MODE"

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


def _choose_mode() -> str:
    from PySide6.QtWidgets import QApplication, QDialog, QDialogButtonBox, QLabel, QRadioButton, QVBoxLayout

    app = QApplication.instance() or QApplication([])
    dialog = QDialog()
    dialog.setWindowTitle("选择 ShotBridge 工作模式")
    layout = QVBoxLayout(dialog)
    layout.addWidget(QLabel("这台电脑主要用于："))
    options = {}
    for mode in MODE_CHOICES:
        option = QRadioButton(MODE_LABELS[mode])
        options[mode] = option
        layout.addWidget(option)
    options["screenshot"].setChecked(True)
    buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
    buttons.button(QDialogButtonBox.Ok).setText("继续")
    buttons.button(QDialogButtonBox.Cancel).setText("取消")
    buttons.accepted.connect(dialog.accept)
    buttons.rejected.connect(dialog.reject)
    layout.addWidget(buttons)
    if dialog.exec() != QDialog.Accepted:
        return ""
    return next(mode for mode, option in options.items() if option.isChecked())


def main(mode_arg: Optional[str] = None) -> int:
    if not bootstrap.acquire_single_instance("ShotBridgeLauncher"):
        return 0
    config = AppModeConfig.load()
    mode = mode_arg or config.mode
    if mode not in MODE_CHOICES:
        mode = _choose_mode()
    if mode not in MODE_CHOICES:
        return 0
    launch_mode(mode)
    return 0
