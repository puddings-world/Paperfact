# Paper presentations

The desktop reader's right side has a **簡報** tab. It turns existing paper research
into an editable presentation with slide points, speaker notes and evidence links.

## Two versions

- **研究筆記** follows the paper's sections, keeps important derivations and
  experiments, and integrates the reader's questions and observations.
- **論文導讀** introduces necessary background and prior work before following
  the paper's question, method, evidence and limitations. It targets an audience
  that has not read the paper.

Each paper saves these versions independently. Both use the same original research
without changing its notes, chat, deep dive or reading state.

## Make and edit a deck

1. Open the paper and select **簡報**.
2. Choose a version, intended audience, slide count (4–24) and speaking time.
3. Select the evidence to include: original, deep dive, citation/context analysis,
   chat and notes. Selecting the deep dive also includes available **逐節精讀**
   sections in their existing order. Original text or a deep dive must be available.
4. Press **生成投影片**. Generation uses AI only when explicitly requested.
5. The **投影片畫布** is an embedded 16:9 editor with slide thumbnails. Double-click
   text to edit; drag objects to move them and drag the lower-right handle to resize.
   Change font size, bold or color, add text and original figures, or delete objects.
   **內容與引用** and the canvas update each other immediately. Editing a linked text
   field preserves object positions, sizes, styles and additional objects. Valid changes
   save automatically after a short pause; incomplete fields remain editable drafts.
   **講稿** edits speaker notes on a centred page, with the length in characters and
   the speaking time (about 250 Chinese characters or 150 English words a minute)
   against the per-slide share of the planned minutes. **核對來源** links locate the source in the left PDF;
   sources without a known location are reported instead of opening an unrelated page.
   Sources are grouped into original text, figures, AI explanations, literature context,
   personal notes and Q&A. **只看本頁已引用** reduces the list to current citations;
   searching finds matching sources even when they are not cited yet. Selecting a row
   previews its content; only its checkbox changes the citations. Citations update
   the canvas footer and exported speaker notes without rewriting slide text.
6. Add, reorder or remove slides. **復原** restores a previous edit in the current
   editing session. Switching papers/versions saves valid pending edits. Ctrl+S
   explicitly saves the current edits, including speaker notes and structured fields.

When the blank canvas, the view tabs or 核對來源 has focus, Up/Down changes slides and
plain Left/Right switches views; this acts only inside 投影片視角. While editing
text or selected objects, arrows keep their editing behavior (moving the caret,
nudging the object), and Alt+Left/Right switches views instead, taking priority
over window history.

Anywhere in 簡報, **A** toggles 頁面目錄, **D** toggles 論文素材 and **R** restores the
panel layout; each button shows its key. A text field or a text box being edited
takes the letter as typing, so these keys never fire while you write.

On the canvas, Ctrl+C/X/V copies, cuts and pastes selected objects; Ctrl+A selects
all objects, Delete removes them, Ctrl+D duplicates them, and Ctrl+Z / Ctrl+Y undo
and redo. Drag on empty space or Ctrl-click to select multiple objects. On macOS
these are the ⌘ equivalents (redo is ⇧⌘Z), the Delete key (⌫) removes objects, and
Option (⌥) takes Alt's place for switching views. These
commands are also in the right-click menu and **物件操作** menu. Original figure
objects can be pasted between slides of the same paper; plain clipboard text can
be pasted as a new text box. While double-click editing inside a text box, the
standard shortcuts operate on its text instead of whole objects. Escape exits text editing.

## Materials (素材)

**素材** opens a panel beside the canvas listing what a slide most often needs from
the paper itself, without a model call. Each material is one line in the list; the
selected one's image, full caption, table or sentence shows in the pane below it:

- **圖表**: every figure and table figures.py extracted, with its page and the
  逐節精讀 section that discusses it. A table whose rows the 逐節精讀 reproduced as a
  Markdown table also offers **表格資料**, which becomes an editable table object on
  the slide rather than a cropped image.
- **章節標題**: the paper's numbered section headings in order, read from the PDF
  text layer (or from the 逐節精讀 when no PDF is available).
- **關鍵句**: click **AI 挑選原文重點** to analyze the original paper through the
  configurable **原文研究重點** AI route. The model selects information-rich quotes
  about the research problem, contributions, method, evidence, definitions and
  limitations, with a separate Traditional Chinese explanation of their importance.
  The model selects original passage IDs; the application retrieves the
  exact text and page from the source instead of asking the model to transcribe it.
  Every quote must match its original page after whitespace normalization.
  Selection reads all extracted original text in chunks and compares candidates
  across chunks; it does not prefilter by keywords or use generated notes as evidence.
  Empty PDF pages are reported as an OCR coverage warning. Text-only fallback has
  no invented page numbers. Select an item to see the full quote and AI rationale.
  **自動重點** in the PDF toolbar prepares this analysis on the first open when an
  AI connection is configured. The same verified quotes become green PDF highlights
  and material entries; manual yellow highlights also appear as materials, labeled
  as manually selected rather than AI judgments. The reusable
  `paper_highlights.prepare_reading()` function shares the analysis cache with both
  views and maps the complete quote to original word positions. Unmatched quotes
  remain materials and are reported instead of being approximately highlighted.
  Results are cached by original content and analysis version. Opening the panel
  reads the cache; **重新分析原文重點** uses AI again (including a newly selected
  provider). Failed or invalid responses preserve the previous cache.

The PDF reader shows the saved AI/manual highlight counts and any analysis failure
above the original. The selection popup has one checked **螢光筆** toggle: click to
mark an unmarked passage or remove an existing mark. Material cards support single
click to jump to the saved original position, double-click/drag to insert into a
slide, and a full preview below. Quote word anchors and figure/heading positions
are cached against the PDF fingerprint. These actions work before a deck exists.

Deep explanations show verified original quotes beside the sections they support,
with **為何畫重點**, **與這段講解的關係**, and a link to the PDF mark. AI maps quotes
to section IDs by meaning; unsupported/unmapped quotes remain explicitly separate.
The link cache follows both original highlights and explanation content, so a
changed explanation cannot silently reuse stale associations. Preparing new or
stale explanation links uses the configurable original-highlights AI route.

Above the slide canvas, enter a short instruction and press **AI 改寫這頁**. This
uses `slide_revise.revise` in the background to replace one slide's content, sources,
figure and layout, then saves automatically. **Ctrl+Z / Ctrl+Y** undo/redo the change.
A failed response or a changed target leaves the current page intact. Object
copy/cut/paste/select-all/delete use **Ctrl+C/X/V/A** and **Delete**; discrete clipboard
and delete operations form separate undo steps. Figures are added from materials.

Background deep dives also prepare highlights only when **自動重點** is ticked
(it starts unticked, so a fresh workspace spends nothing on them). The
explicit full-analysis workflow treats highlights as a separate resumable step,
including papers that already have a deep dive. A per-paper process lock prevents
the background writer and desktop reader from generating the same analysis at once.
Highlight failures leave the saved deep dive intact and can be retried independently.

Double-click an item or its image preview, press **加入目前投影片**, or drag a
material into any presentation view to add it to the current slide. A drop on the
canvas uses the drop position; drops on structured content, source review or speaker
notes return to the canvas with the inserted object selected. They do not overwrite
the text field under the pointer. Blocked insertions explain the reason in the
materials panel.
A figure or table from the paper is added to the deck's evidence index and cited by
the slide; a quoted sentence cites its original page when the deck has one. Table
objects are edited by double-clicking (one row per line, cells separated by Tab) and
export as real tables in HTML, Markdown, OpenDocument and Google Slides, and as the
rendered grid in PDF. The panel reads the paper's figures, PDF text, cached AI highlights and 逐節精讀
from disk and papers.db. AI runs on first preparation when **自動重點** is enabled,
or when the user explicitly requests reanalysis. Reopening uses the existing cache.

Page count, speaking time, audience and source selections configure the next AI
generation. Changing them displays a regeneration hint; no model call happens until
**重新產生** is pressed and its confirmation is accepted (Cancel is the default).
The dialog explains that the whole deck will be replaced, the old draft will be
archived, and generation uses AI credits. Slide edits and undo preserve pending options.

Evidence checkboxes in **製作設定** apply to the next generation. Changing them does not retroactively
remove content from a saved deck: regenerate or edit it before sharing. Slides must
retain at least one known source. Selecting an original figure adds its source too.

A new draft archives the previous version, including manual edits, under
data/presentations/<paper-key>/history. It does not silently overwrite the only copy.
Use **歷史版本** to choose an archived generation and restore it. Restoration also
archives the current draft and creates a new version ID, so both remain recoverable.
Ordinary autosave updates the active draft; it does not create a permanent version
for each keystroke. Edit undo/redo is kept in memory for the current editing session.
Generation failure leaves the saved draft unchanged.

Generation runs in the background. Switching papers does not attach the result to
the wrong paper. The application waits for presentation generation/PDF export before
closing, and blocks switching when current edits fail validation.

## Evidence and coverage

Original text is the primary evidence for author claims. Deep dives and citation
analyses are secondary AI interpretations. Personal notes must remain identifiable
as reader observations. The generation prompt asks for these distinctions and a
paper-order narrative; source IDs are validated, but factual correctness and
narrative quality still require the researcher's review.

Each slide is checked on its own. A source ID that does not exist is dropped, a
slide's figure is added to its sources, and sources beyond eight are cut, all
without another model call. Slides that still fail (text too long, too many
bullets) go back to the model once, together, with the reason for each; only those
slides are replaced. A deck is rejected only when a slide survives that repair still
broken, or the slide count is wrong, and the message names the slide. A batch run
over a reading list rejected about one draft in four before this, each time
discarding eleven good slides for one bad one.

PDF text is collected by page when available; cached text has no page numbers.
Long inputs are bounded across source groups, with coverage/truncation explanations
preserved in the deck. Image captions identify the existing figures; the current
model request is text-only, so it does not visually inspect them. Review that the
chosen figure actually supports the slide.

The feature reuses extracted original figure PNGs when selected. It does not
automatically extract new figures or create scientific diagrams. Used figures are
copied into the presentation's assets so later PDF replacement does not remove them.

## Export

The save dialog defaults to PDF, named **Slides of - <paper title>.pdf**. Characters
forbidden in Windows filenames (including a colon) are replaced, and very long
titles are shortened. HTML remains available as an alternative format.

| Format | Use |
| --- | --- |
| PDF (default) | Landscape slides, one page per slide; no speaker notes |
| HTML | One self-contained file with original images, playback and optional speaker notes |
| Markdown | Text outline and optional speaker notes, with figure labels rather than images |
| JSON | Structured slide data and embedded used images; not an in-app import feature |
| OpenDocument (.odp) | Editable text boxes and original images for compatible slide editors |
| Google Slides | A new editable cloud copy and its Google Slides link |

HTML works offline. Use previous/next, arrow keys, playback, and the notes button.
It can also be printed to PDF from a browser. Content overflow is highlighted for
editing rather than silently treated as a finished layout.

Direct PDF export renders the same native Qt scene as the editor, retaining text
selection and object placement. It does not require Qt WebEngine. PowerPoint (.pptx)
export is not implemented.

**匯出含講者備註** applies to HTML, Markdown, JSON, OpenDocument and Google Slides. Turn it off when sharing only
the slides. Public exports include selected slide content and source labels/links,
not the complete raw research snapshot or AI credentials.

## Google Slides connection

Click **建立 Google Slides**. Once the app's OAuth client is configured, Paperfact
opens the system browser for Google sign-in, creates an editable copy in that
account, and opens its edit link. Later exports reuse the current app-session
login. The adjacent arrow offers **開啟上次建立的簡報** and
**切換 Google 帳號並建立**. Each click creates a new copy; cloud edits are never
silently replaced. This is an export, not two-way synchronization.

Every Google export includes speaker notes and numbered source references with
available page numbers and safe web links. Paperfact imports the editable canvas
through Drive, then writes the notes explicitly with the Slides API. The
HTML/ODP notes option does not disable Google notes. If import succeeds but notes
synchronization fails, the created link is retained and opened with a warning;
no second copy is created automatically. Fonts and conversion details still need
checking in Google Slides after import.

**Deployment setup (developer or self-hosted administrator, once):**

1. Enable both Google Drive API and Google Slides API in the app's Cloud project.
2. Configure the consent screen and a **Desktop app** OAuth client. During testing,
   add permitted test users; configure publication as appropriate for distribution.
3. Supply PAPERFACT_GOOGLE_CLIENT_ID and PAPERFACT_GOOGLE_CLIENT_SECRET to the
   desktop deployment, or import its downloaded JSON from
   **Google Slides → 開發者設定 → 設定應用程式 OAuth…**.

End users should sign in, not create their own Cloud project. An installation
without an app OAuth client reports that Google sign-in is not yet enabled;
it cannot create cloud decks until deployment setup is complete.

Authorization uses a system-browser loopback callback, state, PKCE, and only the
drive.file scope. Files are not made public. Tokens remain in memory for the
current session; account switching clears that session. Imported app configuration
stays in data/google-slides-client.json, outside exports and Git. Credentials do
not belong in a deck or its source records.

See [Google desktop authorization](https://developers.google.com/identity/protocols/oauth2/native-app),
[Drive import conversion](https://developers.google.com/workspace/drive/api/guides/manage-uploads),
and [Google speaker notes](https://developers.google.com/workspace/slides/api/guides/notes).

## Storage and AI

Drafts, archived versions, source snapshots and copied figures live in the
gitignored data/presentations directory. Back it up alongside papers.db.

In **AI 設定 → 各功能使用的 AI**, choose **論文簡報**, or let it follow the default
profile. Generation uses the slides task through llm.complete_result, including
the existing API usage receipts and custom gateway adapter. Exporting and editing
do not consume model tokens.

This is an implemented presentation capability, not an installed plugin or complete
external-agent integration. Managed-mode policy, MCP and billing are separate
planned work. The service, presentation data model, desktop pane and exporters are
separate modules so those integrations can reuse the same behavior.

## Workspace layout

The document toolbar controls the deck, generation, saving, history and exports.
**製作設定** expands a separate, scrollable generation panel; its bottom divider
changes its height. Existing decks open with this panel collapsed by default.
**頁面目錄：開／關** and **論文素材：開／關** toggle the left slide list and right
paper-materials panel independently. Blue means on; the label also states its status. Drag the visible separators to change
column widths; the materials list and full quote/rationale have their own vertical
separator and **詳細內容** toggle; **論文素材** opens and closes the panel. Close the side panels for more canvas space;
there is no separate focus mode. **還原面板配置** restores panel visibility, dimensions and fit-to-window zoom.
It does not regenerate slides, move objects, discard edits or remove history.
The desktop remembers panel layout and canvas zoom when closing normally.

Canvas zoom is separate from text size and exported slide dimensions: use the
percentage control (10–300%), plus/minus, or Ctrl+wheel. Middle-button drag pans
the zoomed canvas; regular scrolling uses the scrollbars. **適合視窗** follows
workspace resizing; manual zoom stays fixed when resizing panels or changing slides.

The four views are **投影片畫布**, **核對來源**, **內容與引用**, and **講稿**.
Use Left/Right on their tab bar, source preview, or an unselected canvas to switch.
Alt+Left/Right switches from anywhere inside the presentation pane. Plain arrows
retain text-caret and selected-object movement while editing. The thumbnail
**前移 / 後移** commands reorder slides; they do not switch editing views.

Citation rows use checkboxes: selecting a row no longer toggles its citation.
The editor prevents removing the last source, selecting more than eight sources,
and removing a source belonging to a figure still in use. Material insertion and
figure paste also check the source limit before modifying the canvas.

If validation still prevents saving, closing offers **返回編輯** or
**保留草稿並關閉** in a nonblocking dialog. The latter writes a separate recovery
file alongside the saved deck. Reopening the same paper and mode restores the
unfinished fields and canvas for correction; successful saving removes recovery.
The saved deck is not replaced by an invalid draft. Recovery is not a crash-time
memory backup: edits lost in an older crashed app cannot be recovered by this code.

Materials preview shows the actual local exhibit image, caption and any extracted
table rows. The editable-table child previews all cells; figures have a
**放大原圖** link for full-resolution inspection. Images fit the preview column as
it resizes. Missing images show an explicit message while retaining captions and
available table data. Table values come from close reading and must be checked
against the original exhibit.

Presentation switches use a persistent blue background while enabled, including
settings, thumbnails, materials, details and fit-to-window zoom. The
bold button reflects the selected text objects; mixed selection can be made bold
with one click. Dragging the material detail divider closed also updates its toggle.

Click the canvas background to give it keyboard focus. Up/Down changes one slide;
selected objects still move with arrows and editing text keeps its caret controls.
Escape exits text editing, then clears object selection on the next press.
Page Up/Down changes slides even with objects selected (outside text editing).
Navigation saves pending changes and stays on the current page if validation fails.
The **加入圖表…** button opens the materials panel for preview; double-click or
drag a chosen item to insert it. It does not insert an image immediately.

## Development restarts

`paperfact app --restart` asks a running compatible reader to save its valid edits
(or preserve an incomplete presentation recovery draft), close gracefully, and reopen
with its paper, editing views and unfinished note/question inputs restored. Active
work or a modal dialog blocks restart. Older running builds need one manual restart
to load this command. It never force-kills a process.
