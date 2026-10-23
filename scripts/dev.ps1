$ErrorActionPreference = "Stop"
Set-Location (Split-Path $PSScriptRoot -Parent)
$env:PYTHONIOENCODING = "utf-8"
if (-not (Test-Path .venv\Scripts\python.exe)) {
    Write-Error "Paperfact is not set up. Run .\scripts\setup.ps1 first."
}
& .\.venv\Scripts\python.exe -m paper_daily @args
exit $LASTEXITCODE
