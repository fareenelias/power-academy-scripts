# Power Academy — Start / check all services
# Run from anywhere: .\start.ps1
#
# Three things must be up for the dashboard to work fully:
#   Caddy   :8080  Windows SERVICE — serves documents\ (PDFs, reports, credit, transcripts)
#   Caddy   :3000  the dashboard — the production BUILD (app\poweracademy\build), same service
#   Node    :3001  API / JSON data (scheduled task PowerAcademy-API if registered)
# 2026-09-24: this script no longer runs `npm start`. Caddy owns :3000 and serves the build, so the
# react-scripts dev server collided with it. After a UI change:  cd E:\PowerAcademy\app\poweracademy ; npm run build
# For live-reload development only:  $env:PORT=3002 ; npm start   (never on 3000)
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

# ── Dashboard (port 3000, served by Caddy from the build) ───────────────────
$build = "E:\PowerAcademy\app\poweracademy\build\index.html"
if (-not (Test-Path $build)) {
    Write-Host "No production build at $build - run: cd E:\PowerAcademy\app\poweracademy ; npm run build" -ForegroundColor Red
} else {
    $age = [int]((Get-Date) - (Get-Item $build).LastWriteTime).TotalHours
    Write-Host "Dashboard build present (built $age h ago)." -ForegroundColor Green
}
if (Get-NetTCPConnection -LocalPort 3000 -State Listen -ErrorAction SilentlyContinue) {
    Write-Host "Port 3000 listening - dashboard: http://localhost:3000  (phone via Tailscale: http://100.86.108.51:3000)" -ForegroundColor Green
} else {
    Write-Host "WARNING: nothing is listening on 3000 - Caddy serves the dashboard there; check the Caddy service / Caddyfile." -ForegroundColor Red
}

# ── Node API server (port 3001) ──────────────────────────────────────────────
if (Get-NetTCPConnection -LocalPort 3001 -State Listen -ErrorAction SilentlyContinue) {
    Write-Host "API already running on 3001." -ForegroundColor Green
    try {
        $health = Invoke-RestMethod -Uri "http://localhost:3001/api/health" -TimeoutSec 3
        Write-Host "Server OK - State file: $($health.stateFile)" -ForegroundColor Green
    } catch { Write-Host "Port 3001 is held but /api/health did not answer - restart the API." -ForegroundColor Yellow }
    Write-Host "Power Academy is up." -ForegroundColor Cyan
    return
}

$task = Get-ScheduledTask -TaskName "PowerAcademy-API" -ErrorAction SilentlyContinue
if ($task) {
    Write-Host "Starting scheduled task PowerAcademy-API..." -ForegroundColor Cyan
    Start-ScheduledTask -TaskName "PowerAcademy-API"
    Start-Sleep -Seconds 3
    if (Get-NetTCPConnection -LocalPort 3001 -State Listen -ErrorAction SilentlyContinue) {
        Write-Host "API started on 3001 (scheduled task - survives closing this window)." -ForegroundColor Green
    } else {
        Write-Host "Task started but nothing listens on 3001 yet - check Task Scheduler history." -ForegroundColor Yellow
    }
    return
}

# No task registered: run the API in THIS window (Ctrl+C stops it). Closing the window stops the API.
Write-Host "No PowerAcademy-API task - running the API in this window. Closing it stops :3001." -ForegroundColor Yellow
Write-Host "  Permanent fix, once, in an admin prompt:  E:\PowerAcademy\scripts\register_api_task.ps1" -ForegroundColor Yellow
$env:ANTHROPIC_API_KEY = $API_KEY
node E:\PowerAcademy\scripts\server.js
