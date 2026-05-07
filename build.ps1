# ============================================================
# One-click build: PyInstaller -> Inno Setup
# Usage:
#   .\build.ps1                # full (clean + exe + installer)
#   .\build.ps1 -SkipExe       # skip PyInstaller, only repack installer
#   .\build.ps1 -SkipInstaller # only build exe
#   .\build.ps1 -NoClean       # do not wipe build/ dist/exe / installer\out
# ============================================================

param(
    [switch]$SkipExe,
    [switch]$SkipInstaller,
    [switch]$NoClean
)

$ErrorActionPreference = "Stop"
$root = $PSScriptRoot

# ---------- 1. 读取版本号 ----------
$versionFile = Join-Path $root "core\version.py"
if (-not (Test-Path $versionFile)) {
    throw "未找到 $versionFile"
}
$verLine = Select-String -Path $versionFile -Pattern '__version__\s*=\s*"([^"]+)"' | Select-Object -First 1
if (-not $verLine) {
    throw "core/version.py: __version__ constant not found"
}
$version = $verLine.Matches[0].Groups[1].Value
Write-Host "[build] Version = $version" -ForegroundColor Cyan

# ---------- 2. 定位 ISCC ----------
$isccCandidates = @(
    "$env:ProgramFiles\Inno Setup 6\ISCC.exe",
    "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
    "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe"
)
$iscc = $isccCandidates | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $SkipInstaller -and -not $iscc) {
    throw "ISCC.exe not found. Install via: winget install JRSoftware.InnoSetup"
}
if ($iscc) { Write-Host "[build] ISCC = $iscc" -ForegroundColor Cyan }

# ---------- 3. Clean ----------
if (-not $NoClean) {
    Write-Host "[build] Cleaning build / dist exe / installer\out ..." -ForegroundColor Yellow
    Remove-Item -Recurse -Force -ErrorAction SilentlyContinue (Join-Path $root "build")
    if (-not $SkipExe) {
        Remove-Item -Force -ErrorAction SilentlyContinue (Join-Path $root "dist\BaiduTiebaSign.exe")
    }
    Remove-Item -Recurse -Force -ErrorAction SilentlyContinue (Join-Path $root "installer\out")
}

# ---------- 4. PyInstaller ----------
if (-not $SkipExe) {
    Write-Host "[build] Running PyInstaller ..." -ForegroundColor Yellow
    Push-Location $root
    try {
        & python -m PyInstaller --noconfirm BaiduTiebaSign.spec
        if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed (exit=$LASTEXITCODE)" }
    } finally {
        Pop-Location
    }
    $exePath = Join-Path $root "dist\BaiduTiebaSign.exe"
    if (-not (Test-Path $exePath)) { throw "exe not produced: $exePath" }
    $sizeMB = [math]::Round((Get-Item $exePath).Length / 1MB, 2)
    Write-Host "[build] exe OK -> $exePath ($sizeMB MB)" -ForegroundColor Green
} else {
    Write-Host "[build] Skipped PyInstaller" -ForegroundColor DarkGray
}

# ---------- 5. Inno Setup ----------
if (-not $SkipInstaller) {
    $iss = Join-Path $root "installer\setup.iss"
    if (-not (Test-Path $iss)) { throw "missing: $iss" }
    Write-Host "[build] Running Inno Setup ..." -ForegroundColor Yellow
    & $iscc "/DMyAppVersion=$version" $iss
    if ($LASTEXITCODE -ne 0) { throw "Inno Setup failed (exit=$LASTEXITCODE)" }
    $setupPath = Join-Path $root "installer\out\BaiduTiebaSign-Setup-$version.exe"
    if (-not (Test-Path $setupPath)) { throw "installer not produced: $setupPath" }
    $setupMB = [math]::Round((Get-Item $setupPath).Length / 1MB, 2)
    Write-Host "[build] Installer OK -> $setupPath ($setupMB MB)" -ForegroundColor Green
} else {
    Write-Host "[build] Skipped Inno Setup" -ForegroundColor DarkGray
}

Write-Host "[build] Done." -ForegroundColor Cyan
