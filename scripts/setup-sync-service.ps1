$ErrorActionPreference = "Stop"
Set-Location (Split-Path $PSScriptRoot -Parent)

function Invoke-ServiceSetupStep([scriptblock] $Step) {
    & $Step
    if ($LASTEXITCODE -ne 0) { throw "Sync-service setup failed; fix the error above and retry." }
}

if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    Invoke-RestMethod https://astral.sh/uv/install.ps1 | Invoke-Expression
    $env:Path = "$env:USERPROFILE\.local\bin;$env:Path"
}
$priorServiceEnvironment = $env:UV_PROJECT_ENVIRONMENT
try {
    $env:UV_PROJECT_ENVIRONMENT = Join-Path (Get-Location) ".venv-sync"
    Invoke-ServiceSetupStep { uv sync --locked --python 3.11 --extra gcp }
} finally {
    $env:UV_PROJECT_ENVIRONMENT = $priorServiceEnvironment
}
Invoke-ServiceSetupStep { & .\.venv-sync\Scripts\python.exe -m paper_daily sync-admin upload-backup --help }
Write-Host "Ready: .\.venv-sync\Scripts\python.exe -m paper_daily sync-admin --help"
Write-Host "No authority, cloud login, upload, resource or service was created."
