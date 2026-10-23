"""屏幕录制：调用内置 ffmpeg 把一块屏幕区域录成 mp4。

为什么用 ffmpeg 子进程
----------------------
* 纯 Python 逐帧抓屏 + 编码在 1080p/30fps 下会吃掉一个核还掉帧；ffmpeg 的
  ``gdigrab`` 抓屏 + 硬编码（``h264_mf``，走 MediaFoundation）开销低得多。
* 编码器按 ``h264_mf`` → ``libx264`` → ``mpeg4`` 的顺序探测，取第一个可用的：
  ``h264_mf`` 是系统自带实现（不牵扯 GPL），``libx264`` 只作兜底。

停止录制时向 ffmpeg 的 stdin 写 ``q``，它会正常收尾（写 moov atom），
直接 kill 会得到无法播放的 mp4。
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Tuple

from . import bootstrap, paths

FFMPEG_ENV = "SUJIE_FFMPEG"
ENCODER_PREFERENCE = ("h264_mf", "libx264", "mpeg4")
STOP_GRACE_SECONDS = 8.0
MIN_FREE_MB = 500
CREATE_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0

_PROBE_CACHE: Optional["ProbeResult"] = None


@dataclass
class ProbeResult:
    """ffmpeg 探测结果。"""

    ok: bool
    path: str = ""
    version: str = ""
    encoder: str = ""
    error: str = ""


def _candidate_paths() -> List[str]:
    candidates: List[str] = []
    env = os.environ.get(FFMPEG_ENV, "").strip()
    if env:
        candidates.append(env)

    exe_dir = Path(sys.executable).resolve().parent
    meipass = getattr(sys, "_MEIPASS", "")
    if meipass:
        candidates.append(str(Path(meipass) / "ffmpeg" / "ffmpeg.exe"))
    if getattr(sys, "frozen", False):
        candidates.append(str(exe_dir / "ffmpeg" / "ffmpeg.exe"))
        candidates.append(str(exe_dir / "_internal" / "ffmpeg" / "ffmpeg.exe"))
    # 源码运行时：<repo>/assets/bin/ffmpeg.exe
    candidates.append(str(Path(__file__).resolve().parents[2] / "assets" / "bin" / "ffmpeg.exe"))
    candidates.append(str(paths.local_data_dir() / "bin" / "ffmpeg.exe"))
    found = shutil.which("ffmpeg")
    if found:
        candidates.append(found)
    return candidates


def ffmpeg_path() -> str:
    """找到可执行的 ffmpeg，找不到返回空串。"""
    for candidate in _candidate_paths():
        if candidate and os.path.isfile(candidate):
            return candidate
    return ""


def _run(args: List[str], timeout: float = 12.0) -> Tuple[int, str]:
    try:
        proc = subprocess.run(
            args,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=timeout,
            creationflags=CREATE_NO_WINDOW,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return 1, str(exc)
    text = (proc.stdout or b"").decode("utf-8", "replace")
    return proc.returncode, text


def probe(refresh: bool = False) -> ProbeResult:
    """检测 ffmpeg 是否可用、支持哪些编码器。结果会缓存。"""
    global _PROBE_CACHE
    if _PROBE_CACHE is not None and not refresh:
        return _PROBE_CACHE

    exe = ffmpeg_path()
    if not exe:
        _PROBE_CACHE = ProbeResult(
            ok=False,
            error="没有找到内置的录制组件（ffmpeg.exe）。请重新安装速截，或把 ffmpeg.exe 放到 %LOCALAPPDATA%\\速截\\bin\\。",
        )
        return _PROBE_CACHE

    code, text = _run([exe, "-hide_banner", "-version"])
    if code != 0:
        _PROBE_CACHE = ProbeResult(ok=False, path=exe, error=f"录制组件无法运行：{text.strip()[:200]}")
        return _PROBE_CACHE
    first_line = text.splitlines()[0] if text else ""
    version = first_line.strip()

    code, encoders = _run([exe, "-hide_banner", "-encoders"])
    available = ""
    for name in ENCODER_PREFERENCE:
        # 注意：f-string 里 {5} 会被当成替换字段，量词必须写成 {{5}}
        if re.search(rf"^\s*V[.\w]{{5}}\s+{re.escape(name)}\s", encoders or "", re.MULTILINE):
            available = name
            break
    if not available:
        _PROBE_CACHE = ProbeResult(
            ok=False, path=exe, version=version,
            error="录制组件缺少可用的 H.264 编码器（h264_mf / libx264），无法录制。",
        )
        return _PROBE_CACHE

    _PROBE_CACHE = ProbeResult(ok=True, path=exe, version=version, encoder=available)
    return _PROBE_CACHE


def default_record_dir() -> Path:
    videos = Path(os.environ.get("USERPROFILE", str(Path.home()))) / "Videos" / "速截"
    return videos


def _even(value: int) -> int:
    """编码器要求宽高为偶数。"""
    value = int(value)
    return value - (value % 2)


def normalize_rect(rect: Tuple[int, int, int, int]) -> Tuple[int, int, int, int]:
    """把矩形修成 gdigrab 能接受的形式（非负坐标 + 偶数宽高）。"""
    x, y, width, height = (int(round(v)) for v in rect)
    if x < 0 or y < 0 or width <= 0 or height <= 0:
        # gdigrab 的 offset 不支持负坐标（副屏在主屏左侧时会出现），尺寸非法时
        # 也没法录，两种情况都退回整块虚拟桌面，保证「按下去一定录得到东西」。
        try:
            from .win32util import virtual_screen_rect

            left, top, vwidth, vheight = virtual_screen_rect()
            return 0, 0, _even(max(2, vwidth)), _even(max(2, vheight))
        except Exception:
            return 0, 0, _even(max(2, width or 2)), _even(max(2, height or 2))
    return x, y, _even(max(2, width)), _even(max(2, height))


def _encoder_args(encoder: str, bitrate: str) -> List[str]:
    if encoder == "h264_mf":
        return ["-b:v", bitrate]
    if encoder == "libx264":
        return ["-preset", "veryfast", "-crf", "23"]
    return ["-q:v", "4"]


def build_command(
    ffmpeg: str,
    output: str,
    rect: Tuple[int, int, int, int],
    fps: int = 30,
    encoder: str = "h264_mf",
    audio: str = "none",
    mic: str = "",
    bitrate: str = "6M",
) -> List[str]:
    """拼出录制命令（抽成纯函数，方便单测）。"""
    x, y, width, height = normalize_rect(rect)
    fps = max(5, min(60, int(fps)))
    command = [
        ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
        "-f", "gdigrab", "-framerate", str(fps),
        "-offset_x", str(x), "-offset_y", str(y),
        "-video_size", f"{width}x{height}",
        "-i", "desktop",
    ]
    if audio == "mic" and mic:
        command += ["-f", "dshow", "-i", f"audio={mic}"]
    command += ["-c:v", encoder] + _encoder_args(encoder, bitrate)
    command += ["-pix_fmt", "yuv420p", "-movflags", "+faststart"]
    if audio == "mic" and mic:
        command += ["-c:a", "aac", "-b:a", "128k", "-shortest"]
    command.append(str(output))
    return command


def list_audio_devices() -> List[str]:
    """列出可用的录音设备（麦克风）。"""
    exe = ffmpeg_path()
    if not exe:
        return []
    code, text = _run([exe, "-hide_banner", "-list_devices", "true", "-f", "dshow", "-i", "dummy"])
    devices: List[str] = []
    for line in (text or "").splitlines():
        match = re.search(r'"([^"]+)"\s*\(audio\)', line)
        if match:
            name = match.group(1).strip()
            if name and name not in devices:
                devices.append(name)
    return devices


class Recorder:
    """一次录制会话。"""

    def __init__(self, config=None):
        self._config = config
        self._proc: Optional[subprocess.Popen] = None
        self._path: Optional[Path] = None
        self._started = 0.0
        self._log_path: Optional[Path] = None
        self._log_handle = None
        self._last_error = ""

    # ------------------------------------------------------------ 状态查询
    def is_recording(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    def current_path(self) -> Optional[Path]:
        return self._path

    def elapsed_seconds(self) -> float:
        if not self._started:
            return 0.0
        return max(0.0, time.monotonic() - self._started)

    def elapsed_text(self) -> str:
        seconds = int(self.elapsed_seconds())
        # 用 00:02 而不是 0:02，因为悬浮球上的计时会和「时长 2.5s」的日志对不上，
        # 两位数格式在球体小字里也更整齐。
        return f"{seconds // 60:02d}:{seconds % 60:02d}"

    def last_error(self) -> str:
        return self._last_error

    # ---------------------------------------------------------------- 录制
    def start(
        self,
        rect: Tuple[int, int, int, int],
        fps: int = 30,
        audio: str = "none",
        mic: str = "",
        out_dir: Optional[str] = None,
        max_mb: int = 0,
    ) -> Path:
        if self.is_recording():
            raise RuntimeError("已经在录制中")

        result = probe()
        if not result.ok:
            raise RuntimeError(result.error)

        directory = Path(out_dir) if out_dir else default_record_dir()
        directory.mkdir(parents=True, exist_ok=True)

        free_ok, free_msg = self.check_disk(str(directory))
        if not free_ok:
            raise RuntimeError(free_msg)

        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        target = directory / f"rec-{stamp}.mp4"
        index = 1
        while target.exists():
            target = directory / f"rec-{stamp}-{index}.mp4"
            index += 1

        command = build_command(
            result.path, str(target), rect, fps=fps, encoder=result.encoder,
            audio=audio, mic=mic,
        )
        self._log_path = paths.local_data_dir() / "logs" / "ffmpeg-rec.log"
        self._log_path.parent.mkdir(parents=True, exist_ok=True)
        self._log_handle = open(self._log_path, "wb")
        bootstrap.log(f"开始录制：{' '.join(command)}")

        try:
            self._proc = subprocess.Popen(
                command,
                stdin=subprocess.PIPE,
                stdout=subprocess.DEVNULL,
                stderr=self._log_handle,
                creationflags=CREATE_NO_WINDOW,
            )
        except OSError as exc:
            self._close_log()
            raise RuntimeError(f"启动录制进程失败：{exc}") from exc

        time.sleep(0.45)
        if self._proc.poll() is not None:
            tail = self._read_log_tail()
            self._close_log()
            self._proc = None
            raise RuntimeError(f"录制启动失败：{tail or 'ffmpeg 立即退出'}")

        self._path = target
        self._started = time.monotonic()
        self._max_mb = int(max_mb or 0)
        self._last_error = ""
        return target

    def stop(self, timeout: float = STOP_GRACE_SECONDS) -> Tuple[bool, Optional[Path], str]:
        """结束录制。返回 (成功, 文件路径, 说明)。"""
        if self._proc is None:
            return False, None, "没有正在进行的录制"

        proc = self._proc
        path = self._path
        if proc.poll() is None:
            try:
                if proc.stdin is not None:
                    proc.stdin.write(b"q")
                    proc.stdin.flush()
            except (OSError, ValueError):
                pass
            try:
                proc.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                proc.terminate()
                try:
                    proc.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    try:
                        proc.wait(timeout=3)
                    except subprocess.TimeoutExpired:
                        pass

        elapsed = self.elapsed_seconds()
        self._proc = None
        self._started = 0.0
        tail = self._read_log_tail()
        self._close_log()

        if path is None:
            return False, None, "录制文件路径丢失"
        if not path.exists() or path.stat().st_size < 2048:
            self._last_error = tail or "录制文件没有生成内容"
            return False, path, self._last_error
        bootstrap.log(f"录制结束：{path.name} 时长 {elapsed:.1f}s 大小 {path.stat().st_size} 字节")
        return True, path, ""

    def cancel(self) -> None:
        """放弃这次录制（删除临时文件）。"""
        if self._proc is not None:
            ok, path, _ = self.stop(timeout=3.0)
            if ok and path is not None:
                try:
                    path.unlink()
                except OSError:
                    pass

    # ------------------------------------------------------------ 资源检查
    def check_disk(self, directory: str = "") -> Tuple[bool, str]:
        target = directory or str(default_record_dir())
        try:
            usage = shutil.disk_usage(target if os.path.isdir(target) else Path(target).parent)
        except OSError:
            return True, ""
        free_mb = usage.free / (1024 * 1024)
        if free_mb < MIN_FREE_MB:
            return False, f"磁盘剩余空间只有 {free_mb:.0f} MB，录制前请先清理（至少需要 {MIN_FREE_MB} MB）。"
        return True, ""

    def output_size_mb(self) -> float:
        if self._path is None or not self._path.exists():
            return 0.0
        return self._path.stat().st_size / (1024 * 1024)

    def over_size_limit(self) -> bool:
        limit = int(getattr(self, "_max_mb", 0) or 0)
        return bool(limit) and self.output_size_mb() > limit

    # ---------------------------------------------------------------- 内部
    def _read_log_tail(self, limit: int = 400) -> str:
        if self._log_path is None or not self._log_path.exists():
            return ""
        try:
            text = self._log_path.read_text(encoding="utf-8", errors="replace").strip()
        except OSError:
            return ""
        lines = [line for line in text.splitlines() if line.strip()]
        return " | ".join(lines[-3:])[:limit]

    def _close_log(self) -> None:
        if self._log_handle is not None:
            try:
                self._log_handle.close()
            except OSError:
                pass
            self._log_handle = None
