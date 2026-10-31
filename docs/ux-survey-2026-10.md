# Paperfact UX survey: patterns from research-reading and AI-paper apps (2026-10-31)

Scope: concrete UX patterns from ~25 apps, mapped onto Paperfact screens (Library/lists, Reader, Notes panel, Analysis, Slides, Pocket reader, mobile PWA). Effort: S = days, M = 1–3 weeks, L = more than a month.

Confidence: **[official]** means the source is the vendor's site, docs, changelog or blog. **[3rd-party]** means a review, directory, library guide or forum, so treat it with caution. When I could not confirm something, the entry says so.

---

## 1. Trusting and verifying AI output against the source

| # | App | What the user sees / does | Why it works | Paperfact mapping |
|---|---|---|---|---|
| 1.1 | **NotebookLM** [official] | Every answer has numbered inline citations. Hovering one shows the full quoted text. Clicking it auto-scrolls the source viewer to that passage. | Checking a claim takes one hover and needs no context switch. The quote is the evidence, not a page number. | Reader + Analysis + 問 AI notes. Extend the core-claim "link back to sentence" to **every** AI sentence (explanation, close reading, Q&A, slide bullets): hover shows the quote, click jumps and flashes it. **M** |
| 1.2 | **Elicit** [official] | "Supports all AI-generated claims with sentence-level citations from the underlying sources." Per-cell citations in extraction tables. A 3rd-party review notes that a citation being present does not prove the claim. | Per-claim granularity rather than per-answer. | Same as 1.1. Also add an **automatic quote check**: verify that each cited quote string actually occurs in the PDF text (exact or normalized match). If it doesn't, show an "unverified" badge instead of a link. **S–M** |
| 1.3 | **Semantic Reader – Skimming highlights** [official] | AI highlights faceted as Goal / Method / Result, with colored **margin labels**. A side panel toggles them on or off and sets the **number** of highlights and their **opacity**. AI2's design case study found users wanted density control, mixed content types, and labels that don't depend on color alone. Parsing errors made them limit rollout. | Lets the reader decide how much AI is shown, and each highlight's role is legible without a legend. | Reader, AI highlight layer (complements the decided layer toggle). Add a facet per highlight (e.g. claim/method/result/limitation), a density slider (top-N by AI score), an opacity slider, and margin chips that open the "reason". **S–M** |
| 1.4 | **Semantic Reader – Definitions on demand** [official] | Dotted-underlined terms. Clicking one opens a popover with a definition *based on how the term is used in this paper*, plus a note that it was AI-generated. | Explicit provenance labelling on every AI popover. | Reader: selection → "define in this paper". Label every AI popover "AI · from this paper". **S** |
| 1.5 | **Readwise Reader – Ghostreader / Quick Lookup** [official, Aug 2026 update] | Global chat over the library returns cited answers that link to source passages. Mobile per-document chat knows the reading position. Quick Lookup offers a dictionary definition, a term lookup that synthesises how the author uses the word across the document, and translation. | AI is position-aware, so the user doesn't have to paste context. | 問 AI: pre-fill context from the current page or selection. Library-wide Q&A with passage links is a natural later step after the decided notes search. **M** |
| 1.6 | **SciSpace Chat with PDF** [3rd-party] | Every answer comes with a citation and its location. An "Explain math and table" mode where you box-select a formula, table or figure. | Equations and tables are where readers get stuck. A region-select is more precise than text selection. | Reader: area-select → 問 AI with a cropped image plus nearby text. Save the result as a Q&A note anchored to that region. **M** (button name unverified) |
| 1.7 | **scite Smart Citations** [3rd-party] | Each citing statement is labelled supporting / contrasting / mentioning, with the sentence shown. The vendor's self-reported accuracy for supporting (64%) and contrasting (59%) is much lower than for mentioning (97%). | Shows the citing sentence, not just a count. The honest lesson: label confidence varies by class. | 承先/啟後 cards: always show the citing sentence and mark AI-inferred stance as tentative. **M** |

## 2. Moving between reading and notes

| # | App | Pattern | Why | Paperfact mapping |
|---|---|---|---|---|
| 2.1 | **Zotero 7–10** [official] | Drag an annotation from the PDF or the sidebar into a note, or right-click → "Add to Note". Drag selected text into a note to get a quote with a citation. A citation in a note → "Show on Page" / "Show Item". Zotero 8 adds **note tabs** (full window, wide margins). | Notes and the source keep a bidirectional link, and a quote carries its citation automatically. | Notes panel: drag an AI highlight, core claim or own highlight into a text note, which inserts a quote block with a page link. Allow "open note in its own tab/window". **S–M** |
| 2.2 | **MarginNote 4** [official] | One card is stored once and appears as a highlight in the document, a node in the mind map, and a flashcard in review. "Extended Note": long-press the PDF to open a free-writing space shown inline, in the margin, or collapsed. "Title Link" auto-highlights concepts from past notes in new documents. | One object, many views, so nothing gets duplicated. | Data model: make highlight, core-claim card and review item the same record. Show margin notes inline next to the anchor (not only in the side panel). "Title link" ≈ highlight terms that already have notes in other papers. **M** |
| 2.3 | **Heptabase** [3rd-party + official roadmap] | PDF highlights become cards you can place on whiteboards. A **pinpoint button** jumps from a highlight back to its spot in the PDF. Mobile PDF highlighting is still "in progress" on the roadmap (Mar 2026). | Return-to-source is always one click. | Every note quote and backlink gets a pinpoint icon. **S** |
| 2.4 | **Logseq** [forum] | PDF highlight → block reference. Long-standing complaint: clicking it "only jumps to the page", which isn't enough for dense papers. Users ask for stronger contrast on the target area. | Anti-pattern to avoid. | Jump to the exact rect and briefly flash it (also applies to the decided backlinks). **S** |
| 2.5 | **Sioyek** [official docs] | **Portals**: press `p` at a source, navigate, press `p` again to link a paragraph to a figure (even in another document). A helper window (often on a second monitor) shows the linked destination while you read near the source. | Keeps a figure or equation visible while reading the text that discusses it. | Reader: "pin figure" side pane. Auto-suggest a pin when the text says "Fig. 3"/"Eq. 2". **M** |
| 2.6 | **Skim** [official + 2007 review] | **Snapshots**: floating windows that keep a region (a table) visible while you scroll. Anchored notes. | Same as above, simpler. | Same as 2.5, a cheaper first step. **S** |
| 2.7 | **LiquidText** [official] | Pull excerpts into a side workspace. "Pinch" collapses a document to compare distant pages. Connected notes: one tap shows the original context. The official site describes no AI features. | Spatial comparison of far-apart passages. | Partly covered by split view. The full canvas is skipped (see the skip list). |

## 3. Citation-context popups (hover a reference → cited paper)

| # | App | Pattern | Why | Paperfact mapping |
|---|---|---|---|---|
| 3.1 | **Semantic Reader** [official] | Hover or click an inline citation to open a card: title, authors, **TLDR**, metrics, Save to Library. "Personalized in-line citations" are colour-coded by their relation to your library ("Cited by a paper saved to your library"). Desktop only. | You learn what [23] is without leaving the page, and the library-aware colour tells you whether you already know it. | Reader: hover `[n]` / "Author (Year)" → card with title/year/venue/abstract-TLDR, **"in your list X" badge**, "Add to list", "Open". Reuse the 承先 data, which already resolves references. **M–L** (needs PDF reference parsing → metadata resolution) |
| 3.2 | **Sioyek** [official docs] | Right-click a reference, "Figure 2.19" or a table to get a scrollable popup preview, **even when the PDF has no links**. `l` previews the first reference on the ruler line. Smart Jump goes straight to it. | Works on any PDF. Also covers figures and equations, not just bibliography entries. | Same hover card for intra-document refs (Fig./Table/Eq./Section) showing a cropped preview. **M** |
| 3.3 | **Semantic Scholar paper page** [official FAQ/tutorial] | Citation intent labels: "Cites Background / Methods / Results". **Highly influential citation** badge, from a model using citation count + context. The FAQ admits coverage gaps (needs full text). | Distinguishes a passing mention from real building-on. | 承先/啟後: tag each edge with intent + influential flag. Sort 啟後 by "most influenced". Show "coverage incomplete" honestly. **M** |

## 4. Visualising paper relationships

| # | App | Pattern | Why | Paperfact mapping |
|---|---|---|---|---|
| 4.1 | **Connected Papers** [3rd-party guides] | Graph built from **similarity** (co-citation + bibliographic coupling), not direct citations. Node size = citation count, colour = year (guides disagree on direction, so check the legend). "**Prior works**" (most cited by graph papers) and "**Derivative works**" (cite many graph papers) lists. | One glance shows foundational vs. recent work. The prior/derivative lists map exactly onto 承先/啟後. | Paper → 承先/啟後 tab: add a graph toggle. List level: "Prior works / Derivative works of this list" as a discovery panel. **L** for the graph, **M** for the lists alone |
| 4.2 | **Litmaps** [3rd-party] | Multi-seed maps (x = year, y = citations). Seeds come from a DOI, title or Zotero. **Email alerts** for new papers related to the map. | Multi-seed beats single-seed for a real reading list. Alerts turn a map into a monitor. | Reading list → "map this list". Feeds the newest-first ML queue ("new papers citing ≥2 of your list"). **L** |
| 4.3 | **ResearchRabbit** (2025 revamp) [3rd-party] | Iterative "rabbit hole" chaining. A citation map with customisable X/Y axes. Reviewers say the graph becomes overwhelming beyond ~50 papers and needs filtering. | Lesson: graphs need filters, or default to a list. | Default to lists and offer the graph as an option, with filters (in-list only, year range). |
| 4.4 | **MarginNote / NotebookLM / Recall** | Auto mind maps / concept graphs from sources. | Low value for a single paper per our scope. See the skip list. | — |

## 5. Onboarding, first run, empty states

| # | App | Pattern | Why | Paperfact mapping |
|---|---|---|---|---|
| 5.1 | **Readwise Reader** [official blog] | The first-run guide is itself a document in the reader. It teaches keyboard shortcuts, the browser extension, mobile apps and Library vs. Feed **by using them**. It recommends installing the mobile app early. | You learn the product inside the product. | Ship a **bundled sample paper** (open-access) with pre-computed AI highlights, a core claim, a Q&A note and 承先/啟後, so the value is visible **before** the user connects Claude/Codex/API. The guide doc doubles as a shortcut primer. **S–M** |
| 5.2 | **Semantic Reader** [official] | Personalised citations "require at least one paper in your library", so the feature explains its own precondition. | Empty states name the precondition. | Every empty panel says what fills it and offers the one button that does: "No AI highlights yet → Analyze (uses your Claude login)"; "No lists → Import .bib / drop PDFs". **S** |
| 5.3 | (Paperfact-specific; general practice, not from one app) | First-run checklist: connect AI → import list → open a paper → make a note → sync phone. | Bring-your-own-AI is the biggest drop-off risk. | Library home. **S** |

## 6. Keyboard workflows

| # | App | Pattern | Why | Paperfact mapping |
|---|---|---|---|---|
| 6.1 | **Readwise Reader** [official blog + FAQ] | Arrow keys move a **paragraph focus** indicator. `h` highlights the focused paragraph, `n` highlights and starts a note, `t` tags a highlight, `z` is multi-step undo, `[`/`]` toggle side panels. **Cmd/Ctrl+K command palette**, `?` quick reference, shortcuts shown on hover. The FAQ admits keyboard highlighting is paragraph-level only. | Highlighting with no mouse is possible because the unit is the paragraph. | Reader: paragraph focus + `h`/`n`/`a` (ask AI about the paragraph). Command palette over every action. `?` overlay. **M** |
| 6.2 | **Sioyek** [official docs] | Every key is a named command, rebindable. `:` opens a searchable command list showing current keys. `m`+letter marks (lowercase per-doc, uppercase global, persistent). `gh`/`gH` list highlights in this/all docs. `O` opens a searchable recent-docs list. **Ruler**: `j`/`k` move a line highlight. | Power users read without the mouse. Marks are a cheap "bookmark here". | Add `j`/`k` = next/previous AI highlight or own highlight, plus marks. Don't ship a config-file keymap. **S–M** |
| 6.3 | **Zotero 8** [official] | Ctrl/Cmd+; opens the tabs menu and you type to filter and switch. | Fast switching between many open papers. | Quick switcher over open papers and lists. **S** |

## 7. Reading progress and resume

| # | App | Pattern | Why | Paperfact mapping |
|---|---|---|---|---|
| 7.1 | **Zotero** [forum, staff replies] | Returns to the last page and syncs that position across devices. **Pitfall**: position sync "doesn't support conflict resolution and just chooses the server side", so an older position can overwrite a newer one. An already-open document won't move to the new position. | A direct lesson for v0.5 sync. | Sync: store `(position, updated_at, device)`. Newest wins. On open, if another device is further along, show "Continue from p. 12 (phone, 2 h ago)?" instead of silently jumping. **S–M** |
| 7.2 | **Zotero 9** [official] | "**Recently Read**" collection of recently opened attachments. | Resume is a list, not a search. | Library sidebar: Recently read / Continue reading. **S** |
| 7.3 | **Readwise Reader** [official Aug 2026] | EPUB progress shown as percent, page, **time left in chapter or book**, or hidden. Focus mode greys out unfocused paragraphs. Swipe to the next or previous document on mobile. | Lets readers choose how much progress info they see. | List rows: a thin progress bar + "~12 min left". PWA: swipe to the next paper in the list. **S** |
| 7.4 | **Zotero 9/10 + iOS Read Aloud** [official] | Read Aloud skips citations, headers, tables and equations, and highlights by sentence. An "Annotate Sentence" button. Position remembered. | Mobile and commute reading. | Possible later for the PWA (Web Speech API). Not a top-10 pick. **M** |

## 8. Review / spaced repetition of highlights

| # | App | Pattern | Why | Paperfact mapping |
|---|---|---|---|---|
| 8.1 | **Readwise Daily Review** [official] | A short daily set of your highlights with feedback buttons, a completion screen, frequency tuning, and "Themed Review" (AI picks highlights on a theme). | Small, finishable daily ritual. | PWA home: "Today: 5 cards" drawn from own highlights + AI core claims of papers read. Each card links back to its sentence. **M** |
| 8.2 | **MarginNote 4** [official site + App Store] | Review uses FSRS (per the App Store listing; the features page doesn't name an algorithm). **Document Recall** hides highlights / cloze-masks text in the book itself. Mind-map recall progressively collapses. | Reviewing in context, not as detached flashcards. | "Recall mode" in the Reader: mask core-claim sentences, and the user reveals them. Reuses the decided layer toggles. **M** |
| 8.3 | **Recall / NotebookLM / Scholarcy** [3rd-party] | Auto-generated quizzes and flashcards from content (Scholarcy "flashcard" summary with key findings). | Low effort, but generic. | Only generate from **user-kept** items (claims the user starred), so the deck doesn't fill with AI noise. |

## 9. Mobile reading

| # | App | Pattern | Why | Paperfact mapping |
|---|---|---|---|---|
| 9.1 | **Readwise Reader mobile** [official] | Opt-in bottom toolbar, swipe between documents, short and long swipes in lists for triage, tap a highlight in the notebook sidebar to scroll to it. Library: Inbox / Later / Archive. | One-hand triage. | PWA list: swipe right = mark read, swipe left = later. Bottom bar with notes, AI layer and next paper. **S–M** |
| 9.2 | **Zotero 10 Reading Mode for PDFs** [official] | Reflowable PDF view with adjustable font, size and line spacing. Highlights and notes made in it also show in the regular PDF view. Ink and image annotations are PDF-view only. | PDFs on a phone are unreadable without reflow. Annotations stay shared across both views. | PWA: a reflow view from the extracted text, with anchors kept so text notes map to PDF positions. Overlaps the decided focus mode on desktop. **L** |
| 9.3 | **Heptabase** [official roadmap] | Mobile PDF highlight still "in progress". | Even mature apps defer mobile annotation. | Our v0.5 mobile scope (read + text notes) is sensible. |

## 10. How competitors already do the five decided v0.5 items well

- **Layer toggles**: Semantic Reader exposes a density slider + opacity + on/off per facet. Zotero's colour filter applies to **both** the sidebar list and the marks on the page (forum-confirmed). MarginNote "Recall" reuses hiding for study. → Let the toggle also filter the sidebar, and remember it per paper.
- **Markdown export**: Highlights (macOS) writes a **sidecar .md next to the PDF**, updated as you annotate (forum report), so Hazel/Obsidian pick it up. Obsidian Zotero Integration links each quote back via `zotero://open-pdf/...?page=N&annotation=ID`. Its users struggle with **re-import overwriting their own edits** (`persist` blocks are flaky). → Include a deep link per quote (`paperfact://open?paper=..&page=..&anchor=..`). Make re-export idempotent: keep user-edited sections, or write to a separate generated block.
- **Notes search + backlinks**: Zotero 8 makes annotations first-class search results (searchable, taggable, appear under the item, a note can be built from results). Heptabase has a pinpoint back-jump. Logseq shows the pitfall of jumping to the page instead of the exact area.
- **Drag-drop / open-with**: Readwise accepts drag-drop of Markdown, EPUB and PDF on web and the share-sheet on mobile. → In the PWA, use the Web Share Target to "share to Paperfact".
- **Focus mode**: Readwise greys out unfocused paragraphs. The Sioyek ruler and Skim reading bar highlight the current line. Zotero 8 Appearance panel themes (Dark/Snow/Sepia/custom, saved per document) darken images instead of inverting them.

---

## Ranked top-10 recommendations (excluding the decided v0.5 items)

1. **Quote-verified AI everywhere** (NotebookLM hover-quote / click-to-scroll + Elicit sentence-level). Every AI sentence in analysis, Q&A and slides carries a citation. Hover shows the quote, click jumps and flashes it, and an automatic string-match marks any citation whose quote isn't found in the PDF as "unverified". *Reader + Analysis + Notes.* **M**. This is the core trust feature for an AI reader.
2. **Reference hover cards in the Reader** (Semantic Reader citation cards + Sioyek reference/figure preview). Hover `[12]` → title/year/TLDR, an "in your list" badge, Add to list. Hover "Fig. 3"/"Eq. 2" → a cropped preview. *Reader.* **M–L**.
3. **AI-highlight density, facets and margin labels** (Semantic Reader skimming). Facet chips such as claim/method/result/limitation, a top-N slider, opacity, labels that don't rely on colour alone, and the reason on click. *Reader.* **S–M**.
4. **Sample paper + honest empty states** (Readwise in-product onboarding, S2 precondition messages). A preloaded open-access paper with precomputed AI output, so the value shows before the AI login. Every empty panel offers its one next action. *First run, Library.* **S–M**.
5. **Reading position sync that never goes backwards + "Continue reading"** (lesson from Zotero's server-wins bug; Zotero 9 Recently Read; Readwise time-left). Newest-timestamp wins, a "continue from p. N on phone?" prompt, progress bars and time-left on list rows. *Sync, Library, PWA.* **S–M**. Directly relevant to v0.5.
6. **Command palette + paragraph-focus keyboard model** (Readwise Ctrl+K, `?`, `h`/`n`; Sioyek `j`/`k`, marks, `:`; Zotero Ctrl+; tab switcher). Add `j`/`k` to step through AI/own highlights and `a` to ask AI about the focused paragraph. *Global + Reader.* **M**.
7. **Citation intent and influence on 承先/啟後** (Semantic Scholar background/method/result + influential badge; scite citing-sentence display). Show the citing sentence on every edge, sort 啟後 by influence, and flag AI-inferred stance as tentative. *Analysis.* **M**.
8. **Daily review of kept highlights and core claims** (Readwise Daily Review; MarginNote in-document recall). Use only user-starred items. Each card links back to its sentence. Ideal for the mobile PWA home. *PWA + Reader recall mode.* **M**.
9. **Prior / Derivative works panel for a list → optional graph** (Connected Papers lists; Litmaps multi-seed + alerts). Start with two ranked lists computed over the whole reading list, and feed "new papers citing ≥2 of your list" into the ML queue. The graph comes later, with filters (ResearchRabbit's 50-paper overload lesson). *Library/list view.* **M** (lists), **L** (graph).
10. **Region-select "explain this" + pinned figure pane** (SciSpace math/table explain; Sioyek portals; Skim snapshots). Box-select an equation, table or figure → 問 AI with the crop, saved as an anchored Q&A note. "Pin" keeps a figure visible while reading the text about it. *Reader.* **M**.

Honourable mentions: drag highlights/claims into text notes as citation-carrying quote blocks (Zotero, **S**). In-paper term definitions labelled "AI · from this paper" (S2/Readwise, **S**). PWA swipe triage + Web Share Target (Readwise, **S–M**). Read-aloud that skips citations and equations (Zotero 9/10, **M**).

## Skip list (doesn't fit a desktop AI research reader, or not now)

- **Infinite canvas / whiteboard workspaces** (LiquidText workspace, Heptabase whiteboards, MarginNote concept canvas): an L+ effort, pen- and iPad-centric, and it competes with Obsidian/Heptabase rather than with readers. Backlinks + Markdown export let users take notes there.
- **Handwriting / ink-first annotation** (InkLayer, LiquidText, MarginNote): desktop mouse users don't benefit. Keep "handwritten" as typed text notes.
- **Auto-generated mind maps / concept graphs per paper** (NotebookLM, MarginNote AI, Heptabase AI action, Recall): impressive to look at, but hard to verify against sentences. That conflicts with recommendation #1.
- **Consensus-style yes/no meter across studies**: a search-engine feature. Reviewers warn it misleads when study quality varies, and Paperfact doesn't do corpus search.
- **Elicit-scale systematic-review tables (1,000 papers, 20k data points)**: a different product (SLR automation). Expensive on a bring-your-own-AI quota.
- **Public comment threads on papers** (alphaXiv): needs a moderated social backend. The read-only pocket pages already cover sharing.
- **Agentic library reorganisation** (Readwise Ghostreader moving and tagging documents itself): risky without an approval queue. If added, use propose → confirm (like the paperfact MCP's propose/commit).
- **Streaks / gamified stats**: optional at most. Academic reading isn't a habit app.
- **Config-file keymaps à la Sioyek**: offer the palette with shown shortcuts instead. Rebinding UI is low priority.
- **Audio overviews / podcast generation** (NotebookLM): costly on a user's own quota, and it moves away from source-grounded reading.

## Sources

- Zotero 7: https://www.zotero.org/blog/zotero-7/ · Zotero 8 (2026-01-22): https://www.zotero.org/blog/zotero-8/ · Blog index (Zotero 9 2026-04-10, Zotero 10 2026-08-17, iOS Read Aloud 2026-10-05): https://www.zotero.org/blog/ · PDF reader docs: https://www.zotero.org/support/pdf_reader · Colour filter: https://forums.zotero.org/discussion/comment/493649/ · Reading position sync: https://forums.zotero.org/discussion/124744/sync-reading-position
- Readwise Reader update Aug 2026: https://readwise.io/reader/update-aug2026 · Getting started: https://blog.readwise.io/p/bf87944f-b0fe-4f08-a461-f75ab8aded6a/ · Highlights FAQ: https://docs.readwise.io/reader/docs/faqs/highlights-tags-notes
- Semantic Reader: https://www.semanticscholar.org/product/semantic-reader · Skimming FAQ: https://www.semanticscholar.org/faq/what-are-skimming-highlights · AI2 design case study: https://allenai.org/blog/case-study-iterative-design-for-skimming-support-5563dbe0899e · Influential citations: https://www.semanticscholar.org/faq/influential-citations · Release notes: https://semanticscholar.org/product/release-notes
- Sioyek docs: https://sioyek-documentation.readthedocs.io/en/latest/usage.html · commands: https://sioyek-documentation.readthedocs.io/en/latest/commands.html
- Skim: https://skim-app.sourceforge.io/ · https://www.macworld.com/article/185084/skim.html
- LiquidText: https://www.liquidtext.net/ · App Store: https://apps.apple.com/ca/app/id922765270
- MarginNote 4: https://www.marginnote.com/en/features/ · https://apps.apple.com/us/app/marginnote-4-ai-notes-mindmap/id1531657269
- Highlights (macOS): https://apps.apple.com/cn/app/highlights-pdf-reader-notes/id1498912833?l=en · sidecar workflow: https://talk.macpowerusers.com/t/pdf-annotation-workflow-using-highlights-app-and-hazel/34333
- PDF Expert: https://support.readdle.com/pdfexpert/reading-pdfs/ai-chat-with-pdf · https://support.readdle.com/pdfexpert/annotate-pdfs/view-and-export-annotation-summary
- Elicit: https://elicit.com/ · caveat review: https://tooliverse.ai/tools/elicit
- SciSpace: https://updf.com/chatgpt/scispace/ (3rd-party) · https://chrome.google.com/webstore/detail/scispace-copilot/cipccbpjpemcnijhjcdjmkjhmhniiick
- Consensus: https://blogs.stthomas.edu/libraries/2025/09/05/introducing-consensus-an-ai-powered-literature-review-tool/ · https://www.toolsforhumans.ai/ai-tools/consensus
- Scholarcy: https://help.scholarcy.com/guide/supercharge-your-reading · https://www.scholarcy.com/article-summarizer
- scite: https://library.hkust.edu.hk/sc/trial-scite/ · https://www.educatorstechnology.com/2026/09/scite-review.html
- Paperpile mobile: https://apps.apple.com/app/id1187562736 (no 2026 release notes found)
- ResearchRabbit: https://aarontay.substack.com/p/researchrabbits-2025-revamp-iterative · https://effortlessacademic.com/research-rabbit-2026-review-for-researchers/
- Litmaps: https://www.tooliverse.ai/tools/litmaps · https://www.educatorstechnology.com/2026/09/litmaps-review.html
- Connected Papers: https://nesslabs.com/connected-papers · https://library.hkust.edu.hk/sc/connected-papers
- Heptabase: https://wiki.heptabase.com/roadmap · https://wiki.heptabase.com/changelog/2025 · https://thesweetsetup.com/?p=163189
- Obsidian + Zotero: https://github.com/mgmeyers/obsidian-zotero-integration · https://forums.zotero.org/discussion/comment/385938/ · persist issue: https://forum.obsidian.md/t/how-to-preserve-annotations-and-meta-information-when-re-importing-from-zotero/102028
- Logseq: https://discuss.logseq.com/t/pdf-annotation-in-logseq/1427 · https://discuss.logseq.com/t/more-contrast-on-the-pdf-highlight-area-when-clicking-the-reference-link/4238
- Recall: https://www.recall.it/faq · https://docs.recall.it/
- NotebookLM: https://support.google.com/notebooklm/answer/14276569?hl=en (hover/click citation behaviour) · https://support.google.com/notebooklm/answer/16164461 (one unverified source says it was renamed "Gemini Notebook" in Jul 2026)
- alphaXiv: https://www.alphaxiv.org/changelog · https://www.toolcenter.ai/en/articles/alphaxiv-review-2026
- Kortex: https://aiindigo.com/blog/kortex-review-2026-a-unified-workspace-for-the-modern-knowledge-worker. I found no Kortex product that is an AI PDF reader. "Research Notes" (open-source AI paper reader, Product Hunt, May 2026) was mentioned in the same results, but I didn't verify it further.

## Not verified / caveats

- Connected Papers' colour direction (guides conflict). ResearchRabbit, Litmaps, Consensus, SciSpace and Scholarcy details are 3rd-party only.
- MarginNote's FSRS comes from the App Store listing. The official features page doesn't name the algorithm.
- Whether Semantic Reader skimming is still limited to CS arXiv papers in late 2026. LiquidText's current AI features (none on the official site). PDF Expert 2026-specific changes.
- Readwise's `h` shortcut: the blog says it highlights the paragraph; the FAQ mentions Shift+H to toggle auto-highlighting.
