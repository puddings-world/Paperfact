---
description: Pop another paper from the queue right now (beyond today's one)
---

Deliver the next paper immediately, without waiting for the nightly run.

1. Run `.\scripts\dev.ps1 today` (PowerShell) or `./scripts/dev.sh today`.
2. Follow the same deep-dive procedure and structure as `/paper-today`, writing to
   `data/briefs/<date>/deep-dive-<n>.md` so it does not overwrite the day's first one.

Use this whenever the reader wants to keep going. The queue is designed to be pulled
from on demand -- one paper per night is the floor, not the cap.
