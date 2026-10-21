"""设置对话框：多接收端、截图参数、工作模式、自启和连接测试。"""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from . import discovery, uploader, win32util
from .config import (
    AppModeConfig,
    CAPTURE_MODE_LABELS,
    CAPTURE_MODES,
    ClientConfig,
    MODE_CHOICES,
    MODE_LABELS,
    receiver_target,
)


class _ScanThread(QThread):
    finished_ok = Signal(list)

    def run(self):  # noqa: D102
        try:
            self.finished_ok.emit(discovery.discover())
        except Exception:
            self.finished_ok.emit([])


class SettingsDialog(QDialog):
    """客户端设置。"""

    def __init__(self, config: ClientConfig, parent=None):
        super().__init__(parent)
        self.config = config
        self._scan_thread: Optional[_ScanThread] = None
        self._targets = [dict(target) for target in config.targets]
        self.setWindowTitle("ShotBridge 设置")
        self.setMinimumWidth(520)
        self._build()
        self._load()

    # ----------------------------------------------------------------- 构建
    def _build(self) -> None:
        layout = QVBoxLayout(self)
        tabs = QTabWidget()
        tabs.addTab(self._build_target_tab(), "接收端")
        tabs.addTab(self._build_capture_tab(), "截图")
        tabs.addTab(self._build_general_tab(), "通用")
        layout.addWidget(tabs)

        self.test_label = QLabel("")
        self.test_label.setWordWrap(True)
        layout.addWidget(self.test_label)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("保存")
        buttons.button(QDialogButtonBox.Cancel).setText("取消")
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _build_target_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)

        hint = QLabel(
            "截图保存在【另一台电脑】上，所以要告诉本机往哪台机器发：\n"
            "① 先在另一台电脑运行 ShotBridge 接收端（开始菜单 → ShotBridge 接收端）；\n"
            "② 这里填那台电脑的 IP 和端口，或点「扫描局域网设备」自动查找；\n"
            "③ 可添加多台接收电脑，截图将发送到列表中的所有目标。"
        )
        hint.setWordWrap(True)
        layout.addWidget(hint)

        form = QFormLayout()
        self.host_edit = QLineEdit()
        self.host_edit.setPlaceholderText("例如 192.168.1.20")
        self.port_spin = QSpinBox()
        self.port_spin.setRange(1, 65535)
        self.token_edit = QLineEdit()
        self.token_edit.setEchoMode(QLineEdit.Password)
        self.token_edit.setPlaceholderText("与接收端一致；接收端未设置则留空")
        form.addRow("接收端 IP", self.host_edit)
        form.addRow("端口", self.port_spin)
        form.addRow("共享密钥", self.token_edit)

        scan_row = QHBoxLayout()
        self.scan_button = QPushButton("扫描局域网设备")
        self.scan_button.clicked.connect(self._scan_devices)
        scan_row.addWidget(self.scan_button)
        form.addRow("", scan_row)

        self.device_list = QListWidget()
        self.device_list.setMaximumHeight(110)
        self.device_list.itemDoubleClicked.connect(self._pick_device)
        form.addRow("发现的设备", self.device_list)

        self.target_list = QListWidget()
        self.target_list.setMaximumHeight(120)
        self.target_list.currentRowChanged.connect(self._load_target)
        form.addRow("发送目标", self.target_list)

        target_buttons = QHBoxLayout()
        add_button = QPushButton("添加 / 更新目标")
        add_button.clicked.connect(self._add_target)
        remove_button = QPushButton("移除选中目标")
        remove_button.clicked.connect(self._remove_target)
        target_buttons.addWidget(add_button)
        target_buttons.addWidget(remove_button)
        form.addRow("", target_buttons)

        layout.addLayout(form)
        return page

    def _build_capture_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        form = QFormLayout()

        self.mode_combo = QComboBox()
        for key in CAPTURE_MODES:
            self.mode_combo.addItem(CAPTURE_MODE_LABELS.get(key, key), key)
        form.addRow("单击小球时截图", self.mode_combo)

        layout.addLayout(form)
        layout.addStretch(1)
        return page

    def _build_general_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        form = QFormLayout()

        self.autostart_check = QCheckBox("开机自动启动")
        form.addRow("", self.autostart_check)

        self.retry_check = QCheckBox("发送失败时自动重试（离线补发）")
        form.addRow("", self.retry_check)

        self.notify_check = QCheckBox("发送成功后弹出提示")
        form.addRow("", self.notify_check)

        self.role_combo = QComboBox()
        for key in MODE_CHOICES:
            self.role_combo.addItem(MODE_LABELS[key], key)
        form.addRow("此电脑的工作模式", self.role_combo)

        layout.addLayout(form)
        layout.addStretch(1)
        return page

    # ----------------------------------------------------------------- 载入
    def _load(self) -> None:
        c = self.config
        self._refresh_targets()

        index = self.mode_combo.findData(c.capture_mode)
        if index >= 0:
            self.mode_combo.setCurrentIndex(index)
        self.autostart_check.setChecked(bool(c.auto_start))
        self.retry_check.setChecked(bool(c.retry_enabled))
        self.notify_check.setChecked(bool(c.notify_on_send))
        mode = AppModeConfig.load().mode or "screenshot"
        index = self.role_combo.findData(mode)
        self.role_combo.setCurrentIndex(max(index, 0))

    def _refresh_targets(self, selected_id: str = "") -> None:
        self.target_list.clear()
        selected_row = 0
        for row, target in enumerate(self._targets):
            name = target.get("name") or target.get("host", "")
            auth = "（已设密钥）" if target.get("token") else "（无密钥）"
            item = QListWidgetItem(
                f"{name}　{target.get('host')}:{target.get('port', 8765)} {auth}"
            )
            item.setData(Qt.UserRole, target.get("id", ""))
            self.target_list.addItem(item)
            if target.get("id") == selected_id:
                selected_row = row
        if self._targets:
            self.target_list.setCurrentRow(selected_row)

    def _load_target(self, row: int) -> None:
        if 0 <= row < len(self._targets):
            target = self._targets[row]
            self.host_edit.setText(str(target.get("host", "")))
            self.port_spin.setValue(int(target.get("port", 8765)))
            self.token_edit.setText(str(target.get("token", "")))

    def _add_target(self) -> None:
        host = self.host_edit.text().strip()
        if not host:
            QMessageBox.warning(self, "缺少配置", "请填写接收端 IP，或双击扫描到的设备。")
            return
        target = receiver_target(host, int(self.port_spin.value()), self.token_edit.text())
        for row, old in enumerate(self._targets):
            if old.get("id") == target["id"]:
                self._targets[row] = target
                self._refresh_targets(target["id"])
                return
        self._targets.append(target)
        self._refresh_targets(target["id"])

    def _remove_target(self) -> None:
        row = self.target_list.currentRow()
        if 0 <= row < len(self._targets):
            self._targets.pop(row)
            self._refresh_targets()
    # ----------------------------------------------------------------- 动作

    def _scan_devices(self) -> None:
        self.scan_button.setEnabled(False)
        self.test_label.setText("正在扫描局域网…")
        self._scan_thread = _ScanThread()
        self._scan_thread.finished_ok.connect(self._on_scan_done)
        self._scan_thread.start()

    def _on_scan_done(self, devices: list) -> None:
        self.scan_button.setEnabled(True)
        self.device_list.clear()
        if not devices:
            self.test_label.setText(
                "没有发现接收端。请确认对方电脑已运行 ShotBridge 接收程序，"
                "且两台机器在同一局域网；也可以手动填写 IP。"
            )
            return
        for device in devices:
            ips = ", ".join(device.get("ips", []) or [device.get("ip", "")])
            item = QListWidgetItem(f"{device.get('device', '未知设备')}　{ips}　:{device.get('http_port', 8765)}")
            item.setData(Qt.UserRole, device)
            self.device_list.addItem(item)
        self.test_label.setText(f"发现 {len(devices)} 台设备，双击填入后添加目标。")

    def _pick_device(self, item: QListWidgetItem) -> None:
        device = item.data(Qt.UserRole)
        if not device:
            return
        ips = device.get("ips") or []
        if ips:
            self.host_edit.setText(ips[0])
        self.port_spin.setValue(int(device.get("http_port", 8765)))
        self.token_edit.clear()

    def _collect(self) -> ClientConfig:
        c = self.config
        c.targets = [dict(target) for target in self._targets]
        c.capture_mode = self.mode_combo.currentData()
        c.auto_start = self.autostart_check.isChecked()
        c.retry_enabled = self.retry_check.isChecked()
        c.notify_on_send = self.notify_check.isChecked()
        self.app_mode = self.role_combo.currentData()
        return c

    def _on_accept(self) -> None:
        config = self._collect()
        if config.targets:
            result = uploader.test_connection(config)
        else:
            result = None
        if result and not result.ok:
            answer = QMessageBox.question(
                self,
                "连接测试未通过",
                f"测试结果：{result.message}\n\n仍然保存设置吗？",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if answer != QMessageBox.Yes:
                return
        elif result:
            self.test_label.setText(f"连接正常：{result.remote_path or result.message}")
        else:
            self.test_label.setText("还没有添加接收端，可稍后在设置中添加。")
        config.save()
        mode = AppModeConfig.load()
        mode.mode = self.app_mode
        mode.save()
        self.accept()
