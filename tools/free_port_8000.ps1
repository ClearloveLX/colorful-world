param(
  [int]$Port = 8000
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Continue'

function Info($m){ Write-Host "[INFO] $m" -ForegroundColor Cyan }
function Ok($m){ Write-Host "[OK]   $m" -ForegroundColor Green }
function Warn($m){ Write-Host "[WARN] $m" -ForegroundColor Yellow }

for($i=0;$i -lt 5;$i++){
  $conns = Get-NetTCPConnection -LocalPort $Port -ErrorAction SilentlyContinue
  if(-not $conns){ Ok "Port $Port is free"; break }
  foreach($c in $conns){
    try{ Stop-Process -Id $c.OwningProcess -Force -ErrorAction SilentlyContinue; Ok "Killed PID $($c.OwningProcess)" } catch{ Warn "Failed PID $($c.OwningProcess)" }
  }
  Start-Sleep -Milliseconds 500
}

Get-NetTCPConnection -LocalPort $Port -ErrorAction SilentlyContinue | Select-Object LocalAddress,LocalPort,State,OwningProcess | Format-Table -AutoSize

