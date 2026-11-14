"""Saved-first modeless Lineage workflow; slow work stays off the GUI thread."""

from __future__ import annotations

import threading
from contextlib import closing
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QPointF, Qt, QThread, QTimer, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from paper_daily import (
    ai_choices,
    audit_lineage,
    lineage_history_originals,
    lineage_lifecycle,
    lineage_sets,
    lineage_source_reader,
    lineage_versions,
    llm,
)
from paper_daily import research_generation as generation
from paper_daily.desktop import activity, fonts
from paper_daily.desktop.claim_evidence import ClaimSection, _label
from paper_daily.desktop.settings_style import apply as style_settings
from paper_daily.lineage_workflow import LineageWorkflow
from paper_daily.manual_highlight_ops import HighlightOwner, _readonly_connection

TEXT = {
    "en": {
        "title": ("Research lineage"),
        "intro": (
            "Choose up to three related papers. Explain earlier gaps, this "
            "paper's change and later developments from selected originals."
        ),
        "search": ("Filter related papers"),
        "peers": ("Related originals (optional; at most 3)"),
        "generate": ("Generate a new analysis"),
        "refresh": ("Refresh saved results"),
        "settings": ("AI account / model"),
        "stop": ("Stop"),
        "close": ("Return to reading"),
        "loading": ("Reading saved results..."),
        "empty": ("No saved analysis yet."),
        "working": ("Preparing selected originals..."),
        "changed": ("The loaded paper changed. Reopen this window."),
        "failed": (
            "Could not finish. Saved research is unchanged; check AI settin"
            "gs or originals and retry."
        ),
        "stopped": ("Stopped. Completed proposals, if any, remain in research history."),
        "retained": ("Proposal retained for review; changed context was not overwritten."),
        "saved_local": ("Saved on this device."),
        "queued_sync": ("Saved on this device; queued for synchronization."),
        "limit": ("Select at most three related papers."),
        "missing": ("Reopen the original before generating analysis."),
        "confirm": ("Create another analysis? Existing analyses are preserved."),
        "model": ("Next analysis: "),
        "unknown": ("not reported"),
        "originals": ("Selected source originals"),
        "first": ("Showing at most 200 related papers. Filter to find others."),
        "unchecked": ("Located quotations do not certify scientific support or influence."),
        "source_retention": ("Retaining exact originals..."),
        "model_stage": ("Waiting for the selected AI..."),
        "quote_verification": ("Checking quotations against selected originals..."),
        "publication": ("Saving analysis and source links..."),
        "prior_gap": ("Earlier gap"),
        "current_change": ("This paper's change"),
        "later_development": ("Later development"),
        "no_statement": ("No grounded statement in the selected originals."),
    },
    "zh-TW": {
        "title": ("研究脈絡"),
        "intro": ("最多選三篇相關論文，依選定原文整理前人缺口、這篇的改變與後續發展。"),
        "search": ("搜尋相關論文"),
        "peers": ("相關原文（可不選，最多三篇）"),
        "generate": ("產生新的脈絡分析"),
        "refresh": ("重新讀取已存結果"),
        "settings": ("AI 帳號與模型"),
        "stop": ("停止"),
        "close": ("回到閱讀"),
        "loading": ("讀取已存分析…"),
        "empty": ("尚無已存脈絡分析。"),
        "working": ("準備選定原文…"),
        "changed": ("目前論文已切換，請重新開啟此視窗。"),
        "failed": ("未能完成。原有研究未變更，請檢查 AI 設定或原文後重試。"),
        "stopped": ("已停止；已完成的提案若有保留，可從研究紀錄檢視。"),
        "retained": ("已保留分析提案供檢視，沒有覆寫已變更的內容。"),
        "saved_local": ("已儲存在本機。"),
        "queued_sync": ("已儲存在本機，等待同步。"),
        "limit": ("最多選三篇相關論文。"),
        "missing": ("請重新開啟原文後再產生分析。"),
        "confirm": ("要新增一份分析嗎？先前的分析會保留。"),
        "model": ("下一次分析使用："),
        "unknown": ("未回報"),
        "originals": ("選定原文"),
        "first": ("最多顯示 200 篇，請用搜尋找到其他論文。"),
        "unchecked": ("找到原文句子不等於已證明論點或學術影響關係。"),
        "source_retention": ("保留原文版本…"),
        "model_stage": ("等待選定的 AI 回應…"),
        "quote_verification": ("以選定原文核對引文…"),
        "publication": ("儲存分析與來源連結…"),
        "prior_gap": ("前人缺口"),
        "current_change": ("本篇改變"),
        "later_development": ("後續發展"),
        "no_statement": ("選定原文中尚無可用的脈絡敘述。"),
    },
}

TEXT["en"].update(
    open_source="View exact original",
    source_unavailable="Exact original unavailable here. Download this version and retry.",
)
TEXT["zh-TW"].update(
    open_source="\u67e5\u770b\u5c0d\u61c9\u539f\u6587",
    source_unavailable="\u6b64\u88dd\u7f6e\u5c1a\u7121\u9019\u500b\u539f\u6587\u7248\u672c\uff0c\u8acb\u4e0b\u8f09\u5f8c\u91cd\u8a66\u3002",
)

TEXT["en"].update(
    audit="Check all originals",
    audit_work="Checking originals: {done} / {total}",
    audit_ready=("Checked snapshot: originals {checked}/{total}; "
                 "quotes located {located}/{quotes}. "
                 "Text location only; scientific support is not checked."),
    audit_failed="Could not check this corpus. Research is unchanged; refresh or retry.",
    audit_unavailable="Original unavailable; this quotation was not checked.",
    audit_review="Quotation needs inspection in its recorded original.",
    audit_help="Check this saved corpus offline. No AI, downloads, edits or original activation.",
)
TEXT["zh-TW"].update(
    audit="\u6838\u5c0d\u6240\u6709\u539f\u6587",
    audit_work="\u6838\u5c0d\u539f\u6587\uff1a{done} / {total}",
    audit_ready=("\u672c\u6b21\u6838\u5c0d\uff1a\u539f\u6587 {checked}/{total}\uff1b"
                 "\u627e\u5230\u5f15\u7528 {located}/{quotes}\u3002"
                 "\u50c5\u6838\u5c0d\u6587\u5b57\u4f4d\u7f6e\uff0c"
                 "\u4e0d\u4ee3\u8868\u8ad6\u9ede\u5df2\u7372\u5f97\u652f\u6301\u3002"),
    audit_failed="\u7121\u6cd5\u6838\u5c0d\u6b64\u7814\u7a76\u8108\u7d61\u3002"
                 "\u5167\u5bb9\u672a\u8b8a\u66f4\uff0c\u8acb\u91cd\u65b0\u8b80\u53d6\u6216\u91cd\u8a66\u3002",
    audit_unavailable="\u539f\u6587\u4e0d\u53ef\u7528\uff0c\u6b64\u5f15\u7528\u5c1a\u672a\u6838\u5c0d\u3002",
    audit_review="\u6b64\u5f15\u7528\u9700\u5728\u8a18\u9304\u7684\u539f\u6587\u4e2d\u6aa2\u67e5\u3002",
    audit_help="\u96e2\u7dda\u6838\u5c0d\u6b64\u7814\u7a76\u8108\u7d61\uff0c"
               "\u4e0d\u547c\u53eb AI\u3001\u4e0b\u8f09\u3001\u6539\u5beb"
               "\u6216\u5207\u63db\u539f\u6587\u3002",
)

TEXT["en"]["completed"] = (
    "Saved analysis: {backend} / requested: {requested} / returned: {returned}"
)
TEXT["zh-TW"]["completed"] = (
    "\u6b64\u4efd\u5206\u6790\uff1a{backend} / "
    "\u6307\u5b9a\uff1a{requested} / \u56de\u5831\uff1a{returned}"
)

TEXT["en"]["requirements"] = (
    "Original passage: {own} / citing passage: {citing} / citation identity: {identity}"
)
TEXT["zh-TW"]["requirements"] = (
    "\u539f\u6587\u6bb5\u843d\uff1a{own} / "
    "\u5f15\u7528\u6bb5\u843d\uff1a{citing} / "
    "\u5f15\u7528\u6587\u737b\u6838\u5c0d\uff1a{identity}"
)


TEXT["en"].update(
    occupied="Remove the current analysis in this slot before restoring another version.",
    unproven="This historical version needs reviewed adoption before restoration.",
    current_results="Current analyses",
    history="History",
    remove="Remove analysis",
    restore="Restore version",
    older="Older",
    newer="Newer",
    historical="Historical version",
    remove_confirm="Remove this analysis? Its history and exact originals are kept.",
    restore_confirm=(
        "Restore this version without AI? Current source permissions will be checked again."
    ),
    lifecycle_work="Saving analysis change...",
    lifecycle_failed=(
        "Could not apply this change. Refresh and review the selected version before retrying."
    ),
    history_source=(
        "Historical originals are verified separately. Viewing them does not restore this analysis."
    ),
    refresh_needed="Change saved. Refresh to load current results.",
)
TEXT["zh-TW"].update(
    occupied="\u8acb\u5148\u79fb\u9664\u6b64\u4f4d\u7f6e\u7684\u76ee\u524d\u5206\u6790\uff0c\u518d\u9084\u539f\u5176\u4ed6\u7248\u672c\u3002",
    unproven="\u6b64\u6b77\u53f2\u7248\u672c\u9700\u6838\u5c0d\u5f8c\u91cd\u65b0\u532f\u5165\uff0c\u7121\u6cd5\u76f4\u63a5\u9084\u539f\u3002",
    current_results="\u76ee\u524d\u5206\u6790",
    history="\u6b77\u53f2\u7248\u672c",
    remove="\u79fb\u9664\u5206\u6790",
    restore="\u9084\u539f\u7248\u672c",
    older="\u8f03\u820a",
    newer="\u8f03\u65b0",
    historical="\u6b77\u53f2\u7248\u672c",
    remove_confirm=("移除這份分析？歷史版本與原文會保留。"),
    restore_confirm=("還原這個版本？不會呼叫 AI，並會重新核對來源權限。"),
    lifecycle_work="\u5132\u5b58\u5206\u6790\u8b8a\u66f4\u2026",
    lifecycle_failed=("無法套用變更，請重新讀取並核對版本後再試。"),
    history_source=("歷史原文會獨立核對，查看不會還原或取代目前分析。"),
    refresh_needed=("變更已儲存，請重新讀取結果。"),
)


class LineageOriginalDialog(QDialog):
    """Read-only PDF from a real Lineage proof, without changing the main reader."""

    def __init__(self, proof, module, owner, row, source_id, parent, *, current, page=1):
        from PySide6.QtPdf import QPdfDocument
        from PySide6.QtPdfWidgets import QPdfView

        super().__init__(parent)
        self._proof, self._module, self._current = proof, module, current
        self.disposed = False
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self.setWindowTitle(parent.t["originals"])
        self.resize(800, 760)
        data = module.for_delivery(proof, owner, row, source_id)
        self.buffer = QBuffer(self)
        self.buffer.setData(QByteArray(data))
        self.buffer.open(QIODevice.OpenModeFlag.ReadOnly)
        self.document = QPdfDocument(self)
        self.document.load(self.buffer)
        self.pdf = QPdfView(self)
        self.pdf.setDocument(self.document)
        self.pdf.setPageMode(QPdfView.PageMode.MultiPage)
        self.pdf.setZoomMode(QPdfView.ZoomMode.FitToWidth)
        layout = QVBoxLayout(self)
        layout.addWidget(_label(parent.t["unchecked"]))
        layout.addWidget(self.pdf, 1)
        self.poll = QTimer(self)
        self.poll.setInterval(250)
        self.poll.timeout.connect(self.check_current)
        self.poll.start()
        self.initial_jump = QTimer(self)
        self.initial_jump.setSingleShot(True)
        self.initial_jump.timeout.connect(
            lambda: self.pdf.pageNavigator().jump(page - 1, QPointF(), 0)
        )
        self.initial_jump.start(0)

    def check_current(self):
        if self.disposed:
            return False
        if not self._current() or not self._module.metadata_current(self._proof):
            self.close()
            return False
        return True

    def closeEvent(self, event):
        self.poll.stop()
        self.initial_jump.stop()
        self.document.close()
        self.buffer.close()
        self.buffer.setData(QByteArray())
        self._proof = None
        self.disposed = True
        event.accept()


class Worker(QThread):
    progress = Signal(str)

    def __init__(self, call, parent):
        super().__init__(parent)
        self.call, self.cancelled = call, threading.Event()
        self.result, self.error = None, None

    def run(self):
        try:
            self.result = self.call(self.cancelled.is_set, self.progress.emit)
        except Exception as error:
            self.error = type(error).__name__


class LineageDialog(QDialog):
    def __init__(
        self,
        database,
        paper_id,
        parent=None,
        *,
        owner,
        document,
        legacy_root,
        current_view,
        language="zh-TW",
        workflow_factory=LineageWorkflow.prepare,
    ):
        super().__init__(parent)
        self.path, self.paper_id = Path(database).resolve(strict=True), paper_id
        if owner is not None and (
            not isinstance(owner, HighlightOwner)
            or owner.database != self.path
            or owner.paper_id != paper_id
        ):
            raise ValueError("Loaded Lineage owner belongs to another paper/workspace")
        self.identity = generation._identity(self.path)
        self.owner, self.document = owner, document
        self.legacy_root, self.current_view = Path(legacy_root), current_view
        self.view, self.workflow_factory = current_view(), workflow_factory
        self.t = TEXT.get(language, TEXT["en"])
        self._worker = None
        self._invalid = self._closing = self.disposed = False
        self._live = threading.Event()
        self._live.set()
        self._handle = activity.Handle()
        self._repair_ticket = None
        self._can_repair = False
        self.language = language
        self.saved, self.workflow = [], None
        self._entries, self.history_offset = [], 0
        self._history_more = False
        self._needs_refresh = False
        self._pending_select = None
        self.source_buttons = []
        self._original_viewer = None
        self._source_expected = None
        self._source_origin = None
        self._audit_pending = self._audit_result = None
        self._audit_summary_label = None
        self.audit_labels = []
        style_settings(self)
        self.setFont(fonts.font(pixels=14))
        self.setWindowTitle(self.t["title"])
        self.setWindowModality(Qt.WindowModality.NonModal)
        self.resize(920, 720)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        title = _label(self.t["title"])
        title.setProperty("role", "title")
        layout.addWidget(title)
        layout.addWidget(_label(self.t["intro"]))
        route = QHBoxLayout()
        self.route = _label("")
        route.addWidget(self.route, 1)
        self.settings_button = QPushButton(self.t["settings"])
        self.settings_button.clicked.connect(self.settings)
        route.addWidget(self.settings_button)
        layout.addLayout(route)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        left = QWidget()
        choices = QVBoxLayout(left)
        choices.addWidget(_label(self.t["peers"]))
        self.search = QLineEdit()
        self.search.setPlaceholderText(self.t["search"])
        self.search.setAccessibleName(self.t["search"])
        self.search.returnPressed.connect(self.refresh)
        choices.addWidget(self.search)
        self.peers = QListWidget()
        self.peers.setSelectionMode(QAbstractItemView.SelectionMode.MultiSelection)
        self.peers.setAccessibleName(self.t["peers"])
        choices.addWidget(self.peers, 1)
        note = _label(self.t["first"])
        note.setProperty("role", "muted")
        choices.addWidget(note)
        splitter.addWidget(left)
        right = QWidget()
        results = QVBoxLayout(right)
        history_bar = QHBoxLayout()
        self.mode = QComboBox()
        self.mode.addItems([self.t["current_results"], self.t["history"]])
        self.mode.setAccessibleName(self.t["history"])
        self.mode.currentIndexChanged.connect(self._mode_changed)
        history_bar.addWidget(self.mode, 1)
        self.newer_button = QPushButton(self.t["newer"])
        self.older_button = QPushButton(self.t["older"])
        self.newer_button.clicked.connect(lambda: self._page_history(-100))
        self.older_button.clicked.connect(lambda: self._page_history(100))
        history_bar.addWidget(self.newer_button)
        history_bar.addWidget(self.older_button)
        self.repair_button = QPushButton(
            "\u66f4\u65b0\u7248\u672c\u7d22\u5f15"
            if language.startswith("zh") else "Update version index"
        )
        self.repair_button.clicked.connect(self.repair_history)
        history_bar.addWidget(self.repair_button)
        results.addLayout(history_bar)
        self.results = QComboBox()
        self.results.setAccessibleName(self.t["refresh"])
        self.results.currentIndexChanged.connect(self.render)
        results.addWidget(self.results)
        lifecycle_bar = QHBoxLayout()
        self.remove_button = QPushButton(self.t["remove"])
        self.restore_button = QPushButton(self.t["restore"])
        self.remove_button.clicked.connect(lambda: self._change_analysis("retire"))
        self.restore_button.clicked.connect(lambda: self._change_analysis("restore"))
        for button in (
            self.remove_button,
            self.restore_button,
            self.newer_button,
            self.older_button,
        ):
            button.setAutoDefault(False)
        lifecycle_bar.addWidget(self.remove_button)
        lifecycle_bar.addWidget(self.restore_button)
        self.audit_button = QPushButton(self.t["audit"])
        self.audit_button.setAutoDefault(False)
        self.audit_button.setToolTip(self.t["audit_help"])
        self.audit_button.clicked.connect(self.audit_sources)
        lifecycle_bar.addWidget(self.audit_button)
        lifecycle_bar.addStretch()
        results.addLayout(lifecycle_bar)
        from paper_daily.desktop.lineage_adoption_action import LineageAdoptionAction

        self.adoption = LineageAdoptionAction(self)
        results.addWidget(self.adoption)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.cards = QWidget()
        self.cards_layout = QVBoxLayout(self.cards)
        self.scroll.setWidget(self.cards)
        results.addWidget(self.scroll, 1)
        splitter.addWidget(right)
        splitter.setSizes([260, 620])
        layout.addWidget(splitter, 1)
        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.setAccessibleName(self.t["working"])
        layout.addWidget(self.progress)
        self.status = _label(self.t["loading"])
        self.status.setAccessibleName("Lineage status")
        layout.addWidget(self.status)
        actions = QHBoxLayout()
        self.generate_button = QPushButton(self.t["generate"])
        self.generate_button.setProperty("role", "primary")
        self.generate_button.clicked.connect(self.generate)
        self.refresh_button = QPushButton(self.t["refresh"])
        self.refresh_button.clicked.connect(self.refresh)
        self.stop_button = QPushButton(self.t["stop"])
        self.stop_button.clicked.connect(self.cancel)
        close = QPushButton(self.t["close"])
        close.clicked.connect(self.close)
        for button in (self.generate_button, self.refresh_button, self.stop_button, close):
            button.setAutoDefault(False)
            actions.addWidget(button)
        layout.addLayout(actions)
        self.poll = QTimer(self)
        self.poll.setInterval(200)
        self.poll.timeout.connect(self._check)
        self.poll.start()
        self._controls()
        QTimer.singleShot(0, self.refresh)

    @property
    def busy(self):
        return self._worker is not None

    def _check(self):
        try:
            same = (
                self.current_view() == self.view
                and generation._identity(self.path) == self.identity
            )
        except (OSError, ValueError, RuntimeError):
            same = False
        if not same and not self._invalid:
            self._invalid = True
            self._live.clear()
            self.cancel()
            self.status.setText(self.t["changed"])
            self._controls()
        return same and not self._invalid and not self.disposed

    def _controls(self):
        enabled = not self.busy and not self._invalid and not self._closing and not self.disposed
        for widget in (
            self.search,
            self.peers,
            self.results,
            self.mode,
            self.refresh_button,
            self.settings_button,
        ):
            widget.setEnabled(enabled)
        self.repair_button.setVisible(self.mode.currentIndex() == 1)
        self.repair_button.setEnabled(
            enabled and self.owner is not None and self._can_repair
            and self.mode.currentIndex() == 1
        )
        self.generate_button.setEnabled(enabled and self.owner is not None)
        self.stop_button.setEnabled(self.busy and not self._closing)
        self.stop_button.setVisible(self.busy)
        self.progress.setVisible(self.busy)
        index = self.results.currentIndex()
        entry = self._entries[index] if 0 <= index < len(self._entries) else None
        current = entry is not None and entry["current"] and not self._needs_refresh
        self.adoption.controls(enabled and not self._needs_refresh, entry)
        self.audit_button.setEnabled(
            enabled and self.owner is not None and current and self.mode.currentIndex() == 0
        )
        if self._invalid or self._closing or self._audit_result is not None and (
            not current or self._audit_result[1] != self.saved[index]
        ):
            self._audit_result = None
            for label in self.audit_labels:
                label.hide()
            if self._audit_summary_label is not None:
                self._audit_summary_label.hide()
        self.remove_button.setEnabled(enabled and self.owner is not None and current)
        self.restore_button.setEnabled(
            enabled
            and self.owner is not None
            and entry is not None
            and not entry["occupied"]
            and not self._needs_refresh
            and entry["origin"] is not None
        )
        self.restore_button.setToolTip(
            self.t["occupied"]
            if entry and entry["occupied"]
            else self.t["unproven"]
            if entry and entry["origin"] is None
            else self.t["restore_confirm"]
        )
        history = self.mode.currentIndex() == 1
        self.newer_button.setVisible(history)
        self.older_button.setVisible(history)
        self.newer_button.setEnabled(enabled and history and self.history_offset > 0)
        self.older_button.setEnabled(enabled and history and self._history_more)
        for button in self.source_buttons:
            button.setEnabled(
                enabled
                and self.owner is not None
                and not self._needs_refresh
                and entry is not None
                and (current or entry["origin"] is not None)
            )

    def _start(self, kind, call):
        if self.busy or self._closing or not self._check():
            return False
        self.progress.setRange(0, 0)
        worker = Worker(call, self)
        worker.kind = kind
        self._worker = worker
        worker.progress.connect(self._stage)
        worker.finished.connect(self._finished)
        self._controls()
        worker.start()
        return True

    def _stage(self, stage):
        if stage.startswith("lineage_audit:"):
            done, total = (int(v) for v in stage.split(":")[1:])
            text = self.t["audit_work"].format(done=done, total=total)
            if self._check() and not self._closing:
                self.progress.setRange(0, total)
                self.progress.setValue(done)
                self._handle.update(dict(stage=text, completed=done, total=total))
        elif stage.startswith("history_reindex:"):
            from paper_daily.desktop.history_index_text import progress_text

            through, target, restored = (int(v) for v in stage.split(":")[1:])
            text = progress_text(
                dict(through=through, target=target, restored=restored), self.language,
            )
        else:
            text = self.t.get("model_stage" if stage == "model" else stage, self.t["working"])
        if self._check() and not self._closing:
            self.status.setText(text)
        self._handle.stage(text)

    def _read(self, search, selected=(), *, history=False, offset=0):
        can_repair = False
        if self.owner is not None:
            with closing(_readonly_connection(self.path)) as conn:
                conn.execute("BEGIN")
                self.owner.check(conn)
                can_repair = bool(conn.execute(
                    "SELECT 1 FROM sqlite_master WHERE name='research_sync_binding'"
                ).fetchone())
                if can_repair:
                    import sqlite3

                    from paper_daily.lineage_history_repair import _pending_in

                    try:
                        can_repair = _pending_in(conn)
                    except (ValueError, sqlite3.Error):
                        # A derived index error must not hide readable saved research.
                        can_repair = True
                papers = conn.execute(
                    "SELECT id,title FROM papers WHERE id<>? AND title LIKE ? "
                    "ORDER BY title,id LIMIT 200",
                    (self.paper_id, "%" + search + "%"),
                ).fetchall()
                if selected:
                    pinned = conn.execute(
                        "SELECT id,title FROM papers WHERE id IN ("
                        + ",".join("?" for _ in selected)
                        + ") ORDER BY title,id",
                        selected,
                    ).fetchall()
                    keep = {row[0] for row in pinned}
                    papers = [*pinned, *(row for row in papers if row[0] not in keep)]
        else:
            papers = []
        catalog = (
            lineage_versions.collect(self.owner, offset=offset)
            if history and self.owner is not None
            else None
        )
        saved = (
            [item["row"] for item in catalog["items"]]
            if catalog is not None
            else lineage_sets.saved(self.path, self.paper_id)
        )
        entries = (
            catalog["items"]
            if catalog is not None
            else [dict(row=row, current=True, occupied=True, origin=None) for row in saved]
        )
        from paper_daily.lineage_direct_adoption import can_offer_in

        with closing(_readonly_connection(self.path)) as conn:
            for entry in entries:
                entry["can_adopt"] = bool(entry["current"] and can_offer_in(conn, entry["row"]))
        labels = []
        for row in saved:
            body = lineage_sets.decode(row["body_json"])
            unavailable = sum(
                source["availability"] == "unavailable" for source in body["report"]["sources"]
            )
            time = datetime.fromisoformat(row["written_at"]).astimezone().strftime("%Y-%m-%d %H:%M")
            labels.append(
                time
                + " / "
                + str(len(body["bindings"]))
                + " sources"
                + (" / " + str(unavailable) + " unavailable" if unavailable else "")
            )
        if history:
            labels = [
                label
                + " / "
                + (self.t["current_results"] if entry["current"] else self.t["historical"])
                for label, entry in zip(labels, entries, strict=True)
            ]
        return dict(
            papers=[tuple(row) for row in papers],
            saved=saved,
            labels=labels,
            entries=entries,
            more=bool(catalog and catalog["more"]),
            can_repair=can_repair,
        )

    def refresh(self):
        if self.busy or self._closing or not self._check():
            return False
        try:
            self.route.setText(
                self.t["model"] + ai_choices.connection_label(llm.settings("lineage"))
            )
        except (OSError, ValueError):
            self.route.setText(self.t["missing"])
        query = self.search.text().strip()
        selected = tuple(item.data(Qt.ItemDataRole.UserRole) for item in self.peers.selectedItems())
        if len(selected) > 3:
            self.status.setText(self.t["limit"])
            return False
        self.status.setText(self.t["loading"])
        history, offset = self.mode.currentIndex() == 1, self.history_offset
        return self._start(
            "read",
            lambda stop, progress: (
                None if stop() else self._read(query, selected, history=history, offset=offset)
            ),
        )

    def repair_history(self):
        if (self.busy or self._closing or not self._can_repair
                or self.mode.currentIndex() != 1 or not self._check()):
            return False
        from paper_daily.workspace_service import Ticket

        ticket = self._repair_ticket = Ticket()
        query, offset = self.search.text().strip(), self.history_offset
        selected = tuple(item.data(Qt.ItemDataRole.UserRole) for item in self.peers.selectedItems())
        path, identity, live = self.path, self.identity, self._live

        def repair(stop, emit):
            from paper_daily import store
            from paper_daily.lineage_history_repair import HistoryRepair
            from paper_daily.sync_deck_publication import runtime

            client = runtime(database=path)
            if client is None:
                raise ValueError("Version index repair requires an enrolled workspace")
            service = HistoryRepair(
                client, current_path=lambda: store.DB_PATH, expected_identity=identity,
                current=lambda: live.is_set() and not stop(),
            )
            def progress(value):
                emit("history_reindex:" + ":".join(str(value[k]) for k in (
                    "through", "target", "restored")))

            result = service.drain(ticket, progress, max_steps=16, seconds=10)
            return dict(repair=result, **self._read(query, selected, history=True, offset=offset))

        self._handle = activity.begin(
            self, self.repair_button.text(), task="lineage", key=f"lineage-index:{path}",
            paper_id=self.paper_id, cancel=self.cancel,
        )
        if not self._handle.accepted:
            return False
        started = self._start("repair_history", repair)
        if not started:
            self._handle.finish(False, self.t["stopped"], cancelled=True)
            self._repair_ticket = None
        return started

    def _mode_changed(self):
        self.history_offset = 0
        self.refresh()

    def _page_history(self, step):
        if self.busy or not self._check() or self.mode.currentIndex() != 1:
            return False
        if step > 0 and not self._history_more or step < 0 and self.history_offset == 0:
            return False
        self.history_offset = max(0, self.history_offset + step)
        return self.refresh()

    def _change_analysis(self, action):
        if (
            self.busy
            or self._closing
            or self.owner is None
            or self._needs_refresh
            or not self._check()
        ):
            return False
        index = self.results.currentIndex()
        if not 0 <= index < len(self._entries):
            return False
        entry = self._entries[index]
        if (
            action == "retire"
            and not entry["current"]
            or action == "restore"
            and (entry["occupied"] or entry["origin"] is None)
        ):
            return False
        answer = QMessageBox.question(
            self,
            self.t["title"],
            self.t["remove_confirm" if action == "retire" else "restore_confirm"],
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if answer != QMessageBox.StandardButton.Yes or self.busy or not self._check():
            return False
        index = self.results.currentIndex()
        if not 0 <= index < len(self._entries) or self._entries[index] != entry:
            return False
        owner, live = self.owner, self._live
        row, origin, request = entry["row"], entry["origin"], str(uuid4())
        query = self.search.text().strip()
        selected = tuple(item.data(Qt.ItemDataRole.UserRole) for item in self.peers.selectedItems())
        self._pending_select = row
        self.mode.blockSignals(True)
        self.mode.setCurrentIndex(1)
        self.mode.blockSignals(False)
        self.history_offset = 0

        def change(stop, progress):
            receipt = lineage_lifecycle.change(
                owner,
                row,
                request_id=request,
                action=action,
                origin=origin if action == "restore" else None,
                cancelled=lambda: stop() or not live.is_set(),
            )
            try:
                return dict(receipt=receipt, **self._read(query, selected, history=True))
            except (OSError, ValueError):
                return dict(receipt=receipt, refresh_error=True)

        self._handle = activity.begin(
            self,
            self.t["remove" if action == "retire" else "restore"],
            task="lineage",
            key=f"lineage:{self.path}:{self.paper_id}",
            paper_id=self.paper_id,
            cancel=self.cancel,
        )
        if not self._handle.accepted:
            return False
        self.status.setText(self.t["lifecycle_work"])
        started = self._start("lifecycle", change)
        if not started:
            self._handle.finish(False, self.t["stopped"], cancelled=True)
        return started

    def settings(self):
        if self.busy or self._closing or not self._check():
            return
        from paper_daily.desktop.ai_picker import AIPickerDialog

        dialog = AIPickerDialog(self, task="lineage")
        dialog.exec()
        dialog.deleteLater()
        if self._check():
            self.refresh()

    def generate(self):
        if self.busy or self._closing or not self._check():
            return False
        if self.owner is None:
            self.status.setText(self.t["missing"])
            return False
        peers = tuple(item.data(Qt.ItemDataRole.UserRole) for item in self.peers.selectedItems())
        if len(peers) > 3:
            self.status.setText(self.t["limit"])
            return False
        if self.saved:
            answer = QMessageBox.question(
                self,
                self.t["title"],
                self.t["confirm"],
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Cancel,
            )
            if answer != QMessageBox.StandardButton.Yes or not self._check() or self.busy:
                return False
        try:
            if not llm.available(task="lineage"):
                from paper_daily.desktop.ai_access import login

                login(self, "lineage", self.t["missing"])
                return False
            routes = llm.freeze_connections(("lineage",))
            selected = routes.settings("lineage")
        except (OSError, ValueError):
            self.status.setText(self.t["failed"])
            return False
        live = self._live

        def route_current():
            with llm.connection_scope(llm.capture_configured_connections()):
                return llm.settings("lineage") == selected

        def generate(stop, progress):
            self.workflow = self.workflow_factory(
                self.owner,
                peers,
                connections=routes,
                legacy_root=self.legacy_root,
                document=self.document,
                cancelled=stop,
                current=live.is_set,
                route_current=route_current,
            )
            outcome = self.workflow.run(cancelled=stop, current=live.is_set, progress=progress)
            return dict(outcome=outcome, **self._read(self.search_text, peers))

        self.mode.blockSignals(True)
        self.mode.setCurrentIndex(0)
        self.mode.blockSignals(False)
        self.history_offset = 0
        self.search_text = self.search.text().strip()
        self._handle = activity.begin(
            self,
            self.t["title"],
            task="lineage",
            key=f"lineage:{self.path}:{self.paper_id}",
            paper_id=self.paper_id,
            cancel=self.cancel,
        )
        if not self._handle.accepted:
            return False
        self.status.setText(self.t["working"])
        started = self._start("generate", generate)
        if not started:
            self._handle.finish(False, self.t["stopped"], cancelled=True)
        return started

    def _finished(self):
        worker = self._worker
        self._worker = None
        same = self._check()
        if worker.kind == "audit":
            self._finish_audit(worker, same)
            worker.deleteLater()
            self._controls()
            if self._closing:
                self.close()
            return
        if worker.kind in {"adopt_prepare", "adopt_apply"}:
            self.adoption.finish(worker, same)
            worker.deleteLater()
            self._controls()
            if self._closing:
                self.close()
            return
        if worker.kind == "original":
            if (
                same
                and not self._closing
                and not worker.cancelled.is_set()
                and worker.result is not None
                and not worker.error
            ):
                try:
                    proof, module = worker.result
                    row, source_id, page = self._source_expected
                    expected_origin = self._source_origin

                    def current():
                        index = self.results.currentIndex()
                        return (
                            self._check()
                            and 0 <= index < len(self.saved)
                            and self.saved[index] == row
                            and (
                                expected_origin is None
                                or self._entries[index]["origin"] == expected_origin
                            )
                        )

                    if not current():
                        raise ValueError("Loaded Lineage result changed")
                    self._original_viewer = LineageOriginalDialog(
                        proof,
                        module,
                        self.owner,
                        row,
                        source_id,
                        self,
                        current=current,
                        page=page,
                    )
                    self._original_viewer.show()
                except (ImportError, OSError, ValueError, RuntimeError):
                    self.status.setText(self.t["source_unavailable"])
            elif same and not self._closing:
                self.status.setText(
                    self.t["stopped"] if worker.cancelled.is_set() else self.t["source_unavailable"]
                )
            worker.deleteLater()
            self._controls()
            if self._closing:
                self.close()
            return
        if same and not self._closing:
            if worker.error or worker.result is None:
                self.status.setText(
                    self.t["stopped"]
                    if worker.cancelled.is_set()
                    else self.t["lifecycle_failed"]
                    if worker.kind == "lifecycle"
                    else self.t["failed"]
                )
            elif worker.result.get("refresh_error"):
                self._needs_refresh = True
                self.status.setText(self.t["refresh_needed"])
            else:
                old_index = self.results.currentIndex()
                selected_row = self._pending_select or (
                    self.saved[old_index] if 0 <= old_index < len(self.saved) else None
                )
                self._pending_select = None
                self._needs_refresh = False
                self.saved = worker.result["saved"]
                self._entries = worker.result["entries"]
                self._history_more = worker.result["more"]
                self._can_repair = bool(worker.result.get("can_repair"))
                selected = {
                    item.data(Qt.ItemDataRole.UserRole) for item in self.peers.selectedItems()
                }
                self.peers.clear()
                for identity, title in worker.result["papers"]:
                    item = QListWidgetItem(title, self.peers)
                    item.setData(Qt.ItemDataRole.UserRole, identity)
                    item.setSelected(identity in selected)
                self.results.blockSignals(True)
                self.results.clear()
                for row, label in zip(self.saved, worker.result["labels"], strict=True):
                    self.results.addItem(label)
                    self.results.setItemData(
                        self.results.count() - 1, row["written_at"], Qt.ItemDataRole.ToolTipRole
                    )
                if selected_row in self.saved:
                    self.results.setCurrentIndex(self.saved.index(selected_row))
                self.results.blockSignals(False)
                self.render()
                outcome = worker.result.get("outcome")
                receipt = worker.result.get("receipt")
                self.status.setText(
                    self.t[receipt["state"]]
                    if receipt
                    else self.t.get(outcome.state, self.t["retained"])
                    if outcome
                    else (self.t["empty"] if not self.saved else self.t["unchecked"])
                )
        if worker.kind == "repair_history":
            self._repair_ticket = None
            if same and not self._closing and worker.result is not None and not worker.error:
                from paper_daily.desktop.history_index_text import progress_text

                self.status.setText(progress_text(worker.result["repair"], self.language))
        if worker.kind in {"generate", "lifecycle", "repair_history"}:
            committed = (
                worker.kind == "lifecycle"
                and worker.result is not None
                and "receipt" in worker.result
            )
            self._handle.finish(
                not worker.error and worker.result is not None,
                self.status.text(),
                cancelled=worker.cancelled.is_set() and not committed,
            )
        worker.deleteLater()
        self._controls()
        if self._closing:
            self.close()

    def _audit_selection(self):
        index = self.results.currentIndex()
        if (self.mode.currentIndex() != 0 or self._needs_refresh
                or not 0 <= index < len(self._entries)
                or not self._entries[index]["current"]):
            return None
        return self.saved[index]

    def audit_sources(self):
        if self.busy or self._closing or self.owner is None or not self._check():
            return False
        row = self._audit_selection()
        if row is None:
            return False
        owner = self.owner
        self._audit_result = None
        self.render()
        self._audit_pending = owner, row

        def check(stop, emit):
            return audit_lineage.prepare(
                owner, row, cancelled=stop,
                progress=lambda done, total: emit(f"lineage_audit:{done}:{total}"),
            )

        self._handle = activity.begin(
            self, self.t["audit"], task="lineage",
            key=f"lineage-audit:{self.path}:{self.paper_id}:{row['corpus_key']}",
            paper_id=self.paper_id, cancel=self.cancel,
        )
        if not self._handle.accepted:
            self._audit_pending = None
            return False
        total = len(lineage_sets.decode(row["body_json"])["report"]["sources"])
        self.status.setText(self.t["audit_work"].format(done=0, total=total))
        if not self._start("audit", check):
            self._audit_pending = None
            self._handle.finish(False, self.t["stopped"], cancelled=True)
            return False
        return True

    def _audit_report(self, row):
        if self._audit_result is None:
            return None
        owner, expected, result = self._audit_result
        try:
            if row != expected or self._audit_selection() != expected:
                raise ValueError("Selected Lineage changed")
            return result.for_delivery(owner if owner is self.owner else None, row)
        except (OSError, ValueError):
            self._audit_result = None
            return None

    def _audit_summary(self, report):
        checks = [check for source in report["sources"] if source["report"] is not None
                  for check in source["report"]["checks"] if check["rule"] == "quote_location"]
        return self.t["audit_ready"].format(
            checked=report["originals_checked"], total=report["originals_total"],
            located=sum(check["state"] == "located" for check in checks),
            quotes=sum(len(indices) for source in report["sources"]
                       for indices in source["passage_indices"].values()),
        )

    def _finish_audit(self, worker, same):
        pending, self._audit_pending = self._audit_pending, None
        ok = False
        if same and not self._closing:
            if worker.cancelled.is_set():
                self.status.setText(self.t["stopped"])
            else:
                try:
                    if worker.error or worker.result is None or pending is None:
                        raise ValueError("No complete corpus audit")
                    owner, row = pending
                    if owner is not self.owner or row != self._audit_selection():
                        raise ValueError("Selected Lineage changed")
                    report = worker.result.for_delivery(owner, row)
                    self._audit_result = owner, row, worker.result
                    self.render()
                    if self._audit_result is None:
                        raise ValueError("Audit changed during rendering")
                    self.status.setText(self._audit_summary(report))
                    ok = True
                except (OSError, ValueError):
                    self._audit_result = None
                    self.status.setText(self.t["audit_failed"])
        self._handle.finish(ok, self.status.text(), cancelled=worker.cancelled.is_set())

    def render(self):
        if self._original_viewer is not None and not self._original_viewer.disposed:
            self._original_viewer.close()
        self.source_buttons = []
        self.audit_labels = []
        self._audit_summary_label = None
        while self.cards_layout.count():
            item = self.cards_layout.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()
        index = self.results.currentIndex()
        if not 0 <= index < len(self.saved):
            self.cards_layout.addWidget(_label(self.t["empty"]))
            self._controls()
            return
        body = lineage_sets.decode(self.saved[index]["body_json"])
        generation_info = body["generation"]
        self.cards_layout.addWidget(
            _label(
                self.t["completed"].format(
                    backend=generation_info["backend"],
                    requested=generation_info["requested_model"] or self.t["unknown"],
                    returned=generation_info["returned_model"] or self.t["unknown"],
                )
            )
        )
        self.cards_layout.addWidget(_label(self.t["unchecked"]))
        if not self._entries[index]["current"]:
            historical = _label(self.t["history_source"])
            historical.setProperty("role", "muted")
            self.cards_layout.addWidget(historical)
        sources = {source["id"]: source for source in body["report"]["sources"]}
        row = self.saved[index]
        audited = self._audit_report(row)
        audit_checks = {}
        if audited is not None:
            summary = _label(self._audit_summary(audited))
            summary.setObjectName("lineageAuditSummary")
            self._audit_summary_label = summary
            self.cards_layout.addWidget(summary)
            for source in audited["sources"]:
                if source["report"] is not None:
                    for check in source["report"]["checks"]:
                        if check["rule"] == "quote_location":
                            audit_checks[(source["source_id"], check["item_id"],
                                          check["original_passage"])] = check
        for stage in ("prior_gap", "current_change", "later_development"):
            section = ClaimSection(self.t[stage], expanded=True)
            for statement in body["report"]["statements"]:
                if statement["stage"] == stage:
                    section.content.addWidget(_label(statement["text"]))
                    section.content.addWidget(_label(statement["judgment"]["reason"]))
                    requirements = statement["requirements"]
                    section.content.addWidget(
                        _label(
                            self.t["requirements"].format(
                                own=requirements["own_source_passage"],
                                citing=requirements["citing_passage"],
                                identity=requirements["citation_identity"],
                            )
                        )
                    )
                    for passage_index, passage in enumerate(statement["passages"]):
                        page = passage["location"]["page"]
                        section.content.addWidget(
                            _label(
                                passage["quote"]
                                + "\n"
                                + passage["location"]["state"]
                                + (" / p. " + str(page) if page else "")
                            )
                        )
                        if audited is not None:
                            from paper_daily.desktop.research_audit import TEXT as AUDIT_TEXT

                            item_id = "lineage:" + row["corpus_key"] + ":" + statement["id"]
                            check = audit_checks.get((passage["source_id"], item_id, passage_index))
                            state = check["state"] if check else None
                            label = _label(
                                AUDIT_TEXT.get(self.language, AUDIT_TEXT["en"]).get(
                                    state, self.t["audit_review"]
                                ) if check else self.t["audit_unavailable"]
                            )
                            label.setObjectName("lineageAuditQuote")
                            self.audit_labels.append(label)
                            section.content.addWidget(label)
                            if check and state == "located" and check["location"].get("anchor"):
                                page = check["location"]["anchor"]["p0"] + 1
                        source = sources[passage["source_id"]]
                        title = source["identity"]["title"]
                        button = QPushButton(self.t["open_source"])
                        button.setText(
                            self.t["open_source"]
                            + " / "
                            + button.fontMetrics().elidedText(
                                title, Qt.TextElideMode.ElideRight, 280
                            )
                        )
                        button.setToolTip(title)
                        button.setAccessibleName(self.t["open_source"] + " / " + title)
                        button.setAutoDefault(False)
                        button.clicked.connect(
                            lambda _checked=False, r=row, key=source["id"], p=page or 1: (
                                self.open_source(r, key, p)
                            )
                        )
                        self.source_buttons.append(button)
                        section.content.addWidget(button)
            if not any(item["stage"] == stage for item in body["report"]["statements"]):
                section.content.addWidget(_label(self.t["no_statement"]))
            self.cards_layout.addWidget(section)
        self.cards_layout.addStretch()
        self._controls()

    def open_source(self, row, source_id, page=1):
        if (
            self.busy
            or self._closing
            or self.owner is None
            or self._needs_refresh
            or not self._check()
        ):
            return False
        index = self.results.currentIndex()
        if (
            not 0 <= index < len(self.saved)
            or self.saved[index] != row
            or (not self._entries[index]["current"] and self._entries[index]["origin"] is None)
        ):
            return False
        if self._original_viewer is not None and not self._original_viewer.disposed:
            self._original_viewer.close()
        self._source_expected = row, source_id, page
        origin = self._entries[index]["origin"] if not self._entries[index]["current"] else None
        self._source_origin = None if origin is None else dict(origin)
        owner = self.owner

        def read(stop, progress):
            if stop():
                return None
            if origin is not None:
                module = lineage_history_originals
                proof = module.prepare(owner, row, origin, source_id, cancelled=stop)
            else:
                with closing(_readonly_connection(owner.database)) as conn:
                    conn.execute("BEGIN")
                    module = lineage_source_reader.reader_in(conn, owner, row)
                proof = module.prepare(owner, row, source_id, cancelled=stop)
            return (proof, module) if proof is not None and not stop() else None

        return self._start("original", read)

    def cancel(self):
        self.adoption.cancel()
        if self._repair_ticket is not None:
            self._repair_ticket.cancel()
        if self._worker is not None:
            self._worker.cancelled.set()

    def reject(self):
        self.close()

    def closeEvent(self, event):
        if self._original_viewer is not None and not self._original_viewer.disposed:
            self._original_viewer.close()
        self._audit_result = None
        self._live.clear()
        if self.busy:
            self._closing = True
            self.cancel()
            self._controls()
            event.ignore()
            return
        self.disposed = True
        self.poll.stop()
        event.accept()


def open_report(reader):
    from paper_daily import store
    from paper_daily.config import PDF_DIR

    if reader.paper is None:
        return None
    host = getattr(reader, "win", reader.window())
    existing = getattr(host, "_lineage_dialog", None)
    if existing is not None and not existing.disposed:
        if existing._check() and not existing._closing:
            existing.show()
            existing.raise_()
            return existing
        if not existing.close():
            return existing

    def current():
        return (
            Path(store.DB_PATH).resolve(),
            reader.paper.id if reader.paper else None,
            getattr(reader, "_qa_epoch", None),
            getattr(reader, "_active_document", None),
        )

    try:
        dialog = LineageDialog(
            store.DB_PATH,
            reader.paper.id,
            reader,
            owner=getattr(reader, "_highlight_owner", None),
            document=getattr(reader, "_active_document", None),
            legacy_root=PDF_DIR,
            current_view=current,
        )
    except (OSError, ValueError):
        reader.ask_status.setText(TEXT["zh-TW"]["failed"])
        return None
    host._lineage_dialog = dialog
    dialog.show()
    return dialog
