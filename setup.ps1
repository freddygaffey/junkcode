# local-dictation - setup for Windows.
# Run in a NORMAL PowerShell window (not admin):
#   powershell -ExecutionPolicy Bypass -File .\setup.ps1
#   powershell -ExecutionPolicy Bypass -File .\setup.ps1 -Check
#   powershell -ExecutionPolicy Bypass -File .\setup.ps1 -Cleanup
param([switch]$Check, [switch]$Cleanup)

$ErrorActionPreference = "Stop"
$Root  = Split-Path -Parent $MyInvocation.MyCommand.Path
$Venv  = Join-Path $Root ".venv"
$Py    = Join-Path $Venv "Scripts\python.exe"
$Pip   = Join-Path $Venv "Scripts\pip.exe"

function Say  ($m) { Write-Host "`n==> $m" -ForegroundColor Cyan }
function Ok   ($m) { Write-Host "    ok   $m" -ForegroundColor Green }
function Warn ($m) { Write-Host "    warn $m" -ForegroundColor Yellow }
function Die  ($m) { Write-Host "    fail $m" -ForegroundColor Red; exit 1 }

if ($Check) {
    if (-not (Test-Path $Py)) { Die "No virtualenv found - run setup.ps1 first" }
    & $Py (Join-Path $Root "src\dictate.py") --check
    exit $LASTEXITCODE
}

Say "local-dictation setup (windows)"

if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
    Say "Installing Python via winget"
    winget install -e --id Python.Python.3.12 --accept-source-agreements --accept-package-agreements
    Warn "Close and reopen PowerShell, then run this script again."
    exit 0
}
Ok ("python " + (python -c "import sys;print('.'.join(map(str,sys.version_info[:3])))"))

if (-not (Test-Path $Venv)) { Say "Creating virtualenv"; python -m venv $Venv }
else { Ok "virtualenv exists" }

Say "Installing Python dependencies"
# pip cannot replace itself while running as pip.exe; go via python -m
& $Py -m pip install --quiet --upgrade pip
& $Pip install --quiet -r (Join-Path $Root "requirements.txt")
if ($LASTEXITCODE -ne 0) { Die "pip install failed" }
Ok "dependencies installed"

# ctranslate2 does not vendor the CUDA runtime; without these an NVIDIA GPU is
# detected but every transcription fails on a missing cublas DLL.
Say "Checking for an NVIDIA GPU"
$hasNvidia = $null -ne (Get-Command nvidia-smi -ErrorAction SilentlyContinue)
if ($hasNvidia) {
    Say "NVIDIA GPU found - installing CUDA runtime libraries"
    & $Py -m pip install --quiet nvidia-cublas-cu12 nvidia-cudnn-cu12
    if ($LASTEXITCODE -eq 0) { Ok "CUDA runtime installed" } else { Warn "CUDA runtime install failed - CPU will still work" }
} else {
    Ok "no NVIDIA GPU - using CPU"
}

if ($Cleanup) {
    if (Get-Command ollama -ErrorAction SilentlyContinue) { Ok "ollama present" }
    else {
        Say "Installing Ollama via winget"
        winget install -e --id Ollama.Ollama --accept-source-agreements --accept-package-agreements
    }
    Say "Pulling cleanup model (this can take a while)"
    ollama pull llama3.1:8b
    & $Py -c @"
import configparser
p = r'$Root\config\config.ini'
c = configparser.ConfigParser(); c.read(p)
c['cleanup']['enabled'] = 'true'
open(p,'w').write('') or None
with open(p,'w') as fh: c.write(fh)
print('    ok   cleanup enabled')
"@
}

Say "Downloading the speech model (first run only)"
& $Py -c @"
import configparser, time
c = configparser.ConfigParser(); c.read(r'$Root\config\config.ini')
name = c['transcription'].get('model','large-v3-turbo')
print(f'    pulling {name} ...')
t0 = time.time()
from faster_whisper import WhisperModel
WhisperModel(name, device='cpu', compute_type='int8')
print(f'    ok   model ready ({time.time()-t0:.0f}s)')
"@
if ($LASTEXITCODE -ne 0) { Die "model download failed" }

Say "Self-test"
& $Py (Join-Path $Root "src\dictate.py") --check

Say "Done"
Write-Host @"

  Run it:      $Py $Root\src\dictate.py
  Settings:    $Py $Root\src\webui.py    then open http://127.0.0.1:5000
  Diagnose:    powershell -ExecutionPolicy Bypass -File .\setup.ps1 -Check

  Note: Windows may need the app allowed through Microphone privacy settings:
    Settings > Privacy & security > Microphone > Let desktop apps access your microphone

"@
