# Reader, notes and sharing

These instructions describe the current desktop and shared readers. Run terminal
examples from the repository root. Some sections retain implementation details
for troubleshooting. See the [README](../README.md) for the short introduction.

## The reader

### Opening it

Double-click **Paperfact** on the Desktop, or type "Paperfact" into the Start
menu. No terminal appears, and launching it a second time raises the window that is
already open rather than adding another.

`scripts/make-shortcut.ps1` creates both entries; on macOS, `scripts/make-app-mac.sh`
creates **Paperfact.app** in `~/Applications`. `paper-daily app` still works from
a terminal when you want to see its output.

The shortcut goes through `scripts/launch-app.vbs` rather than straight at an
interpreter, because neither obvious route works: uv's venv ships `pythonw.exe` as a
trampoline that re-execs the *console* `python.exe`, so a terminal appears anyway,
and dropping the real `pythonw.exe` into the venv fails silently because uv does not
put `python311.dll` beside it. The script starts the process with its window hidden;
the app then asks Win32 to show its own window, because that same hidden flag is
inherited through `STARTUPINFO` and would otherwise swallow the reader too.

### Using it

Two screens.

**The queue.** Every paper in reading order — all 5000, searchable, no cap — with
filters for unread, already read, oral/spotlight, principle-type, "PDF downloaded",
and **地基**. Each row says where the paper was published the way the field says it
(MICCAI 2025, IJCARS 2025, Sci Data 2024), and a paper known only as a preprint is
greyed and marked 預印本; the search box matches that too, so `miccai` or `預印本`
narrows a list to it. Click any row to read it now; the **下一篇** button (Ctrl+N) takes the
next unread one. The list has the keys as soon as it shows: ↑↓ choose a row, Enter
opens it, **A** ticks it and **T** pins it, and ↓ or Enter in the search box moves
into the results (letters typed there stay search text). Alt+← (or Esc, or the
mouse's back button) returns to the list as a browser would, with the paper you were
reading highlighted, and Alt+→ goes back into it. Ctrl+F searches what is
on screen: the queue from the queue, the paper's own text from the reader, where the
box above the PDF steps through every match (Enter / Shift+Enter, or F3) — a phrase
across a line break included — and Esc clears it before it leaves the paper.

**Which panel has the keys.** The reader is made of nested panels: 原文 (the PDF),
分析 (the tabs on the right), and inside it 簡報, which holds the 頁面目錄, 投影片視角
and 素材 panels.
A click anywhere in a panel, its background included, gives that panel the keys; the
innermost panel wins. A key goes to that panel first and then outward, so every
panel on the way is live: the innermost is framed in bright blue, the panels around
it faintly, and the path with the inner panel's keys (分析 › 簡報 › 投影片視角 · ←/→)
shows in its corner for a moment when you arrive. Window keys work everywhere (Ctrl+1 to
Ctrl+6 switch the analysis tabs, counting only the tabs shown, Ctrl+N, Ctrl+F); panel keys only in their panel
(←/→ switch slide views only in 投影片視角, ↑↓ change slides in 頁面目錄, and A / D / R
toggle the slide list, toggle the materials and restore the layout anywhere in 簡報). Hold
Ctrl for a moment to see each tab's key; in 投影片視角 holding Alt shows where Alt+←
and Alt+→ lead.

**On macOS** every Ctrl shortcut is the same key with ⌘ (⌘N, ⌘F, ⌘1–⌘9, ⌘-wheel
zoom). Back and forward are ⌘[ and ⌘], and the next / previous match is ⌘G / ⇧⌘G
instead of F3. Tooltips and menus show the keys the way the running platform writes
them.

Each row reads like a catalogue card: the title; then where and when it was published
(MICCAI 2026), its citation count, its type, how far its analysis got and whether the
PDF is missing; then its authors.

| Tag | Meaning |
|---|---|
| 已分析 | deep dive, 承先 (what its references do) and 啟後 (later work) all exist |
| 缺 承先·啟後 | what is still missing, by name |
| 未分析 | none of it yet |
| 缺 PDF | not downloaded yet; **缺 PDF(找不到,右鍵補)** once every source was tried |

Above the list, **分析:完整 · 部分 · 未分析 · 缺 PDF** counts them, and **分析未完成的 N
篇** runs `analyze --list` for the list on screen, three papers at a time, with its
progress on the same line; press it again to stop. Rows update as papers finish, and
whatever was finished stays. Right-click a row for **分析這篇**, or for **補 PDF** by
pasting a URL or choosing a file you downloaded through the library; the paper is
analysed as soon as the PDF is in.

**清單綜覽**, next to it, reads the whole list as one field rather than as forty
separate papers: how the field got here (its phases, and the papers that turned
it), the lines of work running through the list with their representatives and how
far each has got, a table of the datasets and who uses them, current progress, the
challenges (data, method, evaluation, clinical use) with the papers that name them,
five to eight open problems written as concrete research topics (the problem, why it
is feasible now, the expected contribution, the risk), and a reading order for
someone new to the field. It is one model call over a digest of every paper's deep
dive — its conclusion, its 前導導讀 account of the field and its gap, its core idea,
evidence and limits, and what later work did with it — so it is only as good as the
dives under it, and it says how many papers it had to read from the abstract alone.
It is stored per list, can be edited like a note, and a hand-edited survey is not
replaced without asking. `survey <list>` writes it from the command line.

The dropdown at the end of that row re-sorts what is on screen: by citations, by date
either way (year, and the month from the arXiv id within a year), grouped by venue
(MICCAI, IPCAI, IJCARS, MedIA, TMI … then other venues, preprints last), grouped by
paper type, unanalysed first, by how many queued papers depend on it, by when you last
marked it read, or by title. It applies to a reading list as much as to the queue — a colleague's
bibliography is usually in citation order by accident, and "oldest first" is how you
read a lineage. Two things deliberately do not move: the number on each row stays the
paper's place in the queue or the list, so sorting is a way to look at that order
rather than to renumber it, and **下一篇** still follows the underlying order. The
choice is remembered between launches.

**Code and data.** The line under a paper's title links what it released: 程式碼
MECLabTUDA/SASVi ★17, 模型, 資料集, 專案頁. A repository GitHub does not have is
marked (repo 尚未公開) — usually code a camera-ready paper promised and nobody has
pushed yet, which is worth knowing before planning to compare against it. A
repository found only by searching GitHub for the paper's name says
(搜尋到,未經論文確認). **文中提到的連結** lists the rest: tools and datasets the paper
used, and models other people tied to it on Hugging Face. The first time a paper is
opened the lookup runs in the background, and again once its PDF has arrived.

Right-click any row to act on it without opening it: **從佇列移除** / **從這個清單移除**,
**插到佇列最前面**, **置頂**, and marking it read or unread.

A paper counts as read only when you say so: **標記已讀** in the reader, or the
right-click menu. Opening one is not reading it, so 只看未讀, 讀過的 and the
最近標記已讀 sort all ignore it; in a list an opened paper is tagged 開過, and in the
queue one the nightly job handed you is tagged 已送出.

**Ticking rows.** The box at the left of every row ticks it, and the bar above the
list acts on everything ticked on screen: 全選, 清除勾選, 置頂 / 取消置頂, 標記已讀 /
未讀, 分析 (analyse just those), 從清單移除 (one confirmation for all of them), and
帶出門, which builds the phone page from the ticked papers across every list. Ticks
are remembered between launches. Clicks on the tick box or the 置頂 box never open the
paper, however fast they come; click anywhere else on the row to open it.

**置頂** holds papers above the rest whatever the sort, each queue and list keeping its
own. The 置頂 box at the right end of every row turns it on and off, or tick several
and press 置頂. Pins live in their own table, so the nightly re-rank leaves them be.

In a reading list the filters are 只看未讀, 讀過的, 未分析完, 缺 PDF and 已有原文;
oral / spotlight, 原理型 and 地基 come from the conference crawl and only appear in the
main queue.

**＋ 新增 → 加入論文到這份清單…**, beside the list switcher,
adds one — in a list it takes a pasted citation or a bare title and resolves it the way
an import does; in the main queue it searches all 63,000 crawled papers, since the main
queue is the three conferences and nothing else, and puts the one you pick at the front.

Removing never deletes: a queue paper is marked skipped so the row keeps whether and
when you read it, and a list paper leaves the corpus row, its notes and its deep dive
alone. Adding it again brings it back.

A paper you put there by hand is marked `manual`, and a reference pulled forward from
the lineage block is marked `companion`. The nightly rebuild deletes and regenerates the
pending queue, so those two roles are exempt from both the delete and the re-rank —
without that a hand-picked paper vanished overnight, and "move to the front" silently
undid itself by morning.

地基 is the one view the corpus builds for itself: papers that other queued papers
are known to cite, ordered by how many. It is a curriculum derived from the
reference graph rather than from anyone's opinion, and it agrees with the hand-written
canon list far more often than not — the top eight are all on it. It also found one
the list had missed, InstructGPT, which 44 queued papers build on.

**The reading desk.** The paper on the left, rendered as the PDF it actually is.
Drag across it to select a passage and four things are offered where you selected:
**複製**, **翻譯**, **寫筆記**, **問這段**. Double-click takes a word; Ctrl+wheel zooms about the pointer, continuously, starting
from whatever fit-to-width had chosen.
**問這段** does not ask a fixed question: it switches to 問 AI with the passage
waiting above the box, so the question is yours (the seed buttons apply to it too),
and an empty box asks what the passage is saying. **寫筆記** is the same without a
model in the loop.

Selection is built rather than inherited. `QPdfView` renders and scrolls well and
exposes no way to select text — no `selectedText`, no hit test, not even a
widget-to-page mapping — so a transparent overlay converts the drag into page
coordinates, asks PyMuPDF which words lie between the two points, and draws the
highlight itself. The overlay lays the pages out as `QPdfView` does, page by page:
in FitToWidth each page is scaled to the viewport on its own, so a paper that mixes
portrait pages with landscape table pages has a different scale per page (one
document-wide scale, which this used to take from the scrollbars, was right only when
every page was the same size). Text set at an angle is not selectable: a preprint's
diagonal "ARTICLE IN PRESS" stamp covered the middle of every page and came first in
reading order, so any drag starting over it began at the top of the page. Each end of
a drag takes the word whose box is nearest the pointer, not whose centre is, and the
passage runs between them in reading order, so dragging backwards or across into the
next column selects what it looks like it selects.

**翻譯** answers in about a second from Google Translate (the keyless endpoint browser
extensions use), which is what a glance at a sentence wants. Google renders terms
literally — *phase recognition* comes back as 相位識別 — so the panel offers **用 AI
精譯**, which goes through the model backend and keeps technical terms in English, in
five to fifteen seconds. If Google does not answer, the model takes over without being
asked. The shared web reader uses its host-provided AI capability: an artifact may not
call outside hosts. **寫筆記** opens the notes
tab with the passage quoted in the composer, so a note is about something rather than
about the paper in general. One note holds one passage: choosing another passage saves
a draft you had written under the last one and starts fresh, or replaces a quote you
had not written anything under yet — and it is the same overlay that puts the selection back
when a card is clicked later.

On the right, six tabs:

**How the reading views look.** 深度講解, 筆記 and 問 AI are typeset like a paper:
formulas are written in LaTeX and drawn by KaTeX, an algorithm is a numbered box
with its title (Algorithm 1 · …) and keywords in bold, a mechanism is a drawn
Mermaid flowchart, code is highlighted by language and tables are ruled. Dives
written before this used Unicode maths and box-drawing diagrams; those still
show, with Chinese inside a diagram held to two columns so its borders meet.
`dive-ahead --paper ID --rewrite` rewrites one in the new form. A diagram the
model got wrong shows its source instead of an error. The pocket page and share
pages typeset the same way.

**深入分析** sits at the right end of the tab bar: a violet button, and beside it
which parts exist (講解 · 承先 · 啟後, ✓ when done, … while running, ✗ when a step
failed, with the reason in the tooltip). One press makes everything the paper is
missing: the PDF, the deep dive and close reading, the marked passages, the reading
of every reference (承先) and the field's later work with the 研究脈絡 (啟後). The
explanation and the citations run side by side, so it takes three to six minutes,
and each tab redraws itself as its part lands. The nightly job does the same for the
next papers in reading order, so most papers arrive complete; the button is for the
one you jumped to. 簡報 is separate and made only on request.

**分析排程** (top bar) sets that nightly job: every night, every two days, weekly,
or only when you press the button; how many papers from the main queue and from the
reading lists (0–20 each, 4 and 3 by default); whether the window tells you when
they are done; and whether the open app also analyses the next three in the
background (off by default, since it spends model calls while you read). The dialog
says in one line what will happen next ("今晚 00:00 會分析主佇列接下來 4 篇、清單裡
3 篇"). When a run finishes, a violet strip above the page names the papers
("已深入分析 3 篇，可以讀了：《…》"), once per run, with **開始讀** to open the
first and **知道了** to dismiss it; the taskbar button flashes if the window is in
the background.

Every button that starts AI work has the same look: violet, with a four-pointed
spark, filled for the one action a view is waiting on and outlined otherwise
(問這一頁, the 問 AI questions, 分析／補上標註, AI 挑選原文重點, 用 AI 精譯, 產生此版本,
AI 改寫這頁, 清單綜覽, 分析). Its tooltip says it uses AI. Everything else in the
window — navigation, ticking, pinning — stays blue or grey.

- **深度講解** — the deep dive. These are made ahead rather than only for the
  paper delivered tonight: reading is not one-a-day in practice, since the queue gets
  jumped around and lineage gets followed backwards, so the reader keeps the next few
  unread papers analysed and tops the buffer up in the background whenever a paper is
  opened or marked read. The paper on screen is not started on its own — a paper
  opened for a glance should not spend a model call — so an unexplained one says so
  and offers 深入分析. Ten fixed sections, in order: 一句話結論 ·
  **前導導讀** · 核心洞見 · 方法 · **機制圖解** · 證據 · **該看哪三張圖** · 限制與反駁 ·
  血緣位置 · 三個討論問題. 前導導讀 is the longest: the introduction, background and
  related work are where a paper tells its story — the state of the field, how the
  authors frame the gap, whom they build on and whom they argue against — and a
  summary loses exactly that. It walks those sections in the paper's own order, in
  five parts: 研究當下的狀態, 作者的論證怎麼推進 (paragraph by paragraph, with short
  quotes), 相關研究的地圖, 缺口、主張與貢獻 (each claimed contribution against the
  experiment that tests it), and 讀前導章節時該帶著的問題. The rest stay brief.

  Under the dive, **逐節精讀** takes every section after the front matter at the same
  depth, in the paper's own order and numbering (`3 Method`, `4.2 Ablation`): each
  design and why it was chosen over the alternative, the equations with every symbol
  explained, the datasets, metrics and baselines as tables, and for each experiment
  the question it answers, the rows that matter copied from the paper as a Markdown
  table, and what the gap does and does not show. Where it discusses a figure or
  table, the paper's own rendering of it (the one in 圖表) appears right there, with
  its caption, and the text says what to check in it. The model reads the text and
  the captions, not the images, so it is told to describe a figure only as the paper
  does and never to guess its form or colours. It is a second model
  call (`close-read`), because a dive twice as long is where a model starts to
  compress the end; a paper counts as 講解 on the list only once both exist, so
  **分析未完成的** fills it in for papers explained before it existed.
  機制圖解 is a drawn flowchart of the mechanism with the block this
  paper actually changes marked ★, and 該看哪三張圖 points at exhibits by number, which
  the 圖表 tab then shows. The briefing pack lists the paper's figure and table
  captions separately from the full text for exactly that reason: an explanation that
  says "the ablation shows" without naming Table 3 cannot be checked.
  `dive-ahead --rewrite` moves an existing shelf of dives onto this specification.
  It goes in queue order, not by how old the dive is, because the papers about to be
  read are the ones that benefit; a `spec` column on each dive records which version
  wrote it, so repeated runs walk forward instead of redoing the front every time.
  `--jobs N` writes N at once, since each dive is spent waiting on a model. The
  reader also does this on its own: when the papers near the front are all explained,
  its idle background pass upgrades older dives instead, and the nightly job does six
  more, so a spec change reaches the reading without anyone running a marathon. To do
  the whole shelf at once instead, `scripts\catch-up-dives.ps1` drives it in
  batches — reading lists first, then the queue, then rewrites, which is the order of
  how much is missing. Start it detached, since a hundred dives is hours:

  ```powershell
  Start-Process powershell -WindowStyle Hidden -ArgumentList `
    '-ExecutionPolicy','Bypass','-File','scripts\catch-up-dives.ps1'
  Get-Content data\catch-up.log -Tail 5      # progress
  ```
- **筆記** — one card per note, newest first. A note started from a selection stores
  where it was written as well as what it says, so the quote on the card is a link
  back: clicking it scrolls the PDF to that passage and highlights it again. The
  anchor is the word order within a page, which is the cheapest thing that survives a
  restart — the file on disk does not change, so word 412 on page 3 is the same word
  tomorrow. A card is shut by default and shows only its headline — the question,
  for an answer kept from 問 AI; the first line, for a note written by hand —
  with the date, page and the passage link. Click the headline to open it: the note
  is rendered as the answer was (tables, lists, code), with 編輯 and 刪除. 編輯 opens
  a Markdown editor with three views, 編輯 / 分割 / 預覽; 分割 puts the source and the
  rendered note side by side, scrolling together, and the view chosen is remembered.
  Half the notes are answers worth rewriting in your own words once understood.
- **問 AI** — questions answered from the paper's own extracted text through the
  AI profile chosen in settings, including CLI, vendor APIs or local models.
  **問這一頁** in the PDF toolbar narrows that to the page on screen; a question asked
  from a selection records that passage, so **＋ 存成筆記** under an answer makes a
  card that leads back there too. Each question and its answer is one card, the
  question as its header and the passage it was about beneath it. The conversation
  is stored with the paper (the `chat` table), so closing the window loses nothing;
  **刪除這組問答** removes one exchange, and a note kept from it stays. Which answers
  are worth keeping is a judgement, so it is a button rather than something that
  happens to every answer.
- **引用** reads as summary first, then detail, and places the paper in its field
  rather than in this corpus. The corpus is three ML conferences plus the lists
  imported by hand, so a lineage drawn inside it showed Cataract-1K one ancestor out of
  forty references and five descendants out of forty-seven.

  **研究脈絡** is a few sentences of before-and-after — what the problem was stuck on,
  what this paper rests on, what it added, what later work did with it, what is still
  open — and **接下來必讀**, the handful of papers backwards (承先) and forwards (啟後)
  that matter most, in reading order, title and reason only. Both are one model call
  over the two lists below, stored per paper and editable.

  Below it, one switch between two itemised lists, each sortable:

  - **參考文獻** — every entry in the publisher's reference list, with what this paper
    uses it for (與原文的關係), read from the sentence that cites it. What the paper
    builds on is the top of this list when sorted by verdict, not a separate list. A
    dataset paper's citation of its own data deposit is left out. Crossref supplies
    the numbering the paper itself prints, so `[17]` is looked up rather than guessed;
    a card whose verdict rests on the title alone says so. Papers with no analysis yet
    still show their in-corpus references from Semantic Scholar's graph, labelled as
    not read from the text.
  - **後續研究** — every work that cites it, from OpenAlex (~250M works) and Semantic
    Scholar merged by DOI or title: on Cataract-1K the first found 27 and the second
    47. S2 contributes what OpenAlex lacks — abstracts it withholds for some
    publishers, and the sentence in the later paper that cites this one — and each
    work is judged from that sentence first, then its abstract: what it does with
    this paper, and whether that is worth reading. "Nobody cites it yet" is recorded
    as an answer, distinct from "never asked".

  Every item has **開啟** when the paper is already here, **插到最前面** when it is
  waiting in the main queue (reading Polar Express and clicking once puts
  Preconditioned Spectral Descent at position 1), and **加入清單** with its DOI when it
  is not here. Every verdict and reason has **編輯**; a corrected item is marked, and
  no later run overwrites it. Every line can be selected and copied.

  It all costs model calls — one per paper for the references, one or two for the
  later work, one for the overview — so all of it is stored. **深入分析** (here or
  beside the tabs) runs whatever a paper is missing; **重新查後續研究並更新脈絡** asks
  the field again later; `cites --list` and `followups --list` do a whole list; the
  nightly run does the next papers in reading order. The tab loads only when it is
  opened, since most papers are opened to read.

  Until then the tab says how much is actually known, not just what it can draw:
  "參考文獻 59 篇尚未分析，目前只列出資料庫裡有的 8 篇 · 後續研究尚未查詢（Semantic
  Scholar 記錄被引用 103 次）". Before the analysis, the only references it has are
  the few Semantic Scholar links to papers already in the corpus, and a bare
  "後續研究 0 篇" read as "nobody cites it" when it meant "never asked".

  **條列 | 引用圖** at the top of the tab is one switch with two faces: the lists, or
  a map of the same papers. The lit half is the one showing, and the choice is
  remembered. Both faces, and both sides of the list (參考文獻 / 後續研究, with their
  sort orders beside them), are made once when a paper's tab is opened -- the one
  on screen first, a dozen cards at a time, the rest while idle -- so flipping only
  shows the other one, in about a tenth of a second. It used to rebuild the whole
  tab on every flip: two to four seconds on a paper with 120 later works. On the
  map:

  - references sit to the left of the paper and later work to the right, each in a
    column per year, so the map reads from cause to consequence;
  - a circle's area grows with its citation count, on a log scale so a 90k-cite
    classic does not swallow the rest; inside it are one or two words for the paper
    (the name before the colon, a name-like first word such as `Cataract-1K`, or the
    initials). Its colour is the verdict from the lists. A solid outline means it is
    already here and a dashed one that it is not; a green ring means it has been read;
  - an arrow A → B means B cites A, the way the idea travelled. Arrows to and from
    the paper are faint, because every neighbour has one. The blue ones are the
    citations *among* the neighbours, which show which references form one line of
    work and which later papers build on each other;
  - pointing at a circle opens the same card the lists show: verdict, full title,
    year, venue, citations, 與原文的關係, 這篇在做什麼, 判斷, the sentence that cites it,
    and which other papers on the map it is linked to. Its own arrows light up and
    the rest fade. A click keeps the card open (click the background to let go), and
    its text can be selected. Double-click opens a paper that is already here;
    right-click adds one that is not to the open list (or 延伸閱讀). Drag to pan,
    wheel to zoom, double-click the background to see the whole map again;
  - when a side has more than 30 papers, **顯示** switches between the 30 most
    telling per side (worth-reading verdicts, then papers linked to other
    neighbours, then citations) and all of them.

  Only references the paper's text is seen to cite are drawn. The 參考文獻 list also
  carries entries from Semantic Scholar's reference list that were matched by title
  and never found in the text; some are mismatches (SASVi was offered "Uncle"), and a
  map would draw them as equal circles pointing into the paper. The map says how
  many it left off, and the list still shows them. Before a paper's text has been
  read, the Semantic Scholar entries are all there is, and they are drawn.

  The citations among neighbours come from Semantic Scholar's batch endpoint: each
  neighbour's reference list, a few requests and no model call. They are fetched
  once, with the lists (**深入分析**, or **重新查後續研究並更新脈絡** to refresh); a paper
  analysed before the map existed shows **查彼此引用** instead, and `cite-links` does
  it from the command line. The map says how many neighbours Semantic Scholar could
  not place, since their links are unknown rather than absent.
- **圖表** — every figure and table in the paper, rendered from the PDF with its
  caption, so "Figure 5 shows the ratio diverging around layer 12" can be checked
  without hunting through 44 pages. These are the authors' own graphics, which
  explain the work better than any diagram generated *about* it. Clicking a figure,
  or its **↩ 原文第 N 頁**, puts the PDF on that page with the caption highlighted, so
  the paragraph that discusses it is a scroll away.
  A **跳到** line pinned above the list names every figure and table; pick one to
  scroll straight to it.

Figures are found by their captions, not by `page.get_images()`: most ML figures are
vector drawings with no embedded raster to extract. `figures.py` locates
`Figure N:` / `Table N:` in the text layer and renders the region beside it — above
for a figure, below for a table — bounded by the nearest *prose* block rather than
the nearest block of any kind, because a table's own rows are text blocks and
stopping at those produced two-pixel blanks. The crop then widens to whatever is
actually drawn inside that band, since a plot legend routinely sits outside the
caption's text width and was being clipped off every multi-series chart. Renders are
cached under `data/figures/<paper_id>/`.

Everything lives in `data/papers.db`: the corpus, the queue, your notes, and the
conversation. Nothing goes through a website, which is also why nothing asks for an
approval prompt.

A paper opens with its original text only if the PDF has been downloaded, so
`prefetch` is worth keeping ahead of the queue:

```powershell
.\scripts\dev.ps1 prefetch 30
```

Without it a paper still opens — abstract, metadata, and a link — but the left pane
has nothing to show.

### Reading lists

The nightly queue answers "what should I read next from the field". A reading list
answers a different question — the bibliography of a paper being written, a
colleague's shortlist, a topic to binge — and the reader switches between them from
the dropdown beside the title.

**＋ 新增 → 建立清單…**, beside that dropdown, is the usual way in: name the list, paste the
references, watch the progress line. Import runs as a subprocess rather than a
worker thread — parsing calls the configured AI and every reference needs a Semantic
Scholar lookup, so a 30-entry list runs for minutes — and closing the dialog kills
it, so a half-finished import cannot keep writing to the database behind your back.

The same thing from the command line:

```powershell
.\scripts\dev.ps1 import-list "Quantisation refs" --file refs.txt
```

Paste the references straight out of the PDF, line numbers and page headers and
all. Parsing goes through the selected AI profile, which handles the wrapped lines and
words hyphenated across breaks; each entry is then resolved against Semantic
Scholar for authors, abstract, citations and an arXiv id, so list papers get the
same PDF pane, deep dives, notes and question box as everything else.

Two things are deliberate:

- **List papers live in the same `papers` table but never enter the nightly queue.**
  Most of them are not ICLR/ICML/NeurIPS at all — NAACL, CVPR, JMLR, arXiv-only —
  and `queue.build` is fenced to the three venues so a re-rank cannot pull them in.
- **A list keeps its own read/delivered state**, in `list_papers`, so the nightly
  rebuild leaves it untouched and a paper read in one place is not marked read in
  the other.

Entries that are not papers at all (a GitHub project, say) stay in the list with
whatever the citation said, rather than being dropped for failing to resolve.

**Finding the original.** A citation is resolved against Semantic Scholar first,
then whatever is still missing goes through CVF (for CVPR/ICCV/WACV), arXiv, and
OpenAlex — which indexes ~250M works across every publisher and is the only one of
them that carries a direct link to a legally free copy of a journal paper. That last
one was added after a list of medical-imaging work came back with entries reading
"unknown 0" and no PDF, including a Nature Scientific Data paper whose open-access
PDF was one search away.

Two things about matching are worth knowing, because both were bugs:

- **A failed lookup is not a paper that cannot be found.** Semantic Scholar answers
  429 and arXiv answers 406 whenever either is busy, and the import that hit one
  wrote a row with no PDF and never looked again. `resolve-missing` re-runs the whole
  chain over anything still unreachable, and the nightly job calls it, so a paper
  lost to a throttled minute turns up the next night.
- **A bibliography paraphrases titles.** "CSMAE: Cataract Surgery Masked Autoencoder"
  is filed as "CSMAE: Cataract Surgical Masked Autoencoder (MAE) Based Pre-Training",
  and exact-title matching will never find it. A candidate is accepted when the method
  name before the colon matches and the rest overlaps, or when almost every
  significant word does. The thresholds are deliberately high, and short entries are
  refused outright: "llama.cpp" is two words, both of which appear in a real paper
  called "llama-roofline: a portable memory-bandwidth roofline for llama.cpp", and the
  first version of this rule happily renamed the row to that.

**An imported list prepares itself.** Switching to one starts a background pass that
runs 深入分析 on the next unread papers it is missing (`analyze --ahead 3 --list`),
and its first step downloads and extracts the PDF — so the original, the explanation
and the citations arrive together rather than on first open. The nightly job then
does three more a night across every list (the 閱讀清單 count in 分析排程), so a
list imported today is ready without anyone asking.
For one you want ready now, `scripts\catch-up-dives.ps1` does the lists before
anything else.

### Reading on a phone, and reading together

Each row on the queue screen has a tick box on its left. Ticking one brings up the
batch actions (置頂, 標記已讀, 分析, 從清單移除 and the rest), and **帶出門** in the
toolbar builds one page out of whatever is ticked. What goes out is a selection, not
the queue: an hour on a train is two or three papers, and every paper in the page is
a PDF that has to travel. The selection is kept in `data/pocket/marked.json`, so
ticking three on Friday and rebuilding on Monday is the same errand.

Building only writes `data/pocket/`. Publishing belongs to a Claude session — one
sentence, "發佈口袋頁" — because an artifact is published with the user's own
credentials and this app never calls a model or an HTTP API on their behalf. The
address does not change: every publish replaces the same page, so the phone needs
the link once and never again. The dialog keeps it (`pocket.url` in `kv`).

The page carries everything the desktop reader holds for those papers: the paper's
own PDF in a built-in viewer (原文); the deep dive followed by its 逐節精讀, with the
paper's own figures and tables set where the text discusses them and a tap opening
each one full size (講解); the citation analysis with the research context at its
head (引用, as at the desk); the slide decks made for the paper (簡報), each as a
text outline with its figures and speaker notes, plus **開啟排版好的簡報** for the
slides as laid out, to read on the way and not to edit, since a deck edited in two
places is two decks; and the notes (筆記). When any of the papers belongs to a list
with a 清單綜覽, **綜覽** in the top bar opens it, one per list. Rebuild the page
after analysing or making slides, and it carries the new parts.

The same page is how other people read with you. Share it from the artifact's Share
menu — as **Contributor** for people who should write notes, Viewer for people who
only read — and they get the reader with nothing to install: the PDF, selection →
translate / explain / note, the analysis, and every note anyone has written, which
appears for everyone as it is written. Each note shows who wrote it; only its author
(and the page's owner) can delete it. In the Claude Artifact host, questions run on
the asker's own account. A custom Paperfact host supplies its own session and billing. A viewer who cannot write is told
so, rather than having notes quietly kept in one browser.

The page carried the extracted text for a while instead. Extraction is how the
pipeline reads a paper, not how a person should: a two-column surgical paper came out
with captions adrift from their figures and table cells as one-word paragraphs. The
PDF has neither problem, because it is the document.

The same page from a terminal, for a selection that is easier to express as ids:

```powershell
.\scripts\dev.ps1 python scripts/build_pocket_reader.py ref:abc ref:def
.\scripts\dev.ps1 python scripts/build_pocket_reader.py   # whatever is ticked
# then publish data/pocket/index.html as an Artifact, with data/pocket/files.json
# as its supporting files, declaring capabilities db, user and sample
```

`paper_daily/pocket.py` holds the building; the script and the dialog are two ways
into it.

In the research context, a work that is also in the page is a jump to it; anything
else links to its DOI. The page cannot add to a reading list — that needs papers.db —
so it says what to read and the desk does the adding.

The citation tab is the same analysis `cites.py` writes, in either of the desktop
pane's two orders — verdict first, or the paper's own reference numbering for
following a superscript you just met. Entries judged 略過 are dimmed rather than
hidden, because the point of the tab is that the list is complete.

Selecting a passage offers three things: translate it, ask about it, or write a note
against it — the page carries the `sample` capability, so the question goes to the host's AI
with that passage, its page number and the paper's identity attached, and the answer
is kept as a note too. The 筆記 tab also takes a question about the whole paper: the
page extracts the PDF's text with pdf.js, so no copy of it has to travel, and the
answer becomes a shared note like any other.

A note written against a selection — here or at the desk — has **↩ 回原文**, which
opens the PDF on its page and highlights the passage. Notes remember the words, not
pdf.js's span numbers, because pdf.js and PyMuPDF never split a page into the same
runs; the passage is found again by comparing text with whitespace and hyphens
removed, which survives a line broken as `contribu-` / `tions`. A figure opened from
the deep dive offers the same jump, to its caption.
Notes live in the artifact's own store, which survives a republish and follows you
between devices; anyone the page is shared with as a contributor writes to the same
store, so each note records the id of whoever wrote it and resolves the name at
render time (names are per-viewer and go stale, so only the id is stored). Notes
written at the desk travel too, but read-only: `papers.db` is not reachable from a
phone, so the desktop reader stays their owner.

They come back with `/paper-pull-notes` in Claude Code, which reads the store and
runs `scripts/import_pocket_notes.py`. Each note is filed against its paper with its
page, its kind (note or question) and a `[共享]` stamp, and its quote is matched
against the PDF's words to compute the desktop's own anchor — so a note a colleague
wrote on their phone is a card at the desk that jumps to the passage. Only a Claude
session can read that store, so the pull is a command rather than a cron job.
Pulling twice files nothing new.

### What the viewer does, and why it is built that way

pdf.js is vendored into `data/pocket/lib/` rather than loaded from a CDN, because a
published artifact serves its own files and a cross-origin worker is the one thing
its CSP does not clearly allow. The PDFs are re-encoded on the way out: a surgical
paper is mostly photographs at print resolution, so one of them is 27 MB, and
`rewrite_images` at screen density brings the list from 77 MB to 16 MB without
touching the text layer that selection depends on.

It shows **one page at a time**, which looks like a limitation and is not. The
artifact viewer sizes its frame to the content, so inside the page nothing can tell
which part of it the reader is looking at: every page reports itself as on screen at
once. A continuous view there means rendering all 44 pages of Cataract-LMM at retina
density, which is a gigabyte of canvas on a phone. One page is bounded whatever the
host does with the frame, and each paper remembers the page it was left on.

Selecting any run of text raises 翻譯 / 講解 / 筆記 — the phone equivalent of dragging
over a line at the desk. 譯 in the header does the whole page, for when a selection
is more trouble than it is worth. Three of the fifteen papers have no reachable PDF
(Elsevier, IEEE, and one with no DOI at all); those say so and keep their abstract.

The published page (currently Cataract-1K and Cataract-LMM) lives at
<https://claude.ai/artifact/5bCVGZY6W3u7PNtkQ3XRMa>; republishing the same file path
updates it in place, so the link survives a rebuild. It is private until shared.

### Sharing a reading with someone else

The phone page is for the person reading; it carries the PDF. A page for someone who
has *not* read the papers is a different thing, so it is a separate command. It
carries no PDF, only what the reading produced: your notes in the order of the paper,
the deep dives, the figures, the lineage and what each reference is doing, and — for
two or more papers — a side-by-side.

```powershell
.\scripts\dev.ps1 share draft ref:cataract1kdatasetfordeep ref:4240f929464ce28cde40bc60 --slug cataract-1k-lmm --compare
# edit data\share\cataract-1k-lmm\draft.md
.\scripts\dev.ps1 share build cataract-1k-lmm
```

It is two steps with a person in between. `draft` writes plain Markdown, once: run
it again and it writes `draft.new.md` beside your edited copy instead of over it,
because once a draft is edited the database is no longer its source of truth. Quotes
and figures are written out in full, so any editor can change the draft and nothing
is re-resolved at build time. Places for your own words — the one-line conclusion,
extra comparison rows — are HTML comments, so an unedited draft still builds into a
page that reads cleanly.

A note's quoted passage comes from the desktop note itself (selection notes and kept
answers quote what they were written against), and notes are ordered by page.
`--compare` is one `llm.complete` call over the two dives and abstracts; the page
labels that section as written by AI from the dives, not checked line by line.

`build` renders the Markdown in the browser with marked.js, so the draft stays the
only source. Figures are re-encoded as JPEG where that more than halves them; charts
stay PNG. The Cataract-1K / Cataract-LMM page is at
<https://claude.ai/artifact/64wyRtFrwXh7TXAganS8tf>, private until shared from the
page's Share menu. Both papers are Scientific Data (CC BY 4.0), which is what makes
carrying their figures straightforward; check the licence before sharing others.

### The web reader

There is also an Artifact version of the same reader, for reading on a phone or
another machine. It needs `sync-queue` and `reader-doc` to push data to it, and is
optional; the desktop app is the primary interface.
