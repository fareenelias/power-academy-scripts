# git_save.ps1
# Usage: .\git_save.ps1 "your commit message"
# Run from E:\PowerAcademy\

param(
    [string]$Message = "update $(Get-Date -Format 'yyyy-MM-dd HH:mm')"
)

Set-Location E:\PowerAcademy

# Stage everything
git add -A

# Show what's being committed
git status --short

# Commit
git commit -m $Message

# Push to master
git push origin master

Write-Host "`nDone. Pushed to master." -ForegroundColor Green