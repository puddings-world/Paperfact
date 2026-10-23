$ErrorActionPreference = "Stop"
Set-Location (Split-Path $PSScriptRoot -Parent)

# Windows PowerShell does not turn native nonzero exit codes into exceptions.
function Invoke-SetupStep([scriptblock] $Step) {
    & $Step
    if ($LASTEXITCODE -ne 0) {
        throw "Setup stopped (exit $LASTEXITCODE). Fix the error above and rerun setup."
    }
}

if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    Write-Host "Installing uv..."
    Invoke-RestMethod https://astral.sh/uv/install.ps1 | Invoke-Expression
    $env:Path = "$env:USERPROFILE\.local\bin;$env:Path"
}

# A run cut off while creating it leaves a .venv with no Python, which uv then
# refuses to reuse; recreate it in that case, and keep a working one as it is.
if (-not (Test-Path .venv\Scripts\python.exe)) { Invoke-SetupStep { uv venv --clear --python 3.11 } }
Write-Host "Installing dependencies (the desktop reader pulls ~1 GB of Qt; this takes a few minutes)..."
Invoke-SetupStep { uv sync --extra dev --extra app }
Write-Host "AI profiles can be configured in the reader with AI settings; see docs/architecture.md."
if (-not (Test-Path data)) { New-Item -ItemType Directory data | Out-Null }
Invoke-SetupStep { & .\.venv\Scripts\python.exe -m paper_daily fonts }
Invoke-SetupStep { & .\.venv\Scripts\python.exe -m paper_daily web-assets }
Invoke-SetupStep { & .\.venv\Scripts\python.exe scripts\make_icon.py }

Write-Host ""
Write-Host "Open AI settings in the app to install/sign in to Claude, Codex or Gemini."
Write-Host "Choose your account and model there; API configuration is optional."
Write-Host "A fresh workspace starts empty. Create a list or import a colleague's research bundle."
Write-Host "Importing research bundles and reading saved work need no AI account."

Write-Host ""
Write-Host "Done. Next:"
Write-Host "  .\scripts\dev.ps1 app    # open Paperfact, add your papers and configure AI settings"
Write-Host "  .\scripts\dev.ps1 doctor # check the installation if needed"
Write-Host "  Optional ML conference workflow: see docs/ml-daily.md."
Write-Host ""
Write-Host "Optional ML nightly schedule (configure its corpus first):"
Write-Host "  .\scripts\register-nightly.ps1"
