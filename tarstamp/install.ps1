# tarstamp installer (Windows PowerShell / pwsh)
# Usage:
#   irm https://raw.githubusercontent.com/freddygaffey/tarstamp/main/install.ps1 | iex

$ErrorActionPreference = "Stop"
$repoRaw = "https://raw.githubusercontent.com/freddygaffey/tarstamp/main"
$dest    = Join-Path $HOME ".tarstamp.ps1"

Write-Host "tarstamp: downloading -> $dest"
Invoke-WebRequest -Uri "$repoRaw/tarstamp.ps1" -OutFile $dest -UseBasicParsing

if (-not (Test-Path $PROFILE)) {
    New-Item -ItemType File -Path $PROFILE -Force | Out-Null
    Write-Host "tarstamp: created $PROFILE"
}

$sourceLine = ". `"$dest`""
$existing = Get-Content $PROFILE -ErrorAction SilentlyContinue
if ($existing -notmatch [regex]::Escape(".tarstamp.ps1")) {
    Add-Content -Path $PROFILE -Value "`n# tarstamp`n$sourceLine"
    Write-Host "tarstamp: added source line to $PROFILE"
} else {
    Write-Host "tarstamp: profile already references tarstamp"
}

if (-not (Get-Command tar -ErrorAction SilentlyContinue)) {
    Write-Warning "tarstamp: 'tar' not found in PATH. Windows 10 1803+ ships bsdtar. Older: install Git for Windows or 7-Zip."
}

Write-Host "tarstamp: done. restart shell or run:  . $dest"
