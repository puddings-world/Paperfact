# Write every dive that is missing, then upgrade the ones written to an older spec.
#
# Three phases, in this order, because that is the order of how much is missing:
#
#   1. reading lists       -- a freshly imported list has no explanation at all, and
#                             writing a dive is also what downloads and extracts the
#                             PDF, so this is what makes a list readable.
#   2. the main queue      -- papers near the front with no dive yet.
#   3. rewrites            -- dives that exist but predate the current DIVE_SPEC.
#
# Each dive is committed as it is written, so a run that dies costs at most the dives
# in flight, and re-running picks up where it stopped. Run it detached:
#   Start-Process powershell -WindowStyle Hidden -ArgumentList `
#     '-ExecutionPolicy','Bypass','-File','scripts\catch-up-dives.ps1'

param(
    [int]$Jobs = 2,        # dives in flight at once; each one waits on a model.
                           # Three was enough to make Windows report memory pressure:
                           # every claude CLI call is its own node process tree.
    [int]$Batch = 12,      # dives per pass, so progress is logged as it goes
    [switch]$SkipRewrite   # only write what is missing, leave older dives alone
)

$ErrorActionPreference = "Continue"
Set-Location (Split-Path $PSScriptRoot -Parent)
$env:PYTHONIOENCODING = "utf-8"
# Decode that UTF-8 as UTF-8, not the console code page (see nightly.ps1).
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch {}

$py  = ".\.venv\Scripts\python.exe"
$log = "data\catch-up.log"

function Log($m) { "$(Get-Date -Format s)  $m" | Out-File -FilePath $log -Append -Encoding utf8 }

function Run-Phase($name, $extra) {
    $pass = 0
    while ($true) {
        $pass++
        $cmd = @("-m", "paper_daily", "dive-ahead", "$Batch", "--jobs", "$Jobs") + $extra
        $out = & $py @cmd 2>&1
        $out | Out-File -FilePath $log -Append -Encoding utf8

        $code = $LASTEXITCODE
        $written = 0
        foreach ($line in $out) {
            if ("$line" -match '^\s*(\d+) deep dive') { $written = [int]$Matches[1] }
        }
        Log "$name pass $pass wrote $written (exit $code)"

        # A crash also writes nothing, and reading that as "finished" is how a run
        # that died on a locked database came to log "done" with 74 dives left.
        if ($code -ne 0) {
            Log "$name STOPPED: the command failed -- see the traceback above this line"
            return
        }
        # Nothing written means either the phase is finished or the backend has
        # stopped answering. Either way another pass would repeat it.
        if ($written -eq 0) { return }
    }
}

Log "=== catch-up start ($Jobs at a time) ==="
Run-Phase "lists" @("--list", "all")
Run-Phase "queue" @()
if (-not $SkipRewrite) {
    Run-Phase "rewrite" @("--rewrite")
    # --rewrite alone walks the queue, and a list paper is usually not in it. Without
    # this the run reported "done" with thirty list dives still on the old spec.
    Run-Phase "rewrite-lists" @("--list", "all", "--rewrite")
}
Log "=== catch-up done ==="
