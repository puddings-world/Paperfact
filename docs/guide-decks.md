# Guide decks: presenting one paper to people who have not read it

The 簡報 tab writes a deck in one model call. That is fine for notes to oneself.
A **論文導讀** deck — the one shown to colleagues who have not read the paper —
has a harder job: get the audience into the field and the paper as fast as
possible, without spending the hours and tokens the reader spent. A one-shot
draft does that badly in the same ways every time: it summarises the
introduction instead of explaining where the field stood, it lists references
instead of saying which ones the paper cannot stand without, it ends on "future
work" instead of the problems that are still open and why they matter, and it
repeats any claim the analyses got wrong.

`/paper-guide <paper id>` runs the round that fixes those, in Claude Code. It was
first done by hand on Cataract-1K, Cataract-LMM and SASVi (2026-10-14); 34 review
points were checked against the originals, none failed outright but 10 needed
their wording corrected, and the rebuilt guide decks run to 21 slides each.

## What a guide deck must carry

Allocate the slides roughly like this. There is no fixed count: as many as the
content needs, normally 16–22, never more than 24.

| Part | Share | What it answers |
|---|---|---|
| The field when it was written | 20–25% | The lines of work, representative methods and datasets, typical numbers, the need driving it, the assumptions everyone shared |
| The reasoning | 5–10% | The introduction's argument as a chain — premise → observation → tension → gap → this paper — with the links that are asserted rather than supported marked |
| **承先 — the foundation map** | 10–15% | The references grouped by the role they play (data source, method origin, baseline, claim argued against, background), and the 3–5 the paper cannot stand without, each with what it gives this paper |
| Question and contributions | 10% | The research question in one or two sentences; each contribution as claimed, then what the paper demonstrates versus only asserts |
| Data, method, evidence | 25–35% | With the paper's own figures where they carry the point |
| Limits and corrections | 5–10% | From the verification pass, worded as verified |
| **啟後 — open problems** | 10–15% | What later work did with the paper, by line; and the important problems still unsolved after it — each with the later works that ran into it and why it matters |

The 承先 and 啟後 parts come from the 引用 tab's analysis (references with their
purpose and the sentence that cites them; later work with what it did with this
paper; the 研究脈絡), which `export` writes to `citations.md`.

## The round

1. **Analyse** the paper if it is not complete (`/paper-analyze <id>`): PDF, deep
   dive with 前導導讀, 逐節精讀, references, later work, and `cite-links`. A guide
   deck needs a 論文導讀 deck to replace; generate a draft in the 簡報 tab first.
2. **Export** the work folder: `python scripts/guide_deck.py export <id>` writes
   `data/guide-work/<paper>/` — `original.txt` (by page), `analysis.md`,
   `citations.md`, `decks.json`, `sources.json`, and `highlights.json` when the 簡報
   tab's 素材 panel has picked the paper's key sentences (verbatim, checked).
3. **Build** — one subagent per paper, Brief A below → `frontmatter.md` and
   `guide_deck.json`. Then `guide_deck.py apply-guide <id> --dry-run`, read the
   front-matter and 承先/啟後 slides yourself, and `apply-guide <id>`.
4. **Review** — Brief B: the gaps between the new deck and the analyses, and the
   questions an audience will ask → `review_items.md`.
5. **Verify and place** — Brief C: every item checked against the original and put
   in the slide body, the speaker notes or a Q&A card → `review_plan.json`. Then
   `apply-review <id> --dry-run`, read the slide edits, and `apply-review <id>`.
6. **Key sentences and detail** — export again, then Brief D: the paper's own key
   sentences that the deck does not convey clearly, the 承先 and 啟後 parts if they
   are thin, and slide-level detail, each checked against the original →
   `detail_plan.json`; `apply-review <id> --plan detail_plan.json` (dry-run first).
   This pass may insert slides, up to the 24-slide limit.
7. **Carry it out**: rebuild the 帶出門 page if the paper is ticked, and report what
   changed, what was corrected, and how many Q&A cards were added.

Every write keeps the previous deck in its history folder (`guide-preguide-*`,
`*-prereview-*`), restorable from the 簡報 tab.

## Slide limits (checked by the same validator as the canvas)

- title ≤ 70 characters; section ≤ 100; takeaway ≤ 160
- 1–5 bullets, each ≤ 120, together ≤ 420; with a figure at most 3 bullets, ≤ 220
- `sources`: 1–8 IDs from `sources.json`; a slide with a figure lists that figure
- speaker notes ≤ 6000, normally 300–800: the spoken explanation with transitions

---

## Why a key-sentence pass

A deck written from analyses paraphrases, and a paraphrase drops exactly what an
audience needs to judge a paper: the qualifier ("on the 30 annotated videos"),
the condition ("with ground-truth prompts"), the hedge ("we believe"). The authors'
own sentences for the problem, each contribution, the central definitions, the
headline result and the limits they admit are what the deck has to carry, and the
places the deck states a claim more strongly than the paper does are the ones a
reviewer will catch. A short verbatim quote with its page, explained in Chinese,
does both jobs.

## Brief A — read the front matter and the citations, then build the guide

> Files in `data/guide-work/<paper>/`: `original.txt` (the only authority for
> facts), `analysis.md` (AI deep dive and close reading — use it to find things,
> verify against the original), `citations.md` (references with purpose, verdict
> and citing sentence; later work with what it did; the 研究脈絡), `decks.json`,
> `sources.json` (the only source and figure IDs you may cite).
>
> **Part 1 — write `frontmatter.md`** (Traditional Chinese, English technical
> terms, plain Unicode math, never LaTeX; cite the original as「（原文 p.N）」and
> its references by marker; mark anything not in the original as 非原文 or 推論):
> 1. 研究領域當下的進展 — by line of work, the longest section.
> 2. 背景的思考邏輯 — the argument as a chain, each link with its support; flag
>    links that are asserted rather than supported (check what the cited work
>    actually is).
> 3. 承先：地基地圖 — references grouped by role; the 3–5 the paper cannot stand
>    without, each with what it contributes and where the paper uses it.
> 4. 核心研究問題 — one or two sentences, and why it was open.
> 5. 貢獻 — each as claimed; where tested; demonstrated versus asserted.
> 6. 啟後：之後與未解的重要問題 — what later work did, by line; then the open
>    problems that matter, each with the later works that ran into it and the
>    paper's own limits that point to it.
> 7. 讀這篇最快進入狀況的路徑 — the five things a newcomer must understand, in
>    order, with the figures and tables that carry each.
>
> **Part 2 — write `guide_deck.json`** as `{"title": ..., "slides": [...]}`, each
> slide exactly `{"title","section","takeaway","bullets","speaker_notes","sources","figure"}`,
> allocated by the table in docs/guide-decks.md, within the slide limits. One
> idea per slide; the title states the point; the takeaway is what to remember;
> bullets are evidence. Use the paper's figures where they carry the point, and
> describe them only as the caption and text do. Check every limit with a short
> Python script before finishing. Reply with the slide count per part, the slide
> titles, and anything in the original that contradicts the analyses.

## Brief B — find what the deck misses and what the audience will ask

> Read `guide_deck.json` (or the applied deck in `decks.json` after a fresh
> export), `analysis.md`, `citations.md` and the existing Q&A. Write
> `review_items.md` with one running numbered list:
> - 【漏】3–5 points the analyses establish that matter for judging the paper and
>   that the deck (bullets and speaker notes) does not cover;
> - 【問】6–8 questions someone who heard the talk would ask: comparability of
>   numbers, what a result does not show, reproducibility and data access,
>   relation to the paper's foundations and to later work, what it means for
>   follow-up research. Skip questions already in the Q&A.
>
> Each item one or two lines, with where it comes from. Numbers only as printed.

## Brief C — verify every item against the original and place it

> For each item in `review_items.md`: 成立, 部分成立 (say which part), or 不成立,
> with page numbers and short verbatim quotes from `original.txt`; read a table's
> numbers before accepting an interpretation of it. Then place every item that
> holds:
> 1. **Slide body** — only points that change how the audience should judge the
>    paper; prefer rewriting an existing bullet or takeaway; at most 3 edits per
>    deck; give the complete new value of the field, within the slide limits.
> 2. **Speaker notes** — secondary details; text to append (≤ 400 characters).
> 3. **Q&A** — every 【問】 item, and any 【漏】 item not in the body: the question
>    as a user would type it, and a 300–900 character answer from the original
>    with「（原文 p.N）」citations; say plainly where the paper is silent; mark
>    inference as 推論.
>
> Drop items judged 不成立. Write `review_plan.json`:
> `{"items": [{"n", "verdict", "evidence": [{"page", "quote"}], "comment"}],
> "slide_edits": [{"deck": "guide"|"notes", "slide", "field": "title"|"takeaway"|"bullets", "new", "covers", "why"}],
> "speaker_notes": [{"deck", "slide", "append", "covers"}],
> "qa": [{"covers", "question", "answer"}]}`

## Brief D — key sentences, 承先啟後 and detail

> Files in `data/guide-work/<paper>/`: `decks.json` (both decks as they are now),
> `original.txt` (the authority), `highlights.json` (key sentences already picked
> from the original, verbatim, with page and kind — start from these), `citations.md`,
> `analysis.md`, `sources.json`.
>
> 1. **Key sentences.** List the paper's own sentences that carry its argument:
>    the problem it states, each contribution as claimed, the central definitions,
>    the headline results, the limits the authors admit. Start from
>    `highlights.json`; add any it missed. For each, check whether the 論文導讀
>    deck conveys it **with its qualifiers and conditions** — not just the gist.
>    Where it is missing, blurred, or stated more strongly than the paper states
>    it, propose an edit: the point in the slide body when the sentence is the
>    slide's point, otherwise a speaker-note addition with the verbatim quote
>    (≤ 25 words, English as printed, 「（原文 p.N）」) and one line explaining it.
> 2. **承先 and 啟後.** Does the guide deck name the 3–5 references the paper cannot
>    stand without, each with what it gives the paper? Does it name the important
>    problems still open after it, each with the later works that ran into it? If
>    either is thin, insert slides (at most 3 in all, never past 24 slides) built
>    from `citations.md`, with sources from `sources.json`.
> 3. **Detail.** Titles that label instead of stating the point; takeaways that are
>    not the sentence to remember; numbers that differ from the original; slides
>    over the limits or carrying two ideas; the two decks contradicting each other.
>
> Check every proposed change against `original.txt` before proposing it. At most
> 6 slide-body edits and 3 inserted slides in the `guide` deck, at most 3 edits in
> the `notes` deck; speaker-note additions as needed. Write `detail_plan.json` in
> the Brief C shape, with `items` (`n`, `kind`: 關鍵句 / 承先 / 啟後 / 細節,
> `verdict`, `evidence`, `comment`) and, when inserting,
> `"insert_slides": [{"deck": "guide", "after": <slide number as now>, "slide": {...}}]`.
> Slide numbers everywhere refer to the decks as they are in `decks.json`. Reply
> with the edits and inserts in one line each, and the key sentences that were
> missing.
