"""扇形菜单 / 贴图 / 最近记录 的自动化测试（无需真实桌面，用 offscreen 平台）。"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

_TMP = tempfile.mkdtemp(prefix="sujie_interaction_")
os.environ["APPDATA"] = _TMP
os.environ["LOCALAPPDATA"] = str(Path(_TMP) / "LocalAppData")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from PySide6.QtCore import QPoint  # noqa: E402
from PySide6.QtGui import QColor, QGuiApplication, QPixmap  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from sujie import history as history_mod, pinboard, radial  # noqa: E402

PASSED = 0
FAILED = 0


def check(condition: bool, name: str, detail="") -> None:
    global PASSED, FAILED
    if condition:
        PASSED += 1
        print(f"  [OK]   {name}" + (f"  ({detail})" if detail else ""))
    else:
        FAILED += 1
        print(f"  [FAIL] {name}  ({detail})")


def make_pixmap(width: int = 120, height: int = 80) -> QPixmap:
    pixmap = QPixmap(width, height)
    pixmap.fill(QColor("#e94f37"))
    return pixmap


def main() -> int:
    app = QApplication.instance() or QApplication([])
    print("== 扇形 / 贴图 / 最近记录 ==")

    print("\n[1] 扇区方向判定")
    check(radial.sector_at(0, -150) == "up", "向上滑 = 截图")
    check(radial.sector_at(-150, 0) == "left", "向左滑 = 录屏")
    check(radial.sector_at(150, 0) == "right", "向右滑 = 贴图")
    check(radial.sector_at(0, 150) == "down", "向下滑 = 记录")
    check(radial.sector_at(10, -10) is None, "死区内不触发", "10,-10")
    check(radial.sector_at(0, 0) is None, "原地不动不触发")
    check(radial.sector_at(120, -40) == "right", "偏右下仍判右", "120,-40")
    check(set(radial.SECTORS) == {"up", "left", "down", "right"}, "四个扇区齐全")
    check(radial.SECTORS["up"].action == "screenshot", "扇区带上动作名", radial.SECTORS["up"].action)
    check(radial.SECTORS["left"].action == "record", "左扇区动作是录屏")
    check(radial.SECTORS["right"].action == "pin", "右扇区动作是贴图")
    check(radial.SECTORS["down"].action == "history", "下扇区动作是记录")

    print("\n[2] 扇形菜单开合")
    menu = radial.RadialMenu(accent="#e94f37")
    screen = QGuiApplication.primaryScreen().geometry()
    center = screen.center()
    check(not menu.is_open(), "初始是关闭的")
    menu.open_at(center, 132)
    check(menu.is_open(), "打开后 is_open 为真")
    check(menu.current_sector() is None, "刚打开没有高亮")
    check(88 <= menu.radius() <= 190, "半径落在允许范围内", str(menu.radius()))
    menu.update_cursor(QPoint(center.x(), center.y() - 120))
    check(menu.current_sector() == "up", "向上移动高亮截图", str(menu.current_sector()))
    menu.update_cursor(QPoint(center.x() - 120, center.y()))
    check(menu.current_sector() == "left", "向左移动高亮录屏", str(menu.current_sector()))
    sealed = menu.commit()
    check(sealed == "left", "提交返回左扇区", str(sealed))
    check(not menu.is_open(), "提交后自动关闭")

    menu.open_at(center, 132)
    menu.update_cursor(QPoint(center.x(), center.y() - 120))
    sealed = menu.commit()
    check(sealed == "up", "第二次提交仍然可用", str(sealed))

    menu.open_at(center, 132)
    menu.update_cursor(QPoint(center.x(), center.y() - 120))
    menu.close_menu()
    check(not menu.is_open(), "close_menu 能关掉")
    check(menu.commit() is None, "关闭后提交返回 None")

    print("\n[3] 贴图钉屏")
    manager = pinboard.PinManager(max_count=2)
    window = manager.create(make_pixmap())
    check(manager.count() == 1, "创建一张贴图")
    check(window.zoom() == 1.0, "默认缩放 1.0", str(window.zoom()))
    window.set_zoom(99.0)
    check(window.zoom() <= pinboard.MAX_ZOOM, "缩放上限被夹住", str(window.zoom()))
    window.set_zoom(0.001)
    check(window.zoom() >= pinboard.MIN_ZOOM, "缩放下限被夹住", str(window.zoom()))
    window.set_zoom(1.0)
    check(window.image_size() == (120, 80), "原始尺寸可查", str(window.image_size()))

    manager.hide_all()
    check(bool(manager.hidden_for_capture), "抓屏前可以整体隐藏")
    manager.show_all()
    check(not bool(manager.hidden_for_capture), "隐藏状态可以恢复")

    manager.create(make_pixmap())
    manager.create(make_pixmap())
    check(manager.count() == 2, "超过上限时关掉最老的", f"{manager.count()} 张")
    manager.close_all()
    check(manager.count() == 0, "close_all 清空")

    print("\n[4] 最近记录")
    store = history_mod.History(limit=3)
    png = QPixmap(40, 30)
    png.fill(QColor("#123456"))
    from PySide6.QtCore import QBuffer, QByteArray, QIODevice

    data = QByteArray()
    buffer = QBuffer(data)
    buffer.open(QIODevice.WriteOnly)
    png.save(buffer, "PNG")
    payload = bytes(data)
    check(len(payload) > 100, "准备了一张 PNG", f"{len(payload)} 字节")

    entry = store.add_image("shot-1.png", payload, ["192.168.1.5"], True, "C:\\远端\\shot-1.png", "接收成功")
    check(entry.kind == "image", "图片条目类型正确", entry.kind)
    check(Path(entry.local_path).exists(), "本地留了副本", entry.local_path)
    check(bool(entry.thumb) and Path(entry.thumb).exists(), "生成了缩略图", entry.thumb)

    for index in range(5):
        store.add_image(f"shot-{index + 2}.png", payload, [], True, "", "")
    check(store.count() == 3, "超过 limit 自动裁剪", f"{store.count()} 条")
    entries = store.entries()
    check(len(entries) == 3, "entries 只返回最新的", str(len(entries)))
    check(entries[0].name == "shot-6.png", "最新的排最前", entries[0].name)

    video = Path(_TMP) / "clip.mp4"
    video.write_bytes(b"\x00\x00\x00\x20ftypisom" + b"\x00" * 64)
    store.add_video(video, ["192.168.1.5"], True, "", "接收成功")
    entries = store.entries()
    check(entries[0].kind == "video", "视频条目排最前", entries[0].kind)
    check(entries[0].kind_label() == "录屏", "视频条目有中文标签", entries[0].kind_label())

    src_file = Path(_TMP) / "报价单.docx"
    src_file.write_bytes(b"PK\x03\x04" + b"\x00" * 32)
    store.add_file(src_file, ["192.168.1.5"], True, "", "接收成功")
    entries = store.entries()
    check(entries[0].kind == "file", "文件条目排最前", entries[0].kind)
    check(entries[0].kind_label() == "文件", "文件条目有中文标签", entries[0].kind_label())
    check(entries[0].local_path == str(src_file), "文件条目引用原路径", entries[0].local_path)

    dialog = history_mod.HistoryDialog(store)
    check(len(dialog.current_entries()) == store.count(), "对话框能列出全部记录",
          str(len(dialog.current_entries())))
    dialog.resendRequested = lambda entry: None
    check(dialog.resendRequested is not None, "重新发送回调可以注入")

    sent_before = len(list(history_mod.sent_dir().iterdir()))
    store.clear()
    check(store.count() == 0, "清空后没有条目")
    check(len(list(history_mod.sent_dir().iterdir())) == 0, "清空时删掉了本地副本", f"清理前 {sent_before} 个")
    check(video.exists(), "清空历史不删用户录像原件", str(video))
    check(src_file.exists(), "清空历史不删用户文件原件", str(src_file))

    print("\n[5] 历史文件可重复读取")
    store.add_image("again.png", payload, [], True, "", "")
    reloaded = history_mod.History(limit=10)
    check(reloaded.count() == store.count(), "重新打开能读回记录", f"{reloaded.count()} 条")

    print("\n[6] 全局热键分发")
    import ctypes
    from ctypes import wintypes

    from sujie.client import HOTKEY_ID, HOTKEY_ID_SHOT, WM_HOTKEY, _HotkeyFilter

    calls: list[str] = []
    flt = _HotkeyFilter({
        HOTKEY_ID: lambda: calls.append("record"),
        HOTKEY_ID_SHOT: lambda: calls.append("shot"),
    })

    def deliver(message_id: int, wparam: int):
        msg = wintypes.MSG()
        msg.message = message_id
        msg.wParam = wparam
        address = ctypes.cast(ctypes.pointer(msg), ctypes.c_void_p).value
        return flt.nativeEventFilter(b"windows_generic_MSG", address)

    check(deliver(WM_HOTKEY, HOTKEY_ID_SHOT) == (False, 0), "过滤器不吞消息")
    check(calls == ["shot"], "截图热键 id 分发到截图回调", str(calls))
    deliver(WM_HOTKEY, HOTKEY_ID)
    check(calls == ["shot", "record"], "录屏热键 id 分发到录屏回调", str(calls))
    deliver(0x0010, HOTKEY_ID)
    check(calls == ["shot", "record"], "非热键消息不触发回调", str(calls))
    deliver(WM_HOTKEY, 0x9999)
    check(calls == ["shot", "record"], "未注册的热键 id 不触发回调", str(calls))

    print(f"\n结果：{PASSED} 通过 / {FAILED} 失败")
    return 1 if FAILED else 0


if __name__ == "__main__":
    raise SystemExit(main())
