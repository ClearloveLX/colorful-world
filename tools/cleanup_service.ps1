param(
  [int]$Port = 4396
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Continue'

function Info($m){ Write-Host "[INFO] $m" -ForegroundColor Cyan }
function Ok($m){ Write-Host "[OK]   $m" -ForegroundColor Green }
function Warn($m){ Write-Host "[WARN] $m" -ForegroundColor Yellow }

Info "Searching services related to ColorfulWorld or python"
$svcs = Get-CimInstance Win32_Service | Where-Object {
  ($_.Name -like '*ColorfulWorld*') -or ($_.DisplayName -like '*ColorfulWorld*') -or ($_.PathName -like '*ColorfulWorld*') -or ($_.PathName -like '*python*')
}
if ($svcs) {
  $svcs | Select-Object Name,DisplayName,State,Status,ProcessId,StartName,PathName | Format-Table -AutoSize
  foreach($s in $svcs){
    Warn "Stopping service: $($s.Name)"
    sc.exe stop $s.Name | Out-Null
    Start-Sleep -Milliseconds 500
    Warn "Deleting service: $($s.Name)"
    sc.exe delete $s.Name | Out-Null
  }
} else {
  Warn "No matching services found"
}

Info "Killing listeners on port $Port"
$conns = Get-NetTCPConnection -LocalPort $Port -ErrorAction SilentlyContinue
foreach($c in $conns){
  try { Stop-Process -Id $c.OwningProcess -Force -ErrorAction SilentlyContinue; Ok "Killed PID $($c.OwningProcess)" } catch { Warn "Failed to kill PID $($c.OwningProcess)" }
}

Start-Sleep -Milliseconds 500
Get-NetTCPConnection -LocalPort $Port -ErrorAction SilentlyContinue | Select-Object LocalAddress,LocalPort,State,OwningProcess | Format-Table -AutoSize

