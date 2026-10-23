# 速截 一键打包脚本
#   1) PyInstaller 生成 dist\速截\（onedir，单 exe 双身份）
#   2) 修正产物完整性级别（本机沙箱会继承 Low 标签，Low 下程序无法写配置/日志/截图）
#   3) Inno Setup 编译安装包 dist\installer\速截-Setup-<ver>.exe
#
# 用法：
#   powershell -ExecutionPolicy Bypass -File tools\package.ps1
#   powershell -ExecutionPolicy Bypass -File tools\package.ps1 -SkipBuild      # 只重打安装包
#   powershell -ExecutionPolicy Bypass -File tools\package.ps1 -SkipInstaller  # 只出便携目录

param(
    [switch]$SkipBuild,
    [switch]$SkipInstaller
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
$env:PYTHONIOENCODING = 'utf-8'

function Write-Step([string]$text) {
    Write-Host ""
    Write-Host "==== $text ====" -ForegroundColor Cyan
}

function Find-Python {
    $candidates = @(
        $env:SUJIE_PYTHON,
        'C:\Program Files\Python314\python.exe',
        (Get-Command python -ErrorAction SilentlyContinue | Select-Object -First 1 -ExpandProperty Source)
    )
    foreach ($c in $candidates) {
        if ($c -and (Test-Path $c)) { return $c }
    }
    throw '找不到 Python 解释器，请设置环境变量 SUJIE_PYTHON'
}

function Find-Iscc {
    $candidates = @(
        (Join-Path $env:LOCALAPPDATA 'Programs\Inno Setup 6\ISCC.exe'),
        'C:\Program Files (x86)\Inno Setup 6\ISCC.exe',
        'C:\Program Files\Inno Setup 6\ISCC.exe'
    )
    foreach ($c in $candidates) {
        if ($c -and (Test-Path $c)) { return $c }
    }
    throw '找不到 Inno Setup 的 ISCC.exe，请先安装 Inno Setup 6'
}

# 把 Low 完整性标签改成 Medium。目录需要 (OI)(CI) 继承，单个文件不能带继承标志。
function Repair-Integrity([string]$path) {
    if (-not (Test-Path $path)) { return }
    $item = Get-Item $path
    if ($item.PSIsContainer) {
        $null = & icacls $path /setintegritylevel "(OI)(CI)M" /T 2>&1
    }
    else {
        $null = & icacls $path /setintegritylevel "M" 2>&1
    }
}

$python = Find-Python
$version = (& $python -c "import sys; sys.path.insert(0, 'src'); from sujie import __version__; print(__version__)").Trim()
Write-Host "Python : $python"
Write-Host "版本   : $version"

# ffmpeg.exe 有 87 MB，不进 git；本机没有就从 imageio-ffmpeg 里取一份放好
$ffmpeg = Join-Path $root 'assets\bin\ffmpeg.exe'
if (-not (Test-Path $ffmpeg)) {
    Write-Step '准备 ffmpeg'
    New-Item -ItemType Directory -Force -Path (Split-Path $ffmpeg) | Out-Null
    $src = (& $python -c "import imageio_ffmpeg, sys; sys.stdout.write(imageio_ffmpeg.get_ffmpeg_exe())")
    if (-not $src -or -not (Test-Path $src.Trim())) {
        throw '缺少 assets\bin\ffmpeg.exe：请先 pip install imageio-ffmpeg，或手动把 ffmpeg.exe 放到 assets\bin\'
    }
    Copy-Item $src.Trim() $ffmpeg -Force
    $null = & icacls $ffmpeg /setintegritylevel "M" 2>&1
    Write-Host "ffmpeg : $ffmpeg"
}

# ---------------------------------------------------------------- 1. 构建
if (-not $SkipBuild) {
    Write-Step '1/4 清理旧产物'
    # 只停止本工作区的旧产物；不要关闭 Program Files 中用户正在用的接收端。
    $distExe = [IO.Path]::GetFullPath((Join-Path $root 'dist\速截\速截.exe'))
    Get-Process -Name 速截 -ErrorAction SilentlyContinue |
        Where-Object { $_.Path -and [IO.Path]::GetFullPath($_.Path) -ieq $distExe } |
        Stop-Process -Force -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 1
    foreach ($p in @('dist\速截', 'build\work')) {
        if (Test-Path $p) { Remove-Item $p -Recurse -Force }
    }

    Write-Step '2/4 PyInstaller 构建'
    & $python -m PyInstaller --noconfirm --clean --distpath dist --workpath build\work build\sujie.spec
    if ($LASTEXITCODE -ne 0) { throw "PyInstaller 构建失败（exit $LASTEXITCODE）" }
}
else {
    Write-Step '1-2/4 跳过构建'
}

$appExe = Join-Path $root 'dist\速截\速截.exe'
if (-not (Test-Path $appExe)) { throw "产物不存在：$appExe" }

Write-Step '3/4 修正产物完整性级别'
Repair-Integrity (Join-Path $root 'dist\速截')

$size = [math]::Round((Get-ChildItem (Join-Path $root 'dist\速截') -Recurse -File | Measure-Object -Sum Length).Sum / 1MB, 1)
Write-Host "便携目录 : dist\速截  ($size MB)"

# ---------------------------------------------------------------- 2. 安装包
if (-not $SkipInstaller) {
    Write-Step '4/4 编译安装包'
    $iscc = Find-Iscc
    if (-not (Test-Path 'docs\使用说明.md')) { throw '缺少 docs\使用说明.md，安装包需要它作为说明文档' }
    & $iscc "/DAppVersion=$version" 'installer\sujie.iss'
    if ($LASTEXITCODE -ne 0) { throw "Inno Setup 编译失败（exit $LASTEXITCODE）" }

    $setup = Join-Path $root "dist\installer\速截-Setup-$version.exe"
    if (-not (Test-Path $setup)) { throw "安装包未生成：$setup" }
    Repair-Integrity $setup
    $setupMb = [math]::Round((Get-Item $setup).Length / 1MB, 1)
    Write-Host "安装包   : dist\installer\速截-Setup-$version.exe  ($setupMb MB)"
}
else {
    Write-Step '4/4 跳过安装包'
}

Write-Step '完成'
Write-Host "截图端 : dist\速截\速截.exe"
Write-Host "接收端 : dist\速截\速截.exe --receiver"
