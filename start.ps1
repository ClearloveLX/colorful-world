Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Write-Info($msg) { Write-Host "[INFO] $msg" -ForegroundColor Cyan }
function Write-Ok($msg) { Write-Host "[OK]   $msg" -ForegroundColor Green }
function Write-Warn($msg) { Write-Host "[WARN] $msg" -ForegroundColor Yellow }
function Write-Err($msg) { Write-Host "[ERR]  $msg" -ForegroundColor Red }

$ROOT = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ROOT

# 1) Ensure Python venv
$venv = Join-Path $ROOT ".venv"
if (-not (Test-Path $venv)) {
  Write-Info "Creating virtual environment (.venv)"
  python -m venv .venv
}

$py = Join-Path $venv "Scripts/python.exe"
if (-not (Test-Path $py)) { throw "Python venv not found at $py" }

Write-Info "Upgrading pip and installing backend dependencies"
& $py -m pip install -U pip | Out-Null
& $py -m pip install fastapi uvicorn | Out-Null
Write-Ok "Backend deps ready"

# 2) Build frontend
$frontend = Join-Path $ROOT "frontend"
if (Test-Path $frontend) {
  Write-Info "Building frontend (vite)"
  Push-Location $frontend
  if (Test-Path "package-lock.json") {
    cmd /c npm ci
  } else {
    cmd /c npm install
  }
  cmd /c npm run build
  Pop-Location
  Write-Ok "Frontend built"
} else {
  Write-Warn "Frontend folder not found: $frontend"
}

# 3) Start open helper (user session)
Write-Info "Starting open helper"
powershell -ExecutionPolicy Bypass -NoProfile -File (Join-Path $ROOT "run_open_helper.ps1") -Hidden

# 4) Start server (serves API and built frontend)
Write-Info "Starting server: http://localhost:8000/"
Write-Info "Press Ctrl+C to stop"
& $py -m uvicorn backend.server:app --host 0.0.0.0 --port 8000
