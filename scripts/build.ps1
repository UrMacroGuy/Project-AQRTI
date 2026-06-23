# AQRTI Full Build Script (Windows PowerShell)
# Produces: dist/installers/AQRTI Intelligence Terminal X.X.X Setup.exe
#           dist/installers/AQRTI Portable X.X.X.exe
#
# Usage:
#   .\scripts\build.ps1               # full build
#   .\scripts\build.ps1 -SkipBackend  # skip PyInstaller step (faster iteration)
#   .\scripts\build.ps1 -Portable     # portable exe only

param(
    [switch]$SkipBackend,
    [switch]$Portable
)

$ErrorActionPreference = "Stop"
$Root = Split-Path $PSScriptRoot -Parent
Set-Location $Root

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  AQRTI Intelligence Terminal — Build   " -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# ── 1. Find Python ────────────────────────────────────────────
$PYTHON = $null
$candidates = @(
    "C:\Users\praty\.local\bin\python3.11.exe",
    "python3.11", "python3", "python", "py"
)
foreach ($c in $candidates) {
    try {
        $ver = & $c --version 2>&1
        if ($LASTEXITCODE -eq 0 -or $ver -match "Python") {
            $PYTHON = $c
            Write-Host "[1/4] Python: $ver ($c)" -ForegroundColor Green
            break
        }
    } catch {}
}
if (-not $PYTHON) {
    Write-Host "[1/4] ERROR: Python not found. Install Python 3.10+." -ForegroundColor Red
    exit 1
}

# ── 2. Build Python backend with PyInstaller ──────────────────
if (-not $SkipBackend) {
    Write-Host ""
    Write-Host "[2/4] Building backend (PyInstaller)..." -ForegroundColor Yellow
    & $PYTHON scripts\build_backend.py
    if ($LASTEXITCODE -ne 0) {
        Write-Host "[2/4] ERROR: Backend build failed." -ForegroundColor Red
        exit 1
    }
    Write-Host "[2/4] Backend built." -ForegroundColor Green
} else {
    Write-Host "[2/4] Skipping backend build (-SkipBackend)." -ForegroundColor DarkGray
}

# ── 3. npm install ────────────────────────────────────────────
Write-Host ""
Write-Host "[3/4] Installing Node dependencies..." -ForegroundColor Yellow
npm install --prefer-offline
if ($LASTEXITCODE -ne 0) {
    Write-Host "[3/4] ERROR: npm install failed." -ForegroundColor Red
    exit 1
}
Write-Host "[3/4] Dependencies installed." -ForegroundColor Green

# ── 4. Electron Builder ───────────────────────────────────────
Write-Host ""
Write-Host "[4/4] Packaging with electron-builder..." -ForegroundColor Yellow

if ($Portable) {
    npx electron-builder --win portable --publish never
} else {
    npx electron-builder --win --publish never
}

if ($LASTEXITCODE -ne 0) {
    Write-Host "[4/4] ERROR: electron-builder failed." -ForegroundColor Red
    exit 1
}

Write-Host ""
Write-Host "========================================" -ForegroundColor Green
Write-Host "  BUILD COMPLETE" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Green
Write-Host ""
Write-Host "Output: dist\installers\" -ForegroundColor Cyan
Get-ChildItem "dist\installers\*.exe" -ErrorAction SilentlyContinue |
    Select-Object Name, @{n='Size';e={"$([math]::Round($_.Length/1MB,1)) MB"}} |
    Format-Table -AutoSize
