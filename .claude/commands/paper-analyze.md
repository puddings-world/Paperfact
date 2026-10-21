---
description: Fully analyse a reading list (or some papers) -- PDF, deep dive, 承先, 啟後
argument-hint: <list id | paper ids...> [--retry]
---

Make everything the reader shows for each paper that does not have it yet: the PDF,
a deep dive on the whole paper, the reference analysis (承先), and later work with
the 研究脈絡 overview (啟後). Papers that already have all of it are skipped.

1. If `$ARGUMENTS` is empty, run `.\scripts\dev.ps1 lists` and ask which list.
2. A single word that names a list: run
   `.\scripts\dev.ps1 analyze --list <id> --jobs 3`.
   Paper ids: `.\scripts\dev.ps1 analyze <ids...>`. Pass `--retry` through when given,
   to try again the steps that failed before.
3. It prints one line per finished paper: `[3/17] 原文✓ 講解✓ 承先✓ 啟後✓  <title>`.
   Run it in the background for more than a few papers; each paper takes minutes.
4. Report what is still missing afterwards, especially `原文✗`: no source had the
   PDF. Those need a hand -- right-click the row in the reader → 補 PDF, or
   `.\scripts\dev.ps1 repdf <id> --file <path>` / `--url <url>`, then
   `analyze <id> --retry`.

The desktop reader's **分析未完成的 N 篇** button runs the same command.
