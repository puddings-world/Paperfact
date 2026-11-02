# v0.5.0 reading UX

Status: in development on `feature/0.5-reading-ux`, 2026-10-31. The owner decided
that items 1–5 ship before v0.5.0. Inspiration and evidence: InkLayer (a handwriting,
PDF and Markdown notebook) and the [UX survey](ux-survey-2026-10.md) of about 25
research-reading apps. This branch owns the files listed per item; shared contracts
(sync DTOs, write capture) stay with the parent integration.

| # | Item | State |
|---|---|---|
| 1 | Layers: show or hide AI marks and your own marks/notes | Page marks done; side lists planned |
| 2 | Export a paper's or list's notes as plain Markdown | CLI and menu done; deep links planned |
| 3 | Library-wide notes search; note-to-note links with backlinks | Done |
| 4 | Drag a PDF onto the window; open PDFs with Paperfact | App side done; installer registration at packaging |
| 5 | Focus reading mode | Done |

## 1. Layers

Toggle 原文 / AI 標記 / 我的標記與筆記 in the reader. The toggle filters the marks on
the page **and** the matching side lists (Zotero's colour filter does both), and is
remembered per paper. AI items are always labelled as AI. Acceptance: hiding AI
leaves the user's highlights and notes intact and visible; the choice survives
reopening the paper; nothing is deleted or rewritten by toggling.

Done for the marks on the page: **顯示標記** in the reader bar hides the AI (green)
or own (yellow) layer, per paper (`ui.layers.<paper id>`). Hidden marks are neither
drawn nor clickable, so erasing a passage only removes what is shown. The status line
keeps counting both layers. Turning the pen on brings the own layer back. Planned:
apply the same filter to the materials and notes side lists.

## 2. Markdown export

One file per paper (or a folder per list): title, citation, the user's notes, kept
AI claims and Q&A, each quote followed by `page N` and a `paperfact://` deep link to
the passage. Re-exporting must not overwrite text the user edited in the exported
file: generated content sits in a marked block that is replaced, the rest is kept
(Obsidian–Zotero users report re-imports clobbering edits). No credentials, receipts
or provider details are written.

Done: `paperfact notes-export --paper ID | --list LIST` (`notes_export`) writes the
own highlights, non-hidden AI highlights (labelled AI, with the reason), and notes
with page numbers. Re-export replaces only the marked block. A file whose markers
were deleted is left alone, and the export goes beside it as `.new.md`. The desktop
entry is 研究資料 → 匯出筆記為 Markdown… for the open list. Planned: `paperfact://`
deep links once the app registers that URL scheme (with the open-with work in item
4). Until then a link would lead nowhere, so none is written.

## 3. Notes search and backlinks

Search across every paper's notes, claim cards and Q&A from the list screen; a
result opens the paper on the exact passage and briefly flashes it (jumping only to
the page is a known Logseq complaint). `[[paper title]]` in a note links to that
paper; each paper shows the notes that link to it.

Done (`notes_search`, `NotesSearchDialog`): Ctrl+Shift+F, or 研究資料 → 搜尋全部筆記,
searches notes and own highlights with LIKE (all words must appear; `%` and `_`
are matched literally). LIKE rather than FTS, because a tokenizer can't split
Chinese. A result opens the paper and selects the exact passage, retrying until the
PDF has loaded, then falls back to the page. `[[title]]` resolves on the whole title
(case and spacing ignored) only when one paper matches. Ambiguous or unknown titles
stay plain text. The notes tab lists backlinks from other papers.

## 4. PDF in, from the desktop

Done: dropping PDFs on the window opens **加入清單** per file for the open list, with
the arXiv id, DOI and title read from the first page (`pdf_identity`). The person
confirms the guess; the paper is then read from that file (`list-add --pdf`). A
paper already in the list keeps its PDF, so anchored notes do not move. With the
main queue showing, the window asks for a list. Of seven real PDFs from the corpus,
six were named correctly (small-caps titles included); the seventh, a one-page
supplement holding only a table, could not be, and the dialog leaves it to the person.

Done on the app side: `paperfact app <file.pdf>` opens the same dialog. A second
launch forwards the path to the running window (`pdf:` on the single-instance
socket). macOS `FileOpen` events are handled too. Still to do, at packaging
(release-gated): declare the association. On Windows that means an Inno Setup
`OpenWithProgids` entry passing `"%1"`. On macOS it means `CFBundleDocumentTypes`
for `com.adobe.pdf` in the bundle's Info.plist. A manual check on both systems
follows.

## 5. Focus reading mode

A full-window reader with side panels collapsed, optional dimming of everything but
the current paragraph (Readwise) and a reading ruler (Sioyek, Skim). Esc leaves it.
No animation when the system asks for reduced motion.

Done: **專注** in the PDF bar, or the platform full-screen key, hides the toolbar,
headers, PDF bar and side panels and goes full screen (`focus_mode.FocusMode`).
Esc, the same key again, or leaving the reader restores exactly what was visible,
including a collapsed toolbar. A two-second hint names the way out. Nothing
animates. **R** toggles a reading ruler: everything except a 72 px band around the
pointer is dimmed (`SelectionOverlay.set_ruler`), and the choice is remembered in
`ui.focus_ruler`. It covers the paragraph-dimming idea without needing paragraph
detection.

## Resource budget

From v0.5 the reader must not compete with the person's other work for CPU or
memory. Nothing runs unprompted or unbounded in the background: AI jobs start only
on an explicit action, run one at a time by default, are visible and cancellable,
and never retry in a loop. Prefer on-demand work (search on a debounced keystroke,
export on a click) over watchers, indexers and polling, and local rendering over
extra model calls. A design note for any new background behaviour states its cost.

## Next for v0.5 (from the second survey)

The owner picked the top three of the second survey:

1. **Import report card and fix-up queue**: counts of new, already present and
   unmatched rows that filter the list; candidate cards for unmatched rows with
   "attach to an existing paper"; built on propose/commit.
2. **Job tray for background AI**: every analysis, slides and deep-dive job in one
   status-bar tray with per-item state, cancel, retry failed only, and a failure
   reason with one next step. It is where the resource budget above is enforced.
   Step 1 done (`activity.JobPanel`, see [work-progress](work-progress.md)): the
   panel, 停止 for deep analysis, list jobs and surveys, failure cause plus one next
   step, and a notice poll that sleeps while idle. Step 3 done: a partial list
   analysis offers 重試未完成的, which reruns with `--retry` so only failed steps
   are tried (finished papers have nothing left). List and selection analysis now
   work on one paper at a time; 分析排程 can raise it to 3 (`ui.analysis_parallel`).
   Step 2 done: long AI work (deep and background analysis, list analysis, surveys)
   runs one at a time; the rest waits as 排隊中 with its place, starts when the
   previous one ends and can leave the line without starting anything. A question or
   translation asked while reading does not wait (one per window), so at most one
   long job plus one question run at once. Idle analysis skips rather than queues.
   Still to do: an "unfinished last time" notice after a restart.
3. **Coloured status tags on keys 1–9**: up to nine tags (e.g. 精讀 / 略讀 / 待讀 /
   引用) toggled on a multi-selection in any list and shown as a colour chip.

## Candidates from the survey

Ranked in the survey; none is committed to v0.5 yet: quote-verified AI sentences
everywhere, reference hover cards, AI-highlight density and facet labels, a sample
paper with honest empty states, reading position that never moves backwards with
"continue reading", a command palette, citation intent on 承先/啟後, daily review
of kept claims, prior/derivative works for a list, and region-select "explain this".

A [second survey](ux-survey-2026-10b.md) covers library scale, AI chat scope,
serverless sharing, accessibility/CJK reading, importing and background jobs. Its
top picks: an import report card with a fix-up queue, a job tray for background AI,
coloured status tags on keys 1–9, ask-AI scope chips, a dark theme that leaves
figures alone, a duplicates merge that keeps notes, saved "next to read" views, and
annotated-PDF export.
