"""走真实局域网地址的连通性测试（本机同时扮演发送端和接收端）。

和 e2e_exe_test.py 的区别：这里不用 127.0.0.1，而是用本机网卡的真实 IPv4，
把「另一台电脑」的路径完整跑一遍：
  1. 接收端绑 0.0.0.0，用局域网 IP 访问 /ping
  2. 用 uploader.http_upload 通过局域网 IP 上传一张图，校验落盘
  3. 跑一次 UDP 广播发现，确认接收端被找到
  4. 截图端把目标配成局域网 IP，点球后确认图片到达

用法：
  python tests\\lan_path_test.py                      # 测 dist 里的 exe
  SHOTBRIDGE_EXE=... python tests\\lan_path_test.py   # 测指定 exe
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

EXE = Path(os.environ.get("SHOTBRIDGE_EXE") or (ROOT / "dist" / "ShotBridge" / "ShotBridge.exe"))
# 全程用临时 APPDATA，子进程继承同一环境变量，不碰用户真实配置
_SANDBOX_APPDATA = tempfile.mkdtemp(prefix="sb_lan_appdata_")
os.environ["APPDATA"] = _SANDBOX_APPDATA
APPDATA_DIR = Path(os.environ["APPDATA"]) / "ShotBridge"
SAVE_DIR = ROOT / "tests" / "_lan_saved"
PORT = 18766

results: list[tuple[bool, str, str]] = []


def check(ok: bool, name: str, detail: str = "") -> bool:
    results.append((bool(ok), name, detail))
    print(("  [PASS] " if ok else "  [FAIL] ") + name + (f"  ({detail})" if detail else ""))
    return bool(ok)


def lan_ip() -> str:
    from shotbridge.win32util import local_ipv4_addresses
    ips = local_ipv4_addresses()
    for ip in ips:
        if ip.startswith(("192.168.", "10.", "172.")):
            return ip
    return ips[0]


def kill_all() -> None:
    subprocess.run(["taskkill", "/F", "/IM", "ShotBridge.exe"], capture_output=True)
    time.sleep(1.0)


def http_json(url: str, token: str = "", timeout: float = 3.0) -> dict | None:
    request = urllib.request.Request(url)
    if token:
        request.add_header("X-Token", token)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, OSError, ValueError):
        return None


def wait_ping(url: str, token: str = "", timeout: float = 25.0) -> dict | None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        info = http_json(url, token)
        if info:
            return info
        time.sleep(0.4)
    return None


def main() -> int:
    from shotbridge import discovery, uploader
    from shotbridge import capture

    ip = lan_ip()
    print(f"本机局域网 IP: {ip}")
    print(f"被测 exe: {EXE}")
    if not EXE.exists():
        print("找不到 exe，先跑 tools\\package.ps1 -SkipInstaller")
        return 2

    # 取图与点球需要可交互桌面；锁屏时这两步跳过，其余局域网检查照常执行
    from PIL import ImageGrab

    try:
        ImageGrab.grab(all_screens=True)
        screen_ok = True
    except OSError as exc:
        screen_ok = False
        print(f"注意：屏幕截图不可用（{exc}）——桌面已锁定，取图用合成图片、点球步骤跳过。")

    print("\n[1] 准备接收端配置（绑 0.0.0.0，端口 %d）" % PORT)
    kill_all()
    APPDATA_DIR.mkdir(parents=True, exist_ok=True)
    if SAVE_DIR.exists():
        for f in SAVE_DIR.rglob("*"):
            if f.is_file():
                f.unlink()
    SAVE_DIR.mkdir(parents=True, exist_ok=True)
    (APPDATA_DIR / "receiver.json").write_text(json.dumps({
        "save_dir": str(SAVE_DIR), "port": PORT, "token": "lan-token",
        "subdir_by_date": False, "filename_prefix": "lan",
        "auto_start": False, "bind_address": "0.0.0.0",
    }, ensure_ascii=False, indent=2), encoding="utf-8")

    print("\n[2] 启动接收端并用局域网 IP 访问")
    receiver = subprocess.Popen([str(EXE), "--receiver"], cwd=str(EXE.parent))
    info = wait_ping(f"http://{ip}:{PORT}/ping", token="lan-token")
    if not check(info is not None, "局域网 IP 上 /ping 通", f"http://{ip}:{PORT}/ping"):
        receiver.kill()
        kill_all()
        return 1
    check(info.get("ip") == ip, "接收端上报的 IP 与网卡一致", f"{info.get('ip')} vs {ip}")
    unauth = uploader.http_ping(host=ip, port=PORT, token="")
    check(not unauth.ok, "不带 token 的探测被拒绝", unauth.message)

    print("\n[3] 用上传模块通过局域网 IP 传一张图")
    import io

    from PIL import Image

    if screen_ok:
        img = capture.capture_primary_monitor().image
    else:
        img = Image.new("RGB", (800, 600), (40, 40, 40))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    data = buf.getvalue()
    before = len(list(SAVE_DIR.rglob("*.png")))
    res = uploader.http_upload(
        host=ip, port=PORT, filename="lan-test.png", data=data,
        token="lan-token", timeout=15.0,
    )
    check(res.ok, "局域网 HTTP 上传成功", f"{res.message} {res.remote_path or ''}")
    after = len(list(SAVE_DIR.rglob("*.png")))
    check(after > before, "图片落到指定文件夹", f"{before} -> {after}")

    print("\n[4] 错误的 token 必须被拒")
    bad = uploader.http_upload(
        host=ip, port=PORT, filename="bad.png", data=data,
        token="wrong-token", timeout=10.0,
    )
    check(not bad.ok, "错误 token 被拒绝", bad.message)
    check(len(list(SAVE_DIR.rglob("*.png"))) == after, "被拒的上传没有落盘")

    print("\n[5] UDP 广播发现")
    found = discovery.discover(timeout=2.0)
    names = [d.get("device", "?") for d in found]
    check(len(found) > 0, "发现服务收到应答", f"{len(found)} 个: {names}")
    if found:
        check(any(int(d.get("http_port", 0)) == PORT for d in found), "应答端口与接收端一致",
              str([d.get("http_port") for d in found]))

    if screen_ok:
        print("\n[6] 截图端指向局域网 IP，点球验证")
        (APPDATA_DIR / "client.json").write_text(json.dumps({
            "targets": [{"id": "lan-test", "name": ip, "host": ip, "port": PORT, "token": "lan-token"}],
            "capture_mode": "screen",
            "auto_start": False, "retry_enabled": False, "retry_interval": 60,
            "notify_on_send": True, "sound_on_send": False,
            "show_ball": True, "ball_size": 52, "ball_opacity": 1.0,
            "ball_color": "#e94f37", "ball_position": "",
        }, ensure_ascii=False, indent=2), encoding="utf-8")
        (APPDATA_DIR / "mode.json").write_text(json.dumps({"mode": "screenshot"}), encoding="utf-8")

        client = subprocess.Popen([str(EXE), "--client"], cwd=str(EXE.parent))
        import ctypes
        from ctypes import wintypes
        user32 = ctypes.windll.user32
        user32.SetProcessDPIAware()

        def ball_rect() -> tuple[int, int, int, int] | None:
            def find():
                P = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
                hits = []

                def cb(hwnd, _l):
                    wpid = wintypes.DWORD()
                    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(wpid))
                    if wpid.value != client.pid or not user32.IsWindowVisible(hwnd):
                        return True
                    buf = ctypes.create_unicode_buffer(256)
                    user32.GetWindowTextW(hwnd, buf, 255)
                    if "ShotBridge" not in buf.value:
                        return True
                    r = wintypes.RECT()
                    user32.GetWindowRect(hwnd, ctypes.byref(r))
                    if 20 <= r.right - r.left <= 400 and 20 <= r.bottom - r.top <= 400:
                        hits.append((r.left, r.top, r.right, r.bottom))
                    return True

                user32.EnumWindows(P(cb), 0)
                return hits

            hits = find()
            return hits[0] if hits else None

        rect = None
        deadline = time.time() + 30
        while time.time() < deadline:
            rect = ball_rect()
            if rect:
                break
            time.sleep(0.4)
        if not check(rect is not None, "悬浮球出现", str(rect)):
            client.kill()
            receiver.kill()
            kill_all()
            return 1

        cx, cy = (rect[0] + rect[2]) // 2, (rect[1] + rect[3]) // 2
        before_click = len(list(SAVE_DIR.rglob("*.png")))
        user32.SetCursorPos(cx, cy)
        time.sleep(0.2)
        user32.mouse_event(0x0002, 0, 0, 0, 0)
        time.sleep(0.08)
        user32.mouse_event(0x0004, 0, 0, 0, 0)

        editor = None
        deadline = time.time() + 10
        while time.time() < deadline and editor is None:
            def find_editor(hwnd, _lparam):
                wpid = wintypes.DWORD()
                user32.GetWindowThreadProcessId(hwnd, ctypes.byref(wpid))
                title = ctypes.create_unicode_buffer(128)
                user32.GetWindowTextW(hwnd, title, 128)
                if wpid.value == client.pid and "编辑截图" in title.value:
                    nonlocal editor
                    editor = int(hwnd)
                    return False
                return True

            user32.EnumWindows(ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)(find_editor), 0)
            if editor is None:
                time.sleep(0.2)
        check(editor is not None, "截图后编辑器出现", str(editor))
        if editor is not None:
            user32.BringWindowToTop(editor)
            user32.SetForegroundWindow(editor)
            time.sleep(0.1)
            user32.keybd_event(0x11, 0, 0, 0)
            user32.keybd_event(0x0D, 0, 0, 0)
            user32.keybd_event(0x0D, 0, 2, 0)
            user32.keybd_event(0x11, 0, 2, 0)

        got = None
        deadline = time.time() + 20
        while time.time() < deadline:
            files = sorted(SAVE_DIR.rglob("*.png"))
            if len(files) > before_click:
                got = files[-1]
                break
            time.sleep(0.4)
        if check(got is not None, "点球后图片经局域网到达接收文件夹", str(got)):
            from PIL import Image
            with Image.open(got) as im:
                im.load()
                check(im.width > 100, "到达的图片可打开", f"{im.width}x{im.height}")
    else:
        client = None
        print("\n[6] 跳过点球验证：桌面已锁定（解锁后重跑本测试即可）")

    print("\n[7] 清理")
    if client is not None:
        client.kill()
    receiver.kill()
    time.sleep(1.0)
    kill_all()
    check(True, "已清理进程")

    passed = sum(1 for ok, _, _ in results if ok)
    print(f"\n==== 结果 {passed}/{len(results)} 通过 ====")
    for ok, name, detail in results:
        if not ok:
            print(f"  失败：{name}  {detail}")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
