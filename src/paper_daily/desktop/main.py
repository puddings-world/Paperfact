"""The desktop reader.

Two screens. The queue, which you can search, filter and jump around in; and the
reading desk, which puts the paper as it actually looks on the left and the deep
dive, your notes and a question box on the right.

It reads `papers.db` directly. That is the whole point of it being a desktop app:
nothing goes through a website, nothing needs an approval prompt, and the notes and
the conversation live in the same file as the corpus.
"""

from __future__ import annotations

import hashlib
import html
import json
import os
import sqlite3
import subprocess
import sys
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QByteArray, Qt, QTimer, QUrl
from PySide6.QtGui import (
    QDesktopServices,
    QFont,
    QGuiApplication,
    QIcon,
    QKeySequence,
    QShortcut,
)
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSizePolicy,
    QSplitter,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from paper_daily import (
    closeread,
    llm,
    pdf_highlights,
    pocket,
    resources,
    runtime,
    translate,
    venues,
)
from paper_daily import queue as qmod
from paper_daily.config import DATA_DIR, PDF_DIR, ROOT, ensure_dirs
from paper_daily.desktop import (
    ai_style,
    button_style,
    fonts,
    pdfpane,
    reading,
    rich_view,
    ui_state,
    window_events,
)
from paper_daily.desktop.add_dialog import run_add
from paper_daily.desktop.ai_access import ANALYSIS_TASKS, requires_ai
from paper_daily.desktop.analysis_bar import AnalysisBar
from paper_daily.desktop.ask import AskRunner, build_prompt
from paper_daily.desktop.cites_pane import CitesPane, _spawn
from paper_daily.desktop.fetcher import FetchRunner
from paper_daily.desktop.figure_pane import FigurePane
from paper_daily.desktop.flow_layout import FlowLayout
from paper_daily.desktop.focus_scope import scopes
from paper_daily.desktop.import_dialog import run_import
from paper_daily.desktop.key_hints import KeyHints
from paper_daily.desktop.note_editor import NoteEditor
from paper_daily.desktop.off_thread import OffThread, warm_up
from paper_daily.desktop.pocket_dialog import PocketDialog
from paper_daily.desktop.presentation_pane import PresentationPane
from paper_daily.desktop.queue_view import QueuePage
from paper_daily.store import connect, get_kv, init_db, now

LIGHT = {
    "ground": "#fbfbfd", "surface": "#ffffff", "sunk": "#f2f3f7",
    "ink": "#14161c", "muted": "#5a6170", "faint": "#868ca0",
    "border": "#e3e5ec", "firm": "#cdd1dd",
    "accent": "#2f5bd8", "accentSoft": "#eaeffc",
    "award": "#b4531a", "awardSoft": "#fbeee4",
    "done": "#2f7d55", "doneSoft": "#e6f3ea",
    "warn": "#b42318", "warnSoft": "#fdecea",
    # Buttons that start AI work (ai_style.py): apart from the blue of navigation.
    "ai": "#6d3fc4", "aiSoft": "#f3eefc", "aiStrong": "#56309e", "onAi": "#ffffff",
}
DARK = {
    "ground": "#101218", "surface": "#171a22", "sunk": "#0b0d12",
    "ink": "#e6e8ef", "muted": "#9aa1b1", "faint": "#6f7789",
    "border": "#262a35", "firm": "#383f4e",
    "accent": "#7b9bff", "accentSoft": "#1b2440",
    "award": "#e8934f", "awardSoft": "#2e2013",
    "done": "#67c08d", "doneSoft": "#132a1e",
    "warn": "#ff8a7a", "warnSoft": "#3a1714",
    "ai": "#b59aff", "aiSoft": "#231c3a", "aiStrong": "#cbb8ff", "onAi": "#160f2b",
}

# The AI notice line: its 6px top margin plus one line of text in a box.
AI_ROW_HEIGHT = 34
CHEVRON = Path(__file__).with_name("chevron-down.svg").as_posix()
CHECK = Path(__file__).with_name("check.svg").as_posix()


def ghost(button: QPushButton) -> QPushButton:
    """A borderless button, for settings and navigation beside the main actions."""
    button.setProperty("ghost", True)
    return button

SEED_QUESTIONS = [
    ("核心洞見是什麼", "這篇的核心洞見用一句話說是什麼?為什麼它在當時是不顯然的?"),
    ("審稿人會攻擊哪裡", "這篇的實驗有哪些沒有證明到的地方?一個嚴格的審稿人會從哪裡切入?"),
    ("和前作差在哪", "這個方法和它的前作差在哪?具體是哪一個設計選擇造成差異?"),
    ("關鍵推導逐步展開", "請把這篇的關鍵推導一步一步寫出來,每一步的式子用 LaTeX。"),
]


def palette() -> dict[str, str]:
    try:
        scheme = QGuiApplication.styleHints().colorScheme()
        dark = scheme == Qt.ColorScheme.Dark
    except Exception:
        dark = False
    return DARK if dark else LIGHT


@dataclass
class Paper:
    id: str
    title: str
    venue: str
    year: int
    award: str | None
    paper_type: str | None
    authors: list[str]
    abstract: str | None
    citations: int | None
    is_canon: bool
    pdf_url: str | None
    page_url: str | None
    arxiv_id: str | None
    role: str
    reason: str | None
    state: str
    touched_at: str | None
    dependents: int = 0
    # When it was marked read. Opening a paper is not reading it, so this, not
    # touched_at, is what "read" sorts and filters by.
    read_at: str | None = None
    pinned: bool = False
    # What exists of the analysis (see analyze.py): the deep dive, 承先, 啟後.
    has_dive: bool = False
    has_cites: bool = False
    has_later: bool = False
    # Every source was tried and none had the PDF: it needs a hand.
    pdf_failed: bool = False
    _has_pdf: bool | None = None
    # When it was last opened here, for the 最近開啟 sort; local view history.
    opened_at: str | None = None

    @property
    def read(self) -> bool:
        return self.state == "read"

    @property
    def pdf_path(self) -> Path:
        import re

        return PDF_DIR / (re.sub(r"[^A-Za-z0-9._-]", "_", self.id) + ".pdf")

    @property
    def has_pdf(self) -> bool:
        """Cached: the delegate asks this on every repaint of every visible row, and
        the PDF filter asks it of all 5000, so it must not be a stat() each time."""
        if self._has_pdf is None:
            self._has_pdf = self.pdf_path.exists()
        return self._has_pdf


def _row_to_paper(r: sqlite3.Row) -> Paper:
    try:
        authors = json.loads(r["authors_json"] or "[]")
    except (json.JSONDecodeError, TypeError):
        authors = []
    return Paper(
        id=r["id"], title=r["title"], venue=r["venue"], year=r["year"],
        award=r["award"], paper_type=r["paper_type"], authors=authors,
        abstract=r["abstract"], citations=r["citation_count"],
        is_canon=bool(r["is_canon"]), pdf_url=r["pdf_url"], page_url=r["page_url"],
        arxiv_id=r["arxiv_id"], role=r["role"] or "main", reason=r["reason"],
        state=r["state"] or "pending",
        touched_at=r["read_at"] or r["delivered_at"],
        dependents=r["dependents"] or 0,
        read_at=r["read_at"] if r["state"] == "read" else None,
        has_dive=bool(r["has_dive"]),
        has_cites=bool(r["has_cites"]),
        has_later=bool(r["has_later"]),
        pdf_failed=bool(r["pdf_failed"]),
    )


class Data:
    """Everything the window needs from papers.db."""

    # `dependents` is how many papers in the corpus are known to build on this one.
    # It is the only ranking signal the corpus produces about itself, and it is what
    # the 地基 filter sorts by: read what everything else leans on.
    QUEUE_SQL = (
        "SELECT p.*, q.role, q.reason, q.state, q.rank, q.read_at, q.delivered_at, "
        "       (SELECT COUNT(*) FROM refs r WHERE r.ref_paper_id = p.id) dependents, "
        "       EXISTS(SELECT 1 FROM dives d JOIN close_readings c ON c.paper_id = d.paper_id "
        "              WHERE d.paper_id = p.id) has_dive, "
        "       EXISTS(SELECT 1 FROM cites c WHERE c.paper_id = p.id) has_cites, "
        "       EXISTS(SELECT 1 FROM kv WHERE kv.key = 'followups.checked.' || p.id) has_later, "
        "       EXISTS(SELECT 1 FROM kv WHERE kv.key = 'analyze.failed.pdf.' || p.id "
        "              AND kv.value != 'null') pdf_failed "
        "FROM queue q JOIN papers p ON p.id = q.paper_id "
        "WHERE q.state != 'skipped' ORDER BY q.rank LIMIT ?"
    )

    # A list is ordered by the order someone put it in, not by ranking, and its
    # read/delivered state lives in list_papers so the nightly rebuild cannot touch it.
    LIST_SQL = (
        "SELECT p.*, 'list' role, lp.citation reason, lp.state, lp.position rank, "
        "       lp.read_at, lp.delivered_at, "
        "       (SELECT COUNT(*) FROM refs r WHERE r.ref_paper_id = p.id) dependents, "
        "       EXISTS(SELECT 1 FROM dives d JOIN close_readings c ON c.paper_id = d.paper_id "
        "              WHERE d.paper_id = p.id) has_dive, "
        "       EXISTS(SELECT 1 FROM cites c WHERE c.paper_id = p.id) has_cites, "
        "       EXISTS(SELECT 1 FROM kv WHERE kv.key = 'followups.checked.' || p.id) has_later, "
        "       EXISTS(SELECT 1 FROM kv WHERE kv.key = 'analyze.failed.pdf.' || p.id "
        "              AND kv.value != 'null') pdf_failed "
        "FROM list_papers lp JOIN papers p ON p.id = lp.paper_id "
        "WHERE lp.list_id = ? ORDER BY lp.position LIMIT ?"
    )

    def queue(self, limit: int = 100_000, list_id: str | None = None) -> list[Paper]:
        with connect() as conn:
            if list_id:
                rows = conn.execute(self.LIST_SQL, (list_id, limit))
            else:
                rows = conn.execute(self.QUEUE_SQL, (limit,))
            return [_row_to_paper(r) for r in rows]

    def pins(self, scope: str) -> set[str]:
        with connect() as conn:
            rows = conn.execute("SELECT paper_id FROM pins WHERE scope=?", (scope,))
            return {r[0] for r in rows}

    def set_pin(self, scope: str, paper_id: str, on: bool) -> None:
        with connect() as conn:
            if on:
                conn.execute(
                    "INSERT OR IGNORE INTO pins(scope, paper_id, pinned_at) VALUES (?,?,?)",
                    (scope, paper_id, now()),
                )
            else:
                conn.execute(
                    "DELETE FROM pins WHERE scope=? AND paper_id=?", (scope, paper_id)
                )

    def dive(self, paper_id: str) -> str | None:
        with connect() as conn:
            row = conn.execute(
                "SELECT body FROM dives WHERE paper_id=?", (paper_id,)
            ).fetchone()
        return row["body"] if row else None

    def save_dive(self, paper_id: str, body: str) -> None:
        with connect() as conn:
            conn.execute(
                "INSERT INTO dives(paper_id, body, written_at) VALUES (?,?,?) "
                "ON CONFLICT(paper_id) DO UPDATE SET body=excluded.body, "
                "written_at=excluded.written_at",
                (paper_id, body, now()),
            )

    def notes(self, paper_id: str) -> list[sqlite3.Row]:
        with connect() as conn:
            return conn.execute(
                "SELECT id, body, created_at, kind, page, anchor FROM notes "
                "WHERE paper_id=? ORDER BY created_at DESC",
                (paper_id,),
            ).fetchall()

    def add_note(
        self,
        paper_id: str,
        body: str,
        kind: str = "note",
        page: int | None = None,
        anchor: str | None = None,
    ) -> int:
        with connect() as conn:
            cur = conn.execute(
                "INSERT INTO notes(paper_id, body, created_at, kind, page, anchor) "
                "VALUES (?,?,?,?,?,?)",
                (paper_id, body, now(), kind, page, anchor),
            )
            return int(cur.lastrowid)

    def update_note(self, note_id: int, body: str) -> None:
        with connect() as conn:
            conn.execute("UPDATE notes SET body=? WHERE id=?", (body, note_id))

    def delete_note(self, note_id: int) -> None:
        with connect() as conn:
            conn.execute("DELETE FROM notes WHERE id=?", (note_id,))

    def delete_chat(self, chat_ids: list[int]) -> None:
        with connect() as conn:
            conn.executemany("DELETE FROM chat WHERE id=?", [(i,) for i in chat_ids])

    def chat(self, paper_id: str) -> list[sqlite3.Row]:
        with connect() as conn:
            return conn.execute(
                "SELECT id, role, body, page, anchor FROM chat WHERE paper_id=? ORDER BY id",
                (paper_id,),
            ).fetchall()

    def add_chat(
        self,
        paper_id: str,
        role: str,
        body: str,
        page: int | None = None,
        anchor: str | None = None,
    ) -> None:
        with connect() as conn:
            conn.execute(
                "INSERT INTO chat(paper_id, role, body, created_at, page, anchor) "
                "VALUES (?,?,?,?,?,?)",
                (paper_id, role, body, now(), page, anchor),
            )

    def full_text(self, paper_id: str) -> str | None:
        import re

        from paper_daily.config import TEXT_DIR

        path = TEXT_DIR / (re.sub(r"[^A-Za-z0-9._-]", "_", paper_id) + ".txt")
        if path.exists():
            return path.read_text(encoding="utf-8")
        return None

    def set_state(self, paper_id: str, state: str, list_id: str | None = None) -> None:
        if not list_id:
            with connect() as conn:
                qmod.mark(conn, paper_id, state)
            return
        column = {"delivered": "delivered_at", "read": "read_at"}.get(state)
        with connect() as conn:
            conn.execute(
                f"UPDATE list_papers SET state=?{', ' + column + '=?' if column else ''} "
                "WHERE list_id=? AND paper_id=?",
                (state, now(), list_id, paper_id) if column else (state, list_id, paper_id),
            )


def _split_quote(body: str) -> tuple[str, str]:
    """A note written against a passage keeps the passage on leading "> " lines.

    Showing the two the same way made the notes tab a wall: what you selected and
    what you thought about it read as one paragraph.
    """
    lines = body.splitlines()
    quote = [ln[1:].strip() for ln in lines if ln.startswith(">")]
    rest = [ln for ln in lines if not ln.startswith(">")]
    return " ".join(quote), "\n".join(rest).strip()


# How a question about a selected passage is put to the model (see _ask_passage).
PASSAGE_MARK = "關於這段原文:"


def _exchanges(rows) -> list[tuple]:
    """Pair each question with the answer that followed it: (question, answer),
    with None for an answer still being written or a question lost to a crash."""
    out: list[tuple] = []
    for r in rows:
        if r["role"] == "user":
            out.append((r, None))
        elif out and out[-1][1] is None and out[-1][0] is not None:
            out[-1] = (out[-1][0], r)
        else:
            out.append((None, r))
    return out


def note_headline(body: str, kind: str) -> tuple[str, str, str]:
    """(headline, passage, content) for a note card.

    A collapsed card shows only the headline: the question for an answer kept from
    問 AI, the first line of anything written by hand. The passage it was
    written about is the way back into the paper, so it is kept apart from both.
    """
    quote, content = _split_quote(body)
    if kind == "ask":
        question, _, passage = quote.partition(PASSAGE_MARK)
        headline = " ".join(question.split())
    else:
        passage, headline = quote, ""
    if not headline:
        first = next((ln for ln in content.splitlines() if ln.strip()), "")
        headline = first.strip().lstrip("#*->|` ").strip()
    if len(headline) > 140:
        headline = headline[:138].rstrip() + "…"
    return headline or "(空白筆記)", " ".join(passage.split()), content


def next_after(papers: list, current_id: str | None):
    """The next unread paper after `current_id` in queue order.

    Separate from the window because this rule is the whole meaning of the 下一篇
    button, and it was wrong once already: taking the first not-read paper re-opened
    whatever was on screen, since opening marks a paper delivered rather than read.
    """
    start = 0
    if current_id is not None:
        position = next((i for i, p in enumerate(papers) if p.id == current_id), None)
        if position is not None:
            start = position + 1

    following = next((p for p in papers[start:] if not p.read), None)
    if following is not None:
        return following
    # Past the end, wrap to anything still unread earlier in the queue -- that is
    # where a promoted lineage paper or one skipped over sits.
    return next((p for p in papers if not p.read), None) if start else None


def shows_reason(title: str, reason: str | None) -> bool:
    """Whether the reason a paper is on its list says anything. A list imported
    from bare titles keeps the title itself, and repeated under the heading it is
    noise, not a reason."""
    return bool(reason) and reason.strip().casefold() != title.strip().casefold()


def tag(text: str, pal: dict[str, str], kind: str = "plain") -> str:
    colours = {
        "plain": (pal["sunk"], pal["muted"], pal["border"]),
        "venue": (pal["sunk"], pal["ink"], pal["firm"]),
        "award": (pal["awardSoft"], pal["award"], pal["award"]),
        "canon": (pal["accentSoft"], pal["accent"], pal["accent"]),
        "read": (pal["doneSoft"], pal["done"], pal["done"]),
    }
    bg, fg, bd = colours.get(kind, colours["plain"])
    return (
        f'<span style="background:{bg};color:{fg};border:1px solid {bd};'
        f'padding:1px 5px;font-size:11px;">{text}</span>'
    )


class ReaderPage(QWidget):
    def __init__(self, window: MainWindow) -> None:
        super().__init__()
        self.win = window
        self.paper: Paper | None = None
        # Where the note being written belongs, carried from the selection that
        # started it to the moment it is saved.
        self._pending: tuple[int, str] | None = None
        self._open_notes: set[int] = set()
        self.runner = AskRunner(self)
        # A separate runner: translating a line should not have to wait behind a
        # question that is still being answered.
        self.translate_runner = AskRunner(self)
        # Its own runner: Google failing hands over to it before that thread has quit.
        self.refine_runner = AskRunner(self)
        self.fetcher = FetchRunner(self)
        self.prepare = OffThread(self)
        QTimer.singleShot(1500, warm_up)
        self._res_job: subprocess.Popen | None = None
        self._res_poll = QTimer(self)
        self._res_poll.setInterval(800)
        self._res_poll.timeout.connect(self._resources_poll)
        pal = window.pal

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        head = QWidget()
        self.paper_header = head
        head.setObjectName("paperHeader")
        head.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
        # By name: unscoped, the bottom rule drew under the title, authors and tags too.
        head.setStyleSheet(
            f"#paperHeader{{background:{pal['surface']};"
            f"border-bottom:1px solid {pal['border']};}}"
        )
        head_layout = QVBoxLayout(head)
        head_layout.setContentsMargins(22, 14, 22, 12)
        head_layout.setSpacing(4)
        self.title = QLabel()
        self.title.setWordWrap(True)
        self.title.setFont(fonts.font(fonts.SERIF, 17, QFont.Weight.DemiBold))
        self.title.setStyleSheet(f"color:{pal['ink']};")
        head_layout.addWidget(self.title)
        self.byline = QLabel()
        self.byline.setWordWrap(True)
        self.byline.setStyleSheet(f"color:{pal['muted']};font-size:12px;")
        head_layout.addWidget(self.byline)
        self.facts = QLabel()
        self.facts.setTextFormat(Qt.TextFormat.RichText)
        self.facts.linkActivated.connect(self._facts_link)
        self.facts.setWordWrap(True)
        head_layout.addWidget(self.facts)
        outer.addWidget(head)

        split = QSplitter(Qt.Orientation.Horizontal)

        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(0)
        bar = FlowLayout()
        bar.setContentsMargins(10, 6, 10, 6)
        self.pdf_note = QLabel("")
        self.pdf_note.setStyleSheet(f"color:{pal['faint']};font-size:11px;")
        for text, slot in (("−", lambda: self._zoom(-1)), ("+", lambda: self._zoom(1)),
                           ("寬度", self._fit)):
            btn = QPushButton(text)
            btn.setFixedWidth(50 if text == "寬度" else 30)
            btn.clicked.connect(slot)
            bar.addWidget(btn)
        bar.addWidget(self.pdf_note)
        # Selection has no affordance of its own, and a feature nobody finds is not a
        # feature. Ctrl+wheel zooms too, which is the other thing people try first.
        hint = QLabel(f"選取原文 → 翻譯 / 寫筆記 / 問這段 · {fonts.ZOOM_WHEEL}縮放")
        hint.setStyleSheet(f"color:{pal['faint']};font-size:11px;")
        hint.setToolTip(hint.text())
        self.highlight_button = QPushButton("螢光筆：關")
        self.highlight_button.setCheckable(True)
        self.highlight_button.setToolTip("開啟後拖曳選字即標記並保存；關閉後點選標記可移除。")
        self.highlight_button.setStyleSheet(
            "QPushButton:checked { background:#ffe96b; color:#29220a; border-color:#c9a62b; }"
        )
        self.highlight_button.toggled.connect(
            lambda on: self.highlight_button.setText("螢光筆：開" if on else "螢光筆：關")
        )
        bar.addWidget(self.highlight_button)
        self.auto_highlights = QCheckBox("自動重點")
        self.auto_highlights.setToolTip(
            "首次開啟 PDF 會分析原文重點、同步素材並連結深度講解；已有結果沿用快取。"
            "AI 標記為綠色，手動為黃色。新重點分析或講解連結會使用 AI 額度。"
        )
        self.auto_highlights.setChecked(True)
        self.auto_highlights.toggled.connect(self._auto_highlights_changed)
        self._highlight_attempts = set()
        bar.addWidget(self.auto_highlights)
        self.find_box = QLineEdit()
        self.find_box.setPlaceholderText(f"搜尋內文 ({fonts.key(QKeySequence.StandardKey.Find)})")
        self.find_box.setClearButtonEnabled(True)
        self.find_box.setMinimumWidth(90)
        self.find_box.setMaximumWidth(190)
        self.find_box.returnPressed.connect(lambda: self._find_step(1))
        self.find_box.textChanged.connect(self._find_reset)
        bar.addWidget(self.find_box)
        self.find_count = QLabel("")
        self.find_count.setStyleSheet(f"color:{pal['faint']};font-size:11px;")
        bar.addWidget(self.find_count)
        # Previous / next match. With nothing typed they had nothing to step
        # through and read as broken, so they appear with the first character.
        self.find_steps: list[QPushButton] = []
        for text, step in (("↑", -1), ("↓", 1)):
            btn = QPushButton(text)
            btn.setFixedWidth(30)
            btn.setToolTip("上一個符合處 (Shift+Enter)" if step < 0 else "下一個符合處 (Enter)")
            btn.clicked.connect(lambda _c=False, s=step: self._find_step(s))
            btn.hide()
            bar.addWidget(btn)
            self.find_steps.append(btn)
        back = QShortcut(QKeySequence("Shift+Return"), self.find_box, lambda: self._find_step(-1))
        back.setContext(Qt.ShortcutContext.WidgetShortcut)
        QShortcut(QKeySequence.StandardKey.FindNext, self, lambda: self._find_step(1))
        QShortcut(QKeySequence.StandardKey.FindPrevious, self, lambda: self._find_step(-1))
        self._hits: list[dict] = []
        self._hit = -1
        self.ask_page_btn = QPushButton("問這一頁")
        self.ask_page_btn.setToolTip("把目前這一頁的內容交給 AI,然後提問")
        self.ask_page_btn.clicked.connect(self._ask_this_page)
        ai_style.mark(self.ask_page_btn, pal)
        bar.addWidget(self.ask_page_btn)
        self.open_external = QPushButton("用系統檢視器開啟")
        self.open_external.clicked.connect(self._open_external)
        bar.addWidget(self.open_external)
        # Last, and only where the row has room left: it is a hint, and its width
        # alone kept the divider from moving left.
        bar.addWidget(hint, optional=True)
        # The toolbar's natural width (~900px) used to be the PDF side's minimum, so
        # the divider could only move right -- and editing slides wants the right
        # side wide. Narrower than that, it wraps onto a second row.
        self.pdf_bar = QWidget()
        self.pdf_bar.setLayout(bar)
        self.pdf_bar.setObjectName("pdfBar")
        self.pdf_bar.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
        self.pdf_bar.setStyleSheet(
            f"#pdfBar{{background:{pal['surface']};border-bottom:1px solid {pal['border']};}}"
        )
        self.pdf_bar.setMinimumWidth(0)
        left_layout.addWidget(self.pdf_bar)
        # The highlights' state and its two actions share one line: as a sentence on
        # its own row with the buttons under it, they pushed the page down two rows.
        highlights = QWidget()
        highlights.setObjectName("highlightRow")
        highlights.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
        highlights.setStyleSheet(
            f"#highlightRow{{background:{pal['ground']};border-bottom:1px solid {pal['border']};}}"
        )
        highlight_actions = QHBoxLayout(highlights)
        highlight_actions.setContentsMargins(12, 5, 10, 5)
        highlight_actions.setSpacing(6)
        self.highlight_status = QLabel("尚未標註原文重點。")
        self.highlight_status.setWordWrap(True)
        self.highlight_status.setMinimumWidth(0)
        self.highlight_status.setStyleSheet(f"color:{pal['muted']};font-size:12px;")
        highlight_actions.addWidget(self.highlight_status, 1)
        self.browse_highlights = ghost(QPushButton("查看重點素材"))
        self.browse_highlights.clicked.connect(lambda: self._show_highlight_material())
        self.prepare_highlights = QPushButton("分析／補上標註")
        self.prepare_highlights.setToolTip("有分析結果就補上原文標記；沒有結果才呼叫 AI。")
        self.prepare_highlights.clicked.connect(self._retry_highlights)
        ai_style.mark(self.prepare_highlights, pal)
        highlight_actions.addWidget(self.browse_highlights)
        highlight_actions.addWidget(self.prepare_highlights)
        left_layout.addWidget(highlights)
        left.setMinimumWidth(240)

        self.pdf = pdfpane.make_pdf_pane(palette=pal)
        selection = getattr(self.pdf, "selection", None)
        if selection is not None:
            selection.translate.connect(self._translate_selection)
            selection.note.connect(self._note_selection)
            selection.ask.connect(self._ask_selection)
            selection.refine.connect(self._translate_with_model)
            selection.highlight.connect(self._highlight_selection)
            selection.picked.connect(
                lambda _text: (
                    self._highlight_selection() if self.highlight_button.isChecked() else None
                )
            )
            selection.erase_highlight.connect(self._erase_selection_highlights)
        left_layout.addWidget(self.pdf, 1)
        self.pdf_missing = QLabel()
        self.pdf_missing.setWordWrap(True)
        self.pdf_missing.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.pdf_missing.setContentsMargins(24, 24, 24, 24)
        self.pdf_missing.setStyleSheet(f"color:{pal['muted']};font-size:13px;")
        self.pdf_missing.setOpenExternalLinks(True)
        self.pdf_missing.hide()
        left_layout.addWidget(self.pdf_missing, 1)
        split.addWidget(left)

        from paper_daily.desktop.reading_layout import ReadingTabs

        self.tabs = ReadingTabs()
        self.dive_view = rich_view.RichView(pal)
        self.dive_view.anchorClicked.connect(self._dive_source)
        self.tabs.addTab(self.dive_view, "深度講解")

        notes = QWidget()
        nl = QVBoxLayout(notes)
        nl.setContentsMargins(14, 12, 14, 12)
        nl.setSpacing(8)
        self.note_edit = QPlainTextEdit()
        self.note_edit.setPlaceholderText("你的結論是什麼?哪裡還說不通?")
        self.note_edit.setStyleSheet(
            f"background:{pal['surface']};color:{pal['ink']};"
            f"border:1px solid {pal['firm']};padding:10px;"
        )
        # The cards are what this tab is for; the box you type into only has to be
        # big enough to write a paragraph in.
        self.note_edit.setMaximumHeight(130)
        nl.addWidget(self.note_edit, 0)
        note_bar = QHBoxLayout()
        save = QPushButton("儲存筆記")
        save.clicked.connect(self._save_note)
        note_bar.addWidget(save)
        self.note_status = QLabel("")
        self.note_status.setStyleSheet(f"color:{pal['faint']};font-size:11px;")
        note_bar.addWidget(self.note_status)
        note_bar.addStretch(1)
        nl.addLayout(note_bar)
        self.note_log = rich_view.RichView(pal)
        self.note_log.anchorClicked.connect(self._note_action)
        nl.addWidget(self.note_log, 1)
        self.notes_tab = notes
        self.tabs.addTab(notes, "筆記")

        ask = QWidget()
        al = QVBoxLayout(ask)
        al.setContentsMargins(14, 12, 14, 12)
        al.setSpacing(8)
        al.addWidget(QLabel("通用提問範本 · 點選後可編輯"))
        seeds = QHBoxLayout()
        seeds.setSpacing(6)
        for label, question in SEED_QUESTIONS:
            btn = QPushButton(label)
            btn.setToolTip(question)
            btn.clicked.connect(lambda _=False, q=question: self._draft_question(q))
            seeds.addWidget(btn)
        seeds.addStretch(1)
        al.addLayout(seeds)
        from paper_daily.desktop.research_questions import ResearchQuestions

        self.questions = ResearchQuestions(palette=pal)
        self.questions.chosen.connect(self._draft_question)
        self.questions.return_to_draft.connect(self._resume_question_draft)
        self.questions.source_requested.connect(self._jump_to_source)
        al.addWidget(self.questions)
        self.chat_view = rich_view.RichView(pal)
        if not self.chat_view.rich:
            # The fallback transcript scrolls; let it yield space to the composer.
            self.chat_view.view.setMinimumHeight(64)
        self.runner.result_target = lambda: self.chat_view.setFocus()
        self.chat_view.anchorClicked.connect(self._note_action)
        al.addWidget(self.chat_view, 1)
        # A passage chosen with 問這段 waits here until a question is typed for it,
        # so the question is the reader's and not a fixed "explain this".
        self._passage: tuple[str, int | None, str | None] | None = None
        self.passage_chip = QLabel()
        self.passage_chip.setWordWrap(True)
        self.passage_chip.setTextFormat(Qt.TextFormat.RichText)
        self.passage_chip.setStyleSheet(
            f"background:{pal['accentSoft']};color:{pal['ink']};padding:8px 10px;"
            f"border-radius:4px;font-size:12px;"
        )
        self.passage_chip.linkActivated.connect(lambda _l: self._clear_passage())
        self.passage_chip.hide()
        al.addWidget(self.passage_chip)
        ask_bar = QHBoxLayout()
        self.ask_box = QLineEdit()
        self.ask_box.setPlaceholderText("問這篇論文的任何問題…")
        self.ask_box.returnPressed.connect(lambda: self._ask_from_box(self.ask_box.text()))
        self.ask_box.setStyleSheet(
            f"background:{pal['surface']};color:{pal['ink']};"
            f"border:1px solid {pal['firm']};padding:8px;"
        )
        ask_bar.addWidget(self.ask_box, 1)
        self.ask_btn = QPushButton("送出")
        ai_style.mark(self.ask_btn, pal, primary=True)
        self.ask_btn.clicked.connect(lambda: self._ask_from_box(self.ask_box.text()))
        ask_bar.addWidget(self.ask_btn)
        al.addLayout(ask_bar)
        self.ask_status = QLabel("")
        self.ask_status.setStyleSheet(f"color:{pal['faint']};font-size:11px;")
        al.addWidget(self.ask_status)
        self.ask_tab = ask
        self.tabs.addTab(ask, "問 AI")

        self.figure_pane = FigurePane(pal)
        self.figure_pane.jump.connect(self._jump_to_figure)
        self.figure_pane.extracted.connect(self._figures_ready)
        self.tabs.addTab(self.figure_pane, "圖表")

        self.cites_pane = CitesPane(self.win, pal)
        self.tabs.addTab(self.cites_pane, "脈絡")
        scopes(pal["accent"])  # before the slide panels register theirs
        self.presentation_pane = PresentationPane(self)
        self.presentation_pane.source_requested.connect(self._jump_to_source)
        self.presentation_pane.highlights_ready.connect(self._highlights_ready)
        self.presentation_pane.highlights_status.connect(self._highlight_status_changed)
        self.presentation_pane.materials_panel.source_requested.connect(self._jump_to_source)
        self.tabs.addTab(self.presentation_pane, "簡報")
        # Beside the tabs it fills; the 簡報 tab is made separately, on request.
        self.analysis_bar = AnalysisBar(self.win, pal)
        self.analysis_bar.landed.connect(self._analysis_landed)
        self.analysis_bar.finished.connect(self._analysis_finished)
        self.tabs.setCornerWidget(self.analysis_bar, Qt.Corner.TopRightCorner)
        self._analysis_shortcuts = []
        for index in range(min(9, self.tabs.count())):
            shortcut = QShortcut(QKeySequence(f"Ctrl+{index + 1}"), self)
            # The whole window, not just this page's focus: after a restart, or a
            # click on the list picker or a top-bar button, focus sits outside the
            # page and the keys silently did nothing. A window shortcut still only
            # fires while this page is shown, so the queue is unaffected.
            shortcut.setContext(Qt.ShortcutContext.WindowShortcut)
            shortcut.activated.connect(lambda index=index: self._show_numbered_tab(index))
            self._analysis_shortcuts.append(shortcut)
        # Ctrl+Tab steps through the tabs the way a browser does, so the reader
        # needs no number. On a Mac, Cmd+Tab belongs to the system: there the
        # physical Control key does it.
        for keys, step in (("Tab", 1), ("Shift+Tab", -1)):
            for modifier in ("Meta",) if fonts.MAC else ("Ctrl",):
                cycle = QShortcut(QKeySequence(f"{modifier}+{keys}"), self)
                cycle.setContext(Qt.ShortcutContext.WindowShortcut)
                cycle.activated.connect(lambda step=step: self.step_tab(step))
                self._analysis_shortcuts.append(cycle)
        self._number_tabs()
        self._tab_hints = KeyHints(
            self.tabs.tabBar(),
            Qt.KeyboardModifier.ControlModifier,
            self._tab_badges,
            lambda: self.isVisible() and self.isActiveWindow(),
            pal["accent"],
        )
        self._cites_stale = False
        self.tabs.currentChanged.connect(lambda _i: self._show_cites_if_visible())

        split.addWidget(self.tabs)
        split.setSizes([760, 640])
        split.splitterMoved.connect(
            lambda *_: self.win.remember("split", split.saveState().toHex().data().decode())
        )
        self.split = split
        scopes().add(
            left,
            "原文",
            f"{fonts.key(QKeySequence.StandardKey.Find)} 搜尋 · {fonts.ZOOM_WHEEL}縮放",
            lambda: self.pdf,
        )
        tab_keys = f"{fonts.key('Ctrl+1')}–{min(9, self.tabs.count())}"
        scopes().add(
            self.tabs, "分析", f"{tab_keys} 換分頁", lambda: self.tabs.currentWidget()
        )
        outer.addWidget(split, 1)

    # ---- loading ---------------------------------------------------------
    def load(self, paper: Paper) -> None:
        if self.paper is None or self.paper.id != paper.id:
            # The dive and the conversation are filled in once typeset; until then
            # the last paper's must not show under this one's title.
            self.dive_view.setHtml("")
            self.chat_view.setHtml("")
        self.paper = paper
        pal = self.win.pal
        self.title.setText(paper.title)
        if hasattr(self.win, "compact_title"):
            self.win.compact_title.setText(paper.title)
            self.win.compact_title.setToolTip(paper.title)
        self.byline.setText(" · ".join(paper.authors) if paper.authors else "作者不明")

        bits = [tag(venues.label(paper.venue, paper.year), pal, "venue")]
        if paper.award:
            bits.append(tag(paper.award, pal, "award"))
        if paper.is_canon:
            bits.append(tag("canon", pal, "canon"))
        if paper.paper_type:
            bits.append(tag(paper.paper_type, pal))
        if paper.citations:
            bits.append(tag(f"{paper.citations:,} cites", pal))
        if shows_reason(paper.title, paper.reason):
            bits.append(tag(paper.reason, pal))
        self._facts_bits = bits
        self._render_facts()
        self._check_resources()

        self._load_pdf()
        self._load_dive()
        self.analysis_bar.show_paper(paper.id)
        self._load_notes()
        self._load_chat()
        self.questions.load(paper.id)
        self._figures_stale = True
        self.presentation_pane.load(
            paper.id, paper.title, defer=not self.presentation_pane.isVisible()
        )
        # The references tab is the heaviest thing on the page and most papers are
        # opened to read, not to audit their references; it loads when shown.
        self._cites_stale = True
        self._show_cites_if_visible()

    def _render_facts(self) -> None:
        paper, pal = self.paper, self.win.pal
        links = []
        if paper.page_url:
            links.append(f'<a href="{paper.page_url}" style="color:{pal["accent"]};">會議頁面</a>')
        if paper.arxiv_id:
            links.append(
                f'<a href="https://arxiv.org/abs/{paper.arxiv_id}" '
                f'style="color:{pal["accent"]};">arXiv {paper.arxiv_id}</a>'
            )
        with connect() as conn:
            found = resources.of(conn, paper.id)
        self._others = [r for r in found if not r["own"]]
        for r in found:
            if r["own"]:
                links.append(
                    f'<a href="{html.escape(r["url"])}" style="color:{pal["accent"]};">'
                    f"{html.escape(resources.label(r))}</a>"
                )
        if self._others:
            links.append(
                f'<a href="res:others" style="color:{pal["muted"]};">'
                f"文中提到的連結 {len(self._others)}</a>"
            )
        if self._running(self._res_job):
            links.append(f'<span style="color:{pal["muted"]};">正在找程式碼…</span>')
        self.facts.setText(
            " ".join(self._facts_bits) + ("&nbsp;&nbsp;" + " · ".join(links) if links else "")
        )

    def _facts_link(self, href: str) -> None:
        if href != "res:others":
            QDesktopServices.openUrl(QUrl(href))
            return
        menu = QMenu(self)
        for r in self._others:
            action = menu.addAction(resources.label(r))
            action.triggered.connect(lambda _c=False, u=r["url"]: QDesktopServices.openUrl(QUrl(u)))
        menu.exec(self.facts.mapToGlobal(self.facts.rect().bottomLeft()))

    @staticmethod
    def _running(job: subprocess.Popen | None) -> bool:
        return job is not None and job.poll() is None

    def _check_resources(self) -> None:
        """Look for the paper's code in the background, once, and again once its
        text has arrived: the paper's own words are the best source."""
        if not self.paper or self._running(self._res_job):
            return
        with connect() as conn:
            if not resources.needs_check(conn, self.paper.id):
                return
        self._res_job = _spawn("resources", self.paper.id)
        self._res_for = self.paper.id
        self._res_poll.start()
        self._render_facts()

    def _resources_poll(self) -> None:
        if self._running(self._res_job):
            return
        self._res_poll.stop()
        self._res_job = None
        if self.paper and self.paper.id == self._res_for:
            self._render_facts()
            self._check_resources()

    def _load_pdf(self) -> None:
        assert self.paper
        path = self.paper.pdf_path
        if path.exists() and self.pdf.load(path):
            self.pdf.show()
            self.pdf_missing.hide()
            self.pdf_note.setText(
                f"{self.pdf.page_count()} 頁 · {pdfpane.backend_name()}"
            )
            self.open_external.setEnabled(True)
            # The AI highlight check follows once the saved ones are in.
            self._load_highlights(path, background=True)
            return

        self.pdf.hide()
        self.open_external.setEnabled(False)
        pal = self.win.pal
        target = self.paper.pdf_url or (
            f"https://arxiv.org/abs/{self.paper.arxiv_id}" if self.paper.arxiv_id else None
        )
        link = (
            f'<br><br><a href="{target}" style="color:{pal["accent"]};">線上開啟原文</a>'
            if target else ""
        )

        # Fetch it rather than instructing someone to open a terminal. prefetch walks
        # the queue in order, so any paper reached by a lineage link or by pressing
        # past the buffer arrives with nothing downloaded.
        if not target:
            self.pdf_missing.setText(
                "這篇沒有可取得的 PDF 連結。Semantic Scholar 與 arXiv 都查不到,"
                "只能用右邊的摘要與會議頁面。"
            )
            self.pdf_note.setText("無來源")
        elif self.fetcher.start(self.paper.id, self._pdf_arrived):
            self.pdf_missing.setText("正在下載原文…" + link)
            self.pdf_note.setText("下載中")
        elif self.fetcher.busy:
            self.pdf_missing.setText("另一篇的原文正在下載,稍後會輪到這篇。" + link)
            self.pdf_note.setText("排隊中")
        else:
            self.pdf_missing.setText("這篇的原文暫時取不到。" + link)
            self.pdf_note.setText("尚無 PDF")
        self.pdf_missing.show()

    def showEvent(self, event):
        super().showEvent(event)
        QTimer.singleShot(0, self._prepare_reading_highlights)

    def _highlight_status_changed(self, paper_id, text):
        if self.paper and self.paper.id == paper_id:
            self.highlight_status.setText(text)

    def _retry_highlights(self):
        if not self.paper:
            return
        if self.presentation_pane.busy:
            self.highlight_status.setText("正在處理這篇論文；完成後可再補標。")
            return
        self.presentation_pane._analyze_highlights(force=False)

    def _selected_highlight_material(self):
        selection = getattr(self.pdf, "selection", None)
        ids = selection.selected_highlights() if selection else []
        self._show_highlight_material(ids[0] if ids else None)

    def _show_highlight_material(self, mark_id=None):
        if not self.paper:
            return
        pane = self.presentation_pane
        self.tabs.setCurrentWidget(pane)
        pane.materials_button.setChecked(True)
        pane._load_materials()
        if pane.materials_panel.select_highlight(mark_id):
            pane.materials_panel._locate_selected()
        else:
            self.highlight_status.setText("尚無可用重點；按「分析／補上標註」開始。")

    def _refresh_highlight_materials(self):
        if self.paper and self.presentation_pane.paper_id == self.paper.id:
            self.presentation_pane._load_materials()

    def numbered_tabs(self) -> list[QWidget]:
        """The tabs Ctrl+1 to Ctrl+9 reach, in bar order. A hidden tab is skipped so
        the keys always count what the reader can see."""
        tabs = self.tabs
        shown = [tabs.widget(i) for i in range(tabs.count()) if tabs.isTabVisible(i)]
        return shown[:9]

    def step_tab(self, step: int) -> None:
        """The next (or previous) visible tab, wrapping round."""
        shown = self.numbered_tabs()
        current = self.tabs.currentWidget()
        if shown:
            here = shown.index(current) if current in shown else -step
            self.tabs.setCurrentWidget(shown[(here + step) % len(shown)])

    def _show_numbered_tab(self, number: int) -> None:
        shown = self.numbered_tabs()
        if number < len(shown):
            self.tabs.setCurrentWidget(shown[number])

    def _tab_badges(self) -> list[str | None]:
        shown = self.numbered_tabs()
        return [
            fonts.key(f"Ctrl+{shown.index(tab) + 1}") if tab in shown else None
            for tab in map(self.tabs.widget, range(self.tabs.count()))
        ]

    def _number_tabs(self) -> None:
        """Refresh the key named in each tab's tooltip; call after showing or
        hiding a tab."""
        for index, badge in enumerate(self._tab_badges()):
            name = self.tabs.tabText(index)
            cycle = fonts.key("Meta+Tab" if fonts.MAC else "Ctrl+Tab")
            self.tabs.setTabToolTip(
                index, f"{name}（{badge}）\n{cycle} 下一個分頁" if badge else name
            )

    def _auto_highlights_changed(self, checked: bool) -> None:
        self.win.remember("auto_highlights", "1" if checked else "0")
        ui_state.flush()
        if checked:
            self._prepare_reading_highlights()

    def _prepare_reading_highlights(self) -> None:
        pane = self.presentation_pane
        if (not self.paper or not self.auto_highlights.isChecked()
                or pane.paper_id != self.paper.id or not self.pdf.isVisible()):
            return
        key = (self.paper.id, getattr(self, "_pdf_fingerprint", None))
        if not key[1] or key in self._highlight_attempts:
            return
        if pane.busy:
            self.highlight_status.setText("正在處理論文，稍後同步原文重點與素材。")
            QTimer.singleShot(1000, self._prepare_reading_highlights)
            return
        pane._analyze_highlights(force=False)
        if pane.busy:
            self._highlight_attempts.add(key)

    def _highlights_ready(self, paper_id: str) -> None:
        if self.paper and self.paper.id == paper_id:
            self._load_highlights(self.paper.pdf_path)
            if hasattr(self.win, "data"):
                self._load_dive()
            selection = getattr(self.pdf, "selection", None)
            if selection:
                count = sum(mark.get("origin") == "ai" for mark, _words in selection._marks)
                self.pdf_note.setText(f"已同步 {count} 段 AI 重點（綠色）與素材。")

    def _load_highlights(self, path: Path, *, background: bool = False) -> None:
        """Show the saved highlights. Opening a paper asks in the background: finding
        each highlight's words reads the pages it covers, a third of a second on a
        well-marked paper."""
        selection = getattr(self.pdf, "selection", None)
        self._pdf_fingerprint = None
        if selection is None or not self.paper:
            self.prepare.cancel("highlights")
            return
        paper = self.paper
        try:
            # Here, not on the worker: a highlight drawn the moment the paper opens
            # is saved against it. Hashing the file takes milliseconds.
            fingerprint = self._pdf_fingerprint = pdf_highlights.document_hash(path)
        except OSError as exc:
            self.prepare.cancel("highlights")
            self.highlight_status.setText(f"螢光標記無法載入：{exc}")
            return

        def read():
            try:
                marks = pdf_highlights.list_marks(paper.id, fingerprint)
            except (sqlite3.Error, ValueError) as exc:
                return exc
            pages = {page for mark in marks
                     for page in range(mark["anchor"]["p0"], mark["anchor"]["p1"] + 1)}
            words = {}
            if background and pages:
                from paper_daily.desktop.pdfselect import words_in

                words = words_in(path, pages)
            if background:
                # What the 簡報 tab's highlight check reads next, read here first.
                from paper_daily import paper_highlights

                paper_highlights.read_original(paper.id)
            return marks, words

        def show(result):
            if isinstance(result, Exception):
                self.highlight_status.setText(f"螢光標記無法載入：{result}")
                return
            marks, words = result
            selection.prime(words)
            selection.set_highlights(marks)
            ai = sum(mark.get("origin") == "ai" for mark in marks)
            manual = len(marks) - ai
            self.highlight_status.setText(
                f"原文重點：AI {ai} 段（綠色） · 手動 {manual} 段（黃色）"
                if marks else "尚未標註原文重點；可按「分析／補上標註」。"
            )
            if background:
                self._prepare_reading_highlights()

        if background:
            self.prepare.run("highlights", read, show)
        else:
            self.prepare.cancel("highlights")
            show(read())

    def _highlight_selection(self) -> None:
        selection = getattr(self.pdf, "selection", None)
        fingerprint = getattr(self, "_pdf_fingerprint", None)
        if not self.paper or not selection or not fingerprint or not selection.anchor():
            return
        try:
            pdf_highlights.add(
                self.paper.id, fingerprint, selection.anchor(), selection.selected_text()
            )
            selection.set_highlights(pdf_highlights.list_marks(self.paper.id, fingerprint))
        except (ValueError, OSError, sqlite3.Error) as exc:
            self.pdf_note.setText(f"螢光標記未保存：{exc}")
            return
        selection.clear()
        self._load_highlights(self.paper.pdf_path)
        self._refresh_highlight_materials()
        self.pdf_note.setText("螢光標記已保存並同步素材。")

    def _erase_selection_highlights(self) -> None:
        selection = getattr(self.pdf, "selection", None)
        fingerprint = getattr(self, "_pdf_fingerprint", None)
        if not self.paper or not selection or not fingerprint:
            return
        try:
            pdf_highlights.remove(self.paper.id, fingerprint, selection.selected_highlights())
            selection.set_highlights(pdf_highlights.list_marks(self.paper.id, fingerprint))
        except (OSError, sqlite3.Error) as exc:
            self.pdf_note.setText(f"螢光標記未移除：{exc}")
            return
        selection.clear()
        self._load_highlights(self.paper.pdf_path)
        self._refresh_highlight_materials()
        self.pdf_note.setText("已移除選取範圍的螢光標記。")

    def _pdf_arrived(self, paper_id: str, ok: bool) -> None:
        """Redraw only if the reader is still on the paper that was being fetched."""
        if not self.paper or self.paper.id != paper_id:
            return
        if ok:
            self.paper._has_pdf = True
            self._load_pdf()
            self.figure_pane.load(self.paper.id, self.paper.pdf_path, True)
            self._check_resources()
        else:
            self.pdf_note.setText("下載失敗")
            self.pdf_missing.setText(
                self.pdf_missing.text().replace("正在下載原文…", "原文下載失敗。")
            )

    def _load_dive(self) -> None:
        assert self.paper
        pal = self.win.pal
        body = self.win.data.dive(self.paper.id)
        if body:
            paper, rich = self.paper, self.dive_view.rich

            def typeset():
                from paper_daily import paper_highlights, reading_links
                from paper_daily.figures import extract

                with connect() as conn:
                    close = closeread.get(conn, paper.id)
                # Only the close reading places figures, and only an extracted figure
                # can be placed, so the PDF is read for them only when both exist.
                figures = (
                    extract(paper.id, paper.pdf_path, cached_only=True)
                    if close and paper.has_pdf
                    else []
                )
                # Checking the highlights against the original reads the whole PDF.
                highlights = paper_highlights.cached(paper.id)
                links = (reading_links.cached(paper.id, reading_links.sections(body, close),
                                              highlights)
                         if highlights else None)
                return highlights, reading.render(
                    body, close, figures, pal, highlights=highlights, links=links, rich=rich,
                )

            def show(result):
                self._dive_highlights, page = result
                self.dive_view.setHtml(page)

            self.prepare.run("dive", typeset, show)
            return
        self.prepare.cancel("dive")
        self._dive_highlights = None
        parts = []
        if self.paper.abstract:
            parts.append("## Abstract\n\n" + self.paper.abstract)
        # Say which of the two it is: being made now, or waiting to be asked for.
        # An identical "no dive" message in both cases reads as a dead feature.
        if self.win.analysis_running(self.paper.id):
            parts.append(
                "\n\n---\n\n_正在深入分析這篇：深度講解和引用分析同時進行，大約三到六分鐘。_ "
                "寫好會自動出現在這裡，不用做什麼。在此之前可以先讀左邊的原文，"
                "或到「問 AI」分頁提問。"
            )
        else:
            parts.append(
                "\n\n---\n\n**這篇還沒有深度講解。** 按右上角的「✦ 深入分析」，"
                "或[現在開始深入分析](paperfact-analyze:now)：會一起寫好深度講解與逐節精讀、"
                "標出原文重點、分析每一筆參考文獻，並查後續研究、整理研究脈絡。"
                "\n\n每晚的排程也會替接下來要讀的幾篇先做好。若按了沒有反應，"
                "從上方「AI 設定」檢查目前的 AI 服務。"
            )
        self.dive_view.setHtml(self.dive_view.markdown("\n".join(parts)))

    def _dive_source(self, url):
        if url.scheme() == "paperfact-highlight":
            from paper_daily import materials

            try:
                item = self._dive_highlights["items"][int(url.path())]
            except (ValueError, IndexError, TypeError, AttributeError):
                return
            found = materials.collect(self.paper.id)
            source = next((s for s in found.sentences if s["text"] == item["text"]
                           and s.get("page") == item.get("page")), item)
            self._jump_to_source(dict(source, kind="sentence"))
        elif url.scheme() == "paperfact-analyze" and self.paper:
            self.start_analysis()
        elif url.scheme() in ("https", "http"):
            QDesktopServices.openUrl(url)

    def start_analysis(self) -> None:
        """深入分析 for the paper on screen (the tab corner button, the dive's empty
        state and the 引用 tab all lead here)."""
        if not self.paper:
            return
        self.win.analyse_now(self.paper.id)
        self.analysis_bar.refresh()
        self._load_dive()
        self._cites_stale = True
        self._show_cites_if_visible()

    def _analysis_landed(self, steps: list) -> None:
        """Redraw the tabs a running analysis has just filled, instead of asking
        for the paper to be reopened."""
        if not self.paper:
            return
        if "pdf" in steps:
            self._load_pdf()
        if "highlights" in steps and self.paper.pdf_path.exists():
            self._load_highlights(self.paper.pdf_path)
            self._refresh_highlight_materials()
        if {"dive", "highlights"} & set(steps):
            self._load_dive()
        if {"cites", "later"} & set(steps):
            self._cites_stale = True
            self._show_cites_if_visible()

    def _analysis_finished(self) -> None:
        if not self.paper:
            return
        paper_id = self.paper.id
        self.questions.load(paper_id)
        self._load_dive()
        self._cites_stale = True
        self._show_cites_if_visible()
        self.win.reload()
        with connect() as conn:
            failure = get_kv(conn, f"analyze.failed.highlights.{paper_id}")
        if failure:
            self.highlight_status.setText(f"講解已完成，原文重點尚未完成：{failure}；可按補標重試。")

    # A long answer kept as a note turns the tab back into the wall of text the
    # cards exist to avoid, so a card shows its opening and opens on request.

    def _load_notes(self) -> None:
        assert self.paper
        pal = self.win.pal
        rows = self.win.data.notes(self.paper.id)
        if not rows:
            self.note_log.setHtml(
                f'<div style="color:{pal["faint"]};font-size:12px;">'
                "還沒有筆記。在左邊選一段原文,按「寫筆記」或「問這段」,"
                "寫下來的東西會變成一張便條,點便條上的引文就跳回原處。</div>"
            )
            return
        # A note opened or closed redraws the list; the reader stays where they were.
        self.note_log.setHtml("".join(self._card(r) for r in rows), keep_scroll=True)

    def _card(self, row) -> str:
        """One note as a card: its headline always, the rendered note when opened.

        A dozen kept answers rendered in full made the tab a scroll of tables. Shut,
        a card is one line saying what the note is about; open, it is the note as the
        answer was shown in 問 AI -- tables, lists, code -- not as raw Markdown.
        """
        pal = self.win.pal
        note_id = int(row["id"])
        kind = row["kind"] or "note"
        asked = kind == "ask"
        accent = pal["accent"] if asked else pal["award"]
        tint = pal["accentSoft"] if asked else pal["awardSoft"]
        headline, passage, content = note_headline(row["body"] or "", kind)
        opened = note_id in self._open_notes

        stamp = (row["created_at"] or "")[:16].replace("T", " ")
        where = f" · 第 {row['page']} 頁" if row["page"] else ""
        chip = (
            f'<span style="background:{tint};color:{accent};font-size:10px;">'
            f'&nbsp;{"問 AI" if asked else "手寫"}&nbsp;</span>'
        )
        meta = (
            f'<div style="color:{pal["faint"]};font-size:10px;margin-top:3px;">'
            f"{chip}&nbsp; {stamp}{where}</div>"
        )
        back = ""
        if passage:
            shown = html.escape(passage[:160] + ("…" if len(passage) > 160 else ""))
            back = (
                f'<a href="jump:{note_id}" style="color:{pal["muted"]};">↩ {shown}</a>'
                if row["anchor"] else f'<span style="color:{pal["muted"]};">{shown}</span>'
            )
            back = f'<div style="font-size:11px;margin-top:5px;">{back}</div>'

        head = (
            f'<a href="toggle:{note_id}" style="color:{pal["ink"]};text-decoration:none;">'
            f'<span style="color:{accent};">{"▾" if opened else "▸"}</span>&nbsp; '
            f'<span style="font-size:13px;font-weight:600;">{html.escape(headline)}</span></a>'
        )
        inside = ""
        if opened:
            inside = (
                f'<hr style="border:0;border-top:1px solid {pal["border"]};">'
                f'<div style="color:{pal["ink"]};font-size:13px;">'
                f"{self.note_log.markdown(content)}</div>"
                f'<div align="right" style="font-size:11px;">'
                f'<a href="edit:{note_id}" style="color:{pal["accent"]};">編輯</a>&nbsp;&nbsp; '
                f'<a href="del:{note_id}" style="color:{pal["faint"]};">刪除</a>&nbsp;&nbsp; '
                f'<a href="toggle:{note_id}" style="color:{pal["muted"]};">收合</a></div>'
            )
        return (
            '<table class="note-card" width="100%" cellpadding="10" cellspacing="0" '
            f'style="margin-bottom:8px;border:1px solid {pal["border"]};">'
            f'<tr><td bgcolor="{pal["surface"]}">{head}{meta}{back}{inside}</td></tr></table>'
        )

    # ---- find in the paper ----------------------------------------------
    def focus_find(self) -> None:
        self.find_box.setFocus()
        self.find_box.selectAll()

    def _find_reset(self, _text: str = "") -> None:
        self._hits, self._hit = [], -1
        self.find_count.setText("")
        for btn in self.find_steps:
            btn.setVisible(bool(self.find_box.text().strip()))

    def _find_step(self, step: int) -> None:
        selection = getattr(self.pdf, "selection", None)
        query = self.find_box.text().strip()
        if selection is None or not query:
            return
        if not self._hits:
            self._hits = selection.search(query)
            self._hit = -1 if step > 0 else 0
        if not self._hits:
            self.find_count.setText("找不到")
            return
        self._hit = (self._hit + step) % len(self._hits)
        selection.focus(self._hits[self._hit])
        self.find_count.setText(f"{self._hit + 1}/{len(self._hits)}")

    def _edit_note(self, note_id: int) -> None:
        """Rewrite a note in full, quote line included, since half of them are
        answers kept from 問 AI that are worth tidying once they are understood."""
        assert self.paper
        row = next(
            (r for r in self.win.data.notes(self.paper.id) if int(r["id"]) == note_id), None
        )
        if row is None:
            return
        dialog = NoteEditor(
            row["body"] or "",
            self.win.pal,
            "Markdown。開頭以「> 」起頭的行是引用的原文(問 AI 的筆記則是問題);"
            "刪掉它,這則筆記就不再連回原處。",
            self,
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        body = dialog.text().strip()
        if body and body != (row["body"] or "").strip():
            self.win.data.update_note(note_id, body)
            self._load_notes()

    def _note_action(self, url) -> None:
        """Every link in the notes and the conversation goes through here."""
        what, _, raw = url.toString().partition(":")
        if not raw.isdigit():
            return
        ident = int(raw)
        if what == "jump":
            self._jump_to(ident)
        elif what == "edit":
            self._edit_note(ident)
        elif what == "del":
            self.win.data.delete_note(ident)
            self._open_notes.discard(ident)
            self._load_notes()
        elif what == "toggle":
            self._open_notes.symmetric_difference_update({ident})
            self._load_notes()
        elif what == "delq":
            self._forget_exchange(ident)
        elif what == "keep":
            self._keep_answer(ident)

    def _jump_to(self, note_id: int) -> None:
        """Put the reader back on the passage this note was written against."""
        assert self.paper
        row = next(
            (r for r in self.win.data.notes(self.paper.id) if int(r["id"]) == note_id), None
        )
        selection = getattr(self.pdf, "selection", None)
        if row is None or selection is None or not row["anchor"]:
            return
        try:
            anchor = json.loads(row["anchor"])
        except ValueError:
            return
        if selection.focus(anchor):
            self.note_status.setText(f"已跳到第 {row['page']} 頁")
            QTimer.singleShot(2500, self.note_status, lambda: self.note_status.setText(""))
        else:
            self.note_status.setText("找不到那一段了 — 原文換過了嗎?")

    def _keep_answer(self, chat_id: int) -> None:
        """Keep one answer as a note, with the question and where it was asked.

        The conversation is a thread and is read as one; a note is a thing you find
        again later. Which answers are worth keeping is a judgement, so it is a
        button rather than something that happens to every answer.
        """
        assert self.paper
        rows = self.win.data.chat(self.paper.id)
        answer = next((r for r in rows if int(r["id"]) == chat_id), None)
        if answer is None:
            return
        earlier = [r for r in rows if int(r["id"]) < chat_id and r["role"] == "user"]
        question = earlier[-1] if earlier else None

        quote = " ".join((question["body"] if question else "").split())[:400]
        body = f"> {quote}\n\n{answer['body']}" if quote else answer["body"]
        self.win.data.add_note(
            self.paper.id,
            body,
            "ask",
            question["page"] if question else None,
            question["anchor"] if question else None,
        )
        self._load_notes()
        self.ask_status.setText("存成筆記了 — 在「筆記」分頁,點標題展開。")
        QTimer.singleShot(2500, self.ask_status, lambda: self.ask_status.setText(""))

    def _load_chat(self) -> None:
        assert self.paper
        pal = self.win.pal
        paper_id = self.paper.id

        # Reading and typesetting a long conversation took a third of a second.
        def typeset():
            rows = self.win.data.chat(paper_id)
            return "".join(self._exchange(q, a) for q, a in _exchanges(rows)) if rows else None

        def show(cards):
            if cards is None:
                self.chat_view.setHtml(
                    f'<div style="color:{pal["faint"]};font-size:12px;">'
                    "問答紀錄 · 尚無對話。可在底部自行輸入，或先選擇提問建議。</div>"
                )
                return
            self.chat_view.setHtml("<h3>問答紀錄</h3>" + cards, at_end=True)

        self.prepare.run("chat", typeset, show)

    def _exchange(self, question, answer) -> str:
        """One question and its answer as a card: the question as its header."""
        pal = self.win.pal
        asked, _, passage = (question["body"] if question else "").partition(PASSAGE_MARK)
        where = f" · 第 {question['page']} 頁" if question and question["page"] else ""
        head = (
            f'<td bgcolor="{pal["accentSoft"]}">'
            f'<span style="color:{pal["accent"]};font-size:10px;">問{where}</span><br>'
            f'<span style="color:{pal["ink"]};font-size:13px;font-weight:600;">'
            f"{html.escape(asked.strip())}</span>"
        )
        if passage.strip():
            shown = " ".join(passage.split())
            head += (
                f'<div style="color:{pal["muted"]};font-size:11px;margin-top:4px;">'
                f'{html.escape(shown[:200] + ("…" if len(shown) > 200 else ""))}</div>'
            )
        head += "</td>"
        if answer is None:
            body = f'<span style="color:{pal["faint"]};">思考中…</span>'
            links = ""
        else:
            body = self.chat_view.markdown(answer["body"])
            links = (
                f'<a href="keep:{int(answer["id"])}" style="color:{pal["accent"]};">'
                "＋ 存成筆記</a>&nbsp;&nbsp; "
            )
        if question is not None:
            links += (
                f'<a href="delq:{int(question["id"])}" style="color:{pal["faint"]};">'
                "刪除這組問答</a>"
            )
        return (
            '<table class="note-card" width="100%" cellpadding="10" cellspacing="0" '
            f'style="margin-bottom:12px;border:1px solid {pal["border"]};">'
            f"<tr>{head}</tr>"
            f'<tr><td bgcolor="{pal["surface"]}">'
            f'<div style="color:{pal["ink"]};font-size:13px;">{body}</div>'
            f'<div align="right" style="font-size:11px;">{links}</div></td></tr></table>'
        )

    def _forget_exchange(self, question_id: int) -> None:
        """Delete a question and the answer to it. A note kept from it stays."""
        assert self.paper
        for question, answer in _exchanges(self.win.data.chat(self.paper.id)):
            if question is not None and int(question["id"]) == question_id:
                ids = [question_id] + ([int(answer["id"])] if answer is not None else [])
                self.win.data.delete_chat(ids)
                break
        self._load_chat()

    def _figures_ready(self, paper_id):
        if self.paper and self.paper.id == paper_id:
            self._load_dive()

    def _show_cites_if_visible(self) -> None:
        if (self.paper and self.tabs.currentWidget() is self.figure_pane
                and getattr(self, "_figures_stale", False)):
            self._figures_stale = False
            self.figure_pane.load(self.paper.id, self.paper.pdf_path, self.paper.has_pdf)
        if self.paper and self._cites_stale and self.tabs.currentWidget() is self.cites_pane:
            self._cites_stale = False
            self.cites_pane.load(self.paper.id)

    def _jump_to_source(self, source: dict) -> None:
        """Keep source checks inside the reader, beside the slide being edited."""
        selection = getattr(self.pdf, "selection", None)
        status = self.presentation_pane.status
        kind = source.get("kind")
        # A cited work and the AI analyses live in the right-hand tabs, not in the
        # PDF, so they need no original on screen.
        if kind == "citations":
            self.tabs.setCurrentWidget(self.cites_pane)
            self._show_cites_if_visible()
            status.setText(self.cites_pane.focus(source) or "已切到「脈絡」分頁。")
            return
        if kind in ("dive", "close_reading"):
            self.tabs.setCurrentWidget(self.dive_view)
            heading = str(source.get("label") or "").partition("：")[2].strip()
            if heading and self.dive_view.find(heading):
                status.setText(f"已跳到深度講解的「{heading[:40]}」。")
            else:
                self.dive_view.scroll_to_top()
                status.setText("已切到「深度講解」分頁。")
            return
        if selection is None or not self.pdf.isVisible():
            status.setText("原文尚未載入，請先下載或開啟這篇論文的 PDF。")
            return
        page = source.get("page")
        text = str(source.get("text") or "").strip()
        rect = source.get("rect")
        if (isinstance(rect, list) and len(rect) == 4 and type(page) is int and page > 0
                and source.get("document_hash") == self._pdf_fingerprint):
            selection.clear()
            scroll = selection.view.verticalScrollBar()
            scroll.setValue(max(0, selection.map.doc_y(page - 1, rect[1])
                               - selection.view.viewport().height() // 4))
            status.setText(f"左側原文已定位到第 {page} 頁的素材位置。")
            return
        anchor = source.get("anchor")
        if isinstance(anchor, dict) and selection.focus(anchor):
            status.setText("左側原文已定位到這段螢光重點。")
            return
        anchor = None
        if type(page) is int and page > 0:
            if text and kind != "original":
                anchor = selection.find(page - 1, text)
            selection.clear()
            if anchor is None or not selection.focus(anchor):
                selection.scroll_to_page(page - 1)
            status.setText(
                f"左側原文已定位至第 {page} 頁" + ("，並標示對應段落。" if anchor else "。")
            )
        elif kind in ("abstract", "original") and text:
            query = " ".join(text.split()[:12])
            hits = selection.search(query)
            if hits and selection.focus(hits[0]):
                status.setText("左側原文已定位並標示對應段落。")
            else:
                status.setText("無法在原文定位這段來源；目前 PDF 可能沒有可搜尋的文字。")
        else:
            status.setText("這個來源沒有原文頁碼或段落位置，無法精確跳轉；請搭配原文核對。")

    def _jump_to_figure(self, page: int, caption: str) -> None:
        """Put the PDF on the figure's page, with its caption highlighted."""
        selection = getattr(self.pdf, "selection", None)
        if selection is None or not self.pdf.isVisible():
            return
        anchor = selection.find(page - 1, caption)
        if anchor is None or not selection.focus(anchor):
            selection.scroll_to_page(page - 1)

    # ---- actions ---------------------------------------------------------
    def _ask_this_page(self) -> None:
        """Ask about the page on screen rather than the whole paper.

        Qt's PDF view exposes no mouse selection, so the page you are looking at is
        the narrowest passage the reader can actually point at.
        """
        if not self.paper or not self.pdf.isVisible():
            return
        page = self.pdf.current_page()
        text = self.pdf.page_text(page)
        if not text.strip():
            self.pdf_note.setText(f"第 {page + 1} 頁沒有可抽取的文字")
            return
        self._page_context = (page, text)
        self.tabs.setCurrentWidget(self.ask_tab)
        self.ask_box.setText(f"請解釋第 {page + 1} 頁在講什麼,以及它在整篇論文裡的作用。")
        self.ask_box.setFocus()

    def _zoom(self, direction: int) -> None:
        if self.pdf.isVisible():
            self.pdf_note.setText(self.pdf.zoom(direction))

    def _fit(self) -> None:
        if self.pdf.isVisible():
            self.pdf_note.setText(self.pdf.fit_width())

    def _open_external(self) -> None:
        if self.paper and self.paper.pdf_path.exists():
            QDesktopServices.openUrl(f"file:///{self.paper.pdf_path.as_posix()}")

    # ---- acting on a passage of the paper --------------------------------
    def _translate_selection(self, text: str) -> None:
        """Translate the selected passage in place, quickly, with the model one click away.

        Google answers in a second, which is what a glance at a sentence wants. The
        model keeps technical terms in English, which is what a sentence you half
        understand needs, so it is offered on the same panel and taken over
        automatically when Google does not answer.
        """
        if not text.strip() or self.translate_runner.busy:
            return
        overlay = self.pdf.selection
        overlay.show_result("翻譯中…", text[:160] + ("…" if len(text) > 160 else ""))
        self.translate_runner.start(
            text,
            lambda answer: overlay.show_result("Google 翻譯", answer, refinable=True),
            lambda _reason: self._translate_with_model(text),
            call=translate.machine, task="translate",
        )

    def _translate_with_model(self, text: str) -> None:
        if not text.strip() or self.refine_runner.busy:
            return
        overlay = self.pdf.selection
        overlay.show_result("AI 精譯中…",
                            text[:160] + ("…" if len(text) > 160 else ""))
        prompt = (
            "把下面這段論文原文翻成繁體中文。技術名詞、模型名稱、資料集名稱保留英文,"
            "數學用 Unicode 純文字,絕不使用 LaTeX。只輸出譯文,不要前言。\n\n" + text
        )
        self.refine_runner.start(
            prompt,
            lambda answer: overlay.show_result("AI 精譯", answer.strip()),
            lambda reason: overlay.show_result("翻不出來", reason),
            task="translate",
        )

    def _where(self) -> tuple[int | None, str | None]:
        """The current selection as (page for a human, anchor for the machine).

        The page is one-based because it is shown; the anchor inside stays
        zero-based because that is what the overlay indexes by.
        """
        selection = getattr(self.pdf, "selection", None)
        spot = selection.anchor() if selection is not None else None
        if not spot:
            return None, None
        return spot["p0"] + 1, json.dumps(spot)

    def _note_selection(self, text: str) -> None:
        """Start a note against this passage, with the passage quoted in it."""
        if not text.strip():
            return
        quote = " ".join(text.split())[:400]
        # One note, one passage. A draft already holding a passage and some thoughts
        # is saved where it belongs before the new one starts; a bare quote with
        # nothing written under it is simply replaced.
        _old, written = _split_quote(self.note_edit.toPlainText())
        if written and self._pending is not None:
            self._save_note()
        elif not written:
            self.note_edit.clear()
        self._pending = self._where()
        self.tabs.setCurrentWidget(self.notes_tab)
        kept = self.note_edit.toPlainText().strip()
        self.note_edit.setPlainText(f"> {quote}\n\n{kept}".rstrip() + "\n")
        cursor = self.note_edit.textCursor()
        cursor.movePosition(cursor.MoveOperation.End)
        self.note_edit.setTextCursor(cursor)
        self.note_edit.setFocus()

    def _ask_selection(self, text: str) -> None:
        if not text.strip():
            return
        self.tabs.setCurrentWidget(self.ask_tab)
        passage = " ".join(text.split())[:1200]
        page, anchor = self._where()
        self._passage = (passage, page, anchor)
        pal = self.win.pal
        short = passage if len(passage) <= 160 else passage[:160] + "…"
        where = f" · 第 {page} 頁" if page else ""
        self.passage_chip.setText(
            f"<b>針對這段提問</b>{where}　"
            f"<a href='clear' style='color:{pal['muted']};'>取消</a><br>"
            f"<span style='color:{pal['muted']};'>「{html.escape(short)}」</span>"
        )
        self.passage_chip.show()
        self.ask_box.setPlaceholderText("對這段想問什麼?留空直接按「問」= 解釋這段在說什麼")
        self.ask_box.setFocus()

    def _clear_passage(self) -> None:
        self._passage = None
        self.passage_chip.hide()
        self.ask_box.setPlaceholderText("問這篇論文的任何問題…")

    def _resume_question_draft(self):
        paper = self.paper

        def focus():
            if (self.isVisible() and self.tabs.currentWidget() is self.ask_tab
                    and self.paper is paper):
                self.ask_box.setFocus()

        # A modal's own focus restoration happens after rejected/accepted.
        QTimer.singleShot(0, self.ask_box, focus)

    def _draft_question(self, question):
        self._clear_passage()
        self.ask_box.setText(question)
        self.ask_box.setFocus()
        self._resume_question_draft()

    def _ask_from_box(self, question: str) -> None:
        """Ask what was typed, about the chosen passage when there is one."""
        question = (question or "").strip()
        if self._passage is None:
            self._ask(question)
            return
        passage, page, anchor = self._passage
        question = question or "解釋這一段在說什麼,以及它為什麼重要。"
        self._clear_passage()
        self._ask(f"{question}\n\n關於這段原文:\n{passage}", page=page, anchor=anchor)

    def _save_note(self) -> None:
        if not self.paper:
            return
        body = self.note_edit.toPlainText().strip()
        if not body:
            return
        page, anchor = self._pending or (None, None)
        self.win.data.add_note(self.paper.id, body, "note", page, anchor)
        self._pending = None
        self.note_edit.clear()
        self.note_status.setText("已儲存")
        QTimer.singleShot(2500, self.note_status, lambda: self.note_status.setText(""))
        self._load_notes()

    @requires_ai("ask")
    def _ask(self, question: str, page: int | None = None, anchor: str | None = None) -> None:
        if not self.paper:
            return
        question = (question or "").strip()
        if not question:
            return
        if self.runner.busy:
            # Silence here read as "Enter does nothing". Say what is happening.
            self.ask_status.setText("上一個問題還在處理中,等它回完再問。")
            return
        if not llm.available(task="ask"):
            QMessageBox.warning(
                self, "還沒有設定模型後端",
                "問答需要一個後端:安裝 claude CLI(不需要 API key),或設定 "
                "API 金鑰；也可以從上方「AI 設定」選擇模型。",
            )
            return

        # Acknowledge the keystroke before touching the database. A write can block
        # for seconds behind a background crawl, and the app runs with no console, so
        # anything that fails in between is invisible unless it is said here.
        self.ask_status.setText("AI 正在讀這篇論文…")
        self.ask_btn.setEnabled(False)
        QApplication.processEvents()

        try:
            self.win.data.add_chat(self.paper.id, "user", question, page, anchor)
            self.ask_box.clear()
            self._load_chat()
        except Exception as e:
            self.ask_status.setText(f"寫入失敗:{type(e).__name__} — 稍後再試")
            self.ask_btn.setEnabled(True)
            return

        history = [(r["role"], r["body"]) for r in self.win.data.chat(self.paper.id)][:-1]
        body = self.win.data.full_text(self.paper.id)
        page_context = getattr(self, "_page_context", None)
        if page_context:
            page, page_text = page_context
            # Put the page first and label it, so the answer is about the passage the
            # reader is looking at rather than the paper in general.
            body = "\n\n".join(
                [
                    f"[讀者目前正在看第 {page + 1} 頁]",
                    page_text,
                    "[全文]",
                    body or "",
                ]
            )
            self._page_context = None
        prompt = build_prompt(
            self.paper.title, self.paper.venue, self.paper.year, self.paper.abstract,
            body, history, question,
        )
        from paper_daily import ai_choices

        self.ask_status.setText(
            "本次問答：" + ai_choices.connection_label(llm.settings(task="ask"))
        )
        self.runner.start(prompt, self._ask_done, self._ask_failed)

    def _ask_done(self, answer: str) -> None:
        if self.paper:
            self.win.data.add_chat(self.paper.id, "assistant", answer)
            self._load_chat()
        self.ask_status.setText("")
        self.ask_btn.setEnabled(True)

    def _ask_failed(self, message: str) -> None:
        self.ask_status.setText(message)
        self.ask_btn.setEnabled(True)


class MainWindow(QWidget):
    def __init__(self, open_next: bool = False) -> None:
        super().__init__()
        self.pal = palette()
        self.data = Data()
        self.papers: list[Paper] = []
        self._dive_job: subprocess.Popen | None = None
        self._job_paper: str | None = None
        self.active_list: str | None = None
        self._switching = False
        self._marked: list[str] = pocket.marked_ids()

        self.setWindowTitle("Paperfact")
        self.resize(1480, 950)
        self.setStyleSheet(
            f"QWidget{{background:{self.pal['ground']};color:{self.pal['ink']};"
            f"font-family:{fonts.css()};}}"
            # Text sits on whatever panel holds it: painted with the window's ground,
            # every label on a white bar or card showed as a grey band.
            f"QLabel,QCheckBox{{background:transparent;}}"
            # A styled check box no longer draws the platform's box, so it gets one.
            f"QCheckBox{{spacing:6px;}}"
            f"QCheckBox::indicator{{width:14px;height:14px;border-radius:3px;"
            f"border:1px solid {self.pal['firm']};background:{self.pal['surface']};}}"
            f"QCheckBox::indicator:hover{{border-color:{self.pal['accent']};}}"
            f"QCheckBox::indicator:checked{{background:{self.pal['accent']};"
            f"border-color:{self.pal['accent']};image:url({CHECK});}}"
            f"{button_style.pressable(self.pal)}"
            f"QPushButton::menu-indicator{{image:none;width:0;}}"
            # Settings and navigation: present, but quieter than the reading actions.
            f"QPushButton[ghost=\"true\"]{{background:transparent;border-color:transparent;"
            f"border-bottom:1px solid transparent;color:{self.pal['muted']};padding:6px 9px;}}"
            f"QPushButton[ghost=\"true\"]:hover{{background:{self.pal['sunk']};"
            f"color:{self.pal['ink']};}}"
            f"QPushButton[ghost=\"true\"]:pressed{{background:{self.pal['firm']};"
            f"padding:7px 9px 5px 9px;}}"
            f"QPushButton[ghost=\"true\"]:checked{{color:{self.pal['accent']};}}"
            f"QLineEdit{{background:{self.pal['surface']};color:{self.pal['ink']};"
            f"border:1px solid {self.pal['firm']};border-radius:5px;padding:7px;}}"
            f"QLineEdit:focus{{border-color:{self.pal['accent']};}}"
            f"QComboBox{{background:{self.pal['surface']};color:{self.pal['ink']};"
            f"border:1px solid {self.pal['firm']};border-radius:5px;"
            f"padding:5px 26px 5px 9px;}}"
            f"QComboBox:hover{{border-color:{self.pal['accent']};}}"
            f"QComboBox::drop-down{{subcontrol-origin:padding;subcontrol-position:center right;"
            f"width:24px;border:0;}}"
            f"QComboBox::down-arrow{{image:url({CHEVRON});width:10px;height:10px;}}"
            f"QComboBox QAbstractItemView{{background:{self.pal['surface']};"
            f"color:{self.pal['ink']};border:1px solid {self.pal['firm']};outline:0;"
            f"selection-background-color:{self.pal['accentSoft']};"
            f"selection-color:{self.pal['ink']};}}"
            f"QTabBar::tab{{background:{self.pal['ground']};color:{self.pal['muted']};"
            f"padding:8px 16px;border:0;}}"
            f"QTabBar::tab:selected{{color:{self.pal['accent']};"
            f"border-bottom:2px solid {self.pal['accent']};}}"
            f"QTabWidget::pane{{border:0;border-left:1px solid {self.pal['border']};"
            f"border-top:1px solid {self.pal['border']};}}"
            f"QTabBar::tab:hover{{color:{self.pal['ink']};}}"
            f"QTabWidget#views::pane{{border:1px solid {self.pal['firm']};top:-1px;}}"
            f"QTabWidget#views>QTabBar::tab{{padding:6px 14px;margin-right:2px;"
            f"background:{self.pal['sunk']};border:1px solid {self.pal['border']};"
            f"border-bottom:0;}}"
            f"QTabWidget#views>QTabBar::tab:selected{{background:{self.pal['surface']};"
            f"color:{self.pal['accent']};border:1px solid {self.pal['firm']};"
            f"border-top:2px solid {self.pal['accent']};border-bottom:0;}}"
        )

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # Where you are on the left (back, which list, what to add to it); what to do
        # with the paper on the right. Settings stay quiet between the two.
        bar = QHBoxLayout()
        bar.setContentsMargins(16, 8, 12, 8)
        bar.setSpacing(6)
        brand = QLabel("Paperfact")
        brand.setFont(fonts.font(fonts.SERIF, 13, QFont.Weight.DemiBold))
        bar.addWidget(brand)
        bar.addSpacing(10)
        self.back_btn = ghost(QPushButton("← 清單"))
        self.back_btn.setToolTip(
            f"回到清單({fonts.key(QKeySequence.StandardKey.Back)},或滑鼠側鍵)"
        )
        self.back_btn.clicked.connect(self.go_back)
        self.back_btn.hide()
        bar.addWidget(self.back_btn)
        self.list_picker = QComboBox()
        self.list_picker.setMinimumWidth(170)
        self.list_picker.currentIndexChanged.connect(self._list_changed)
        bar.addWidget(self.list_picker)

        add_button = QPushButton("＋ 新增")
        add_button.setToolTip("建立研究清單，或加入論文到目前清單")
        add_menu = QMenu(add_button)
        add_menu.setToolTipsVisible(True)
        create = add_menu.addAction("建立清單…", self._import_list)
        create.setToolTip("從參考文獻、研究主題或空白清單開始")
        self.add_paper_action = add_menu.addAction("加入論文到這份清單…", self._add_paper)
        add_button.setMenu(add_menu)
        bar.addWidget(add_button)

        self.research_data_button = QPushButton("研究資料 ▾")
        self.research_data_button.setToolTip("匯入研究資料包，或分享目前清單的 PDF、分析與筆記")
        data_menu = QMenu(self.research_data_button)
        data_menu.setToolTipsVisible(True)
        self.import_bundle_action = data_menu.addAction("匯入研究資料包…", self._import_bundle)
        self.import_bundle_action.setToolTip("載入同事分享的清單與研究內容")
        self.import_link_action = data_menu.addAction("從分享網址匯入…", self._import_bundle_link)
        self.export_bundle_action = data_menu.addAction(
            "匯出目前清單資料包…", self._export_bundle)
        self.export_bundle_action.setToolTip(
            "將目前清單已儲存的 PDF、分析、筆記與可編輯簡報打包成 ZIP")
        data_menu.addSeparator()
        data_menu.addAction("本地整合 · 連接 agent…", self._local_integration)
        self.research_data_button.setMenu(data_menu)
        bar.addWidget(self.research_data_button)

        self.progress = QLabel("")
        self.progress.setStyleSheet(f"color:{self.pal['muted']};font-size:12px;")
        bar.addSpacing(6)
        bar.addWidget(self.progress)
        bar.addStretch(1)
        from paper_daily.desktop.ai_dialog import AIStatusButton

        self.ai_picker = AIStatusButton(self)
        self.ai_picker.clicked.connect(self._ai_settings)
        bar.addWidget(self.ai_picker)
        self.schedule_btn = ghost(QPushButton("分析排程"))
        self.schedule_btn.setToolTip("每晚自動深入分析多久做一次、做幾篇，完成後要不要提醒")
        self.schedule_btn.clicked.connect(self._schedule_settings)
        bar.addWidget(self.schedule_btn)
        divider = QFrame()
        divider.setFixedSize(1, 22)
        divider.setStyleSheet(f"background:{self.pal['border']};")
        bar.addSpacing(4)
        bar.addWidget(divider)
        bar.addSpacing(4)
        self.read_btn = QPushButton("標記已讀")
        self.read_btn.clicked.connect(self._toggle_read)
        self.read_btn.hide()
        bar.addWidget(self.read_btn)
        self.next_btn = QPushButton("下一篇")
        self.next_btn.setToolTip(f"下一篇未讀的論文({fonts.key('Ctrl+N')})")
        self.next_btn.setStyleSheet(
            f"{button_style.pressable_accent(self.pal, 'QPushButton')}"
        )
        self.next_btn.clicked.connect(self.open_next_unread)
        bar.addWidget(self.next_btn)
        self.top_toggle = ghost(QPushButton("收合"))
        self.top_toggle.setCheckable(True)
        self.top_toggle.setToolTip("收起工具列與論文資訊，保留展開按鈕；不更動閱讀或編輯內容。")
        self.top_toggle.toggled.connect(self._set_top_collapsed)
        bar.addWidget(self.top_toggle)
        barw = QWidget()
        self.top_toolbar = barw
        barw.setLayout(bar)
        barw.setObjectName("topBar")
        barw.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
        # By name: a bare rule here reached every button and label in the bar.
        barw.setStyleSheet(
            f"#topBar{{background:{self.pal['surface']};"
            f"border-bottom:1px solid {self.pal['border']};}}"
        )
        self.compact_header = QWidget()
        compact_bar = QHBoxLayout(self.compact_header)
        compact_bar.setContentsMargins(12, 2, 12, 2)
        compact_bar.addWidget(QLabel("Paperfact"))
        self.compact_title = QLabel("閱讀工作區")
        self.compact_title.setMinimumWidth(0)
        self.compact_title.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        compact_bar.addWidget(self.compact_title, 1)
        self.top_expand = ghost(QPushButton("展開頂部"))
        self.top_expand.setStyleSheet("padding:2px 8px;")
        self.top_expand.clicked.connect(lambda: self.top_toggle.setChecked(False))
        compact_bar.addWidget(self.top_expand)
        self.compact_header.hide()
        outer.addWidget(self.compact_header)
        outer.addWidget(barw)

        from paper_daily.desktop.account_status import AccountStatus

        # A notice board of one fixed line: wrapping, or hiding on the tabs that use
        # no AI, made the whole reader jump up and down as the tabs changed.
        self.ai_summary = QLabel()
        self.ai_summary.setFixedHeight(AI_ROW_HEIGHT)
        self.ai_summary.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self.ai_summary.setStyleSheet(
            f"QLabel{{background:{self.pal['sunk']};color:{self.pal['muted']};"
            f"border:1px solid {self.pal['border']};border-radius:6px;"
            f"margin:6px 16px 0 16px;padding:0 10px;font-size:11.5px;}}"
        )
        from paper_daily.desktop.activity import ActivityBoard, ActivityHub

        self.activity_hub = ActivityHub(self)
        self.activity_board = ActivityBoard(
            self.activity_hub, self.ai_summary, self.pal, height=AI_ROW_HEIGHT)
        outer.addWidget(self.activity_board)
        self.account_status = AccountStatus(self, self._refresh_ai_summary)
        from paper_daily.desktop.analysis_settings import ReadyBanner

        self.ready_banner = ReadyBanner(self.pal)
        self.ready_banner.open_paper.connect(self.open_anywhere)
        outer.addWidget(self.ready_banner)
        from paper_daily.desktop.update_banner import UpdateBanner

        self.update_banner = UpdateBanner(
            self.pal, prepare_install=self._prepare_update, cancel_install=self._cancel_update
        )
        self.update_banner.quit_for_update.connect(self.close)
        outer.addWidget(self.update_banner)
        # The nightly run finishes while the window may already be open on
        # yesterday's paper; looking again now and then is how it hears.
        self._ready_poll = QTimer(self)
        self._ready_poll.setInterval(10 * 60 * 1000)
        self._ready_poll.timeout.connect(self.announce_ready)
        self._ready_poll.start()

        self.stack = QStackedWidget()
        self.queue_page = QueuePage(self)
        self.queue_page.restore_sort()
        self.reader_page = ReaderPage(self)
        self.stack.addWidget(self.queue_page)
        self.stack.addWidget(self.reader_page)
        from paper_daily.desktop.list_overview import ListOverview

        self.lists_page = ListOverview(self)
        self.stack.addWidget(self.lists_page)
        for key, action in (("Left", self.show_lists), ("Right", self.queue_page._open_current)):
            shortcut = QShortcut(QKeySequence(key), self.queue_page.view, action)
            shortcut.setContext(Qt.ShortcutContext.WidgetShortcut)
        self.reader_page.tabs.currentChanged.connect(lambda _i: self._refresh_ai_summary())
        outer.addWidget(self.stack, 1)

        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setStyleSheet(f"color:{self.pal['border']};")
        outer.addWidget(line)

        footer = QHBoxLayout()
        footer.setContentsMargins(12, 0, 12, 0)
        footer.addStretch(1)
        self.feedback_btn = QPushButton("使用資料與回饋")
        self.feedback_btn.setFlat(True)
        self.feedback_btn.setStyleSheet(
            f"border:0;padding:2px 6px;color:{self.pal['muted']};"
        )
        self.feedback_btn.setToolTip("自願參與、查看本機紀錄、匯出或撤回；不需要 AI 登入")
        self.feedback_btn.clicked.connect(self._feedback_settings)
        footer.addWidget(self.feedback_btn)
        self.support_btn = QPushButton("診斷與回報")
        self.support_btn.setFlat(True)
        self.support_btn.setStyleSheet(self.feedback_btn.styleSheet())
        self.support_btn.setToolTip("預覽並匯出診斷包；不會自動上傳")
        self.support_btn.clicked.connect(self._support)
        footer.addWidget(self.support_btn)
        from paper_daily import build_identity

        self.build_identity = build_identity.identity()
        self.version_btn = QPushButton(build_identity.label(self.build_identity))
        self.version_btn.setObjectName("appVersion")
        self.version_btn.setFlat(True)
        self.version_btn.setStyleSheet(
            self.feedback_btn.styleSheet() + "font-size:10px;"
        )
        self.version_btn.setToolTip(build_identity.describe(self.build_identity))
        self.version_btn.setAccessibleName("版本與更新")
        self.version_btn.clicked.connect(self._version_info)
        footer.addWidget(self.version_btn)
        outer.addLayout(footer)

        QShortcut(QKeySequence("Ctrl+N"), self, self.open_next_unread)
        QShortcut(QKeySequence("Escape"), self, self._escape)
        # Back and forward as a browser has them, from the keyboard or the mouse's
        # side buttons, so the queue is one gesture away without reaching for a button.
        QShortcut(QKeySequence.StandardKey.Back, self, self.go_back)
        QShortcut(QKeySequence.StandardKey.Forward, self, self.go_forward)
        window_events.watch(self)
        self._last_paper: str | None = None
        QShortcut(QKeySequence.StandardKey.Find, self, self._find)

        self._restore_layout()
        with connect() as conn:
            self.active_list = ui_state.read(conn, "ui.list")
        self.refresh_lists()
        self.reload()
        self._refresh_ai_summary()
        self.announce_ready()
        from paper_daily.desktop.workspace_changes import WorkspaceChanges

        self._external_refresh_pending = False
        self.workspace_changes = WorkspaceChanges(self)
        self.workspace_changes.changed.connect(self._external_lists_changed)
        self.workspace_changes.timer.timeout.disconnect(self.workspace_changes.poll_in_background)
        self.workspace_changes.timer.timeout.connect(
            lambda: self._poll_external_lists(background=True)
        )
        self._external_lists_changed()
        from paper_daily.desktop import warm_up

        QTimer.singleShot(warm_up.DELAY_MS, warm_up.start)
        if open_next:
            self.open_next_unread()
        elif not self.papers and self.list_picker.count() == 0:
            self.show_lists()

    def showEvent(self, event):
        super().showEvent(event)
        if not getattr(self, "_screen_fit_scheduled", False):
            self._screen_fit_scheduled = True
            from paper_daily.desktop.reading_layout import schedule_startup_fit

            schedule_startup_fit(self)

    def _set_top_collapsed(self, collapsed: bool) -> None:
        self.top_toolbar.setVisible(not collapsed)
        self.reader_page.paper_header.setVisible(not collapsed)
        self.compact_header.setVisible(collapsed)
        self.remember("top_collapsed", "1" if collapsed else "0")
        self._refresh_ai_summary()

    def _local_integration(self):
        from paper_daily.desktop.integration_dialog import IntegrationDialog

        IntegrationDialog(self).exec()

    def _external_lists_changed(self):
        # Keep the open paper, editor contents, selection and keyboard focus intact.
        self._external_refresh_pending = True
        if (QApplication.activeModalWidget() is not None
                or QApplication.activePopupWidget() is not None
                or QApplication.mouseButtons() != Qt.MouseButton.NoButton):
            return
        try:
            self._refresh_external_list_views()
        except sqlite3.Error:
            # Retain the pending change: the next timer tick retries even if no
            # further write occurs. Never reload a reader to recover a list view.
            return
        self._external_refresh_pending = False

    def _refresh_external_list_views(self):
        self.refresh_lists()
        self.lists_page.refresh(preserve_state=True)
        if self.stack.currentWidget() is self.queue_page:
            current = self.queue_page._current_paper()
            scroll = self.queue_page.view.verticalScrollBar().value()
            self.papers = self.data.queue(list_id=self.active_list) if self.active_list else []
            pins = self.data.pins(self.active_list or "queue")
            for paper in self.papers:
                paper.pinned = paper.id in pins
            self.queue_page.refresh()
            self.queue_page._select(current.id if current else None)
            self.queue_page.view.verticalScrollBar().setValue(scroll)
            read = sum(1 for paper in self.papers if paper.read)
            self.progress.setText(f"已讀 {read} · 未讀 {len(self.papers) - read}")

    def _poll_external_lists(self, *, background=False):
        if background:
            self.workspace_changes.poll_in_background()
        else:
            self.workspace_changes.poll()
        if self._external_refresh_pending and QApplication.activeModalWidget() is None:
            self._external_lists_changed()

    def _schedule_settings(self) -> None:
        from paper_daily.desktop.analysis_settings import AnalysisSettings

        AnalysisSettings(self, self.pal).exec()
        self.announce_ready()

    def _support(self) -> None:
        from paper_daily.desktop.support_dialog import SupportDialog

        if getattr(self, "_support_dialog", None) is not None:
            self._support_dialog.raise_()
            self._support_dialog.activateWindow()
            return
        dialog = SupportDialog(self)
        self._support_dialog = dialog
        try:
            dialog.exec()
        finally:
            self._support_dialog = None
            dialog.deleteLater()

    def _version_info(self):
        from paper_daily.desktop.version_dialog import VersionDialog

        if getattr(self, "_version_dialog", None) is not None:
            self._version_dialog.raise_()
            self._version_dialog.activateWindow()
            return
        dialog = VersionDialog(self, self.update_banner, self.build_identity, self._support)
        self._version_dialog = dialog

        def finished(_result):
            self._version_dialog = None
            dialog.deleteLater()

        dialog.finished.connect(finished)
        dialog.show()

    def _prepare_update(self):
        # Match closeEvent's dialog/operation guards before starting an installer.
        from paper_daily.desktop.integration_dialog import OperationWorker

        if any(worker.isRunning() for worker in self.findChildren(OperationWorker)):
            return False
        for name in ("_workspace_dialog", "_review_dialog"):
            dialog = getattr(self, name, None)
            if dialog is not None and not dialog.disposed:
                return False
        try:
            return self._prepare_restart()
        except (OSError, ValueError, sqlite3.Error):
            return False

    def _feedback_settings(self) -> None:
        from paper_daily.desktop.feedback_dialog import FeedbackDialog

        FeedbackDialog(self).exec()

    def announce_ready(self) -> None:
        """Say which papers the scheduled analysis finished, once per batch."""
        from paper_daily import analysis_schedule

        with connect() as conn:
            ids = analysis_schedule.unseen(conn)
            titles = {
                r["id"]: r["title"]
                for r in conn.execute(
                    f"SELECT id, title FROM papers WHERE id IN ({','.join('?' * len(ids))})",
                    ids,
                )
            } if ids else {}
        if not ids:
            self.ready_banner.hide()
            return
        if self.ready_banner.isHidden():
            QApplication.alert(self)
        self.ready_banner.show_batch(ids, titles)

    def _ai_settings(self) -> None:
        from paper_daily import feedback

        feedback.safe_record("ui.action", "ai_settings")
        from paper_daily.desktop.ai_picker import AIPickerDialog

        try:
            dialog = AIPickerDialog(self)
        except (ValueError, OSError):
            from paper_daily.desktop.ai_recovery import offer

            if not offer(self):
                return
            dialog = AIPickerDialog(self)
        dialog.exec()
        self.ai_picker.refresh()
        self._refresh_ai_summary(check=True)

    def _refresh_ai_summary(self, *, check=False):
        from paper_daily import ai_choices, llm

        self.ai_picker.refresh()
        try:
            # The expanded toolbar already identifies the global connection.
            # Keep this row for the current task, or restore global context when collapsed.
            lines = []
            reading = hasattr(self, "reader_page") and (
                self.stack.currentWidget() is self.reader_page
            )
            if self.top_toggle.isChecked():
                lines.append("全域 AI：" + ai_choices.connection_label(llm.settings()))
            if reading:
                # By widget, not position: a tab added between them moved 簡報
                # along and the row named the wrong one.
                reader = self.reader_page
                task = {
                    reader.dive_view: "dive",
                    reader.ask_tab: "ask",
                    reader.cites_pane: "citations",
                    reader.presentation_pane: "slides",
                }.get(reader.tabs.currentWidget())
                if task:
                    mode = "個別指定" if task in llm.task_routes() else "沿用全域"
                    title = self.reader_page.tabs.tabText(self.reader_page.tabs.currentIndex())
                    lines.append(f"{title}（{mode}，新工作）：" + ai_choices.connection_label(
                        llm.settings(task=task)
                    ))
            if not lines and reading:
                lines.append("這個分頁不用 AI")
            text = "　｜　".join(lines)
            self.ai_summary.setText(text)
            self.ai_summary.setToolTip(text)
            self.ai_summary.setVisible(bool(lines))
            if check:
                self.account_status.check(ai_choices.accounts())
        except (ValueError, OSError):
            self.ai_summary.setText("AI 設定需要修復；請開啟 AI 設定。")
            self.ai_summary.show()

    # ---- layout memory ---------------------------------------------------
    def remember(self, key: str, value: str) -> None:
        ui_state.save(f"ui.{key}", value)

    def _restore_layout(self) -> None:
        """Put the window back where it was. Kept in the same database as everything
        else, so there is still exactly one file to move or delete."""
        with connect() as conn:
            geometry = ui_state.read(conn, "ui.geometry")
            split = ui_state.read(conn, "ui.split")
            presentation_layout = ui_state.read(conn, "ui.presentation")
            top_collapsed = ui_state.read(conn, "ui.top_collapsed")
            auto_highlights = ui_state.read(conn, "ui.auto_highlights")
        self.reader_page.auto_highlights.setChecked(auto_highlights == "1")
        self.top_toggle.setChecked(top_collapsed == "1")
        if geometry:
            self.restoreGeometry(QByteArray.fromHex(geometry.encode()))
        if split and hasattr(self.reader_page, "split"):
            self.reader_page.split.restoreState(QByteArray.fromHex(split.encode()))

        if presentation_layout:
            with suppress(ValueError, TypeError):
                self.reader_page.presentation_pane.restore_workspace(json.loads(presentation_layout))

    def _cancel_update(self):
        # Installation failed: subsequent edits need normal close/save protection.
        self._closing_with_recovery = False

    def _prepare_restart(self) -> bool:
        hub = getattr(self, "activity_hub", None)
        if hub is not None and hub.busy:
            return False
        downloads = getattr(self, "pdf_downloads", None)
        if downloads is not None and downloads.busy:
            downloads.cancel()
            self.queue_page.pdf_status.setText("正在停止 PDF 下載，結束後可安全重啟。")
            return False
        access = getattr(self, "ai_access", None)
        if access is not None and access.runner.busy:
            return False
        reader = self.reader_page
        pane = reader.presentation_pane
        questions = getattr(reader, "questions", None)
        if questions is not None and questions.runner.busy:
            return False
        if (pane.busy or any(worker.busy for worker in (
                reader.runner, reader.translate_runner, reader.refine_runner, reader.fetcher,
                getattr(reader, "document_runner", None),
        ) if worker is not None) or QApplication.activeModalWidget() is not None):
            pane.status.setText("仍有工作或對話視窗，暫不重啟；完成後可再試一次。")
            return False
        recovered = False
        if not pane.save_changes():
            try:
                pane.save_recovery()
            except (ValueError, OSError) as exc:
                pane.status.setText(f"草稿保存失敗，暫不重啟：{exc}")
                return False
            recovered = True
        self.remember("restart", json.dumps({
            "paper": reader.paper.id if reader.paper else None,
            "reader": self.stack.currentWidget() is reader,
            "tab": reader.tabs.currentIndex(), "mode": pane._mode,
            "slide": pane._index, "view": pane.views.currentIndex(),
            "note": reader.note_edit.toPlainText(), "question": reader.ask_box.text(),
            "pdf_page": reader.pdf.current_page() if reader.pdf.isVisible() else 0,
        }))
        # A failed flush must keep the current process and its drafts alive.
        if not ui_state.flush():
            return False
        self._closing_with_recovery = recovered
        return True

    def _restore_restart(self) -> None:
        with connect() as conn:
            value = ui_state.read(conn, "ui.restart")
        if not value:
            return
        try:
            state = json.loads(value)
            paper = next((p for p in self.papers if p.id == state.get("paper")), None)
            if paper:
                reader = self.reader_page
                pane = reader.presentation_pane
                mode_index = pane.mode.findData(state.get("mode", "guide"))
                if mode_index >= 0:
                    pane.mode.setCurrentIndex(mode_index)
                reader.load(paper)
                selection = getattr(reader.pdf, "selection", None)
                page = state.get("pdf_page", 0)
                if selection and type(page) is int and 0 <= page < reader.pdf.page_count():
                    QTimer.singleShot(0, selection, lambda: selection.scroll_to_page(page))
                if not pane._dirty and 0 <= state.get("slide", -1) < pane.outline.count():
                    pane.outline.setCurrentRow(state["slide"])
                pane.views.setCurrentIndex(state.get("view", 0))
                reader.tabs.setCurrentIndex(state.get("tab", 0))
                reader.note_edit.setPlainText(state.get("note", ""))
                reader.ask_box.setText(state.get("question", ""))
                self._last_paper = paper.id
                if state.get("reader"):
                    self.stack.setCurrentWidget(reader)
                    self.back_btn.show()
                    self.read_btn.show()
                    self.read_btn.setText("已讀 ✓" if paper.read else "標記已讀")
            self.remember("restart", "")
        except (ValueError, TypeError, KeyError):
            self.reader_page.presentation_pane.status.setText("無法恢復重啟前的視角；草稿仍保留。")

    def closeEvent(self, event) -> None:
        from paper_daily.desktop.integration_dialog import OperationWorker

        if any(worker.isRunning() for worker in self.findChildren(OperationWorker)):
            event.ignore()
            return
        reader = self.reader_page
        hub = getattr(self, "activity_hub", None)
        workers = (getattr(reader, name, None) for name in
                   ("runner", "translate_runner", "refine_runner", "fetcher"))
        if (hub is not None and hub.busy) or any(r is not None and r.busy for r in workers):
            event.ignore()
            board = getattr(self, "activity_board", None)
            if board is not None:
                board.setFocus()
                board.setToolTip("尚有背景工作，請等候完成或在原操作區停止。")
            return
        downloads = getattr(self, "pdf_downloads", None)
        if downloads is not None and downloads.busy:
            downloads.cancel()
            self.queue_page.pdf_status.setText("正在停止下載並清理暫存檔，完成後關閉…")
            event.ignore()
            if not getattr(self, "_pdf_close_waiting", False):
                self._pdf_close_waiting = True

                def retry_close():
                    self._pdf_close_waiting = False
                    self.close()

                QTimer.singleShot(200, self, retry_close)
            return
        access = getattr(self, "ai_access", None)
        if access is not None and access.runner.busy:
            self.reader_page.presentation_pane.status.setText("正在檢查 AI 登入，完成後即可關閉。")
            event.ignore()
            return
        questions = getattr(self.reader_page, "questions", None)
        if questions is not None and questions.runner.busy:
            questions.status.setText("候選問題正在儲存，完成後即可關閉。")
            event.ignore()
            return
        pane = self.reader_page.presentation_pane
        if pane.busy:
            pane.status.setText("簡報工作進行中，請等候生成或匯出完成再關閉視窗。")
            self.stack.setCurrentWidget(self.reader_page)
            self.reader_page.tabs.setCurrentWidget(pane)
            event.ignore()
            return
        if not getattr(self, "_closing_with_recovery", False) and not pane.save_changes():
            event.ignore()
            if getattr(self, "_close_dialog", None):
                self._close_dialog.raise_()
                return
            box = QMessageBox(self)
            box.setWindowTitle("簡報有未完成修改")
            box.setText("可以保留未完成草稿後關閉；下次開啟這篇論文時會恢復，已儲存簡報不會被覆蓋。")
            box.setInformativeText(pane.status.text())
            keep = box.addButton("保留草稿並關閉", QMessageBox.ButtonRole.AcceptRole)
            back = box.addButton("返回編輯", QMessageBox.ButtonRole.RejectRole)
            box.setDefaultButton(back)
            self._close_dialog = box

            def finish(_result):
                self._close_dialog = None
                if box.clickedButton() is keep:
                    try:
                        pane.save_recovery()
                    except (ValueError, OSError) as exc:
                        pane.status.setText(f"草稿保存失敗，視窗仍開啟：{exc}")
                    else:
                        self._closing_with_recovery = True
                        QTimer.singleShot(0, self.close)
                else:
                    self.stack.setCurrentWidget(self.reader_page)
                    self.reader_page.tabs.setCurrentWidget(pane)
                    pane.views.setCurrentIndex(2)
                box.deleteLater()

            box.finished.connect(finish)
            # A modal exec inside closeEvent can re-enter native window teardown.
            box.open()
            return
        self.remember("presentation", json.dumps(pane.workspace_state()))
        self.remember("geometry", self.saveGeometry().toHex().data().decode())
        ui_state.flush()
        self.update_banner.shutdown()
        super().closeEvent(event)

    # Papers kept analysed ahead of the reading while the window is open.
    ANALYSIS_BUFFER = 3

    def analysis_running(self, paper_id: str | None = None) -> bool:
        """Is the background job alive -- and, given a paper, is it that paper's
        深入分析 rather than the idle work on the papers coming up?"""
        alive = self._dive_job is not None and self._dive_job.poll() is None
        return alive and (paper_id is None or self._job_paper == paper_id)

    def _spawn_job(self, args: list[str], paper_id: str | None) -> None:
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        from paper_daily.desktop.activity import begin

        self._job_paper = paper_id
        def show_result():
            if paper_id:
                self.open_anywhere(paper_id)
                self.reader_page._analysis_finished()
                self.reader_page.tabs.setCurrentWidget(self.reader_page.dive_view)
                self.reader_page.dive_view.setFocus()
        self._analysis_activity = begin(
            self.reader_page, "深入分析" if paper_id else "背景分析",
            key=f"analysis:{paper_id}", result=show_result, paper_id=paper_id)
        if not self._analysis_activity.accepted:
            return
        try:
            self._dive_job = subprocess.Popen(
                runtime.cli_command(*args),
                cwd=str(ROOT),
                creationflags=flags,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, encoding="utf-8", errors="replace",
                env={**os.environ, "PAPERFACT_PROGRESS": "1", "PYTHONUNBUFFERED": "1",
                     "PYTHONIOENCODING": "utf-8"},
            )
            self.activity_hub.watch_popen(self._analysis_activity, self._dive_job)
        except OSError:
            self._analysis_activity.finish(False, "無法啟動分析，請重試")
            self._dive_job = None

    @requires_ai(*ANALYSIS_TASKS)
    def analyse_now(self, paper_id: str) -> None:
        """深入分析 for one paper, asked for by pressing the button.

        One analysis job at a time, so the same paper is never analysed twice at
        once; idle work on the papers ahead gives way, and since every step skips
        what already exists, it loses nothing it had finished.
        """
        if self.queue_page._job is not None:
            self.activity_board.setFocus()
            return
        if self.analysis_running(paper_id):
            self.activity_board.setFocus()
            return
        if self.analysis_running():
            self._dive_job.terminate()
            self._analysis_activity.finish(cancelled=True)
        self._spawn_job(["analyze", paper_id, "--retry"], paper_id)

    def stop_analysis(self) -> None:
        if self.analysis_running():
            self._dive_job.terminate()
            self._analysis_activity.finish(cancelled=True)

    def top_up_dives(self) -> None:
        """Keep the next few papers fully analysed, in the background.

        The same 深入分析 the nightly job runs, so a paper reached while the window
        is open arrives with its 引用 tab filled in, not only its explanation. Once
        everything nearby is done, the idle time brings older dives onto the current
        specification instead, in queue order, which is where the reading is.

        The paper on screen is not started here: that is the button's job, and a
        paper opened only to glance at should not spend a model call.
        """
        # Desktop background spending is opt-in; opening/importing a list only reads it.
        with connect() as conn:
            if ui_state.read(conn, "ui.background_analysis") != "1":
                return
        if self.analysis_running():
            return
        from paper_daily import analyze

        with connect() as conn:
            ahead = analyze.upcoming(conn, self.ANALYSIS_BUFFER, self.active_list)
            stale = not ahead and self._stale_dives(conn, self.active_list)
        scope = ["--list", self.active_list] if self.active_list else []
        if ahead:
            self._spawn_job(
                ["analyze", "--ahead", str(self.ANALYSIS_BUFFER), "--jobs", "1", *scope],
                None,
            )
        elif stale:
            self._spawn_job(["dive-ahead", "2", *scope, "--rewrite"], None)

    @staticmethod
    def _stale_dives(conn, list_id: str | None) -> bool:
        """Is anything still on an older dive specification?"""
        from paper_daily.dive import DIVE_SPEC

        if list_id:
            return bool(
                conn.execute(
                    "SELECT 1 FROM list_papers lp JOIN dives d ON d.paper_id = lp.paper_id "
                    "WHERE lp.list_id = ? AND COALESCE(d.spec,'') != ? LIMIT 1",
                    (list_id, DIVE_SPEC),
                ).fetchone()
            )
        return bool(
            conn.execute(
                "SELECT 1 FROM queue q JOIN dives d ON d.paper_id = q.paper_id "
                "WHERE COALESCE(d.spec,'') != ? LIMIT 1",
                (DIVE_SPEC,),
            ).fetchone()
        )

    def refresh_lists(self) -> None:
        """All desktop lists are peers; retain only the current selection."""
        from paper_daily import lists as lists_mod

        adopted = lists_mod.adopt_legacy_queue()
        if self.active_list is None and adopted:
            self.active_list = adopted
        entries = lists_mod.all_lists()
        self._switching = True
        self.list_picker.clear()
        for entry in entries:
            self.list_picker.addItem(
                f"{entry['name']} ({entry['read']}/{entry['count']})", entry["id"]
            )
        index = self.list_picker.findData(self.active_list)
        if index < 0:
            # The stored list was deleted while the window was closed.
            index = 0 if self.list_picker.count() else -1
            self.active_list = self.list_picker.itemData(index) if index >= 0 else None
        self.list_picker.setCurrentIndex(index)
        self._switching = False

    def _import_list(self) -> None:
        list_id = run_import(self.pal, ROOT, self, on_analysis=self._analyze_created_list)
        if list_id:
            self._open_list(list_id)

    def _analyze_created_list(self, list_id):
        self._open_list(list_id)
        self.queue_page._start(["analyze", "--list", list_id, "--jobs", "1"])

    def _open_list(self, list_id):
        self.active_list = list_id
        self.refresh_lists()
        ui_state.save("ui.list", list_id)
        self.show_queue()

    def _import_bundle(self):
        from paper_daily import feedback

        feedback.safe_record("ui.action", "bundle_import")
        from paper_daily.desktop.bundle_dialog import BundleDialog

        source, _filter = QFileDialog.getOpenFileName(
            self, "匯入研究資料包", "", "Paperfact 研究資料包 (*.zip)"
        )
        if not source:
            return
        dialog = BundleDialog(self, source=source)
        dialog.exec()
        if dialog.result_data:
            self._open_list(dialog.result_data["list"])

    def _import_bundle_link(self):
        from tempfile import TemporaryDirectory

        from paper_daily.desktop.bundle_dialog import BundleDialog
        from paper_daily.desktop.bundle_link_dialog import BundleLinkDialog

        if getattr(self, "_link_transfer_active", False):
            return
        self._link_transfer_active = True
        try:
            with TemporaryDirectory(prefix="paperfact-shared-") as folder:
                download = BundleLinkDialog(Path(folder), self)
                if download.exec() != QDialog.DialogCode.Accepted or not download.source:
                    return
                dialog = BundleDialog(self, source=download.source, download_missing=False)
                dialog.exec()
                if dialog.result_data:
                    self._open_list(dialog.result_data["list"])
        finally:
            self._link_transfer_active = False

    def _export_bundle(self):
        if not self.active_list:
            return
        self._export_list_bundle(self.active_list)

    def _export_list_bundle(self, list_id):
        from paper_daily import feedback

        feedback.safe_record("ui.action", "bundle_export")
        from paper_daily.desktop.bundle_dialog import BundleDialog

        with connect() as conn:
            listing = conn.execute("SELECT name FROM lists WHERE id=?", (list_id,)).fetchone()
        if listing is not None:
            BundleDialog(self, list_id=list_id, list_name=listing["name"]).exec()

    def _list_changed(self, _index: int) -> None:
        if self._switching:
            return
        self.active_list = self.list_picker.currentData()
        ui_state.save("ui.list", self.active_list)
        self.show_queue()
        # Switching to a list is the moment to start preparing it: a freshly imported
        # one has no dives and no PDFs, and waiting until a paper is opened means the
        # first thing you see is an empty 深度講解 tab.
        self.top_up_dives()

    def reload(self) -> None:
        self.export_bundle_action.setEnabled(bool(self.active_list))
        self.add_paper_action.setEnabled(bool(self.active_list))
        self.papers = self.data.queue(list_id=self.active_list) if self.active_list else []
        pinned = self.data.pins(self.active_list or "queue")
        for paper in self.papers:
            paper.pinned = paper.id in pinned
        read = sum(1 for p in self.papers if p.read)
        self.progress.setText(f"已讀 {read} · 未讀 {len(self.papers) - read}")
        self.queue_page.refresh()
        if self.stack.currentWidget() is self.queue_page:
            self.queue_page.enqueue_pdfs()

    def show_queue(self) -> None:
        self.stack.setCurrentWidget(self.queue_page)
        self.back_btn.setText("← 清單總覽")
        self.back_btn.show()
        self.read_btn.hide()
        self.reload()
        # Back on the list, the highlight is the paper you came from.
        self.queue_page._select(self._last_paper)
        self.queue_page.view.setFocus()
        self._refresh_ai_summary()

    def _find(self) -> None:
        """Search what is on screen: the paper's text when reading, the queue otherwise."""
        if self.stack.currentWidget() is self.reader_page:
            self.reader_page.focus_find()
        elif self.stack.currentWidget() is self.lists_page:
            self.lists_page.view.setFocus()
        else:
            self.queue_page.search.setFocus()

    def _escape(self) -> None:
        box = self.reader_page.find_box
        if box.hasFocus():
            box.clear()
            self.reader_page.pdf.setFocus()
            return
        # Inside a nested panel (a slide list inside 簡報), Esc first steps out to
        # the panel around it; only from the outermost one does it leave the page.
        if scopes().step_out(self):
            return
        self.go_back()

    def go_back(self) -> None:
        if self.stack.currentWidget() is self.reader_page:
            self.show_queue()
        elif self.stack.currentWidget() is self.queue_page:
            self.show_lists()

    def show_lists(self) -> None:
        from paper_daily import feedback

        feedback.safe_record("ui.action", "list_overview")
        self.refresh_lists()
        self.lists_page.refresh()
        self.stack.setCurrentWidget(self.lists_page)
        self.back_btn.hide()
        self.read_btn.hide()
        self.lists_page.view.setFocus()
        self._refresh_ai_summary()

    def go_forward(self) -> None:
        if self.stack.currentWidget() is self.lists_page:
            self.show_queue()
        elif self.stack.currentWidget() is self.queue_page and self._last_paper:
            self.open_paper(self._last_paper)

    def eventFilter(self, obj, event) -> bool:
        if event.type() == event.Type.MouseButtonPress:
            if event.button() == Qt.MouseButton.BackButton:
                self.go_back()
                return True
            if event.button() == Qt.MouseButton.ForwardButton:
                self.go_forward()
                return True
        return False

    def open_paper(self, paper_id: str) -> None:
        if not self.reader_page.presentation_pane.save_changes():
            QMessageBox.warning(self, "簡報修改尚未保存", "請先修正簡報內容，再切換論文。")
            return
        paper = next((p for p in self.papers if p.id == paper_id), None)
        if not paper:
            return
        if paper.state == "pending":
            self.data.set_state(paper.id, "delivered", list_id=self.active_list)
            paper.state = "delivered"
        paper.opened_at = now()
        ui_state.save(f"ui.paper.opened:{paper.id}", paper.opened_at)
        self.reader_page.load(paper)
        self._last_paper = paper.id
        self.top_up_dives()
        self.stack.setCurrentWidget(self.reader_page)
        self._refresh_ai_summary()
        self.back_btn.setText("← 清單")
        self.back_btn.show()
        self.read_btn.show()
        self.read_btn.setText("已讀 ✓" if paper.read else "標記已讀")

    def open_anywhere(self, paper_id: str) -> bool:
        """Open a paper by id from outside (`app --paper`), switching to the queue
        or a list that holds it when the one on screen does not."""
        if not any(p.id == paper_id for p in self.papers):
            for index in range(self.list_picker.count()):
                list_id = self.list_picker.itemData(index)
                if any(p.id == paper_id for p in self.data.queue(list_id=list_id)):
                    self.list_picker.setCurrentIndex(index)
                    break
            else:
                return False
        self.open_paper(paper_id)
        return self.reader_page.paper is not None and self.reader_page.paper.id == paper_id

    def open_next_unread(self) -> None:
        """Advance to the next unread paper after the one on screen.

        Reloads first, because the nightly run changes queue state while the window
        is open and the in-memory list would otherwise be days stale.
        """
        self.reload()
        current = self.reader_page.paper
        paper = next_after(self.papers, current.id if current else None)
        if not paper:
            QMessageBox.information(
                self, "目前沒有未讀論文",
                "可以加入新論文，或回到清單總覽選擇另一份清單。",
            )
            return
        self.open_paper(paper.id)

    def marked_ids(self) -> list[str]:
        return self._marked

    def set_marked(self, paper_ids: list[str]) -> None:
        self._marked = list(paper_ids)
        pocket.set_marked(self._marked)
        self.queue_page.update_pocket_btn()
        self.queue_page.view.viewport().update()

    def toggle_marked(self, paper_id: str) -> None:
        if paper_id in self._marked:
            self.set_marked([p for p in self._marked if p != paper_id])
        else:
            self.set_marked([*self._marked, paper_id])

    def set_pinned(self, paper_ids: list[str], on: bool) -> None:
        for paper_id in paper_ids:
            self.data.set_pin(self.active_list or "queue", paper_id, on)
        self.reload()

    def show_pocket(self) -> None:
        PocketDialog(self).exec()
        self.queue_page.update_pocket_btn()
        self.queue_page.view.viewport().update()

    def promote(self, paper_id: str) -> None:
        """Move a paper to the front of the queue, keeping why it got there.

        Following a lineage only works if you can act on it: seeing that tonight's
        paper rests on Shampoo is useless if Shampoo is 3000 rows away.
        """
        if self.active_list:
            from paper_daily import lists as lists_mod

            with connect() as conn:
                ids = [r[0] for r in conn.execute(
                    "SELECT paper_id FROM list_papers WHERE list_id=? ORDER BY position",
                    (self.active_list,),
                )]
            if paper_id in ids:
                lists_mod.reorder_papers(self.active_list,
                                        [paper_id, *[pid for pid in ids if pid != paper_id]])
                self.reload()
            return
        with connect() as conn:
            # Across every state, not just pending: papers already read keep their
            # place in the list, so beating only the unread ones would drop the
            # promoted paper below them and make the button look broken.
            front = conn.execute(
                "SELECT MIN(rank) FROM queue WHERE state != 'skipped'"
            ).fetchone()[0]
            conn.execute(
                "UPDATE queue SET rank=?, role='companion', reason=? "
                "WHERE paper_id=? AND state='pending'",
                ((front or 0) - 1.0, "你讀的論文建立在這篇之上", paper_id),
            )
        self.reload()

    def in_queue(self, paper_id: str) -> bool:
        """Whether promote() can move this paper: pending in the main queue, viewed there."""
        return paper_id in self.waiting([paper_id])

    def waiting(self, paper_ids: list[str]) -> set[str]:
        """Which of these papers promote() can move, in one query: the 脈絡 tab asks
        for every work it lists."""
        ids = list(dict.fromkeys(paper_ids))
        if not ids:
            return set()
        marks = ",".join("?" * len(ids))
        with connect() as conn:
            if self.active_list:
                rows = conn.execute(
                    f"SELECT paper_id FROM list_papers WHERE list_id=? AND state='pending' "
                    f"AND paper_id IN ({marks})", (self.active_list, *ids)
                )
            else:
                rows = conn.execute(
                    f"SELECT paper_id FROM queue WHERE state='pending' AND paper_id IN ({marks})",
                    ids,
                )
            return {r[0] for r in rows}

    def remove_paper(self, paper_id: str, title: str) -> None:
        """Take a paper out of whatever is on screen.

        Neither kind of removal deletes the paper: the corpus row, its notes and its
        deep dive are worth keeping, and in the main queue the row also records that
        it was read.
        """
        where = "這個清單" if self.active_list else "佇列"
        answer = QMessageBox.question(
            self, f"從{where}移除",
            f"把這篇從{where}移除?\n\n{title[:90]}\n\n"
            "論文本身、筆記與深度講解都會留著,之後要加回來也可以。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return

        if self.active_list:
            from paper_daily import lists as lists_mod

            lists_mod.remove_paper(self.active_list, paper_id)
            self.refresh_lists()
        else:
            with connect() as conn:
                qmod.remove(conn, paper_id)
        self.reload()

    def remove_papers(self, paper_ids: list[str]) -> bool:
        """Take several ticked papers out at once, asking once. True if removed."""
        if len(paper_ids) == 1:
            title = next((p.title for p in self.papers if p.id == paper_ids[0]), "")
            before = len(self.papers)
            self.remove_paper(paper_ids[0], title)
            return len(self.papers) < before
        where = "這個清單" if self.active_list else "佇列"
        answer = QMessageBox.question(
            self, f"從{where}移除",
            f"把勾選的 {len(paper_ids)} 篇從{where}移除?\n\n"
            "論文本身、筆記與深度講解都會留著,之後要加回來也可以。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return False
        if self.active_list:
            from paper_daily import lists as lists_mod

            for paper_id in paper_ids:
                lists_mod.remove_paper(self.active_list, paper_id)
            self.refresh_lists()
        else:
            with connect() as conn:
                for paper_id in paper_ids:
                    qmod.remove(conn, paper_id)
        self.reload()
        return True

    def set_read_many(self, paper_ids: list[str], read: bool) -> None:
        for paper_id in paper_ids:
            self.data.set_state(
                paper_id, "read" if read else "pending", list_id=self.active_list
            )
        self.reload()

    def set_read(self, paper_id: str, read: bool) -> None:
        """Mark a row read or unread without opening it."""
        self.data.set_state(
            paper_id, "read" if read else "pending", list_id=self.active_list
        )
        self.reload()

    def _add_paper(self) -> None:
        if run_add(self):
            self.reload()
            self.top_up_dives()

    def _toggle_read(self) -> None:
        paper = self.reader_page.paper
        if not paper:
            return
        new_state = "delivered" if paper.read else "read"
        self.data.set_state(paper.id, new_state, list_id=self.active_list)
        paper.state = new_state
        self.read_btn.setText("已讀 ✓" if paper.read else "標記已讀")
        read = sum(1 for p in self.papers if p.read)
        self.progress.setText(f"已讀 {read} · 未讀 {len(self.papers) - read}")
        self.top_up_dives()


# One window per data folder, not per machine: an installed copy and a source
# checkout keep separate papers, and a second launch of one must not raise the
# other's window. The build's smoke test relies on it too.
SINGLE_INSTANCE_KEY = "paperfact-" + hashlib.sha1(
    str(DATA_DIR.resolve()).lower().encode("utf-8")
).hexdigest()[:12]

SW_SHOW = 5


def _force_visible(window: QWidget) -> None:
    """Show the window even when the process was started hidden.

    The shortcut launches us through a script that starts the process with SW_HIDE,
    which is the only reliable way to suppress the console window uv's venv forces on
    us. Windows passes that flag down in STARTUPINFO and it swallows the first
    top-level window too, so `show()` alone leaves the reader running invisibly.
    Asking Win32 directly is the fix.
    """
    window.raise_()
    window.activateWindow()
    if sys.platform != "win32":
        return
    import ctypes

    hwnd = int(window.winId())
    ctypes.windll.user32.ShowWindow(hwnd, SW_SHOW)
    ctypes.windll.user32.SetForegroundWindow(hwnd)


def _hand_off_to_running_instance(
    open_next: bool, restart: bool = False, paper: str | None = None
) -> bool:
    """If a window is already open, tell it to come forward and return True.

    The nightly job launches the reader every midnight, and double-clicking the
    shortcut is the other way in. Without this, a second launch would stack another
    window on the first instead of raising the one already showing tonight's paper.
    """
    socket = QLocalSocket()
    socket.connectToServer(SINGLE_INSTANCE_KEY)
    if not socket.waitForConnected(300):
        return False
    if paper:
        command = b"open:" + paper.encode()
    else:
        command = b"restart" if restart else b"next" if open_next else b"show"
    socket.write(command)
    socket.flush()
    socket.waitForBytesWritten(500)
    if restart:
        socket.waitForReadyRead(3000)
        response = bytes(socket.readAll().data())
        if response == b"restarting":
            if socket.state() != QLocalSocket.LocalSocketState.UnconnectedState:
                socket.waitForDisconnected(3000)
            if socket.state() == QLocalSocket.LocalSocketState.UnconnectedState:
                return False
        print("Restart not completed: the running app is busy or needs a one-time manual restart.")
    socket.disconnectFromServer()
    return True


def _install_error_log() -> None:
    from paper_daily.config import DATA_DIR
    from paper_daily.diagnostics import install_error_hooks

    install_error_hooks(phase="desktop", directory=DATA_DIR)


def style(app: QApplication) -> None:
    """One look on every platform.

    Each platform's native style sizes buttons, combo boxes and scroll bars its own
    way: on macOS the PDF toolbar overflowed the pane and the tab bar centred itself,
    on a layout that fits on Windows. Fusion draws them the same everywhere.

    The same goes for the default font: each system has its own size (12 px on
    Windows, 13 on macOS, often 15 on Linux), and every label without a size of its
    own grew or shrank with it.
    """
    app.setStyle("Fusion")
    app.setFont(fonts.font(fonts.SANS, pixels=fonts.UI_PIXELS))


def _finish_smoke(app) -> None:
    # A first-use dialog runs its own event loop before app.exec(). quit() alone
    # does not end that loop. Reject it; never acknowledge consent in a smoke run.
    modal = app.activeModalWidget()
    if modal is not None:
        modal.close()
    app.quit()


def run(open_next: bool = False, restart: bool = False, paper: str | None = None) -> int:
    ensure_dirs()
    init_db()
    _install_error_log()
    rich_view.prepare()
    runtime.adopt_login_path()
    app = QApplication.instance() or QApplication(sys.argv)
    style(app)
    fonts.load()
    # Without it the Dock (macOS) and the taskbar show the Python interpreter's icon.
    app.setWindowIcon(QIcon(str(ROOT / "assets" / "paper-daily.ico")))

    if _hand_off_to_running_instance(open_next, restart, paper):
        return 0

    smoke = os.environ.get("PAPERFACT_SMOKE_SECONDS")
    if smoke:
        QTimer.singleShot(int(float(smoke) * 1000), lambda: _finish_smoke(app))
    from paper_daily.desktop.onboarding_dialog import ensure_accepted

    if not ensure_accepted(show=_force_visible):
        return 0

    window = MainWindow(open_next=open_next)
    from paper_daily.desktop.usage_monitor import UsageMonitor

    window.usage_monitor = UsageMonitor(window)
    from paper_daily.desktop import ai_access

    window.ai_access = ai_access.install(window)
    from paper_daily import ui_stalls
    from paper_daily.config import DATA_DIR

    window.stall_watch = ui_stalls.install(DATA_DIR, window)
    window._restore_restart()
    if paper:
        window.open_anywhere(paper)
    window.update_banner.check_in_background()

    # A crashed previous run can leave the socket name taken on Windows; removing it
    # is the documented way to reclaim it, and it is ours by name.
    QLocalServer.removeServer(SINGLE_INSTANCE_KEY)
    server = QLocalServer(window)
    server.listen(SINGLE_INSTANCE_KEY)

    def on_second_launch() -> None:
        conn = server.nextPendingConnection()
        if conn is None:
            return

        def handle() -> None:
            command = bytes(conn.readAll().data())
            if command == b"restart":
                if window._prepare_restart() and window.close():
                    server.close()
                    conn.write(b"restarting")
                else:
                    conn.write(b"busy")
                conn.flush()
                conn.disconnectFromServer()
                return
            window.showNormal()
            _force_visible(window)
            if command == b"next":
                window.reload()
                window.open_next_unread()
            elif command.startswith(b"open:"):
                window.open_anywhere(command[5:].decode(errors="replace"))
            conn.disconnectFromServer()

        conn.readyRead.connect(handle)

    server.newConnection.connect(on_second_launch)

    from paper_daily.pdf_downloads import DownloadQueue

    window.pdf_downloads = DownloadQueue()
    window.queue_page.enable_downloads(window.pdf_downloads)
    app.aboutToQuit.connect(window.pdf_downloads.close)
    window.show()
    from paper_daily.desktop.feedback_dialog import FeedbackInvitation

    window.feedback_invitation = FeedbackInvitation(window)
    window._refresh_ai_summary(check=True)
    _force_visible(window)
    # The build's smoke test: the whole app, web views included, starts and quits
    # cleanly on a machine with no screen and no papers.
    return app.exec()
