param(
  [string]$Name = 'ColorfulWorld API',
  [int]$Port = 8000,
  [string]$Bind = '0.0.0.0',
  [switch]$BuildFrontend
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$ROOT = Split-Path -Parent $MyInvocation.MyCommand.Path
$runner = Join-Path $ROOT 'run_server.ps1'
if (-not (Test-Path $runner)) { throw "run_server.ps1 not found: $runner" }

$startup = Join-Path $env:APPDATA 'Microsoft\Windows\Start Menu\Programs\Startup'
if (-not (Test-Path $startup)) { throw "Startup folder not found: $startup" }

$lnk = Join-Path $startup ("{0}.lnk" -f $Name)
$arg = "-NoLogo -NoProfile -ExecutionPolicy Bypass -File `"$runner`" -Port $Port -Bind `"$Bind`""
if ($BuildFrontend.IsPresent) { $arg += ' -BuildFrontend' }

$ws = New-Object -ComObject WScript.Shell
$sc = $ws.CreateShortcut($lnk)
$sc.TargetPath = (Get-Command powershell.exe).Source
$sc.Arguments = $arg
$sc.WorkingDirectory = $ROOT
$sc.IconLocation = $sc.TargetPath
$sc.Save()

Write-Host "[OK] Startup shortcut created: $lnk" -ForegroundColor Green
Write-Host "It will auto start on next logon. You can also run it now:" -ForegroundColor Cyan
Write-Host "powershell $arg" -ForegroundColor Yellow
