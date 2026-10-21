---
description: Build a paper's 論文導讀 deck by the guide round -- front matter, 承先啟後, review, verify against the original
argument-hint: <paper ids...>
---

Rebuild the 論文導讀 deck of each paper in `$ARGUMENTS` (or the papers ticked for
帶出門, `pocket.marked_ids()`, when none are given) so that someone who has not
read the paper gets into its field fast. The method, the slide allocation and the
three subagent briefs are in `docs/guide-decks.md` — read it first and follow it.
Talk to the user in Traditional Chinese.

1. For each paper, check it is analysed (`.\scripts\dev.ps1 analyze <id>`; it skips
   what exists) and has a 論文導讀 deck (if not, ask the user to generate a draft
   in the 簡報 tab, any length). Papers with no PDF cannot go through the round:
   say so and leave them.
2. `.\scripts\dev.ps1 python scripts/guide_deck.py export <id>` for each.
3. **Build**: one background subagent per paper with Brief A, pointed at its
   `data/guide-work/<paper>/`. When each returns, run
   `guide_deck.py apply-guide <id> --dry-run`, read the slides of the field, 承先
   and 啟後 parts yourself (are the foundations named with what they give? are
   the open problems specific and evidenced?), then `apply-guide <id>`.
4. Export again (the decks changed), then **review** with Brief B and **verify and
   place** with Brief C, one subagent per paper for each. Read the proposed slide
   edits before `guide_deck.py apply-review <id>`; dry-run first.
5. Export again, then the **key-sentence and detail** pass with Brief D, one
   subagent per paper → `detail_plan.json`. Read its edits and inserted slides,
   then `guide_deck.py apply-review <id> --plan detail_plan.json` (dry-run first).
6. If any paper is ticked for 帶出門, rebuild the page
   (`.\scripts\dev.ps1 python scripts/build_pocket_reader.py`) and offer to publish.
7. Report per paper: slide count and how many went to the field / 承先 / 啟後
   parts, items held / partly held / failed and the notable corrections, slide
   edits, inserted slides, speaker-note additions, Q&A cards added, and the key
   sentences that had been missing. Previous decks are in history.
