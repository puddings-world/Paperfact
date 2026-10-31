---
description: Deliver and deep-dive today's paper from the reading queue
---

Deep-dive today's paper.

## Steps

1. Find today's pack: `ls data/briefs/<today's local date>/*-pack.md`. If there is
   none, run `.\scripts\dev.ps1 today` (PowerShell) or `./scripts/dev.sh today` to
   pop the next paper and build one.
2. Read the pack in full. It carries the paper's id, the abstract, the ranking
   rationale, the lineage, what has been read recently, and the extracted full text.
3. Write the deep dive to `data/briefs/<date>/<paper id as filename>-deep-dive.md`
   **and** print it in the conversation so it can be discussed straight away.
4. Store it against the paper, by id — take the id from the pack's **Paper id** line:

   ```powershell
   .\scripts\dev.ps1 set-dive "<paper id>" --file "data\briefs\<date>\<file>.md"
   .\scripts\dev.ps1 mark "<paper id>" read
   ```

   Use `set-dive` rather than relying on the filename or the folder. An earlier
   version matched dive files to papers by the date folder they sat in, and the
   moment two papers were delivered on one day the wrong paper ended up displaying
   another paper's explanation.

## What the deep dive must contain

Write in Traditional Chinese, keeping every technical term, paper title, and author
name in English. Maths is LaTeX — `$...$` inline, `$$` on its own line around a
displayed equation — because the reader and the pocket page typeset it with
KaTeX. (This is the one exception to the global plain-Unicode rule: the dive is
read in the app, never in the terminal.)

Use the paper's actual study design: theoretical, empirical, observational,
qualitative or review. Separate author claims, observations/proofs, inference and
missing evidence. Unreported is not zero; a located quote is not semantic proof.
Do not infer causation, replication or influence without the necessary sources.
The canonical executable specification is `dive.DIVE_INSTRUCTIONS`; its current
recipe is `2026-10-study-design`. Existing saved explanations remain available.

Structure:

1. **一句話結論** — what this paper actually established, in one sentence.
2. **前導導讀** — the longest section: a guided reading of the Introduction,
   Background and Related Work (and any Preliminaries or Motivation before the
   method), following the paper's own order, so the reader could state the authors'
   argument without rereading those pages. Five `###` subsections: 研究當下的狀態
   (the field when it was written: dominant methods, datasets, typical numbers,
   assumptions, with citation markers), 作者的論證怎麼推進 (the introduction
   paragraph by paragraph: each claim, its support, and where the argument turns
   from state of the art to gap to approach; short English quotes allowed),
   相關研究的地圖 (lines of prior work, what each lacks per the authors, and how this
   paper relates to each), 缺口、主張與貢獻 (the stated contributions, each with the
   evidence or argument appropriate to its design (proof, observations, materials,
   experiments or listed exhibits), or explicitly missing support), and 讀前導章節時該帶著的
   問題 (up to five grounded doubts to carry into subsequent methods, arguments or
   evidence; do not fill a quota). Without
   full text, say so and work from the abstract only.
3. **核心洞見** — the single idea the paper turns on. If you cannot name it in two
   sentences, you have not found it yet.
4. **方法** — identify the study design, assumptions and reproducible steps.
   Apply relevant checks for samples/materials, controls, measurement/analysis and
   uncertainty, theorem conditions/proofs, qualitative sampling/coding or review
   search/eligibility criteria. Mark unreported items; use equations when relevant.
5. **機制圖解** — show the actual sampling, intervention, analysis, proof or
   screening workflow. Model/gradient/tensor details apply only when the paper has
   them. If no useful mechanism diagram exists, explain the key relations instead.
6. **證據** — what the data, observations, proof or experiment supports and does
   not support. Report applicable comparisons, controls, uncertainty and sensitivity
   checks; point to provided figures, tables, theorems or source passages.
7. **該看哪三張圖** — the three exhibits worth stopping on: number and page, which
   line or cell to look at, and what seeing it changes.
8. **限制與反駁** — the honest weaknesses. Where would a sharp reviewer push?
9. **血緣位置** — how this follows from the prior work listed in the pack, and what
   it enabled afterwards.
10. **三個討論問題** — ranked by how much they would change the reader's
    understanding.

Diagrams are ```mermaid blocks (flowchart LR or TD) with short node text, quoted
when it holds brackets, colons or operators; maths inside a diagram is Unicode,
since Mermaid does not typeset LaTeX. Algorithms go in a ```pseudocode block whose
fence line names it (```pseudocode Algorithm 1 · CIP-MPC), one step per line with
English keywords. Code goes in a block labelled with its language. Never
box-drawing art, TikZ or image syntax.

## Build on what has already been read

The pack's **Lineage** and **Recently read** sections carry, for every paper the
reader has already been through, the one-line conclusion they were given at the
time. Use it.

- When tonight's paper builds on one of them, say so by name and say what changed:
  "你讀過的 Shampoo 用 ... ,這篇把那一步換成 ... ,理由是 ..."
- When it contradicts an earlier conclusion, say that plainly. A reader who was told
  something last week and is being told the opposite tonight needs to know which
  holds and why.
- Do not re-explain background the reader has already had. Reference it in a clause
  and spend the space on what is new.

A deep dive that would read identically whether or not the reader had seen the
prior work has failed at the only thing this queue is for.

## Rules

- Work from the extracted full text in the pack, not from memory of the paper. If
  the pack says the full text is unavailable, say so explicitly and work from the
  abstract, rather than inventing details.
- If a claim in the paper seems wrong or overstated, say so and explain why.
- Never fabricate numbers. Quote figures from the text or omit them.
