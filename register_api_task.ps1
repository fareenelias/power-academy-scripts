# Power Academy - register the Node API server as a scheduled task
# Run ONCE, in an ELEVATED PowerShell:  E:\PowerAcademy\scripts\register_api_task.ps1
#
# Why this exists: start.ps1 launches Node with Start-Job, which binds the API's lifetime
# to that PowerShell window. Close the terminal and :3001 dies, which presents in the UI as
# "Couldn't load consensus data (Failed to fetch)" - an infrastructure failure wearing a
# data failure's clothes. The tracker recorded this task as created on 2026-07-30; it was
# not. Get-ScheduledTask showed only PowerAcademy-LibraryIndexer on 2026-08-02.
#
# v2 (2026-08-02): v1 shipped two bugs that are the whole point of this project's QC rules.
#   1. No elevation gate. Register-ScheduledTask returned "Access is denied" and the script
#      carried on to print "Registered and started".
#   2. The success check could not fail. It health-checked port 3001 - which was already
#      held by a hand-started node - so it reported a task that does not exist as working.
#      A green check that proves nothing is worse than no check.
# Both are now hard gates: it refuses to run unelevated, and it asserts the task exists by
# reading it back before claiming anything.

$TaskName = "PowerAcademy-API"
$ServerJs = "E:\PowerAcademy\scripts\server.js"

# ---------------------------------------------------------------- GATE 1: elevation ----
$id        = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = New-Object Security.Principal.WindowsPrincipal($id)
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Write-Host ""
    Write-Host "NOT ELEVATED - stopping before changing anything." -ForegroundColor Red
    Write-Host "Registering a scheduled task needs an admin shell." -ForegroundColor Red
    Write-Host ""
    Write-Host "  Right-click PowerShell -> Run as administrator, then:" -ForegroundColor Yellow
    Write-Host "  E:\PowerAcademy\scripts\register_api_task.ps1" -ForegroundColor Yellow
    Write-Host ""
    exit 1
}

# ---------------------------------------------------------------- GATE 2: prereqs ------
$NodePath = (Get-Command node -ErrorAction SilentlyContinue).Source
if (-not $NodePath)             { Write-Host "ERROR: node not found on PATH." -ForegroundColor Red; exit 1 }
if (-not (Test-Path $ServerJs)) { Write-Host "ERROR: $ServerJs not found."    -ForegroundColor Red; exit 1 }

# A node already holding 3001 would make the final health check pass no matter what the task
# does - that is precisely how v1 reported success on a task it had failed to create.
$holder = Get-NetTCPConnection -LocalPort 3001 -State Listen -ErrorAction SilentlyContinue
if ($holder) {
    $pids = ($holder | Select-Object -ExpandProperty OwningProcess -Unique) -join ', '
    Write-Host "Port 3001 is already held by PID $pids - stopping it so this script's" -ForegroundColor Yellow
    Write-Host "health check tests the TASK's server rather than a pre-existing one." -ForegroundColor Yellow
    $holder | Select-Object -ExpandProperty OwningProcess -Unique |
        ForEach-Object { Stop-Process -Id $_ -Force -ErrorAction SilentlyContinue }
    Start-Sleep -Seconds 2
}

# Task Scheduler actions cannot set environment variables, so the Anthropic key has to be a
# persistent USER env var for the task to inherit it. The data routes do not need it - it is
# used solely by the /api/anthropic proxy in server.js.
if ($env:ANTHROPIC_API_KEY -and $env:ANTHROPIC_API_KEY -ne 'YOUR_ANTHROPIC_API_KEY_HERE') {
    [Environment]::SetEnvironmentVariable('ANTHROPIC_API_KEY', $env:ANTHROPIC_API_KEY, 'User')
    Write-Host "Persisted ANTHROPIC_API_KEY as a USER environment variable." -ForegroundColor Green
} else {
    Write-Host "No ANTHROPIC_API_KEY in this shell - registering without it." -ForegroundColor Yellow
    Write-Host "  Data routes work fine; only the /api/anthropic proxy stays inactive." -ForegroundColor Yellow
    Write-Host "  Add later:  [Environment]::SetEnvironmentVariable('ANTHROPIC_API_KEY','sk-ant-...','User')" -ForegroundColor Yellow
}

# ---------------------------------------------------------------- REGISTER -------------
Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue

$Action  = New-ScheduledTaskAction -Execute $NodePath -Argument "`"$ServerJs`"" -WorkingDirectory "E:\PowerAcademy\scripts"
$Trigger = New-ScheduledTaskTrigger -AtLogOn
$Settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -ExecutionTimeLimit ([TimeSpan]::Zero) -RestartInterval (New-TimeSpan -Minutes 1) -RestartCount 3 `
    -MultipleInstances IgnoreNew
$Principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType Interactive -RunLevel Limited

try {
    Register-ScheduledTask -TaskName $TaskName -Action $Action -Trigger $Trigger `
        -Settings $Settings -Principal $Principal `
        -Description "Power Academy Node API on :3001. Serves data\ to the dashboard." `
        -ErrorAction Stop | Out-Null
} catch {
    Write-Host ""
    Write-Host "REGISTRATION FAILED: $($_.Exception.Message)" -ForegroundColor Red
    Write-Host "No task was created. Nothing else was changed." -ForegroundColor Red
    exit 1
}

# ---------------------------------------------------------------- VERIFY ---------------
# Read the task back. Registration reporting no error is not proof the task exists.
$task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if (-not $task) {
    Write-Host "VERIFY FAILED: Register-ScheduledTask raised no error but no task is present." -ForegroundColor Red
    exit 1
}
Write-Host "Task exists. State: $($task.State)" -ForegroundColor Green

Start-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
Start-Sleep -Seconds 4

$ok = $false
try {
    $h = Invoke-RestMethod -Uri "http://localhost:3001/api/health" -TimeoutSec 5
    $ok = [bool]$h.ok
    Write-Host "Health check OK  - ok=$($h.ok)  stateFile=$($h.stateFile)  apiKeySet=$($h.apiKeySet)" -ForegroundColor Green
} catch {
    Write-Host "Health check FAILED - the task is registered but its server is not answering." -ForegroundColor Red
    Write-Host "  Inspect with:  Get-ScheduledTaskInfo -TaskName '$TaskName'" -ForegroundColor Yellow
}

Write-Host ""
if ($ok) {
    Write-Host "DONE - $TaskName is registered, running, and starts at logon." -ForegroundColor Cyan
    Write-Host "The API now survives closing any terminal." -ForegroundColor Cyan
} else {
    Write-Host "PARTIAL - the task is registered but did not come up. Do not assume :3001 is covered." -ForegroundColor Red
}
Write-Host ""
Write-Host "Status:  Get-ScheduledTask -TaskName '$TaskName' | Select TaskName,State" -ForegroundColor Yellow
Write-Host "Last run: Get-ScheduledTaskInfo -TaskName '$TaskName'" -ForegroundColor Yellow
Write-Host "Remove:  Unregister-ScheduledTask -TaskName '$TaskName' -Confirm:`$false" -ForegroundColor Yellow
