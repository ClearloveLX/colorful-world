param(
  [switch]$Hidden
)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$ROOT = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ROOT

function Info($m){ Write-Host "[INFO] $m" -ForegroundColor Cyan }
function Ok($m){ Write-Host "[OK]   $m" -ForegroundColor Green }
function Warn($m){ Write-Host "[WARN] $m" -ForegroundColor Yellow }

$venv = Join-Path $ROOT ".venv"
$py = Join-Path $venv "Scripts/python.exe"
if (-not (Test-Path $py)) {
  $pythonCmd = Get-Command python -ErrorAction SilentlyContinue
  if ($pythonCmd) { $py = $pythonCmd.Path } else { throw "Python not found" }
}

Info "Starting open helper on 127.0.0.1:4397"
if ($Hidden) {
  Start-Process -WindowStyle Hidden -FilePath $py -ArgumentList "-m backend.open_helper"
} else {
  & $py -m backend.open_helper
}
