# scripts/start_live.ps1
# Usage: .\scripts\start_live.ps1 -IntervalMinutes 360
param([int]$IntervalMinutes = 360)

$ProjectRoot = Split-Path -Parent $PSScriptRoot
$LogDir = Join-Path $ProjectRoot "logs"
if (-not (Test-Path $LogDir)) { New-Item -ItemType Directory -Path $LogDir | Out-Null }
$LogFile = Join-Path $LogDir "live.log"
Set-Location $ProjectRoot

Write-Host "SignalWatch live loop: interval=$IntervalMinutes min, log=$LogFile"
Write-Host "Press Ctrl+C to stop."

while ($true) {
    $ts = (Get-Date).ToString("yyyy-MM-dd HH:mm:ss")
    Add-Content $LogFile "[$ts] Starting cycle"
    python "$ProjectRoot\scripts\run_cycle.py" --source channel3 --provider cached 2>&1 | Tee-Object -Append -FilePath $LogFile
    Start-Sleep -Seconds ($IntervalMinutes * 60)
}