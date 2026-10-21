# ShotBridge 一键打包脚本
#   1) PyInstaller 生成 dist\ShotBridge\（onedir，单 exe 双身份）
#   2) 修正产物完整性级别（本机沙箱会继承 Low 标签，Low 下程序无法写配置/日志/截图）
#   3) Inno Setup 编译安装包 dist\installer\ShotBridge-Setup-<ver>.exe
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
        $env:SHOTBRIDGE_PYTHON,
        'C:\Program Files\Python314\python.exe',
        (Get-Command python -ErrorAction SilentlyContinue | Select-Object -First 1 -ExpandProperty Source)
    )
    foreach ($c in $candidates) {
        if ($c -and (Test-Path $c)) { return $c }
    }
    throw '找不到 Python 解释器，请设置环境变量 SHOTBRIDGE_PYTHON'
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
$version = (& $python -c "import sys; sys.path.insert(0, 'src'); from shotbridge import __version__; print(__version__)").Trim()
Write-Host "Python : $python"
Write-Host "版本   : $version"

# ---------------------------------------------------------------- 1. 构建
if (-not $SkipBuild) {
    Write-Step '1/4 清理旧产物'
    # 正在运行的 exe 会锁住 _internal\*.dll，导致删除失败（WinError 5）
    Get-Process -Name ShotBridge -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 1
    foreach ($p in @('dist\ShotBridge', 'build\work')) {
        if (Test-Path $p) { Remove-Item $p -Recurse -Force }
    }

    Write-Step '2/4 PyInstaller 构建'
    & $python -m PyInstaller --noconfirm --clean --distpath dist --workpath build\work build\shotbridge.spec
    if ($LASTEXITCODE -ne 0) { throw "PyInstaller 构建失败（exit $LASTEXITCODE）" }
}
else {
    Write-Step '1-2/4 跳过构建'
}

$appExe = Join-Path $root 'dist\ShotBridge\ShotBridge.exe'
if (-not (Test-Path $appExe)) { throw "产物不存在：$appExe" }

Write-Step '3/4 修正产物完整性级别'
Repair-Integrity (Join-Path $root 'dist\ShotBridge')

$size = [math]::Round((Get-ChildItem (Join-Path $root 'dist\ShotBridge') -Recurse -File | Measure-Object -Sum Length).Sum / 1MB, 1)
Write-Host "便携目录 : dist\ShotBridge  ($size MB)"

# ---------------------------------------------------------------- 2. 安装包
if (-not $SkipInstaller) {
    Write-Step '4/4 编译安装包'
    $iscc = Find-Iscc
    if (-not (Test-Path 'docs\使用说明.md')) { throw '缺少 docs\使用说明.md，安装包需要它作为说明文档' }
    & $iscc 'installer\shotbridge.iss'
    if ($LASTEXITCODE -ne 0) { throw "Inno Setup 编译失败（exit $LASTEXITCODE）" }

    $setup = Join-Path $root "dist\installer\ShotBridge-Setup-$version.exe"
    if (-not (Test-Path $setup)) { throw "安装包未生成：$setup" }
    Repair-Integrity $setup
    $setupMb = [math]::Round((Get-Item $setup).Length / 1MB, 1)
    Write-Host "安装包   : dist\installer\ShotBridge-Setup-$version.exe  ($setupMb MB)"
}
else {
    Write-Step '4/4 跳过安装包'
}

Write-Step '完成'
Write-Host "截图端 : dist\ShotBridge\ShotBridge.exe"
Write-Host "接收端 : dist\ShotBridge\ShotBridge.exe --receiver"
