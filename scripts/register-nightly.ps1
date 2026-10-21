# Register (or re-register) the nightly run with Windows Task Scheduler.
#
# Runs at 00:00 every day. The machine has to be awake: a laptop that is asleep
# simply skips that night, and the queue picks up where it left off -- nothing is
# lost and nothing is served twice.

$ErrorActionPreference = "Stop"
$root = Split-Path $PSScriptRoot -Parent
$script = Join-Path $root "scripts\nightly.ps1"
$name = "paper-daily nightly"

$action = New-ScheduledTaskAction -Execute "powershell.exe" `
    -Argument "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$script`"" `
    -WorkingDirectory $root
$trigger = New-ScheduledTaskTrigger -Daily -At 00:00
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable `
    -DontStopIfGoingOnBatteries -AllowStartIfOnBatteries `
    -ExecutionTimeLimit (New-TimeSpan -Hours 2)

if (Get-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue) {
    Unregister-ScheduledTask -TaskName $name -Confirm:$false
    Write-Host "replaced the existing task"
}

Register-ScheduledTask -TaskName $name -Action $action -Trigger $trigger `
    -Settings $settings -Description "Deliver and explain one ICLR/ICML/NeurIPS paper" | Out-Null

Write-Host "Registered '$name' for 00:00 daily."
Write-Host ""
Write-Host "  -StartWhenAvailable is on, so a night the machine was asleep runs as"
Write-Host "  soon as it wakes rather than being skipped entirely."
Write-Host ""
Write-Host "Check it:   Get-ScheduledTask -TaskName '$name' | Get-ScheduledTaskInfo"
Write-Host "Run it now: Start-ScheduledTask -TaskName '$name'"
Write-Host "Remove it:  Unregister-ScheduledTask -TaskName '$name'"
