---
description: Show what is coming up in the reading queue
---

Run `.\scripts\dev.ps1 peek 20` (PowerShell) or `./scripts/dev.sh peek 20` and show
the upcoming papers.

Then briefly explain the shape of what is coming: which year block is being read,
roughly how many papers remain in it, and any canon or companion papers due soon.
Get the remaining counts from `.\scripts\dev.ps1 status`.

If the reader wants to change what is coming, the levers are:
- `mark <paper_id> skipped` to drop one paper;
- `rank --per-year N` to change how many papers each conference year contributes;
- editing `ScoreWeights` in `src/paper_daily/config.py` to re-weight the signals,
  then `rank` to rebuild.
