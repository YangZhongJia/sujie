"""打包产物（dist\\速截\\速截.exe）端到端测试。

流程：
  1. 停掉已在运行的 速截 进程
  2. 写干净的 client.json / receiver.json（接收目录用临时目录）
  3. 启动接收端 exe，等 /ping 通
  4. 启动截图端 exe，等悬浮球窗口出现
  5. 校验悬浮球真的画出来了（窗口矩形内是球的颜色）
  6. 用 Win32 鼠标事件真点一下球
  7. 轮询接收目录，等新图片落盘并校验可打开

用法： python tests\\e2e_exe_test.py
"""

from __future__ import annotations

import ctypes
import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from ctypes import wintypes
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
# 可以用 SUJIE_EXE 指向别处（例如安装后的 %LOCALAPPDATA%\Programs\速截\速截.exe）
EXE = Path(os.environ.get("SUJIE_EXE") or (ROOT / "dist" / "速截" / "速截.exe"))
# 全程用临时 APPDATA，别动用户真实配置（子进程继承同一环境变量）
_SANDBOX_APPDATA = tempfile.mkdtemp(prefix="sb_e2e_appdata_")
os.environ["APPDATA"] = _SANDBOX_APPDATA
APPDATA_DIR = Path(os.environ["APPDATA"]) / "速截"
SAVE_DIR = ROOT / "tests" / "_e2e_saved"
PORT = 18765  # 用非默认端口，避免和用户正在跑的实例撞车

user32 = ctypes.windll.user32
user32.SetProcessDPIAware()

results: list[tuple[bool, str, str]] = []


def check(ok: bool, name: str, detail: str = "") -> bool:
    results.append((bool(ok), name, detail))
    print(("  [PASS] " if ok else "  [FAIL] ") + name + (f"  ({detail})" if detail else ""))
    return bool(ok)


# ----------------------------------------------------------------- 进程管理
def kill_all() -> None:
    subprocess.run(["taskkill", "/F", "/IM", "速截.exe"], capture_output=True)
    time.sleep(1.0)


def pids() -> set[int]:
    out = subprocess.run(
        ["tasklist", "/FI", "IMAGENAME eq 速截.exe", "/FO", "CSV", "/NH"],
        capture_output=True, text=True, errors="replace",
    ).stdout
    found = set()
    for line in out.splitlines():
        parts = line.strip('"').split('","')
        if len(parts) > 1 and parts[1].strip().isdigit():
            found.add(int(parts[1]))
    return found


def window_of(pid: int, title: str = "速截") -> tuple[int, tuple[int, int, int, int]] | None:
    """找属于该进程、可见、标题匹配的窗口，返回 (hwnd, rect)。"""

    def find():
        P = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
        hits: list[tuple[int, tuple[int, int, int, int]]] = []

        def cb(hwnd, _lparam):
            wpid = wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(wpid))
            if wpid.value != pid or not user32.IsWindowVisible(hwnd):
                return True
            buf = ctypes.create_unicode_buffer(256)
            user32.GetWindowTextW(hwnd, buf, 256)
            if title not in buf.value:
                return True
            rect = wintypes.RECT()
            user32.GetWindowRect(hwnd, ctypes.byref(rect))
            w, h = rect.right - rect.left, rect.bottom - rect.top
            if 20 <= w <= 400 and 20 <= h <= 400:  # 只可能是悬浮球这种小窗
                hits.append((int(hwnd), (rect.left, rect.top, rect.right, rect.bottom)))
            return True

        user32.EnumWindows(P(cb), 0)
        return hits

    hits = find()
    return hits[0] if hits else None


def editor_window(pid: int) -> int | None:
    P = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
    hit = []

    def cb(hwnd, _lparam):
        wpid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(wpid))
        title = ctypes.create_unicode_buffer(128)
        user32.GetWindowTextW(hwnd, title, 128)
        if wpid.value == pid and user32.IsWindowVisible(hwnd) and "编辑截图" in title.value:
            hit.append(int(hwnd))
            return False
        return True

    user32.EnumWindows(P(cb), 0)
    return hit[0] if hit else None


def press_dialog_key(hwnd: int, key: int, control: bool = False) -> None:
    user32.BringWindowToTop(hwnd)
    user32.SetForegroundWindow(hwnd)
    time.sleep(0.1)
    if control:
        user32.keybd_event(0x11, 0, 0, 0)
    user32.keybd_event(key, 0, 0, 0)
    user32.keybd_event(key, 0, 2, 0)
    if control:
        user32.keybd_event(0x11, 0, 2, 0)


# ----------------------------------------------------------------- 点击
def click(x: int, y: int) -> None:
    user32.SetCursorPos(int(x), int(y))
    time.sleep(0.15)
    user32.mouse_event(0x0002, 0, 0, 0, 0)  # LEFTDOWN
    time.sleep(0.08)
    user32.mouse_event(0x0004, 0, 0, 0, 0)  # LEFTUP


def drag(x1: int, y1: int, x2: int, y2: int) -> None:
    """按住左键从 (x1,y1) 拖到 (x2,y2)。

    用 SetCursorPos 逐步移动（会产生真实 WM_MOUSEMOVE），中间必须留出时间片，
    否则无激活窗口偶发收不到移动消息，整段拖动会退化成一次点击。
    """
    user32.SetCursorPos(int(x1), int(y1))
    time.sleep(0.25)
    user32.mouse_event(0x0002, 0, 0, 0, 0)  # LEFTDOWN
    time.sleep(0.2)
    steps = 16
    for i in range(1, steps + 1):
        user32.SetCursorPos(int(x1 + (x2 - x1) * i / steps), int(y1 + (y2 - y1) * i / steps))
        time.sleep(0.04)
    time.sleep(0.2)
    user32.mouse_event(0x0004, 0, 0, 0, 0)  # LEFTUP
    time.sleep(0.3)


def long_press_swipe(x: int, y: int, dx: int, dy: int, hold: float = 0.85) -> None:
    """按住小球不放（触发长按）、再朝某个方向滑出去、松手。"""
    user32.SetCursorPos(int(x), int(y))
    time.sleep(0.2)
    user32.mouse_event(0x0002, 0, 0, 0, 0)  # LEFTDOWN
    time.sleep(hold)                        # 超过长按阈值（默认 500ms）
    steps = 10
    for i in range(1, steps + 1):
        user32.SetCursorPos(int(x + dx * i / steps), int(y + dy * i / steps))
        time.sleep(0.02)
    time.sleep(0.15)
    user32.mouse_event(0x0004, 0, 0, 0, 0)  # LEFTUP
    time.sleep(0.5)


CLIENT_LOG = Path(os.environ.get("LOCALAPPDATA", "")) / "速截" / "logs" / "client.log"


def log_size() -> int:
    try:
        return CLIENT_LOG.stat().st_size
    except OSError:
        return 0


def wait_log(marker: str, offset: int = 0, timeout: float = 8.0) -> bool:
    """等客户端日志在 offset 之后出现某段文字，用于判断上一步交互真的结束了。"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with open(CLIENT_LOG, "rb") as handle:
                handle.seek(offset)
                text = handle.read().decode("utf-8", "replace")
        except OSError:
            text = ""
        if marker in text:
            return True
        time.sleep(0.2)
    return False


def _tasklist() -> str:
    try:
        out = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq ffmpeg.exe", "/FO", "CSV", "/NH"],
            capture_output=True, timeout=15,
        )
        return (out.stdout or b"").decode("utf-8", "replace")
    except (OSError, subprocess.SubprocessError):
        return ""


# ----------------------------------------------------------------- HTTP
def ping() -> dict | None:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{PORT}/ping", timeout=1.5) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, OSError, ValueError):
        return None


def wait_ping(timeout: float = 25.0) -> dict | None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        info = ping()
        if info:
            return info
        time.sleep(0.4)
    return None


# ----------------------------------------------------------------- 主流程
def main() -> int:
    from PIL import Image, ImageGrab

    print(f"测试目标: {EXE}")
    if not EXE.exists():
        print("找不到 exe，先跑 tools\\package.ps1 -SkipInstaller")
        return 2

    # 锁屏/无交互会话时 ImageGrab 会抛 OSError，此时无法做真实鼠标点击，直接跳过。
    try:
        ImageGrab.grab(all_screens=True)
    except OSError as exc:
        print(f"屏幕截图不可用（{exc}）——桌面已锁定或无交互会话，跳过 GUI 端到端测试。")
        print("解锁屏幕后重新运行本测试即可。")
        return 0

    print("\n[1] 准备干净的配置")
    kill_all()
    APPDATA_DIR.mkdir(parents=True, exist_ok=True)
    if SAVE_DIR.exists():
        for f in SAVE_DIR.rglob("*"):
            if f.is_file():
                f.unlink()
    SAVE_DIR.mkdir(parents=True, exist_ok=True)

    (APPDATA_DIR / "receiver.json").write_text(json.dumps({
        "save_dir": str(SAVE_DIR), "port": PORT, "token": "",
        "subdir_by_date": False, "filename_prefix": "e2e",
        "auto_start": False, "bind_address": "127.0.0.1",
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    (APPDATA_DIR / "client.json").write_text(json.dumps({
        "targets": [{"id": "e2e", "name": "本机接收端", "host": "127.0.0.1", "port": PORT, "token": ""}],
        "capture_mode": "screen",
        "auto_start": False, "retry_enabled": False, "retry_interval": 60,
        "notify_on_send": True, "sound_on_send": False,
        "show_ball": True, "ball_size": 52, "ball_opacity": 1.0,
        "ball_color": "#e94f37", "ball_position": "",
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    (APPDATA_DIR / "mode.json").write_text(json.dumps({"mode": "both"}), encoding="utf-8")
    check(True, "配置已写入", str(APPDATA_DIR))

    print("\n[2] 通过双端模式启动接收端和截图端")
    launcher = subprocess.Popen([str(EXE), "--mode", "both"], cwd=str(EXE.parent))
    info = wait_ping()
    if not check(info is not None, "接收端 /ping 有响应", str(info)):
        kill_all()
        return 1
    check(info.get("save_dir") == str(SAVE_DIR), "接收端保存目录正确", info.get("save_dir", ""))
    launcher.wait(timeout=10)
    check(len(pids()) == 2, "双端模式各启动一个角色进程", str(sorted(pids())))

    print("\n[3] 等待双端模式中的截图端")
    client_pid = None
    ball = None
    deadline = time.time() + 30
    while time.time() < deadline:
        for pid in pids():
            hit = window_of(pid)
            if hit:
                client_pid, ball = pid, hit
                break
        if ball:
            break
        time.sleep(0.4)
    if not check(ball is not None, "悬浮球窗口已出现", str(ball)):
        kill_all()
        return 1

    hwnd, rect = ball
    left, top, right, bottom = rect
    check(20 <= (right - left) <= 200, "悬浮球尺寸合理", f"{right - left}x{bottom - top}")

    # 球必须完整落在某块屏幕内（不能卡在双屏接缝）
    screen_w = user32.GetSystemMetrics(0)
    screen_h = user32.GetSystemMetrics(1)
    check(0 <= left and right <= screen_w + screen_w and 0 <= top and bottom <= screen_h,
          "悬浮球在屏幕可见范围内", f"({left},{top})-({right},{bottom})")

    print("\n[4] 校验悬浮球真的画出来了")
    ratio = 0.0
    for _ in range(6):
        time.sleep(1.0)
        shot = ImageGrab.grab(all_screens=True).convert("RGB")
        px = shot.load()
        reds = 0
        total = 0
        for y in range(top + 4, bottom - 4, 2):
            for x in range(left + 4, right - 4, 2):
                if not (0 <= x < shot.width and 0 <= y < shot.height):
                    continue
                total += 1
                r, g, b = px[x, y]
                if r > 150 and r - g > 55 and r - b > 55:
                    reds += 1
        ratio = reds / max(1, total)
        if ratio > 0.35:
            break
        # 球可能正被一张截图占用（hide → show），重新取一次窗口位置再试
        cur = window_of(client_pid)
        if cur:
            hwnd, rect = cur
            left, top, right, bottom = rect
    check(ratio > 0.35, "悬浮球窗口内是球体颜色", f"{ratio:.0%} 像素命中橙红")

    print("\n[5] 拖动小球")
    start_count = len(list(SAVE_DIR.rglob("*.png")))
    moved = None
    failed_attempts = 0
    for attempt in (1, 2, 3):
        drag((left + right) // 2, (top + bottom) // 2,
             (left + right) // 2 - 220, (top + bottom) // 2 + 120)
        deadline = time.time() + 4
        while time.time() < deadline:
            time.sleep(0.4)
            cur = window_of(client_pid)
            if cur is not None and cur[1] != rect:
                moved = cur
                break
        if moved:
            break
        failed_attempts += 1
        cur = window_of(client_pid)
        if cur is not None:
            hwnd, rect = cur  # 位置没变也要刷新一次句柄
        print(f"  (第 {attempt} 次拖动没生效——等价于一次点击，重试)")
    check(moved is not None, "悬浮球可以被拖动", str(moved[1] if moved else None))

    time.sleep(2.5)  # 等「失败尝试」触发的那几张截图落盘，避免算进后面的统计
    drag_shots = len(list(SAVE_DIR.rglob("*.png"))) - start_count
    check(
        drag_shots <= failed_attempts,
        "拖动阶段没有多余截图",
        f"新增 {drag_shots} 张，失败尝试 {failed_attempts} 次（每次失败尝试=一次点击）",
    )

    if moved is None:
        moved = (hwnd, rect)
    hwnd, rect = moved
    left, top, right, bottom = rect

    print("\n[6] 编辑器取消测试及打包上传测试")
    before = len(list(SAVE_DIR.rglob("*.png")))
    click((left + right) // 2, (top + bottom) // 2)
    deadline = time.time() + 10
    editor = None
    while time.time() < deadline:
        editor = editor_window(client_pid)
        if editor:
            break
        time.sleep(0.2)
    if not check(editor is not None, "截图后打开编辑器"):
        kill_all()
        return 1
    press_dialog_key(editor, 0x1B)  # Escape = cancel
    deadline = time.time() + 3
    while time.time() < deadline and editor_window(client_pid) is not None:
        time.sleep(0.1)
    check(editor_window(client_pid) is None, "取消关闭编辑器")
    time.sleep(0.8)
    check(len(list(SAVE_DIR.rglob("*.png"))) == before, "取消编辑不会上传")

    print("  使用打包 exe 自检发送 PNG，验证接收端完整传输")
    selftest = subprocess.run(
        [str(EXE), "--selftest", "--host", "127.0.0.1", "--port", str(PORT)],
        cwd=str(EXE.parent), timeout=40,
    )
    check(selftest.returncode == 0, "打包 exe 自检上传通过", f"exit={selftest.returncode}")
    got = None
    deadline = time.time() + 20
    while time.time() < deadline:
        files = sorted(SAVE_DIR.rglob("*.png"))
        if len(files) > before:
            got = files[-1]
            break
        time.sleep(0.4)
    if check(got is not None, "打包 exe 发送后接收端目录收到图片", str(got)):
        try:
            with Image.open(got) as im:
                im.load()
                check(im.width > 100 and im.height > 100, "收到的是合法图片", f"{im.width}x{im.height}")
        except Exception as exc:  # noqa: BLE001
            check(False, "收到的是合法图片", repr(exc))
        check(got.stat().st_size > 5000, "图片大小合理", f"{got.stat().st_size} 字节")

    print("\n[7] 长按扇形菜单：上滑截图 / 左滑录屏")
    ball = window_of(client_pid)
    if ball is None:
        check(False, "截图端仍在运行（扇形测试）")
    else:
        bx = (ball[1][0] + ball[1][2]) // 2
        by = (ball[1][1] + ball[1][3]) // 2

        # 上滑 = 截图：应该和单击一样弹出编辑器
        png_before = len(list(SAVE_DIR.rglob("*.png")))
        long_press_swipe(bx, by, 0, -120)
        editor = None
        deadline = time.time() + 12
        while time.time() < deadline:
            editor = editor_window(client_pid)
            if editor is not None:
                break
            time.sleep(0.3)
        check(editor is not None, "长按上滑触发了截图（打开编辑器）")
        if editor is not None:
            offset = log_size()
            press_dialog_key(editor, 0x1B)  # ESC = 取消
            wait_log("编辑器里取消了", offset, timeout=6.0)
            time.sleep(0.4)
        check(len(list(SAVE_DIR.rglob("*.png"))) == png_before, "取消后没有多出图片")

        # 左滑 = 录屏：启动 ffmpeg；上一步编辑器刚关，客户端可能还在收尾，失败就重试
        mp4_before = len(list(SAVE_DIR.rglob("*.mp4")))
        started = False
        for _attempt in range(3):
            long_press_swipe(bx, by, -120, 0)
            deadline = time.time() + 6
            while time.time() < deadline:
                if "ffmpeg" in _tasklist():
                    started = True
                    break
                time.sleep(0.4)
            if started:
                break
            extra = editor_window(client_pid)   # 万一把长按判成了点击，先关掉再重试
            if extra is not None:
                press_dialog_key(extra, 0x1B)
            time.sleep(0.8)
        check(started, "长按左滑启动了 ffmpeg 录制")
        if started:
            time.sleep(2.0)
            click(bx, by)               # 录制中单击 = 停止并发送
            got_mp4 = None
            deadline = time.time() + 40
            while time.time() < deadline:
                files = list(SAVE_DIR.rglob("*.mp4"))
                if len(files) > mp4_before:
                    got_mp4 = max(files, key=lambda p: p.stat().st_mtime)
                    break
                time.sleep(1.0)
            if check(got_mp4 is not None, "录屏文件已上传到接收端", str(got_mp4)):
                check(got_mp4.stat().st_size > 5000, "视频大小合理", f"{got_mp4.stat().st_size} 字节")
                with open(got_mp4, "rb") as handle:
                    handle.seek(4)
                    check(handle.read(4) == b"ftyp", "收到的是合法 mp4")
            deadline = time.time() + 20
            while time.time() < deadline and "ffmpeg" in _tasklist():
                time.sleep(0.5)
            check("ffmpeg" not in _tasklist(), "停止后 ffmpeg 已退出")

    print("\n[8] 工作模式切换")
    (APPDATA_DIR / "mode.json").write_text(json.dumps({"mode": "screenshot"}), encoding="utf-8")
    deadline = time.time() + 8
    while time.time() < deadline and ping() is not None:
        time.sleep(0.25)
    check(ping() is None and window_of(client_pid) is not None,
          "切到只截图后保留截图端并停止接收端")

    (APPDATA_DIR / "mode.json").write_text(json.dumps({"mode": "receiver"}), encoding="utf-8")
    deadline = time.time() + 10
    receiver_back = None
    while time.time() < deadline:
        receiver_back = ping()
        if receiver_back is not None and window_of(client_pid) is None:
            break
        time.sleep(0.25)
    check(receiver_back is not None and window_of(client_pid) is None,
          "切到只收图后启动接收端并停止截图端")

    print("\n[9] 清理")
    kill_all()
    check(len(pids()) == 0, "进程已全部退出")

    passed = sum(1 for ok, _, _ in results if ok)
    print(f"\n==== 结果 {passed}/{len(results)} 通过 ====")
    for ok, name, detail in results:
        if not ok:
            print(f"  失败：{name}  {detail}")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
