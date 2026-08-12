param(
  [int]$Port = 4396,
  [string]$Bind = '0.0.0.0',
  [int]$Workers = 2,
  [switch]$BuildFrontend,
  [switch]$SkipInstall
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$ROOT = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ROOT

function Info($m){ Write-Host "[INFO] $m" -ForegroundColor Cyan }
function Ok($m){ Write-Host "[OK]   $m" -ForegroundColor Green }
function Warn($m){ Write-Host "[WARN] $m" -ForegroundColor Yellow }

$venv = Join-Path $ROOT ".venv"
if (-not (Test-Path $venv)) {
  $python = $null
  $cands = @(
    'C:\Program Files\Python311\python.exe',
    'C:\Python311\python.exe'
  )
  foreach($p in $cands){ if (Test-Path $p) { $python = $p; break } }
  if (-not $python) {
    $pythonCmd = Get-Command python -ErrorAction SilentlyContinue
    if ($pythonCmd) { $python = $pythonCmd.Path }
  }
  if (-not $python) { throw "Python 3.11 not found." }
  & $python -m venv .venv
}
$py = Join-Path $venv "Scripts/python.exe"
if (-not (Test-Path $py)) { throw "Python venv not found at $py" }

if (-not $SkipInstall) {
  Info "Ensuring backend deps"
  & $py -m pip install -U pip
  if ($LASTEXITCODE -ne 0) { throw "pip upgrade failed ($LASTEXITCODE)" }
  if (Test-Path (Join-Path $ROOT 'requirements.txt')) {
    & $py -m pip install -r (Join-Path $ROOT 'requirements.txt')
    if ($LASTEXITCODE -ne 0) { throw "pip install requirements failed ($LASTEXITCODE)" }
  } else {
    & $py -m pip install fastapi uvicorn Pillow opencv-python numpy
    if ($LASTEXITCODE -ne 0) { throw "pip install base deps failed ($LASTEXITCODE)" }
  }
  & $py -c "import PIL, numpy, cv2"
  if ($LASTEXITCODE -ne 0) {
    Info "Installing missing imaging deps"
    & $py -m pip install Pillow opencv-python numpy
    if ($LASTEXITCODE -ne 0) { throw "pip install imaging deps failed ($LASTEXITCODE)" }
  }
} else {
  Info "Skipping dependency installation per -SkipInstall"
}

if ($BuildFrontend) {
  $frontend = Join-Path $ROOT "frontend"
  if (Test-Path $frontend) {
    Info "Building frontend"
    Push-Location $frontend
    if (Test-Path "package-lock.json") { cmd /c npm ci } else { cmd /c npm install }
    cmd /c npm run build
    Pop-Location
  }
}

Info "Starting server on http://$($Bind):$Port/"
& $py -m uvicorn backend.server:app --host $Bind --port $Port --workers $Workers
