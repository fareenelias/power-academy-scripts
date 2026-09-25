# Power Academy — Start All Services
# Run from anywhere: .\start.ps1
#
# Three things must be up for the dashboard to work fully:
#   Caddy   :8080  Windows SERVICE — serves documents\ (PDFs, reports, credit, transcripts)
#   Node    :3001  API / JSON data
#   React   :3000  the dashboard itself
# Caddy is a service, so it does NOT die with this script and is NOT started by it
# under normal conditions — it is checked here only because a stopped Caddy shows up
# as dead source deep-links in the UI, which looks like a data problem rather than an
# infrastructure one. Permanent fix is StartupType=Automatic (see the warning below).

$API_KEY = $env:ANTHROPIC_API_KEY

Write-Host "Starting Power Academy..." -ForegroundColor Cyan

# ── Caddy (static file server, port 8080) ────────────────────────────────────
$caddy = Get-Service caddy -ErrorAction SilentlyContinue
if (-not $caddy) {
    Write-Host "Caddy service NOT FOUND - all /reports/, /credit/ and /transcripts/ links will fail." -ForegroundColor Red
} else {
    if ($caddy.Status -ne 'Running') {
        Write-Host "Caddy is $($caddy.Status) - starting..." -ForegroundColor Yellow
        try {
            Start-Service caddy -ErrorAction Stop
            Start-Sleep -Seconds 1
            Write-Host "Caddy started on port 8080." -ForegroundColor Green
        } catch {
            $id = [Security.Principal.WindowsIdentity]::GetCurrent()
            $principal = New-Object Security.Principal.WindowsPrincipal($id)
            $isAdmin = $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
            if (-not $isAdmin) {
                Write-Host "Could not start Caddy - this shell is not elevated." -ForegroundColor Red
                Write-Host "  Run in an admin prompt:  Start-Service caddy" -ForegroundColor Red
            } else {
                Write-Host "Could not start Caddy: $($_.Exception.Message)" -ForegroundColor Red
            }
        }
    } else {
        Write-Host "Caddy already running on port 8080." -ForegroundColor Green
    }

    # Nag until the recurrence is actually fixed. Manual start type is the reason
    # this goes down on every reboot.
    # Win32_Service.StartMode ('Auto' | 'Manual' | 'Disabled') rather than
    # ServiceController.StartType — present on every Windows PowerShell version.
    $startMode = (Get-CimInstance Win32_Service -Filter "Name='caddy'" -ErrorAction SilentlyContinue).StartMode
    if ($startMode -and $startMode -ne 'Auto') {
        Write-Host "Caddy start mode is '$startMode' - it will be down again after a reboot." -ForegroundColor Yellow
        Write-Host "  Fix once, in an admin prompt:  Set-Service caddy -StartupType Automatic" -ForegroundColor Yellow
    }
}

# Confirm something is actually listening, rather than trusting the service state
$listening = Get-NetTCPConnection -LocalPort 8080 -State Listen -ErrorAction SilentlyContinue
if (-not $listening) {
    Write-Host "WARNING: nothing is listening on 8080 - document deep-links will show ERR_CONNECTION_REFUSED." -ForegroundColor Red
}

# ── Node API server (port 3001) ──────────────────────────────────────────────
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

# ── React dev server (port 3000, foreground) ─────────────────────────────────
Write-Host "Starting React app..." -ForegroundColor Cyan
Set-Location E:\PowerAcademy\app\poweracademy
npm start

# When npm start exits, clean up server job.
# Caddy is deliberately left running - it is a service, shared, and not ours to stop.
Stop-Job $serverJob
Remove-Job $serverJob
Write-Host "Power Academy stopped (Caddy left running)." -ForegroundColor Cyan
