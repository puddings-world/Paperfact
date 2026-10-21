# Nightly cloud routine

The prompt below is what the scheduled cloud agent receives every night. It lives here
so it can be edited and re-applied with `RemoteTrigger action:"update"` rather than
rewritten from memory.

The agent runs in Anthropic's cloud with no access to the machine holding `papers.db`,
so everything it needs comes from the reader artifact's store and from public paper
URLs:

| Document | Written by | Contents |
|---|---|---|
| `queue/upcoming` | `paper-daily sync-queue` | the next N papers in reading order |
| `state/cursor` | the routine | how far it has got |
| `papers/<paper id>` | the routine, and `paper-daily prefetch` | `fullText`, `deepDive` |

Writing the deep dive to `papers/<paper id>` — the same document the reader already
renders — is what makes the nightly result show up in the reading queue rather than in
a separate per-date pile.

---

You are writing tonight's paper deep dive for a reader working backwards through ten
years of ICLR / ICML / NeurIPS, newest first, who wants the principle behind each
paper rather than a summary of its results.

Artifact: https://claude.ai/code/artifact/bc9c4713-41bb-4f11-9095-df5fb01c66c6

1. Read `state/cursor` (`Artifact` tool, `action:"read_db"`, `db_op:"get"`,
   `collection:"state"`, `doc_id:"cursor"`). Missing means index 0.
2. Read `queue/upcoming` (`db_op:"get"`, `collection:"queue"`, `doc_id:"upcoming"`)
   and take `papers[index]`. If the index is past the end, write nothing, advance
   nothing, and reply saying the synced queue is exhausted and
   `paper-daily sync-queue` needs re-running.
3. Read `papers/<the paper's id>`. If it already has a `fullText`, use it. Otherwise
   fetch the paper: `curl -sL "<pdfUrl>" -o paper.pdf`, or
   `https://arxiv.org/pdf/<arxivId>` when there is no `pdfUrl`. Extract with
   `pdftotext` if present, else `pip install --quiet pymupdf` and a short script.
   If extraction fails, work from `abstract` and say so plainly in the deep dive --
   never invent content you could not read.
4. Write the deep dive in Traditional Chinese, keeping technical terms, paper titles
   and author names in English. Maths in LaTeX (`$...$` inline, `$$` blocks),
   diagrams as ```mermaid flowcharts, algorithms as ```pseudocode blocks: the
   reader typesets all three.

   Use exactly these sections:

   ## 一句話結論
   ## 前導導讀 — the longest section: a guided reading of the introduction, background
      and related work in the paper's order (state of the field, the argument
      paragraph by paragraph, the map of prior work, the claimed contributions
      against the experiments that test them, doubts to carry forward)
   ## 核心洞見 — the single idea the paper turns on
   ## 方法 — the mechanism, with key equations, and why each piece is there
   ## 證據 — what the experiments show, and as importantly what they do not
   ## 限制與反駁 — where a sharp reviewer would push
   ## 血緣位置 — what it follows from and what it enabled
   ## 三個討論問題 — ranked by how much answering them would change understanding

   Quote figures only from text you actually read. If a claim looks overstated, say so.

5. Write it back: `action:"write_db"`, `db_op:"update"`, `collection:"papers"`,
   `doc_id:"<the paper's id>"`, data `{"deepDive": "...", "fullText": "...",
   "writtenAt": "<ISO timestamp>"}`. Use `update`, not `set`, so an already-pushed
   `fullText` is not lost. Truncate `fullText` to 100000 characters.
6. Advance the cursor: `db_op:"set"`, `collection:"state"`, `doc_id:"cursor"`,
   data `{"index": <index + 1>, "lastPaperId": "<id>", "updatedAt": "<ISO>"}`.
7. Reply with the paper's title, venue and year, and one sentence on what it
   established.
