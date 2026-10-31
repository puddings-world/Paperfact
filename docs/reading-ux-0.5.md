# v0.5.0 reading UX

Status: in development on `feature/0.5-reading-ux`, 2026-10-31. The owner decided
that items 1–5 ship before v0.5.0. Inspiration and evidence: InkLayer (a handwriting,
PDF and Markdown notebook) and the [UX survey](ux-survey-2026-10.md) of about 25
research-reading apps. This branch owns the files listed per item; shared contracts
(sync DTOs, write capture) stay with the parent integration.

| # | Item | State |
|---|---|---|
| 1 | Layers: show or hide AI marks and your own marks/notes | Planned |
| 2 | Export a paper's or list's notes as plain Markdown | Planned |
| 3 | Library-wide notes search; note-to-note links with backlinks | Planned |
| 4 | Drag a PDF onto the window; open PDFs with Paperfact | Drag done; open-with planned |
| 5 | Focus reading mode | Planned |

## 1. Layers

Toggle 原文 / AI 標記 / 我的標記與筆記 in the reader. The toggle filters the marks on
the page **and** the matching side lists (Zotero's colour filter does both), and is
remembered per paper. AI items are always labelled as AI. Acceptance: hiding AI
leaves the user's highlights and notes intact and visible; the choice survives
reopening the paper; nothing is deleted or rewritten by toggling.

## 2. Markdown export

One file per paper (or a folder per list): title, citation, the user's notes, kept
AI claims and Q&A, each quote followed by `page N` and a `paperfact://` deep link to
the passage. Re-exporting must not overwrite text the user edited in the exported
file: generated content sits in a marked block that is replaced, the rest is kept
(Obsidian–Zotero users report re-imports clobbering edits). No credentials, receipts
or provider details are written.

## 3. Notes search and backlinks

Search across every paper's notes, claim cards and Q&A from the list screen; a
result opens the paper on the exact passage and briefly flashes it (jumping only to
the page is a known Logseq complaint). `[[paper title]]` in a note links to that
paper; each paper shows the notes that link to it.

## 4. PDF in, from the desktop

Done: dropping PDFs on the window opens **加入清單** per file for the open list, with
the arXiv id, DOI and title read from the first page (`pdf_identity`). The person
confirms the guess; the paper is then read from that file (`list-add --pdf`). A
paper already in the list keeps its PDF, so anchored notes do not move. With the
main queue showing, the window asks for a list. Of seven real PDFs from the corpus,
six were named correctly (small-caps titles included); the seventh, a one-page
supplement holding only a table, could not be, and the dialog leaves it to the person.

Planned: register Paperfact as an "open with" handler for `.pdf` on Windows and macOS
and forward the file to the running instance (the app is single-instance through
`QLocalServer`), landing in the same dialog.

## 5. Focus reading mode

A full-window reader with side panels collapsed, optional dimming of everything but
the current paragraph (Readwise) and a reading ruler (Sioyek, Skim). Esc leaves it.
No animation when the system asks for reduced motion.

## Candidates from the survey

Ranked in the survey; none is committed to v0.5 yet: quote-verified AI sentences
everywhere, reference hover cards, AI-highlight density and facet labels, a sample
paper with honest empty states, reading position that never moves backwards with
"continue reading", a command palette, citation intent on 承先/啟後, daily review
of kept claims, prior/derivative works for a list, and region-select "explain this".
