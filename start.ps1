# Power Academy — Start All Services
# Run from anywhere: .\start.ps1

$API_KEY = $env:ANTHROPIC_API_KEY

Write-Host "Starting Power Academy..." -ForegroundColor Cyan

# Start Node API server in background
$serverJob = Start-Job -ScriptBlock {
    param($key)
    $env:ANTHROPIC_API_KEY = $key
    node E:\PowerAcademy\scripts\server.js
} -ArgumentList $API_KEY

Write-Host "API server starting on port 3001..." -ForegroundColor Green

# Give server 2 seconds to start
Start-Sleep -Seconds 2

# Test server health
try {
    $health = Invoke-RestMethod -Uri "http://localhost:3001/api/health" -TimeoutSec 3
    Write-Host "Server OK - State file: $($health.stateFile)" -ForegroundColor Green
} catch {
    Write-Host "Server health check failed - check port 3001" -ForegroundColor Yellow
}

# Start React dev server in foreground
Write-Host "Starting React app..." -ForegroundColor Cyan
Set-Location E:\PowerAcademy\app\poweracademy
npm start

# When npm start exits, clean up server job
Stop-Job $serverJob
Remove-Job $serverJob
Write-Host "Power Academy stopped." -ForegroundColor Cyan