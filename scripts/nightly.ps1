# The nightly run. Registered by scripts/register-nightly.ps1 to fire at 00:00.
#
# Order matters: pick up newly published papers, deliver the next one, generate its
# deep dive through the selected AI profile, then open the reader. By the time
# you next touch the machine the window is already showing tonight's paper with its
# explanation written.

$ErrorActionPreference = "Continue"
Set-Location (Split-Path $PSScriptRoot -Parent)
$env:PYTHONIOENCODING = "utf-8"
# PowerShell decodes a program's output with the console code page (cp950 on a
# Traditional Chinese Windows), so Python's UTF-8 came out as mojibake in the log.
# Under Task Scheduler there may be no console to set it on.
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch {}

$py  = ".\.venv\Scripts\python.exe"
$pyw = ".\.venv\Scripts\pythonw.exe"
# The data folder may sit outside the checkout (PAPERFACT_DATA, or .env).
$data = & $py -c "from paper_daily.config import DATA_DIR, ensure_dirs; ensure_dirs(); print(DATA_DIR)"
$log = Join-Path $data "nightly.log"

# Tee-Object in PowerShell 5.1 writes UTF-16LE, which renders the log unreadable.
function Log($m) { "$(Get-Date -Format s)  $m" | Out-File -FilePath $log -Append -Encoding utf8 }

Log "=== nightly start ==="

# Newly published papers land at the front of the queue by construction, so this is
# also how a new conference year enters the reading order.
Log "refresh"
& $py -m paper_daily refresh 2>&1 | Out-File -FilePath $log -Append -Encoding utf8

Log "today"
& $py -m paper_daily today 2>&1 | Out-File -FilePath $log -Append -Encoding utf8

# Pull the PDF and text for the papers after tonight's, so tomorrow is instant and
# jumping around the queue always has the original to show.
Log "prefetch"
& $py -m paper_daily prefetch 10 2>&1 | Out-File -FilePath $log -Append -Encoding utf8

# Walk the citation graph ahead of the reading, so the lineage tab has something to
# show before you get to a paper rather than after.
Log "lineage"
& $py -m paper_daily lineage 40 2>&1 | Out-File -FilePath $log -Append -Encoding utf8

Log "backfill"
& $py -m paper_daily backfill --limit 60 2>&1 | Out-File -FilePath $log -Append -Encoding utf8

# Semantic Scholar answers 429 and arXiv answers 406 whenever either is busy, and the
# import that hit one wrote a paper with no route to its original. Try those again:
# a lookup that failed is not a paper that cannot be found.
Log "resolve-missing"
& $py -m paper_daily resolve-missing 20 2>&1 | Out-File -FilePath $log -Append -Encoding utf8

# The whole 深入分析 for the next few papers, as one unit: deep dive and close
# reading, the passages marked in the original, what each reference is doing (承先)
# and what later work did with it (啟後). Scheduled separately they ran on different
# budgets, and a paper arrived explained but with an empty 引用 tab. How often and
# how many (main queue and reading lists) is the reader's 分析排程 setting; reading
# lists are included because they are otherwise analysed only while open.
Log "analyze --scheduled"
& $py -m paper_daily analyze --scheduled --jobs 2 2>&1 | Out-File -FilePath $log -Append -Encoding utf8

# Preprints in the reading lists get published; Semantic Scholar keeps saying arXiv.
Log "venues"
& $py -m paper_daily venues --list all 2>&1 | Out-File -FilePath $log -Append -Encoding utf8

# And bring papers analysed under an older specification onto the current one, the
# same way dives are rolled forward.
Log "resources"
& $py -m paper_daily resources --list all 2>&1 | Out-File -FilePath $log -Append -Encoding utf8
Log "cites-ahead --rewrite"
& $py -m paper_daily cites-ahead 2 --rewrite --scheduled 2>&1 | Out-File -FilePath $log -Append -Encoding utf8

# Then bring older dives onto the current specification, in queue order. A few a
# night means a spec change reaches the papers about to be read without a marathon.
Log "dive-ahead --rewrite"
& $py -m paper_daily dive-ahead 6 --rewrite --jobs 2 --scheduled 2>&1 | Out-File -FilePath $log -Append -Encoding utf8

# All AI generation above uses the selected profile through paper_daily.llm.
# /paper-today remains available manually in Claude Code for agent-driven discussion.

# Through the .vbs so no console window is left behind; it also raises the window
# if the reader is already open rather than stacking a second one.
Log "opening the reader"
Start-Process -WindowStyle Hidden -FilePath "$env:SystemRoot\System32\wscript.exe" `
              -ArgumentList "`"$(Join-Path (Get-Location) 'scripts\launch-app.vbs')`"", "--next"

Log "=== nightly done ==="
