"""The 引用 tab: a paper's place in its field, then every work on either side of it.

It reads top to bottom as summary, then detail:

* 研究脈絡 -- a few sentences of before-and-after, and 接下來必讀: the handful of papers
  backwards and forwards that matter most, in the order to read them, title and
  reason only. Written once per paper and kept; both can be rewritten by hand.
* 參考文獻 -- every reference, with what this paper uses it for, read from the
  sentence that cites it. What the paper builds on is the top of this list, not a
  separate one.
* 後續研究 -- every work that cites this paper across the whole field, with what it
  does with this paper, read from the sentence in the later paper that cites it.

Each item can be opened if it is already here, moved to the front of the queue if it
is waiting there, or added to a reading list if it is not here at all. Each verdict
and reason can be corrected; a corrected item keeps the correction through reruns.

Both lists can also be read as one map (引用圖, see cite_graph.py): the same papers
as circles sized by citations, with the citations among them drawn in.

條列 and 引用圖 are two faces of one switch, and 參考文獻 / 後續研究 two sides of the
list. 條列 is one page in a web view holding both sides, so flipping between them
only shows the other; the map is made the first time it is asked for and kept.
As widgets, a card cost Qt ten milliseconds or more to show, and a lineage of a
hundred and more cards held the window for a second whichever way they were made.
"""

from __future__ import annotations

import html
import json
import subprocess
import threading

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QButtonGroup,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from paper_daily import analyze, citegraph, cites, followups, lineage_team, runtime
from paper_daily.desktop import ai_style, rich_view, ui_state
from paper_daily.desktop.ai_access import requires_ai
from paper_daily.desktop.cite_graph import VERDICT_STYLE, CiteMap
from paper_daily.store import connect, title_key

# Where a reference goes when you are reading the main queue rather than a list.
SPILLOVER_ID = "extra-reading"
SPILLOVER_NAME = "延伸閱讀(從引用加入)"

SELECTABLE = (
    Qt.TextInteractionFlag.TextSelectableByMouse
    | Qt.TextInteractionFlag.TextSelectableByKeyboard
)

VERDICT_COLOURS = {
    "必讀": ("award", "awardSoft"),
    "值得": ("accent", "accentSoft"),
    "參考": ("muted", "sunk"),
    "略過": ("faint", "sunk"),
}

ROOT = runtime.bundle_root()

def story_note(data: dict) -> tuple[str, str | None]:
    """What the 研究脈絡 box says under the story, and which button it offers.

    It promised "深入分析會…再寫成脈絡" for papers where nothing would be written
    -- every reference judged background, or the last attempt failed -- so the
    button finished in a second and the promise stood unchanged.
    """
    story, judged = data.get("story"), sum(1 for r in data["refs"] if r.get("verdict"))
    partial = (
        "參考文獻只分析了一部分；深入分析會補齊其餘的。" if data.get("partial") else ""
    )
    if story:
        return partial, "run-all" if partial else "refresh"
    if data.get("why"):
        return f"上次沒有完成：{data['why']}{partial}", "run-all"
    if data.get("untold"):
        return (
            "這篇目前沒有已判讀的參考文獻或後續研究，沒有可整理成脈絡的內容。" + partial,
            "run-all" if partial else None,
        )
    need = [] if judged and not partial else ["分析參考文獻"]
    need += [] if data.get("asked") else ["查後續研究"]
    return (
        "還沒整理。深入分析會" + ("先" + "、".join(need) + "，" if need else "")
        + "再寫成脈絡，同時補上這篇還沒有的深度講解。",
        "run-all",
    )


# Neighbours per side the map shows before 全部畫出 is asked for: past this the
# labels no longer fit and the shape is lost in the crowd.
GRAPH_LIMIT = 30


def coverage(
    refs: list[dict], later: list[dict], asked: str | None,
    reference_count: int | None, citation_count: int | None,
) -> str:
    """How much of each side is actually known, in words.

    Before the analysis the reference list holds only the few works Semantic
    Scholar links to papers already in the corpus, and "後續研究 0 篇" meant "never
    asked", not "nobody cites it": a paper with 59 references and 103 citations
    read as having 8 and none.
    """
    judged = sum(1 for r in refs if r.get("verdict"))
    graph_only = sum(1 for r in refs if r.get("basis") == "graph")
    if judged:
        back = f"參考文獻已分析 {judged} 筆"
        if reference_count and reference_count > judged:
            back += f"（共 {reference_count} 篇）"
    else:
        back = f"參考文獻 {reference_count} 篇尚未分析" if reference_count else "參考文獻尚未分析"
        if graph_only:
            back += f"，目前只列出資料庫裡有的 {graph_only} 篇"
    if asked:
        forward = f"後續研究 {len(later)} 篇"
    else:
        forward = "後續研究尚未查詢"
        if citation_count:
            forward += f"（Semantic Scholar 記錄被引用 {citation_count} 次）"
    return f"{back} · {forward}"


def graph_legend(pal: dict[str, str]) -> str:
    """The map's key: each verdict as the swatch the map draws, then how to move
    around it. A sentence naming colours made the reader match words to circles."""
    swatches = " ".join(
        f"<span style='color:{pal[line]};font-size:14px;'>●</span>&nbsp;{verdict}"
        for verdict, (_fill, line) in VERDICT_STYLE.items()
    )
    marks = " · ".join((
        "圓越大，被引用越多",
        "實線框已在資料庫，虛線框還沒有",
        f"<span style='color:{pal['done']};'>綠外圈</span>是讀過",
        "A → B：B 引用了 A",
        f"<span style='color:{pal['accent']};'>藍線</span>是彼此之間的引用",
    ))
    moves = (
        "游標移到圓上看資訊 · 點一下固定 · 雙擊開啟 · 右鍵加入清單 · "
        "拖曳平移 · 滾輪縮放 · 雙擊空白處回到全圖"
    )
    return (
        f"<div style='margin-bottom:3px;'>{swatches}&nbsp;&nbsp;&nbsp;{marks}</div>"
        f"<div style='color:{pal['faint']};'>{moves}</div>"
    )


def _spawn(*args: str) -> subprocess.Popen:
    return subprocess.Popen(
        runtime.cli_command(*args),
        cwd=str(ROOT),
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def _esc(value) -> str:
    return html.escape(str(value or ""))


def _say(text: str, colour: str, size: float) -> str:
    return f'<div style="color:{colour};font-size:{size}px;margin:4px 0;">{_esc(text)}</div>'


def _box(inner: str, pal: dict[str, str]) -> str:
    """A bordered panel, as a table so the plain fallback view draws it too."""
    return (
        f'<table class="box" width="100%" cellspacing="0" cellpadding="12" '
        f'style="margin-bottom:12px;border:1px solid {pal["border"]};">'
        f'<tr><td bgcolor="{pal["surface"]}" style="background:{pal["surface"]};">'
        f"{inner}</td></tr></table>"
    )


def _ai_link(href: str, label: str, primary: bool = False) -> str:
    # The spark and the violet that every button starting AI work carries.
    return f'<div><a class="ai{" primary" if primary else ""}" href="{href}">✦ {label}</a></div>'


def _segments(name: str, options, current: str, pal: dict[str, str], *, action: str | None = None,
              hidden: bool = False, title: str = "") -> str:
    """Joined switches, one lit, as links."""
    links = "".join(
        f'<a id="seg-{name}-{key}" class="{"on" if key == current else ""}" '
        f'href="cite:{action or name}:{key}">'
        + (f"<b>{label}</b>" if key == current else label) + "</a>"
        for label, key in options
    )
    shown = ' style="display:none;"' if hidden else ""
    return f'<span class="seg" id="{name}" title="{_esc(title)}"{shown}>{links}</span>'


def _page_css(pal: dict[str, str]) -> str:
    p = pal
    return f"""
.cites {{ font-size:13px; line-height:1.6; }}
.cites table {{ display:table; width:100%; overflow:visible; margin:0 0 10px; font-size:inherit;
  border-collapse:separate; border-spacing:0; }}
.cites table td {{ border:0; padding:0; vertical-align:top; }}
.cites table.box, .cites table.card {{ border-radius:6px; overflow:hidden; }}
.cites table.box > tbody > tr > td {{ padding:12px 16px; }}
.cites table.card td.edge {{ width:3px; }}
.cites table.card td.body {{ padding:11px 14px 12px; }}
.cites table.card.flash td.body {{ background:{p["accentSoft"]} !important; }}
.cites table.card.flash {{ outline:1px solid {p["accent"]}; }}
.cites table.fields {{ width:auto; margin:6px 0 0; }}
.cites table.fields td {{ padding:0 0 5px; font-size:12.5px; background:transparent !important; }}
.cites table.fields td.name {{ white-space:nowrap; padding-right:4px; }}
.cites .quote {{ border-left:2px solid {p["border"]}; padding-left:9px; }}
.cites .actions a.btn, .cites .actions .done {{ display:inline-block; margin:8px 6px 0 0; }}
.cites a.btn {{ padding:2px 10px; border:1px solid {p["firm"]}; border-radius:4px;
  background:{p["surface"]}; color:{p["ink"]}; font-size:11.5px; text-decoration:none; }}
.cites a.btn:hover {{ border-color:{p["accent"]}; color:{p["accent"]}; text-decoration:none; }}
.cites a.ai {{ display:inline-block; margin:8px 0 2px; padding:3px 11px 2px;
  border:1px solid {p["ai"]}; border-bottom-width:2px; border-radius:6px;
  background:{p["aiSoft"]}; color:{p["ai"]}; font-weight:600; font-size:12px; }}
.cites a.ai.primary {{ background:{p["ai"]}; color:{p["onAi"]}; }}
.cites a.ai:hover {{ text-decoration:none; filter:brightness(1.08); }}
.cites .bar {{ line-height:2.3; }}
.cites .seg {{ display:inline-block; white-space:nowrap; margin-right:6px; }}
.cites .seg a {{ display:inline-block; padding:2px 13px; line-height:1.7;
  border:1px solid {p["firm"]}; border-left-width:0; background:{p["surface"]};
  color:{p["muted"]}; font-size:12px; font-weight:600; text-decoration:none; }}
.cites .seg a b {{ font-weight:600; }}
.cites .seg a:first-child {{ border-left-width:1px; border-radius:4px 0 0 4px; }}
.cites .seg a:last-child {{ border-radius:0 4px 4px 0; }}
.cites .seg a:hover {{ background:{p["sunk"]}; text-decoration:none; }}
.cites .seg a.on {{ background:{p["accent"]}; color:#ffffff; border-color:{p["accent"]}; }}
"""


_PAGE_SCRIPT = """
var sideScroll = {};
function showSide(s) {
  var refs = document.getElementById('side-refs');
  var was = refs && refs.style.display === 'none' ? 'later' : 'refs';
  sideScroll[was] = window.scrollY;
  ['refs', 'later'].forEach(function (k) {
    var on = k === s;
    ['side-' + k, 'order-' + k].forEach(function (id) {
      var el = document.getElementById(id);
      if (el) el.style.display = on ? '' : 'none';
    });
    var b = document.getElementById('seg-side-' + k);
    if (b) b.className = on ? 'on' : '';
  });
  // Back where this side was left; the first time, at the top of its cards.
  var bar = document.querySelector('.cites .bar');
  var start = bar ? bar.getBoundingClientRect().top + window.scrollY : 0;
  if (sideScroll[s] !== undefined) window.scrollTo(0, sideScroll[s]);
  else if (window.scrollY > start) window.scrollTo(0, start);
}
function flash(id) {
  var el = document.getElementById(id);
  if (!el) return false;
  el.scrollIntoView({ block: 'center' });
  el.classList.add('flash');
  setTimeout(function () { el.classList.remove('flash'); }, 1800);
  return true;
}
function mark(id, text) {
  var el = document.getElementById(id);
  if (!el) return;
  var done = document.createElement('span');
  done.className = 'done';
  done.textContent = text;
  el.replaceWith(done);
}
function say(id, text) {
  var el = document.getElementById(id);
  if (!el) return;
  el.textContent = text;
  el.style.display = text ? '' : 'none';
}
"""


class _Text(QLabel):
    """A wrapped label that remembers its height at a width.

    QLabel lays its text out again on every heightForWidth, and a page of 120
    cards is asked several times per show or hide: switching 參考文獻 / 後續研究
    took a second of re-measuring text that had not changed."""

    def __init__(self, text: str) -> None:
        super().__init__(text)
        # A few widths, not one: a layout pass asks at the card's width and at
        # the label's, alternately.
        self._measured: dict[int, int] = {}

    def setText(self, text: str) -> None:
        self._measured = {}
        super().setText(text)

    def heightForWidth(self, width: int) -> int:
        height = self._measured.get(width)
        if height is None:
            if len(self._measured) > 8:
                self._measured.clear()
            height = self._measured[width] = super().heightForWidth(width)
        return height


class CitesPane(QWidget):
    # (generation, result) from the author/institution lookup thread.
    team_ready = Signal(int, object)
    team_progress = Signal(int, int, int)

    def __init__(self, window, palette: dict[str, str], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.win = window
        self.pal = palette
        self.paper_id: str | None = None
        # 全域 shows the whole lineage; 作者團隊 only work sharing an author or an
        # institution with this paper, as OpenAlex lists them.
        self._team = "all"
        self._team_data: dict | None = None
        self._team_loading = False
        self._team_progress = ""
        self._paper_info: dict = {}
        self.team_ready.connect(self._team_done)
        self.team_progress.connect(self._team_step)
        self._cites_job: subprocess.Popen | None = None
        self._follow_job: subprocess.Popen | None = None
        self._side = "refs"            # or "later"
        self._ref_order = "verdict"    # or "number"
        self._later_order = "verdict"  # or "cited", "new"
        self._links_job: subprocess.Popen | None = None
        # What is on the page, so a source cited by a slide can be found again:
        # ("ref", marker) and ("title", normalised title) -> (side, the card's anchor).
        self._cards: dict[tuple[str, str], tuple[str, str]] = {}
        # Per side, the works in the order shown: a card's links name it by place.
        self._rows: dict[str, list[dict]] = {}
        # What a card's link says once it has been used, by (action, work).
        self._done: dict[tuple[str, int], str] = {}
        self._waiting: set[str] = set()
        self._map: CiteMap | None = None
        self._graph_all = False
        self._coverage = ""
        self._data: dict | None = None
        self._graph_face: QWidget | None = None
        self._graph_note: QLabel | None = None
        self._generation = 0
        with connect() as conn:
            self._view = ui_state.read(conn, "ui.cites_view", "list")  # or "graph"
        # The links lookup takes a few seconds; the map redraws itself when it is
        # done instead of waiting for the tab to be reopened.
        self._watch = QTimer(self)
        self._watch.setInterval(1500)
        self._watch.timeout.connect(self._links_done)

        self.setObjectName("citesPane")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
        self.setStyleSheet(f"#citesPane{{background:{palette['ground']};}}")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        top = QHBoxLayout()
        top.setContentsMargins(18, 12, 18, 6)
        self._view_bar, self._view_buttons = self._segmented(
            (("條列", "list"), ("引用圖", "graph")), self._view, self._set_view
        )
        self._view_bar.setToolTip("同一份承先啟後資料的兩種看法，切換不會重新整理")
        self._view_bar.hide()
        top.addWidget(self._view_bar)
        top.addStretch(1)
        outer.addLayout(top)

        # 條列 is one page in a web view: a lineage is a hundred cards or more, and
        # as widgets each one cost Qt ten milliseconds or more to show, so the tab
        # took a second to appear and the rest stuttered in. The page lays itself
        # out away from the window's thread.
        self._list_view = rich_view.RichView(palette)
        self._list_view.anchorClicked.connect(self._link)
        self._page_ready = True
        self._waiting_js: list[str] = []
        if self._list_view.rich:
            self._list_view.view.loadFinished.connect(self._page_loaded)
        outer.addWidget(self._list_view, 1)

        self._area = QScrollArea()
        self._area.setWidgetResizable(True)
        self._area.setStyleSheet(f"QScrollArea{{background:{palette['ground']};border:0;}}")
        self._inner = QWidget()
        self._layout = QVBoxLayout(self._inner)
        self._layout.setContentsMargins(18, 4, 18, 24)
        self._layout.setSpacing(10)
        self._area.setWidget(self._inner)
        self._layout.addStretch(1)
        self._area.hide()
        outer.addWidget(self._area, 1)

    # ---- loading ---------------------------------------------------------
    def load(self, paper_id: str) -> None:
        self.paper_id = paper_id
        self._clear()
        with connect() as conn:
            refs = followups.references(conn, paper_id)
            later = followups.for_paper(conn, paper_id)
            story = followups.overview_for(conn, paper_id)
            asked = followups.checked(conn, paper_id)
            untold = followups.nothing_to_tell(conn, paper_id)
            partial = bool(refs) and not cites.complete(conn, paper_id)
            why = analyze.failed(conn, paper_id, "later") or analyze.failed(conn, paper_id, "cites")
            for r in refs + later:
                r["here"] = followups.in_corpus(
                    conn, r.get("doi"), r.get("title"), r.get("corpus_id")
                )
            counts = conn.execute(
                "SELECT reference_count, citation_count, title, doi FROM papers WHERE id=?",
                (paper_id,),
            ).fetchone()
        self._paper_info = {"title": counts["title"], "doi": counts["doi"]} if counts else {}
        self._team_data, self._team_loading = None, False
        self._coverage = coverage(
            refs, later, asked,
            counts["reference_count"] if counts else None,
            counts["citation_count"] if counts else None,
        )
        self._data = {"refs": refs, "later": later, "story": story, "asked": asked,
                      "untold": untold, "partial": partial, "why": why}
        # Which works already here are waiting in the queue, for 插到最前面.
        self._waiting = self.win.waiting(
            [r["here"]["id"] for r in refs + later if r["here"] and not r["here"]["read"]]
        )
        self._view_bar.show()
        self._render()
        self._show_face()
        if self._team == "team":
            self._start_team()

    def _clear(self) -> None:
        """Drop the page and the map; the switch above them stays."""
        self._generation += 1
        self._cards, self._rows, self._done = {}, {}, {}
        self._map = None
        self._graph_note = None
        if self._graph_face is not None:
            # Out of the layout but still a child: until the deferred delete runs
            # it keeps painting where it was, over the new page (seen on macOS).
            self._layout.removeWidget(self._graph_face)
            self._graph_face.hide()
            self._graph_face.deleteLater()
        self._graph_face = None

    def _show_face(self) -> None:
        """Show the face the switch is on; the map is made the first time it is."""
        if self._data is None:
            return
        if self._view == "graph":
            if self._graph_face is None:
                self._build_graph_face()
            self._list_view.hide()
            self._area.show()
            self._graph_face.show()
            self._fit()
            QTimer.singleShot(0, self._fit)
        else:
            self._area.hide()
            self._list_view.show()

    def _set_view(self, view: str) -> None:
        if view == self._view:
            return
        self._view = view
        self._view_buttons[view].setChecked(True)
        ui_state.save("ui.cites_view", view)
        self._show_face()

    # ---- the page of 條列 -------------------------------------------------
    def _render(self, keep_scroll: bool = False) -> None:
        """Write the whole page: the summary, the switches and both sides, the
        side not chosen hidden, so flipping between them only shows the other.
        The plain fallback view has no scripts; it gets the chosen side alone."""
        if self._data is None:
            return
        self._cards = {}
        rich = self._list_view.rich
        body = [f"<style>{_page_css(self.pal)}</style>"] if rich else []
        body += ['<div class="cites">', self._story_html(), self._bar_html()]
        for side in ("refs", "later"):
            rows = self._side_rows(side)
            self._rows[side] = rows
            for index, r in enumerate(rows):
                self._remember(side, f"c-{side}-{index}", r)
            if rich or side == self._side:
                body.append(self._side_html(side, rows))
        body.append("</div>")
        if rich:
            body.append(f"<script>{_PAGE_SCRIPT}</script>")
            self._page_ready = False
        self._list_view.setHtml("".join(body), keep_scroll=keep_scroll)

    def _page_loaded(self, _ok: bool) -> None:
        self._page_ready = True
        waiting, self._waiting_js = self._waiting_js, []
        for code in waiting:
            self._list_view.view.page().runJavaScript(code)

    def _js(self, code: str) -> None:
        """Run a script on the page, once it has loaded."""
        if not self._list_view.rich:
            return
        if self._page_ready:
            self._list_view.view.page().runJavaScript(code)
        else:
            self._waiting_js.append(code)

    def _side_rows(self, side: str) -> list[dict]:
        if side == "refs":
            rows = self._team_rows("refs", self._data["refs"])
            if self._ref_order == "number":
                rows = sorted(rows, key=lambda r: (
                    int(r["ref_key"]) if str(r.get("ref_key")).isdigit() else 10**6,
                    str(r.get("ref_key")),
                ))
            return rows
        rows = self._team_rows("later", self._data["later"])
        if self._later_order == "cited":
            rows = sorted(rows, key=lambda r: -(r.get("citations") or 0))
        elif self._later_order == "new":
            rows = sorted(rows, key=lambda r: -(r.get("year") or 0))
        return rows

    def _story_html(self) -> str:
        pal, data = self.pal, self._data
        story = data["story"]
        parts = [
            f'<div style="font-size:14px;font-weight:600;color:{pal["ink"]};">研究脈絡'
            + ('&nbsp;&nbsp;<a class="btn" href="cite:story-edit">編輯</a>' if story else "")
            + "</div>",
            _say("依據：" + self._coverage + (" · 已手動修改" if story and story["edited"] else ""),
                 pal["faint"], 11.5),
        ]
        if story and story["summary"]:
            parts.append(_say(story["summary"], pal["ink"], 13))
        if story and story["reading"]:
            parts.append(
                f'<div style="color:{pal["muted"]};font-size:12px;font-weight:600;'
                f'margin-top:6px;">接下來必讀</div>'
            )
            for i, x in enumerate(story["reading"], 1):
                parts.append(
                    f'<div style="font-size:12.5px;margin:0 0 6px;color:{pal["ink"]};">{i}. '
                    f'<span style="color:{pal["faint"]};">[{_esc(x.get("direction"))}]</span> '
                    f"<b>{_esc(x['title'])}</b><br>"
                    f'<span style="color:{pal["muted"]};">{_esc(x.get("why"))}</span></div>'
                )
        if self._busy():
            parts.append(_say(
                "正在深入分析：讀參考文獻、查後續研究並整理脈絡…約三到六分鐘，"
                "完成後這個分頁會自己更新。", pal["muted"], 12.5,
            ))
        else:
            text, action = story_note(data)
            if text:
                parts.append(_say(text, pal["muted"], 12.5))
            if action == "run-all":
                parts.append(_ai_link("cite:run-all", "深入分析", primary=True))
            elif action == "refresh":
                parts.append(_ai_link("cite:refresh", "重新查後續研究並更新脈絡"))
        return _box("".join(parts), pal)

    def _bar_html(self) -> str:
        data = self._data
        sides = _segments("side", (
            (f"參考文獻 {sum(1 for r in data['refs'] if r.get('ref_key'))}", "refs"),
            (f"後續研究 {len(data['later'])}", "later"),
        ), self._side, self.pal)
        orders = "".join(
            _segments(f"order-{side}", options, current, self.pal, action="order",
                      hidden=side != self._side)
            for side, options, current in (
                ("refs", (("值得讀的排前面", "verdict"), ("照論文編號", "number")),
                 self._ref_order),
                ("later", (("值得讀的排前面", "verdict"), ("被引用最多", "cited"),
                           ("最新", "new")), self._later_order),
            )
        )
        team = _segments("team", (("全域", "all"), ("作者團隊", "team")), self._team, self.pal,
                         title="作者團隊：只看和這篇有共同作者或同一研究機構的前作與後續研究"
                               "（作者與機構資料來自 OpenAlex）")
        note = self._team_note()
        return (
            f'<div class="bar">{sides}&nbsp;&nbsp;{orders}&nbsp;&nbsp;{team}</div>'
            f'<div id="team-note" style="color:{self.pal["faint"]};font-size:11.5px;'
            f'margin:6px 0 0;{"" if note else "display:none;"}">{_esc(note)}</div>'
        )

    def _side_html(self, side: str, rows: list[dict]) -> str:
        pal = self.pal
        shown = "" if side == self._side else "display:none;"
        parts = [f'<div id="side-{side}" style="margin-top:10px;{shown}">']
        if side == "refs":
            judged = [r for r in rows if r.get("verdict")]
            if not judged:
                if self._busy():
                    parts.append(_say(
                        "正在讀這篇的引用句並判斷每一筆的用途…一篇大約一兩分鐘。", pal["muted"], 13
                    ))
                else:
                    parts.append(_say(
                        "還沒分析這篇的參考文獻。分析會把每一處引用的句子抓出來,判斷這篇「為什麼」"
                        "引用它——當 baseline、資料來源、方法出處、被推翻的說法,還是背景鋪陳——"
                        "再給一個值不值得讀的判斷。", pal["muted"], 13,
                    ))
                    parts.append(_ai_link("cite:run-cites", "分析這篇的參考文獻", primary=True))
            else:
                # Say how many verdicts rest on a citing sentence and how many on a
                # title alone: the second kind is a much weaker answer.
                quoted = sum(1 for r in judged if r.get("basis") == "context")
                worth = sum(1 for r in judged if r.get("verdict") in ("必讀", "值得"))
                parts.append(_say(
                    f"{len(judged)} 筆 · {quoted} 筆讀得到引用句,"
                    f"{len(judged) - quoted} 筆只能從標題判斷 · "
                    f"其中 {worth} 筆是這篇建立在其上、值得往下讀的", pal["faint"], 11.5,
                ))
        elif not rows:
            asked = self._data["asked"]
            if self._busy():
                text = "正在向 OpenAlex 和 Semantic Scholar 查引用這篇的論文…"
            elif asked:
                text = f"目前沒有論文引用它(OpenAlex 與 Semantic Scholar 都查過,{asked[:10]})。"
            else:
                text = "還沒查。會向 OpenAlex 和 Semantic Scholar 查整個領域裡引用這篇的論文。"
            parts.append(_say(text, pal["muted"], 13))
            if not asked and not self._busy():
                parts.append(_ai_link("cite:run-followups", "查後續研究", primary=True))
        else:
            with_ctx = sum(1 for r in rows if r.get("contexts"))
            parts.append(_say(
                f"{len(rows)} 篇 · {with_ctx} 篇讀得到它引用這篇的原句,其餘依摘要或標題判斷",
                pal["faint"], 11.5,
            ))
        parts.extend(self._card_html(side, index, r) for index, r in enumerate(rows))
        parts.append("</div>")
        return "".join(parts)

    def _card_html(self, side: str, index: int, r: dict) -> str:
        pal = self.pal
        anchor = f"c-{side}-{index}"
        verdict = r.get("verdict") or ""
        fg, bg = VERDICT_COLOURS.get(verdict, ("muted", "sunk"))
        parts = []
        match = (self._team_data or {}).get(side, {}).get(
            r.get("ref_key") if side == "refs" else r.get("work_id")
        )
        if self._team == "team" and match:
            said = []
            if match["authors"]:
                said.append("同作者：" + "、".join(match["authors"]))
            if match["institutions"]:
                said.append("同機構：" + "、".join(match["institutions"]))
            parts.append(_say(" · ".join(said), pal["accent"], 11.5))
        pill = (
            f'<span style="background:{pal[bg]};color:{pal[fg]};font-weight:600;">'
            f"&nbsp;{_esc(verdict)}&nbsp;</span> " if verdict else ""
        )
        if side == "refs":
            key = f"[{r['ref_key']}] " if r.get("ref_key") else ""
            title = key + (r.get("title") or "(無法辨識是哪一篇)")
            fields = (("與原文的關係", r.get("purpose")), ("這篇在做什麼", r.get("gist")),
                      ("判斷", r.get("why")))
            quote = "原文引用它的句子"
        else:
            title = r.get("title") or ""
            fields = (("與原文的關係", r.get("relation")), ("判斷", r.get("why")))
            quote = "它引用原文的句子"
        parts.append(
            f'<div style="font-size:13.5px;color:{pal["ink"]};">{pill}<b>{_esc(title)}</b></div>'
        )
        meta = self._meta(r)
        if meta:
            parts.append(_say(meta, pal["faint"], 11))
        rows = [(label, value) for label, value in fields if value]
        if rows:
            parts.append(
                '<table class="fields" cellspacing="0" cellpadding="0" style="margin-top:6px;">'
                + "".join(
                    f'<tr><td class="name" style="color:{pal["accent"]};">{label}&nbsp;&nbsp;</td>'
                    f'<td style="color:{pal["muted"]};">{_esc(value)}</td></tr>'
                    for label, value in rows
                )
                + "</table>"
            )
        if r.get("contexts"):
            parts.append(
                f'<div class="quote" style="color:{pal["faint"]};font-size:11.5px;'
                f'margin-top:4px;">{quote}:「{_esc(r["contexts"][0][:320])}」</div>'
            )
        elif side == "later" and not r.get("abstract"):
            parts.append(_say("沒有摘要也沒有引用句,只能從標題判斷。", pal["faint"], 11.5))
        parts.append(self._actions_html(side, index, r))
        return (
            f'<a name="{anchor}"></a>'
            f'<table id="{anchor}" class="card" width="100%" cellspacing="0" cellpadding="0" '
            f'style="margin-bottom:10px;border:1px solid {pal["border"]};">'
            f'<tr><td class="edge" width="3" bgcolor="{pal[fg]}"></td>'
            f'<td class="body" bgcolor="{pal["surface"]}">{"".join(parts)}</td></tr></table>'
        )

    def _actions_html(self, side: str, index: int, r: dict) -> str:
        here = r.get("here")
        title = r.get("title") or ""
        # When the model cannot tell which paper a marker points at, it says so in
        # prose rather than inventing a title. Offering to look that up would send a
        # sentence to Semantic Scholar and file whatever came back.
        looks_like_title = len([w for w in title.split() if w.isascii()]) >= 3 and len(title) > 15
        links = []
        if here:
            links.append(("open", "已讀 · 開啟" if here["read"] else "開啟"))
            # Following the context only works if you can act on it: a paper this
            # one rests on is useless 3000 rows down the queue.
            if not here["read"] and here["id"] in self._waiting:
                links.append(("lift", "插到最前面"))
        elif r.get("doi") or r.get("s2_id") or looks_like_title:
            links.append(("add", "加入清單"))
        if side == "later" or r.get("ref_key"):
            links.append(("edit", "編輯"))
        out = []
        for action, label in links:
            done = self._done.get((action, id(r)))
            if done:
                out.append(
                    f'<span class="done" style="color:{self.pal["faint"]};">{_esc(done)}</span>'
                )
            else:
                out.append(
                    f'<a class="btn" id="a-{action}-{side}-{index}" '
                    f'href="cite:{action}:{side}:{index}">{label}</a>'
                )
        return f'<div class="actions">{"&nbsp; ".join(out)}</div>' if out else ""

    def _link(self, url) -> None:
        """Every link on the page of 條列 comes here."""
        parts = url.toString().split(":")
        if parts[0] != "cite":
            if url.scheme() in ("http", "https"):
                QDesktopServices.openUrl(url)
            return
        action = parts[1] if len(parts) > 1 else ""
        value = parts[2] if len(parts) > 2 else ""
        if action == "side" and value in ("refs", "later"):
            self._set_side(value)
        elif action == "order" and value:
            self._set_order(value)
        elif action == "team" and value in ("all", "team"):
            self._set_team(value)
        elif action == "story-edit" and self._data and self._data["story"]:
            self._edit_story(self._data["story"])
        elif action == "run-all":
            self._run_all()
        elif action == "refresh":
            self._refresh_context()
        elif action == "run-cites":
            self._run_cites()
        elif action == "run-followups":
            self._run_followups()
        elif len(parts) == 4 and parts[3].isdigit():
            rows = self._rows.get(value, [])
            index = int(parts[3])
            if index < len(rows):
                self._act(action, value, index, rows[index])

    def _act(self, action: str, side: str, index: int, r: dict) -> None:
        here = r.get("here")
        if action == "open" and here:
            self.win.open_paper(here["id"])
        elif action == "lift" and here:
            self.win.promote(here["id"])
            self._mark(action, side, index, r, "已插到最前面")
        elif action == "add":
            # The import runs for a few seconds against Semantic Scholar; the
            # switcher picks it up on the next refresh rather than blocking reading.
            where = self._send_to_list({"title": r.get("title") or "", "doi": r.get("doi")})
            self._mark(action, side, index, r, f"已送到「{where}」")
        elif action == "edit":
            self._edit_item("ref" if side == "refs" else "later", r)

    def _mark(self, action: str, side: str, index: int, r: dict, text: str) -> None:
        self._done[(action, id(r))] = text
        if self._list_view.rich:
            self._js(f"mark({json.dumps(f'a-{action}-{side}-{index}')}, {json.dumps(text)})")
        else:
            self._render(keep_scroll=True)

    def _set_side(self, side: str) -> None:
        if side == self._side:
            return
        self._side = side
        if self._data is None:
            return
        if self._list_view.rich:
            self._js(f"showSide({json.dumps(side)})")
        else:
            self._render()

    def _set_order(self, order: str) -> None:
        if self._side == "refs":
            self._ref_order = order
        else:
            self._later_order = order
        self._render()

    # ---- the paper's own team ---------------------------------------------
    def _set_team(self, team: str) -> None:
        if team == self._team:
            return
        self._team = team
        if team == "team" and self._team_data is None:
            self._start_team()
        self._render(keep_scroll=True)

    def _team_step(self, generation: int, done: int, total: int) -> None:
        if generation == self._generation and self._team == "team":
            self._team_progress = f"正在向 OpenAlex 查作者與機構…{done}/{total}"
            self._js(f"say('team-note', {json.dumps(self._team_progress)})")

    def _team_done(self, generation: int, result: dict) -> None:
        if generation != self._generation:
            return
        self._team_data, self._team_loading = result, False
        if self._team == "team":
            self._render(keep_scroll=True)

    def _team_note(self) -> str:
        data = self._team_data
        if self._team != "team":
            return ""
        if data is None:
            return self._team_progress or "正在向 OpenAlex 查作者與機構…"
        if not data.get("own"):
            return "OpenAlex 找不到這篇論文，無法比對作者與機構。"
        shown = len(data["refs"]) + len(data["later"])
        return (
            f"和這篇有共同作者或同一機構的：參考文獻 {len(data['refs'])} 篇、"
            f"後續研究 {len(data['later'])} 篇（OpenAlex 查到 {data['known']}/"
            f"{data['total']} 篇的作者資料）"
            + ("" if shown else "。這篇的團隊沒有出現在它的承先啟後裡。")
        )

    # ---- finding one work again ---------------------------------------------
    def _remember(self, side: str, anchor: str, r: dict) -> None:
        if side == "refs" and r.get("ref_key"):
            self._cards[("ref", str(r["ref_key"]))] = (side, anchor)
        if r.get("title"):
            self._cards.setdefault(("title", title_key(r["title"])), (side, anchor))

    def focus(self, source: dict) -> str:
        """Show the work a slide cites, in whichever view is open. Returns what
        happened, for the status line.

        A deck names a reference by its marker (cite:12) and a later work by its
        position in the list at generation time (later:3), which moves as the
        field is asked again -- so a later work is found by its title instead.
        """
        sid = str(source.get("id") or "")
        label = str(source.get("label") or "")
        if sid == "context":
            if self._view == "graph":
                self._area.verticalScrollBar().setValue(0)
            else:
                self._list_view.scroll_to_top()
            return "已跳到「脈絡」分頁最上方的研究脈絡。"
        if sid.startswith("cite:"):
            side, key = "refs", ("ref", sid.removeprefix("cite:"))
            title = label.split("] ", 1)[1] if "] " in label else ""
        elif sid.startswith("later:"):
            side, key = "later", None
            title = label.split("：", 1)[1] if "：" in label else label
        else:
            return ""
        wanted = [k for k in (key, ("title", title_key(title)) if title else None) if k]
        if self._view == "graph":
            self._show_face()
            dot = self._find_dot(side, sid, title)
            if dot is None and not self._graph_all:
                # The map draws the most telling neighbours first; the one asked
                # for may be among those left out.
                self._set_density(True)
                dot = self._find_dot(side, sid, title)
            if dot is None:
                return (
                    "引用圖上找不到這一篇（可能是內文找不到引用句，沒有畫在圖上）；"
                    "切到條列可以看到。"
                )
            self._map.pin(dot)
            QTimer.singleShot(60, lambda: self._area.ensureWidgetVisible(self._map))
            return f"已在引用圖上標示：{dot.node.title[:60]}"
        self._show_face()
        hit = next((self._cards[k] for k in wanted if k in self._cards), None)
        if hit is None:
            return "「脈絡」分頁裡找不到這一篇；簡報產生之後，引用分析可能重新整理過。"
        side, anchor = hit
        self._set_side(side)
        if self._list_view.rich:
            self._js(f"flash({json.dumps(anchor)})")
        else:
            self._list_view.view.scrollToAnchor(anchor)
        return "已跳到「脈絡」分頁的" + ("參考文獻" if side == "refs" else "後續研究") + "這一筆。"

    def _fit(self) -> None:
        # A scroll area does not re-measure wrapped text that is replaced while it is
        # on screen: the page stays the height of the window and every card is
        # squeezed to a line. A minimum height measured at the real width holds it.
        self._layout.activate()
        width = self._area.viewport().width()
        self._inner.setMinimumHeight(max(0, self._inner.heightForWidth(width)))

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._fit()

    def _reload(self) -> None:
        if self.paper_id:
            self.load(self.paper_id)

    def _face(self) -> tuple[QWidget, QVBoxLayout]:
        face = QWidget()
        layout = QVBoxLayout(face)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        face.hide()
        # Above the stretch that closes the page.
        self._layout.insertWidget(self._layout.count() - 1, face)
        return face, layout

    # ---- small parts -----------------------------------------------------

    def _label(
        self, text: str, size: float = 12.5, colour: str = "muted", rich: bool = False
    ) -> QLabel:
        label = _Text(text)
        label.setWordWrap(True)
        if rich:
            label.setTextFormat(Qt.TextFormat.RichText)
        label.setTextInteractionFlags(SELECTABLE)
        label.setStyleSheet(f"color:{self.pal[colour]};font-size:{size}px;border:0;")
        return label

    def _button(self, text: str, primary: bool = False) -> QPushButton:
        pal = self.pal
        button = QPushButton(text)
        button.setStyleSheet(
            f"background:{pal['accent']};color:#ffffff;border:1px solid {pal['accent']};"
            f"border-radius:4px;padding:6px 14px;font-weight:600;font-size:12px;"
            if primary
            else f"background:{pal['surface']};color:{pal['ink']};"
            f"border:1px solid {pal['firm']};border-radius:4px;padding:4px 10px;"
            f"font-size:11.5px;"
        )
        return button

    def _frame(self, accent: str | None = None) -> tuple[QFrame, QVBoxLayout]:
        pal = self.pal
        box = QFrame()
        box.setObjectName("card")
        left = f"border-left:3px solid {pal[accent]};" if accent else ""
        box.setStyleSheet(
            f"QFrame#card{{background:{pal['surface']};border:1px solid {pal['border']};"
            f"{left}border-radius:6px;}}"
        )
        layout = QVBoxLayout(box)
        layout.setContentsMargins(14, 11, 14, 12)
        layout.setSpacing(6)
        return box, layout

    def _heading(self, text: str) -> QLabel:
        label = QLabel(text)
        label.setStyleSheet(
            f"color:{self.pal['muted']};font-size:12px;font-weight:600;border:0;margin-top:4px;"
        )
        return label

    def _ai_button(self, text: str, primary: bool = False) -> QPushButton:
        return ai_style.mark(QPushButton(text), self.pal, primary)

    @staticmethod
    def _running(job: subprocess.Popen | None) -> bool:
        return job is not None and job.poll() is None

    def lookups_running(self) -> bool:
        """This tab's own reference or later-work job, apart from 深入分析."""
        return self._running(self._follow_job) or self._running(self._cites_job)

    def _busy(self) -> bool:
        return self.lookups_running() or bool(
            self.paper_id and self.win.analysis_running(self.paper_id)
        )

    # ---- 研究脈絡 and the switches, for the map --------------------------------

    def _story(self, story: dict | None, refs: list, later: list, asked: str | None) -> QWidget:
        box, layout = self._frame()
        head = QHBoxLayout()
        title = QLabel("研究脈絡")
        title.setStyleSheet(f"color:{self.pal['ink']};font-size:14px;font-weight:600;border:0;")
        head.addWidget(title)
        head.addStretch(1)
        if story:
            edit = self._button("編輯")
            edit.clicked.connect(lambda: self._edit_story(story))
            head.addWidget(edit)
        layout.addLayout(head)

        layout.addWidget(self._label(
            "依據：" + self._coverage
            + (" · 已手動修改" if story and story["edited"] else ""),
            11.5, "faint",
        ))

        if story and story["summary"]:
            layout.addWidget(self._label(story["summary"], 13, "ink"))
        if story and story["reading"]:
            layout.addWidget(self._heading("接下來必讀"))
            items = []
            for i, x in enumerate(story["reading"], 1):
                tag = (
                    f"<span style='color:{self.pal['faint']};'>"
                    f"[{html.escape(x.get('direction') or '')}]</span> "
                )
                items.append(
                    f"<p style='margin:0 0 6px 0;'>{i}. {tag}<b>{html.escape(x['title'])}</b>"
                    f"<br><span style='color:{self.pal['muted']};'>"
                    f"{html.escape(x.get('why') or '')}</span></p>"
                )
            layout.addWidget(self._label("".join(items), 12.5, "ink", rich=True))

        if self._busy():
            layout.addWidget(self._label(
                "正在深入分析：讀參考文獻、查後續研究並整理脈絡…約三到六分鐘，"
                "完成後這個分頁會自己更新。"
            ))
        else:
            text, action = story_note(self._data)
            if text:
                layout.addWidget(self._label(text))
            if action == "run-all":
                go = self._ai_button("深入分析", primary=True)
                go.clicked.connect(self._run_all)
                layout.addWidget(go, 0, Qt.AlignmentFlag.AlignLeft)
            elif action == "refresh":
                again = self._ai_button("重新查後續研究並更新脈絡")
                again.clicked.connect(self._refresh_context)
                layout.addWidget(again, 0, Qt.AlignmentFlag.AlignLeft)
        return box

    def _segmented(self, options, current: str, pick) -> tuple[QWidget, dict]:
        """Joined buttons, one lit: the states side by side rather than a button
        whose label is the state it is not in. Restyled by Qt on toggle, never
        rebuilt."""
        pal = self.pal
        bar = QWidget()
        row = QHBoxLayout(bar)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(0)
        group = QButtonGroup(bar)
        buttons = {}
        last = len(options) - 1
        for i, (label, key) in enumerate(options):
            b = QPushButton(label)
            b.setCheckable(True)
            b.setChecked(key == current)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            left = "4px" if i == 0 else "0"
            right = "4px" if i == last else "0"
            b.setStyleSheet(
                f"QPushButton{{background:{pal['surface']};color:{pal['muted']};"
                f"border:1px solid {pal['firm']};{'' if i == 0 else 'border-left:0;'}"
                f"border-top-left-radius:{left};border-bottom-left-radius:{left};"
                f"border-top-right-radius:{right};border-bottom-right-radius:{right};"
                f"padding:4px 14px;font-size:12px;font-weight:600;}}"
                f"QPushButton:hover:!checked{{background:{pal['sunk']};}}"
                f"QPushButton:checked{{background:{pal['accent']};color:#ffffff;"
                f"border-color:{pal['accent']};}}"
            )
            group.addButton(b)
            b.clicked.connect(lambda _=False, k=key: pick(k))
            row.addWidget(b)
            buttons[key] = b
        return bar, buttons

    def _start_team(self) -> None:
        if self._team_loading or self._data is None:
            return
        self._team_loading = True
        generation = self._generation
        info = dict(self._paper_info)
        refs, later = list(self._data["refs"]), list(self._data["later"])

        def look() -> None:
            result = lineage_team.team(
                info, refs, later,
                progress=lambda done, total: self.team_progress.emit(generation, done, total),
            )
            self.team_ready.emit(generation, result)

        threading.Thread(target=look, name="lineage-team", daemon=True).start()

    def _team_rows(self, side: str, rows: list) -> list:
        """The side's rows under the 作者團隊 filter; all of them under 全域."""
        if self._team != "team":
            return rows
        found = (self._team_data or {}).get(side, {})
        key = "ref_key" if side == "refs" else "work_id"
        return [r for r in rows if r.get(key) in found]

    # ---- the map -----------------------------------------------------------

    def _build_graph_face(self) -> None:
        data = self._data
        face, layout = self._face()
        self._graph_face = face
        self._fill_graph(layout)
        # The map is what was asked for; the summary follows it rather than pushing
        # it below the fold.
        layout.addWidget(self._story(data["story"], data["refs"], data["later"], data["asked"]))

    def _rebuild_graph(self) -> None:
        """Only the map: the lists do not change when it is redrawn."""
        if self._graph_face is None:
            return
        layout = self._graph_face.layout()
        story = layout.takeAt(layout.count() - 1).widget()
        while layout.count():
            item = layout.takeAt(0)
            if item.widget():
                item.widget().hide()
                item.widget().deleteLater()
        self._map = None
        self._fill_graph(layout)
        layout.addWidget(story)
        if self._view == "graph":
            self._fit()

    def _fill_graph(self, layout: QVBoxLayout) -> None:
        with connect() as conn:
            whole = citegraph.build(conn, self.paper_id)
        if not whole.nodes:
            return
        graph = citegraph.pick(whole, None if self._graph_all else GRAPH_LIMIT)
        centre = whole.nodes[0].key
        among = sum(1 for a, b in whole.edges if centre not in (a, b))
        refs = sum(1 for n in whole.nodes if n.side == "ref")
        later = sum(1 for n in whole.nodes if n.side == "later")

        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(6)
        shown = f"{self._coverage} · 圖上畫出 {refs + later} 篇"
        if whole.unconfirmed:
            shown += (
                f"(另有 {whole.unconfirmed} 筆只在 Semantic Scholar 的參考文獻表裡、"
                f"內文找不到引用句,可能是錯配,圖上不畫,條列裡看得到)"
            )
        if self._running(self._links_job):
            shown += " · 正在查彼此之間的引用…"
        elif whole.checked:
            shown += f" · 彼此之間的引用 {among} 條"
            if whole.unplaced:
                shown += f"({whole.unplaced} 篇在 Semantic Scholar 上找不到,它們的引用不明)"
        row.addWidget(self._label(shown, 11.5, "faint"), 1)
        # Only a paper analysed before the map existed has never been asked; the
        # lists' own refresh (整理研究脈絡) asks again, so there is no second button.
        if refs + later and not whole.checked and not self._running(self._links_job):
            links = self._button("查彼此引用")
            links.clicked.connect(self._run_links)
            row.addWidget(links)
        holder = QWidget()
        holder.setLayout(row)
        layout.addWidget(holder)
        if sum(graph.hidden.values()) or self._graph_all:
            layout.addWidget(self._density(refs, later))

        self._graph_note = self._label(graph_legend(self.pal), 11.5, "muted", rich=True)
        layout.addWidget(self._graph_note)
        if refs + later == 0:
            layout.addWidget(self._label(
                "還沒有承先啟後的資料。按「深入分析」，參考文獻與後續研究整理好後就會畫在這裡。",
                13,
            ))
        view = CiteMap(self.pal, self.win.open_paper, self._add_node)
        self._map = view
        view.show_graph(graph)
        # As tall as the map needs at this width, up to the window's height, so a
        # small map does not sit in a field of white.
        rect = view.scene().sceneRect()
        width = max(1.0, self._area.viewport().width() - 40.0)
        needed = rect.height() * min(1.0, width / max(rect.width(), 1.0)) + 12
        tallest = max(460, self._area.viewport().height() - 60)
        view.setFixedHeight(int(min(max(needed, 360), tallest)))
        layout.addWidget(view)

    def _density(self, refs: int, later: int) -> QWidget:
        """How many papers to draw."""
        bar = QWidget()
        row = QHBoxLayout(bar)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(0)
        row.addWidget(self._label("顯示:", 11.5, "muted"))
        row.addSpacing(6)
        options, _buttons = self._segmented(
            ((f"每邊最值得看的 {GRAPH_LIMIT} 篇", "top"), (f"全部 {refs + later} 篇", "all")),
            "all" if self._graph_all else "top",
            lambda key: self._set_density(key == "all"),
        )
        row.addWidget(options)
        row.addSpacing(8)
        row.addWidget(self._label(
            "值得讀的判定優先,其次是和其他篇互相引用的,再來是被引用數", 11, "faint"
        ), 1)
        return bar

    def _find_dot(self, side: str, sid: str, title: str):
        if self._map is None:
            return None
        if side == "refs" and sid.startswith("cite:"):
            dot = self._map.dots.get("ref:" + sid.removeprefix("cite:"))
            if dot is not None:
                return dot
        want = title_key(title) if title else ""
        return next(
            (
                d
                for d in self._map.dots.values()
                if d.node.side == ("ref" if side == "refs" else "later")
                and want
                and title_key(d.node.title) == want
            ),
            None,
        )

    def _set_density(self, everything: bool) -> None:
        if everything == self._graph_all:
            return
        self._graph_all = everything
        self._rebuild_graph()

    def _run_links(self) -> None:
        if not self.paper_id or self._running(self._links_job):
            return
        self._links_job = _spawn("cite-links", self.paper_id)
        self._watch.start()
        self._rebuild_graph()

    def _links_done(self) -> None:
        if self._running(self._links_job):
            return
        self._watch.stop()
        self._links_job = None
        self._rebuild_graph()

    def _add_node(self, node: citegraph.Node) -> None:
        where = self._send_to_list({"title": node.title, "doi": node.doi})
        if self._graph_note is not None:
            self._graph_note.setText(f"「{node.label}」已送到「{where}」,幾秒後會出現在清單裡。")

    # ---- cards -----------------------------------------------------------

    def _meta(self, r: dict) -> str:
        meta = [str(x) for x in (r.get("year"), (r.get("venue") or "")[:44]) if x]
        if r.get("citations"):
            meta.append(f"{r['citations']:,} cites")
        if r.get("influential"):
            meta.append("★ influential")
        if r.get("basis") == "title":
            meta.append("文中未抓到引用句")
        if r.get("edited"):
            meta.append("已手動修改")
        return " · ".join(meta)

    # ---- edits -----------------------------------------------------------

    def _edit_item(self, kind: str, r: dict) -> None:
        fields = (
            (("purpose", "與原文的關係"), ("gist", "這篇在做什麼"), ("why", "判斷"))
            if kind == "ref"
            else (("relation", "與原文的關係"), ("why", "判斷"))
        )
        dialog = QDialog(self)
        dialog.setWindowTitle("編輯")
        dialog.resize(560, 380)
        form = QFormLayout(dialog)
        title = QLabel(r.get("title") or "")
        title.setWordWrap(True)
        form.addRow(title)
        verdict = QComboBox()
        verdict.addItems(list(followups.VERDICTS))
        verdict.setCurrentText(r.get("verdict") or "參考")
        form.addRow("判定", verdict)
        boxes = {}
        for key, label in fields:
            box = QPlainTextEdit(r.get(key) or "")
            box.setFixedHeight(72)
            form.addRow(label, box)
            boxes[key] = box
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        form.addRow(buttons)
        if dialog.exec() != QDialog.DialogCode.Accepted or not self.paper_id:
            return
        values = {k: b.toPlainText().strip() for k, b in boxes.items()}
        values["verdict"] = verdict.currentText()
        if kind == "ref":
            followups.edit_reference(self.paper_id, r["ref_key"], **values)
        else:
            followups.edit_followup(self.paper_id, r["work_id"], **values)
        self._reload()

    def _edit_story(self, story: dict) -> None:
        dialog = QDialog(self)
        dialog.setWindowTitle("編輯研究脈絡")
        dialog.resize(640, 540)
        form = QVBoxLayout(dialog)
        form.addWidget(QLabel("承先啟後的敘述"))
        summary = QPlainTextEdit(story["summary"])
        form.addWidget(summary, 1)
        form.addWidget(QLabel("接下來必讀(一行一篇:承先 或 啟後 | 標題 | 理由)"))
        reading = QPlainTextEdit("\n".join(
            f"{x.get('direction', '')} | {x['title']} | {x.get('why', '')}"
            for x in story["reading"]
        ))
        form.addWidget(reading, 1)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        form.addWidget(buttons)
        if dialog.exec() != QDialog.DialogCode.Accepted or not self.paper_id:
            return
        items = []
        for line in reading.toPlainText().splitlines():
            parts = [p.strip() for p in line.split("|")]
            if len(parts) >= 2 and parts[1]:
                items.append({
                    "direction": parts[0],
                    "title": parts[1],
                    "why": parts[2] if len(parts) > 2 else "",
                })
        followups.edit_overview(self.paper_id, summary.toPlainText().strip(), items)
        self._reload()

    # ---- background work -------------------------------------------------

    @requires_ai("citations")
    def _run_cites(self) -> None:
        if not self.paper_id or self._running(self._cites_job):
            return
        self._cites_job = _spawn("cites", self.paper_id)
        self._reload()

    @requires_ai("followups", "overview")
    def _run_followups(self) -> None:
        if not self.paper_id or self._running(self._follow_job):
            return
        self._follow_job = _spawn("followups", self.paper_id)
        self._reload()

    def _run_all(self) -> None:
        """The whole 深入分析, the same job as the button beside the tabs, so the
        reader tracks it in one place and the dive is made along with the context."""
        if self.paper_id:
            self.win.reader_page.start_analysis()
            self._reload()

    @requires_ai("citations", "followups", "overview")
    def _refresh_context(self) -> None:
        """Ask the field again: later work keeps arriving after the first look."""
        if not self.paper_id or self._busy():
            return
        self._follow_job = _spawn("followups", self.paper_id, "--with-cites")
        self._reload()

    def _send_to_list(self, row: dict) -> str:
        """Start adding a work to the open list; returns the list's name."""
        target = self.win.active_list or SPILLOVER_ID
        args = ["list-add", target, row["title"]]
        # With the publisher's DOI there is nothing to search for and nothing to get
        # wrong -- it names the paper outright.
        if row.get("doi"):
            args += ["--doi", row["doi"]]
        if not self.win.active_list:
            args += ["--create", SPILLOVER_NAME]
        _spawn(*args)
        return SPILLOVER_NAME if target == SPILLOVER_ID else target
