param([string]$Name = 'ColorfulWorldApiService')

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Info($m){ Write-Host "[INFO] $m" -ForegroundColor Cyan }
function Ok($m){ Write-Host "[OK]   $m" -ForegroundColor Green }
function Warn($m){ Write-Host "[WARN] $m" -ForegroundColor Yellow }
function Err($m){ Write-Host "[ERR]  $m" -ForegroundColor Red }

# Require admin
$isAdmin = ([Security.Principal.WindowsPrincipal] [Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) { throw '请以“管理员 PowerShell”运行此脚本' }

$nssm = (Get-Command nssm -ErrorAction SilentlyContinue | Select-Object -First 1).Source
if (-not $nssm) {
  $tryPath = Join-Path (Split-Path -Parent $MyInvocation.MyCommand.Path) 'tools/nssm/nssm.exe'
  if (Test-Path $tryPath) { $nssm = $tryPath }
}
if (-not $nssm) { throw '未找到 nssm.exe，请确保已安装 NSSM 或将 nssm.exe 放到 tools/nssm/nssm.exe' }

try { & $nssm stop $Name | Out-Null } catch {}
try { & $nssm remove $Name confirm | Out-Null } catch {}
Ok "服务已卸载：$Name"

