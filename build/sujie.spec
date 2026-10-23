# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 打包脚本：生成 onedir 版 速截（一个 exe，两种身份）。

用 onedir 而不是 onefile：
- onefile 每次启动都要把 40+MB 解压到 %TEMP%，启动慢，且会遇到
  "Could not create temporary directory" 这类临时目录问题；
- onedir 启动快、体积更小、杀毒软件误报更少。
"""

from pathlib import Path

ROOT = Path(SPECPATH).parent
SRC = ROOT / "src"
ICON = ROOT / "assets" / "sujie.ico"
VERSION = ROOT / "assets" / "version_info.txt"
FFMPEG = ROOT / "assets" / "bin" / "ffmpeg.exe"

# 录屏依赖的 ffmpeg 放在 _internal/ffmpeg/ffmpeg.exe（recorder.ffmpeg_path 会去找）
datas = []
binaries = []
if FFMPEG.exists():
    datas.append((str(FFMPEG), "ffmpeg"))

a = Analysis(
    [str(SRC / "sujie_app.py")],
    pathex=[str(SRC)],
    binaries=binaries,
    datas=datas,
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # 排除用不到的重型依赖
    excludes=[
        "tkinter",
        "PyQt5",
        "PyQt6",
        "numpy",
        "pandas",
        "matplotlib",
        "pytest",
        "unittest",
        "pydoc_data",
        "cryptography",
        "cffi",
        "smbclient",
        "smbprotocol",
        "asn1crypto",
        "mss",
    ],
    noarchive=False,
    optimize=0,
)

# PyInstaller may pick up incompatible ICU DLLs from PATH (for example Poppler's
# version-suffixed ICU exports); Windows provides the ICU forwarders Qt expects.
a.binaries = [
    item for item in a.binaries
    if Path(item[0]).name.lower() != "icuuc.dll"
    and not Path(item[0]).name.lower().startswith("icudt")
]

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="速截",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(ICON),
    version=str(VERSION) if VERSION.exists() else None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="速截",
)
