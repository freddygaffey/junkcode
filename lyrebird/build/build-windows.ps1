# Build Yap.exe (and an installer if Inno Setup is present).
#   powershell -ExecutionPolicy Bypass -File .\build\build-windows.ps1
param([switch]$ExeOnly)

$ErrorActionPreference = "Stop"
$env:PROJECT_ROOT = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$env:APP_NAME     = if ($env:APP_NAME) { $env:APP_NAME } else { "Lyrebird" }
$Venv = Join-Path $env:PROJECT_ROOT ".venv"
$Dist = Join-Path $env:PROJECT_ROOT "dist"

function Say($m) { Write-Host "`n==> $m" -ForegroundColor Cyan }

if (-not (Test-Path $Venv)) { Write-Host "Run setup.ps1 first"; exit 1 }

Say "Building $($env:APP_NAME).exe"
Remove-Item -Recurse -Force $Dist -ErrorAction SilentlyContinue
& (Join-Path $Venv "Scripts\pyinstaller.exe") `
    --noconfirm --clean `
    --distpath $Dist `
    --workpath (Join-Path $env:PROJECT_ROOT "build\work") `
    (Join-Path $env:PROJECT_ROOT "build\app.spec")

$AppDir = Join-Path $Dist $env:APP_NAME
if (-not (Test-Path $AppDir)) { Write-Host "Build failed"; exit 1 }
Say "Built $AppDir"

if ($ExeOnly) { exit 0 }

# Inno Setup produces a normal Windows installer if it is available.
$Iscc = Get-Command iscc -ErrorAction SilentlyContinue
if (-not $Iscc) {
    Say "Inno Setup not found - skipping installer"
    Write-Host "  Install it with:  winget install -e --id JRSoftware.InnoSetup"
    Write-Host "  Or just zip $AppDir and share that."
    exit 0
}

$Iss = Join-Path $env:PROJECT_ROOT "build\installer.iss"
@"
[Setup]
AppName=$($env:APP_NAME)
AppVersion=1.0.0
DefaultDirName={autopf}\$($env:APP_NAME)
DefaultGroupName=$($env:APP_NAME)
OutputDir=$Dist
OutputBaseFilename=$($env:APP_NAME)-Setup
Compression=lzma2
SolidCompression=yes
PrivilegesRequired=lowest
[Files]
Source: "$AppDir\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs
[Icons]
Name: "{group}\$($env:APP_NAME)"; Filename: "{app}\$($env:APP_NAME).exe"
Name: "{autodesktop}\$($env:APP_NAME)"; Filename: "{app}\$($env:APP_NAME).exe"
[Run]
Filename: "{app}\$($env:APP_NAME).exe"; Description: "Launch $($env:APP_NAME)"; Flags: nowait postinstall skipifsilent
"@ | Set-Content -Encoding UTF8 $Iss

Say "Creating installer"
& iscc $Iss
Say "Done - see $Dist"
