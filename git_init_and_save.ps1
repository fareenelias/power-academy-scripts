# git_init_and_save.ps1
# Run this ONCE to initialize git and make first commit
# After this, use git_save.ps1 for subsequent commits

Set-Location E:\PowerAcademy

# Check if already a git repo
if (Test-Path ".git") {
    Write-Host "Already a git repo - skipping init" -ForegroundColor Yellow
} else {
    git init
    Write-Host "Git initialized" -ForegroundColor Green
}

# Check if remote already set
$remotes = git remote 2>$null
if ($remotes -notcontains "origin") {
    # Set your GitHub remote - update this URL to your actual repo
    git remote add origin https://github.com/fareenelias/power-academy.git
    Write-Host "Remote added" -ForegroundColor Green
} else {
    Write-Host "Remote already set" -ForegroundColor Yellow
}

# Create .gitignore
@"
node_modules/
.env
*.log
data/state.json
data/server_log.txt
"@ | Out-File -FilePath ".gitignore" -Encoding utf8

# Stage, commit, push
git add -A
git commit -m "initial commit - power academy dashboard"
git branch -M master
git push -u origin master

Write-Host "`nDone. Repo initialized and pushed to master." -ForegroundColor Green
Write-Host "From now on, just run: .\scripts\git_save.ps1 `"your message`"" -ForegroundColor Cyan