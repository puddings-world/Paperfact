# Create double-click launchers for the reader, with no console window.
#
# The shortcut runs scripts\launch-app.vbs, which starts the app with its console
# window hidden. pythonw.exe is not usable here: uv's venv ships it as a trampoline
# that re-execs the console python.exe, so a terminal appears anyway.

$ErrorActionPreference = "Stop"
$root = Split-Path $PSScriptRoot -Parent
$vbs  = Join-Path $root "scripts\launch-app.vbs"
$icon = Join-Path $root "assets\paper-daily.ico"

if (-not (Test-Path (Join-Path $root ".venv\Scripts\python.exe"))) {
    throw "the venv is missing -- run scripts\setup.ps1 first."
}
if (-not (Test-Path $icon)) {
    Write-Host "Generating the icon..."
    & (Join-Path $root ".venv\Scripts\python.exe") (Join-Path $root "scripts\make_icon.py")
}

$targets = @(
    [IO.Path]::Combine([Environment]::GetFolderPath("Desktop"), "Paperfact.lnk"),
    [IO.Path]::Combine([Environment]::GetFolderPath("StartMenu"), "Programs", "Paperfact.lnk")
)

$shell = New-Object -ComObject WScript.Shell
foreach ($path in $targets) {
    $dir = Split-Path $path -Parent
    if (-not (Test-Path $dir)) { New-Item -ItemType Directory -Path $dir -Force | Out-Null }
    $lnk = $shell.CreateShortcut($path)
    # wscript.exe rather than the .vbs directly, so the shortcut still works on a
    # machine where .vbs is associated with an editor.
    $lnk.TargetPath       = "$env:SystemRoot\System32\wscript.exe"
    $lnk.Arguments        = "`"$vbs`""
    $lnk.WorkingDirectory = $root
    $lnk.IconLocation     = "$icon,0"
    $lnk.Description      = "Read papers, take notes, and explore research"
    $lnk.WindowStyle      = 1
    $lnk.Save()
    Write-Host "created  $path"
}

Write-Host ""
Write-Host "Double-click 'Paperfact' on the Desktop, or find it in the Start"
Write-Host "menu (type 'Paperfact'). No terminal opens, and launching it twice raises the"
Write-Host "window that is already open instead of adding another."
