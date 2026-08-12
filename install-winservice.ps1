param(
  [string]$Name = 'ColorfulWorldApiService',
  [int]$Port = 4396,
  [string]$Bind = '0.0.0.0',
  [switch]$BuildFrontend
)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Info($m){ Write-Host "[INFO] $m" -ForegroundColor Cyan }
function Ok($m){ Write-Host "[OK]   $m" -ForegroundColor Green }
function Warn($m){ Write-Host "[WARN] $m" -ForegroundColor Yellow }
function Err($m){ Write-Host "[ERR]  $m" -ForegroundColor Red }

# Require admin
$isAdmin = ([Security.Principal.WindowsPrincipal] [Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) { throw '请以“管理员 PowerShell”运行此脚本' }

$ROOT = Split-Path -Parent $MyInvocation.MyCommand.Path
$runner = Join-Path $ROOT 'run_server.ps1'
if (-not (Test-Path $runner)) { throw "缺少 run_server.ps1：$runner" }

# Find NSSM
$nssm = $null
$nssmCmd = Get-Command nssm -ErrorAction SilentlyContinue | Select-Object -First 1
if ($nssmCmd) {
  if ($nssmCmd.PSObject.Properties['Path']) { $nssm = $nssmCmd.Path }
  elseif ($nssmCmd.PSObject.Properties['Definition']) { $nssm = $nssmCmd.Definition }
  elseif ($nssmCmd.PSObject.Properties['Source']) { $nssm = $nssmCmd.Source }
}
if (-not $nssm) {
  $candidates = @(
    (Join-Path $ROOT 'tools/nssm/nssm.exe'),
    'C:\Program Files\nssm\win64\nssm.exe',
    'C:\Program Files\nssm-2.24\win64\nssm.exe',
    'C:\Program Files (x86)\nssm\win64\nssm.exe',
    'C:\Program Files (x86)\nssm-2.24\win64\nssm.exe',
    'C:\Program Files\nssm\win32\nssm.exe',
    'C:\Program Files (x86)\nssm\win32\nssm.exe'
  )
  foreach ($p in $candidates) { if (Test-Path $p) { $nssm = $p; break } }
}
if (-not $nssm) {
  Warn 'NSSM not found. Please install via winget: winget install -e --id NSSM.NSSM or place nssm.exe at tools/nssm/nssm.exe'
  throw 'NSSM is not installed'
}

$pwshCmd = Get-Command powershell.exe
if ($pwshCmd.PSObject.Properties['Path']) { $pwsh = $pwshCmd.Path }
elseif ($pwshCmd.PSObject.Properties['Definition']) { $pwsh = $pwshCmd.Definition }
else { $pwsh = $pwshCmd.Source }
$args  = "-NoLogo -NoProfile -ExecutionPolicy Bypass -File `"$runner`" -Port $Port -Bind `"$Bind`""
if ($BuildFrontend.IsPresent) { $args += ' -BuildFrontend' }

Info "安装 Windows 服务：$Name"
& $nssm install $Name $pwsh $args | Out-Null
& $nssm set $Name AppDirectory $ROOT | Out-Null
& $nssm set $Name AppStopMethodConsole 15000 | Out-Null
& $nssm set $Name AppExit Default Restart | Out-Null
& $nssm set $Name AppStdout "$ROOT\\logs\\$Name.out.log" | Out-Null
& $nssm set $Name AppStderr "$ROOT\\logs\\$Name.err.log" | Out-Null
& $nssm set $Name Start SERVICE_AUTO_START | Out-Null
& $nssm set $Name DisplayName $Name | Out-Null
& $nssm set $Name Description "ColorfulWorld service hosting frontend and API" | Out-Null

New-Item -ItemType Directory -Force -Path (Join-Path $ROOT 'logs') | Out-Null

& $nssm start $Name | Out-Null
$okmsg = "Service installed and started: $Name. Open http://localhost:$Port/"
Ok $okmsg

