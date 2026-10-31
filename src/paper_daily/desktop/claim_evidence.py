"""Saved-first claim cards; explicit captured AI work never edits reader drafts."""

from __future__ import annotations

import hashlib
import threading
from contextlib import closing
from pathlib import Path

from PySide6.QtCore import Qt, QThread, QTimer, Signal, Slot
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)
from shiboken6 import isValid

from paper_daily import ai_choices, annotation_reader, claim_jobs, llm, work_progress
from paper_daily import research_generation as generation
from paper_daily.desktop import activity, ai_style, fonts
from paper_daily.desktop.flow_layout import FlowLayout
from paper_daily.document_reader import document_current

TEXT = {
    "en": {
        "title": "Review claims against the original",
        "heading": "Claims & evidence",
        "original": "View original version…",
        "original_check": "Verifying the owned original version…",
        "original_unavailable": "Original version is unavailable on this device. "
        "Import or download its research files, then retry.",
        "original_failed": "Original could not be opened safely. Existing research is retained.",
        "original_opened": "Original version opened in a separate read-only window.",
        "original_changed": "Original ownership or research changed. Reopen the original version.",
        "empty_heading": "No saved proposals yet",
        "deleted_heading": "Proposals were deleted",
        "passages": "Original passages ({count})",
        "generate": "Generate proposals",
        "regenerate": "Regenerate proposals",
        "refresh": "Reload saved",
        "stop": "Stop",
        "close": "Close",
        "intro": "AI proposals, not verified conclusions. Quote locations refer to the original "
        "snapshot; semantic support has not been verified.",
        "loading": "Loading saved research; no AI call is running…",
        "empty": "No saved claim set. Complete deep reading and close reading before generating.",
        "deleted": "Deleted set. Confirm restoration explicitly. Opening this view starts no AI.",
        "restore": "Restore proposals…",
        "confirm_restore": "Restore this deleted set using the loaded original and selected AI? "
        "This creates a new research version; notes remain unchanged.",
        "refreshed": "Saved research changed elsewhere; these cards now show the latest saved set.",
        "saved": "Showing saved proposals. Opening this view does not need AI login.",
        "failed": "The task did not complete. Existing research is retained; retry explicitly.",
        "changed": "Paper or workspace changed. This original snapshot stays visible; reopen it.",
        "working": "Preparing the captured paper, source and selected AI route…",
        "stopping": "Stopping safely. The current model call may finish; its result is retained.",
        "stopped": "Stopped. Completed original-source work is retained for review.",
        "retained": "Completed work was retained for review; it did not replace the current set.",
        "login": "Sign in to the AI selected for claim extraction, then press Generate again.",
        "route": "Next Claims generation: ",
        "settings": "Account and model…",
        "settings_unavailable": "AI settings unavailable; saved research is unchanged.",
        "saved_run": "Saved generation: ",
        "requested_model": "Requested model: ",
        "reported_model": "Reported model: ",
        "default_model": "Provider default",
        "unreported_model": "Not reported",
        "default_route": "Generation uses the Claims AI task setting.",
        "source_old": "Original snapshot; the loaded PDF differs or is unavailable.",
        "source_same": "Original-snapshot location record. View source checks the loaded PDF.",
        "source": "View source",
        "source_failed": "The exact original reader is unavailable. No jump occurred.",
        "source_check": "Verifying the exact loaded original before navigating…",
        "proposal": "Proposed judgment: ",
        "supported": "supported",
        "inferred": "inferred",
        "unresolved": "unresolved",
        "reason": "Reason and open questions",
        "no_passages": "No original passage was proposed; evidence remains an open question.",
        "located": "Quote located in the original snapshot",
        "missing": "Quote not located",
        "ambiguous": "Multiple possible quote locations; none selected",
        "invalid_page": "Proposed page is invalid",
        "invalid_anchor": "Proposed location is invalid",
        "more": "Show remaining proposals",
        "count": "Showing {shown} of {total}, in proposal order.",
        "confirm": "Generate a new set? Notes stay unchanged; prior results remain "
        "in research history.",
    },
    "zh-TW": {
        "title": "核對論證與原文",
        "heading": "論證與原文",
        "original": "查看原始版本…",
        "original_check": "正在核對原始版本與所屬論文…",
        "original_unavailable": "此裝置尚無可用的原始版本；匯入或下載研究檔案後可再試。",
        "original_failed": "無法安全開啟原始版本；既有研究資料保持不變。",
        "original_opened": "原始版本已在獨立唯讀視窗開啟。",
        "original_changed": "原始版本或所屬研究已變更，請重新開啟。",
        "empty_heading": "尚無儲存的論證提案",
        "deleted_heading": "論證提案已刪除",
        "passages": "原文引句（{count}）",
        "generate": "產生主張提案",
        "regenerate": "重新產生提案",
        "refresh": "重新讀取",
        "stop": "停止",
        "close": "返回閱讀",
        "intro": "這些是 AI 提案，不是已核實結論。引句位置只針對原始快照；尚未驗證語意支持程度。",
        "loading": "正在讀取已儲存研究；尚未呼叫 AI…",
        "empty": "尚無已儲存主張。請先完成深入分析與逐段精讀，再明確產生提案。",
        "deleted": "此資料組已刪除；復原需明確確認，開啟此頁不會啟動 AI。",
        "restore": "復原論證提案…",
        "confirm_restore": "要使用目前原文與選定的 AI 復原已刪除的論證資料組嗎？"
        "這會建立新的研究版本，筆記保持不變。",
        "refreshed": "研究資料已在其他操作中更新；此處已顯示最新儲存結果。",
        "saved": "目前顯示已儲存提案；開啟此視窗不需登入 AI。",
        "failed": "工作未完成；既有研究保留，可明確重試。",
        "changed": "論文或工作區已變更；此視窗保留原始快照，請重新開啟。",
        "working": "正在準備已選定的論文、原文與 AI 路由…",
        "stopping": "正在安全邊界停止；目前模型呼叫可能仍會完成，完成內容將保留。",
        "stopped": "已停止；完成的原始版本內容保留供後續審閱。",
        "retained": "完成內容已保留待審閱，未覆蓋目前資料組。",
        "login": "請先登入「核對論證」所選的 AI，再按一次產生；不會自動送出。",
        "route": "下次論點產生使用：",
        "settings": "帳號與模型…",
        "settings_unavailable": "目前無法讀取 AI 設定；已存研究保持不變。",
        "saved_run": "已存產生紀錄：",
        "requested_model": "指定模型：",
        "reported_model": "回報模型：",
        "default_model": "服務預設",
        "unreported_model": "未回報",
        "default_route": "產生時使用「核對論證」的 AI 功能設定。",
        "source_old": "原始版本快照；目前載入的 PDF 版本不同或尚未就緒。",
        "source_same": "原始快照的定位記錄；按「核對原文」後才會驗證目前原文並跳轉。",
        "source": "核對原文",
        "source_failed": "目前無法確認相同原文版本，未跳轉至其他文件。",
        "source_check": "正在核對實際載入的原文版本，再進行定位…",
        "proposal": "建議判斷：",
        "supported": "有支持",
        "inferred": "推論",
        "unresolved": "未釐清",
        "reason": "判斷理由與待釐清事項",
        "no_passages": "尚未提出原文依據；這仍是一項待補證據的提案。",
        "located": "已在原始快照定位引句",
        "missing": "未定位到引句",
        "ambiguous": "有多個可能位置，尚未選定",
        "invalid_page": "建議頁碼無效",
        "invalid_anchor": "建議位置無效",
        "more": "顯示其餘提案",
        "count": "依提案順序顯示 {shown}／{total} 項。",
        "confirm": "要重新產生主張提案嗎？不會改動既有筆記，先前結果會保留在研究歷史。",
    },
}


def _label(text):
    label = QLabel(text)
    label.setTextFormat(Qt.TextFormat.PlainText)
    label.setWordWrap(True)
    label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
    label.setTextInteractionFlags(
        Qt.TextInteractionFlag.TextSelectableByMouse
        | Qt.TextInteractionFlag.TextSelectableByKeyboard
    )
    return label


class DisclosureButton(QToolButton):
    def keyPressEvent(self, event):
        # QToolButton otherwise forwards Return to the dialog's default AI action.
        if event.key() in {Qt.Key.Key_Return, Qt.Key.Key_Enter}:
            self.click()
            event.accept()
            return
        super().keyPressEvent(event)


class ClaimSection(QWidget):
    """A native keyboard disclosure; expanding saved text never starts work."""

    def __init__(self, title, *, expanded=True, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        self.button = DisclosureButton()
        self.button.setText(title)
        self.button.setCheckable(True)
        self.button.setChecked(expanded)
        self.button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.body = QWidget()
        self.content = QVBoxLayout(self.body)
        self.content.setContentsMargins(0, 0, 0, 0)
        self.content.setSpacing(8)
        layout.addWidget(self.button)
        layout.addWidget(self.body)
        self.button.toggled.connect(self._toggle)
        self._toggle(expanded)

    @Slot(bool)
    def _toggle(self, expanded):
        self.body.setVisible(expanded)
        self.button.setArrowType(Qt.ArrowType.DownArrow if expanded else Qt.ArrowType.RightArrow)


class ClaimWorker(QThread):
    progress = Signal(object)

    def __init__(self, call, parent):
        super().__init__(parent)
        self.call = call
        self.cancelled = threading.Event()
        self.result = self.error = None

    def run(self):
        try:
            with work_progress.observe(self.progress.emit):
                self.result = self.call(self.cancelled.is_set)
        except Exception as error:
            self.error = type(error).__name__


def verify_source(owner, document, digest, cancelled):
    """Verify exact owned loaded bytes off-thread; a stored page is never authority."""
    if cancelled():
        return False
    with closing(generation._connect(owner.database)) as conn:
        owner.check(conn)
    if (
        document is None
        or document.local_id != owner.paper_id
        or document._owner.db_path.resolve() != owner.database
        or not document.available
        or document.sha256 != digest
        or not document_current(document)
    ):
        return False
    with document.path.open("rb") as stream:
        if hashlib.file_digest(stream, "sha256").hexdigest() != digest:
            return False
    with closing(generation._connect(owner.database)) as conn:
        owner.check(conn)
    return not cancelled() and document_current(document)


class ClaimEvidenceDialog(QDialog):
    def __init__(
        self,
        database,
        paper_id,
        parent=None,
        *,
        legacy_root,
        current_path=None,
        current_view=None,
        document=None,
        owner=None,
        source_callback=None,
        language="zh-TW",
        job_factory=claim_jobs.ClaimJob.capture,
        changes=None,
    ):
        super().__init__(parent)
        self.path, self.paper_id = Path(database).resolve(strict=True), paper_id
        info = self.path.stat()
        self.identity = info.st_dev, info.st_ino
        self.current_path = current_path or (lambda: self.path)
        self.current_view = current_view
        self.view = current_view() if current_view else None
        self.document, self.owner = document, owner
        self.legacy_root = Path(legacy_root).resolve()
        self.source_callback = source_callback
        self.job_factory = job_factory
        self.t = TEXT.get(language, TEXT["en"])
        self.saved = None
        self.last_error = None
        self.disposed = self._closing = self._invalid = False
        self._worker = None
        self._handle = activity.Handle()
        self._all = False
        self._refresh_pending = False
        self.source_buttons = []
        self.sections = []
        self._expanded = {}
        self._compact = False
        self._original_viewer = None
        self._settings_open = False
        self.language = language
        self.setWindowTitle(self.t["title"])
        self.setWindowModality(Qt.WindowModality.WindowModal)
        self.resize(760, 660)
        self.setFont(fonts.font(pixels=13))
        from paper_daily.desktop.main import palette

        host = getattr(parent, "win", parent)
        self.pal = dict(getattr(host, "pal", None) or palette())
        self._style()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(12)
        self.heading = _label(self.t["heading"])
        self.heading.setProperty("role", "title")
        layout.addWidget(self.heading)
        self.intro = _label(self.t["intro"])
        self.intro.setProperty("role", "muted")
        layout.addWidget(self.intro)
        self.route = _label(self.t["default_route"])
        self.route.setObjectName("claimsNextRoute")
        self.route.setProperty("role", "meta")
        route_row = QHBoxLayout()
        route_row.addWidget(self.route, 1)
        self.settings_button = QPushButton(self.t["settings"])
        self.settings_button.setObjectName("claimsModelSettings")
        self.settings_button.setAutoDefault(False)
        self.settings_button.clicked.connect(self.settings)
        route_row.addWidget(self.settings_button)
        layout.addLayout(route_row)
        self.saved_run = _label("")
        self.saved_run.setObjectName("claimsSavedRun")
        self.saved_run.setProperty("role", "meta")
        self.saved_run.hide()
        layout.addWidget(self.saved_run)
        self.version = _label("")
        self.version.setProperty("role", "meta")
        layout.addWidget(self.version)
        self.original_button = QPushButton(self.t["original"])
        self.original_button.setVisible(False)
        self.original_button.clicked.connect(self.open_original)
        layout.addWidget(self.original_button, 0, Qt.AlignmentFlag.AlignLeft)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.cards = QWidget()
        self.cards_layout = QVBoxLayout(self.cards)
        self.cards_layout.setContentsMargins(0, 0, 4, 0)
        self.cards_layout.setSpacing(12)
        self.scroll.setWidget(self.cards)
        layout.addWidget(self.scroll, 1)
        actions = FlowLayout(spacing=6)
        self.generate_button = QPushButton(self.t["generate"])
        self.generate_button.clicked.connect(self.generate)
        ai_style.mark(self.generate_button, self.pal, primary=True)
        self.refresh_button = QPushButton(self.t["refresh"])
        self.refresh_button.clicked.connect(self.refresh)
        self.more_button = QPushButton(self.t["more"])
        self.more_button.clicked.connect(self.show_all)
        for button in (self.generate_button, self.refresh_button, self.more_button):
            actions.addWidget(button)
        layout.addLayout(actions)
        self.status = _label(self.t["loading"])
        self.status.setProperty("role", "meta")
        layout.addWidget(self.status)
        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.setTextVisible(False)
        layout.addWidget(self.progress)
        bottom = QHBoxLayout()
        self.stop_button = QPushButton(self.t["stop"])
        self.stop_button.clicked.connect(self.cancel)
        self.stop_button.hide()
        self.close_button = QPushButton(self.t["close"])
        self.close_button.clicked.connect(self.close)
        bottom.addWidget(self.stop_button)
        bottom.addStretch()
        bottom.addWidget(self.close_button)
        layout.addLayout(bottom)
        self.poll = QTimer(self)
        self.poll.setInterval(250)
        self.poll.timeout.connect(self._check)
        self.poll.start()
        self.freshness = QTimer(self)
        self.freshness.setInterval(2000)
        self.freshness.timeout.connect(self.request_refresh)
        self.freshness.start()
        if changes is not None:
            changes.changed.connect(self.request_refresh)
        self._refresh_intent()
        self._controls()
        QTimer.singleShot(0, self.refresh)

    def _style(self):
        p = self.pal
        self.setStyleSheet(f"""
            QWidget {{ color:{p["ink"]}; background:transparent; }}
            QDialog {{ background:{p["ground"]}; color:{p["ink"]}; }}
            QLabel {{ color:{p["ink"]}; background:transparent; }}
            QLabel[role="title"] {{ font-size:22px; font-weight:600; }}
            QLabel[role="claim"] {{ font-size:16px; font-weight:600; }}
            QLabel[role="muted"] {{ color:{p["muted"]}; font-size:13px; }}
            QLabel[role="meta"] {{ color:{p["muted"]}; font-size:12px; }}
            QLabel[role="proposal"] {{ color:{p["ai"]}; background:{p["aiSoft"]};
                border-radius:5px; padding:4px 8px; font-size:12px; }}
            QFrame[role="card"] {{ background:{p["surface"]};
                border:1px solid {p["border"]}; border-radius:10px; }}
            QFrame[role="quote"] {{ background:{p["sunk"]}; border:0;
                border-left:3px solid {p["firm"]}; border-radius:4px; }}
            QScrollArea, QScrollArea > QWidget > QWidget {{ border:0;
                background:{p["ground"]}; }}
            QPushButton {{ background:{p["surface"]}; color:{p["ink"]};
                border:1px solid {p["firm"]}; border-radius:6px; padding:6px 12px; }}
            QPushButton:hover {{ border-color:{p["accent"]}; background:{p["accentSoft"]}; }}
            QPushButton:pressed {{ background:{p["sunk"]}; }}
            QPushButton:focus, QToolButton:focus {{ border:2px solid {p["accent"]}; }}
            QPushButton:disabled {{ color:{p["faint"]}; border-color:{p["border"]}; }}
            QToolButton {{ color:{p["muted"]}; background:transparent; text-align:left;
                border:1px solid transparent; border-radius:4px; padding:4px 2px;
                font-size:12px; font-weight:600; }}
            QToolButton:hover {{ color:{p["ink"]}; background:{p["sunk"]}; }}
            QToolButton:checked {{ color:{p["ink"]}; }}
            QProgressBar {{ background:{p["sunk"]}; border:0; border-radius:3px;
                min-height:5px; max-height:5px; }}
            QProgressBar::chunk {{ background:{p["ai"]}; border-radius:3px; }}
        """)

    def _section(self, claim_id, kind, title, *, expanded):
        key = (claim_id, kind)
        section = ClaimSection(title, expanded=self._expanded.get(key, expanded))
        section.button.toggled.connect(
            lambda checked, k=key: self._expanded.__setitem__(k, checked)
        )
        section.setProperty("section", kind)
        self.sections.append(section)
        return section

    @property
    def busy(self):
        return self._worker is not None

    def _check(self):
        if self.disposed:
            return False
        try:
            info = self.path.stat()
            current = self.current_view() if self.current_view else None
            same = (
                Path(self.current_path()).resolve() == self.path
                and (info.st_dev, info.st_ino) == self.identity
                and current == self.view
            )
        except (OSError, ValueError, RuntimeError):
            same = False
        if not same:
            self._invalid = True
            if self._original_viewer is not None:
                self._original_viewer.close()
            self.cancel()
            self.status.setText(self.t["changed"])
            self._controls()
        return same and not self._invalid

    def _controls(self):
        watching = self.busy and self._worker.kind == "watch"
        active = (
            (not self.busy or watching)
            and not self.disposed
            and not self._closing
            and not self._invalid
        )
        deleted = self.saved is not None and "report" not in self.saved
        active = active and not self._refresh_pending
        self.generate_button.setEnabled(active and self.owner is not None)
        self.settings_button.setEnabled(active and not self.busy and not self._settings_open)
        self.refresh_button.setEnabled(active)
        self.original_button.setEnabled(active and self.owner is not None)
        self.generate_button.setText(
            self.t["restore"]
            if deleted
            else self.t["regenerate"]
            if self.saved is not None
            else self.t["generate"]
        )
        for button in self.source_buttons:
            button.setEnabled(active and button.property("exact_source"))
        self.stop_button.setVisible(self.busy and not watching)
        self.stop_button.setEnabled(self.busy and not watching and not self._closing)
        self.progress.setVisible(self.busy and self._worker.kind != "watch")
        self.more_button.setEnabled(active)

    def _refresh_intent(self):
        if self.disposed or self._closing or not self._check():
            return
        try:
            text = ai_choices.connection_label(llm.settings(task="claims"))
        except (OSError, ValueError):
            text = self.t["settings_unavailable"]
        self.route.setText(self.t["route"] + text)

    def settings(self):
        if self.busy or self._settings_open or self._closing or not self._check():
            return
        from paper_daily.desktop.ai_picker import AIPickerDialog

        self._settings_open = True
        self._controls()
        dialog, failed = None, False
        try:
            dialog = AIPickerDialog(self, task="claims")
            dialog.exec()
        except (OSError, ValueError, RuntimeError):
            failed = True
        finally:
            if dialog is not None and isValid(dialog):
                dialog.deleteLater()
            self._settings_open = False
            if isValid(self) and not self.disposed and not self._closing and self._check():
                if failed:
                    self.route.setText(self.t["route"] + self.t["settings_unavailable"])
                else:
                    self._refresh_intent()
                self._controls()

    def _start(self, kind, call):
        if self.busy or not self._check() or self._closing:
            return False
        worker = ClaimWorker(call, self)
        self._worker = worker
        worker.kind = kind
        worker.progress.connect(self._progress)
        worker.finished.connect(self._finished)
        self._controls()
        worker.start()
        return True

    @Slot()
    def request_refresh(self):
        """Coalesce revision signals and cover unlisted papers with a bounded saved read."""
        if self.disposed or self._closing or not self._check():
            return
        if self.busy:
            self._refresh_pending = True
            self._controls()
        else:
            self.refresh(quiet=True)

    def refresh(self, *, quiet=False):
        if self.busy or self.disposed or self._closing:
            return False
        self._refresh_intent()
        self._refresh_pending = False
        if not quiet:
            self.status.setText(self.t["loading"])
        owner = self.owner

        def read(cancelled):
            if cancelled():
                return None
            captured = owner
            if captured is not None:
                with closing(generation._connect(self.path)) as conn:
                    captured.check(conn)
            return {
                "owner": captured,
                "saved": annotation_reader.saved(self.path, self.paper_id, "claims"),
            }

        return self._start("watch" if quiet else "read", read)

    def generate(self):
        if self.busy or self.owner is None or self._closing or not self._check():
            return False
        if self._refresh_pending:
            return False
        displayed = self.saved
        restoring = displayed is not None and "report" not in displayed
        if displayed is not None:
            choice = QMessageBox.question(
                self,
                self.t["title"],
                self.t["confirm_restore"] if restoring else self.t["confirm"],
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Cancel,
            )
            if (
                choice != QMessageBox.StandardButton.Yes
                or not self._check()
                or self._refresh_pending
                or self.busy
                or self.saved != displayed
            ):
                return False
        try:
            connections = llm.capture_connections()
            with llm.connection_scope(connections):
                if not llm.available(task="claims"):
                    from paper_daily.desktop.ai_access import login

                    self.status.setText(self.t["login"])
                    login(self, "claims", self.t["login"])
                    return False
                selected = llm.settings(task="claims")
                self.route.setText(self.t["route"] + ai_choices.connection_label(selected))
        except (OSError, ValueError):
            self.status.setText(self.t["login"])
            return False
        if not self._check():
            return False
        self._handle = activity.begin(
            self, task="claims", key=f"claims:{self.path}:{self.paper_id}", paper_id=self.paper_id
        )
        if not self._handle.accepted:
            return False
        owner, document = self.owner, self.document
        self.status.setText(self.t["working"])

        def run(cancelled):
            if cancelled():
                return None
            with closing(generation._connect(self.path)) as conn:
                owner.check(conn)
            job = self.job_factory(
                self.path,
                self.paper_id,
                legacy_root=self.legacy_root,
                connections=connections,
                document=document,
                owner=owner,
                restore_deleted=restoring,
            )
            outcome = job.run(cancelled=cancelled)
            return {
                "outcome": outcome.status,
                "saved": annotation_reader.saved(self.path, self.paper_id, "claims"),
            }

        started = self._start("generate", run)
        if not started:
            self._handle.finish(False)
        return started

    @Slot(object)
    def _progress(self, value):
        worker = self.sender()
        if self._worker is worker:
            self._handle.update(value)
            if not self._closing and self._check() and not worker.cancelled.is_set():
                stage = value.get("stage")
                if isinstance(stage, str):
                    self.status.setText(stage[:200])

    @Slot()
    def _finished(self):
        worker = self.sender()
        kind = worker.kind
        if not isValid(self) or self._worker is not worker:
            return
        self._worker = None
        self.last_error = worker.error
        if kind == "generate":
            self._handle.finish(
                not worker.error and not worker.cancelled.is_set(),
                cancelled=worker.cancelled.is_set(),
            )
        if not self._closing and self._check():
            if worker.cancelled.is_set():
                self.status.setText(self.t["stopped"])
            elif worker.error or worker.result is None:
                key = (
                    (
                        "original_unavailable"
                        if worker.error == "OriginalUnavailable"
                        else "original_failed"
                    )
                    if kind == "original"
                    else "failed"
                )
                self.status.setText(self.t[key])
            elif kind == "original":
                from paper_daily.desktop.original_version import OriginalVersionDialog

                if not self._refresh_pending and self.saved == self._original_expected:
                    try:
                        viewer = OriginalVersionDialog(
                            worker.result,
                            self,
                            current=lambda: self._check() and self.saved == self._original_expected,
                            language=self.language,
                        )
                        self._original_viewer = viewer
                        viewer.closed.connect(self._original_closed)
                        viewer.invalidated.connect(self._original_invalidated)
                        viewer.show()
                        self.status.setText(self.t["original_opened"])
                    except (OSError, ValueError, RuntimeError):
                        self.status.setText(self.t["original_failed"])
                else:
                    self.status.setText(self.t["original_changed"])
            elif kind == "source":
                if worker.result and self.source_callback is not None and not self._refresh_pending:
                    result = self.source_callback(self._source_request)
                    if result is not False:
                        self.close()
                        worker.deleteLater()
                        return
                self.version.setText(self.t["source_old"])
                self.original_button.show()
                for button in self.source_buttons:
                    button.setProperty("exact_source", False)
                self.status.setText(self.t["source_failed"])
            elif kind in {"read", "watch"} or worker.result.get("outcome") == "accepted":
                if kind in {"read", "watch"}:
                    self.owner = worker.result["owner"]
                changed = self.saved != worker.result["saved"]
                self.saved = worker.result["saved"]
                if kind != "watch" or changed:
                    self._render()
                    if kind == "watch":
                        self.status.setText(self.t["refreshed"])
            else:
                self.status.setText(self.t["retained"])
        worker.deleteLater()
        self._controls()
        if self._closing:
            self.close()
        elif self._refresh_pending and not self._invalid:
            QTimer.singleShot(0, self.request_refresh)

    def _render(self):
        scroll = self.scroll.verticalScrollBar().value()
        focused = QApplication.focusWidget()
        passage_focus = focused.property("passage_id") if focused in self.source_buttons else None
        while self.cards_layout.count():
            item = self.cards_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self.source_buttons = []
        self.sections = []
        report = (self.saved or {}).get("report")
        metadata = (self.saved or {}).get("generation") if report is not None else None
        self.saved_run.setVisible(metadata is not None)
        self.saved_run.setText(
            self.t["saved_run"] + metadata["backend"] + " / "
            + self.t["requested_model"] + (metadata["requested_model"] or self.t["default_model"])
            + " / " + self.t["reported_model"]
            + (metadata["returned_model"] or self.t["unreported_model"])
            if metadata is not None else ""
        )
        if report is None:
            card = QFrame()
            card.setProperty("role", "card")
            card.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
            empty = QVBoxLayout(card)
            empty.setContentsMargins(16, 16, 16, 16)
            label = _label(self.t["deleted_heading"] if self.saved else self.t["empty_heading"])
            label.setProperty("role", "claim")
            empty.addWidget(label)
            self.cards_layout.addWidget(card)
            self.cards_layout.addStretch()
            self.version.clear()
            self.version.hide()
            self.original_button.hide()
            self.status.setText(self.t["deleted"] if self.saved else self.t["empty"])
            self.more_button.hide()
            self._compact = True
            self.resize(self.width(), min(self.height(), 360))
            return
        if self._compact:
            self.resize(self.width(), 660)
            self._compact = False
        self.version.show()
        source_hash = report["source"]["document_hash"]
        exact = (
            self.owner is not None
            and self.document is not None
            and self.document.available
            and self.document.local_id == self.paper_id
            and self.document._owner.db_path.resolve() == self.path
            and self.document.sha256 == source_hash
        )
        self.version.setText(self.t["source_same"] if exact else self.t["source_old"])
        self.original_button.setVisible(not exact)
        claims = report["claims"] if self._all else report["claims"][:5]
        for claim in claims:
            card = QFrame()
            card.setProperty("role", "card")
            card.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
            inner = QVBoxLayout(card)
            inner.setContentsMargins(16, 14, 16, 14)
            inner.setSpacing(8)
            title = _label(claim["text"])
            title.setProperty("role", "claim")
            inner.addWidget(title)
            judgment = _label(self.t["proposal"] + self.t[claim["judgment"]["status"]])
            judgment.setProperty("role", "proposal")
            inner.addWidget(judgment)
            reason = self._section(claim["id"], "reason", self.t["reason"], expanded=False)
            reason.content.addWidget(_label(claim["judgment"]["reason"]))
            inner.addWidget(reason)
            if not claim["passages"]:
                inner.addWidget(_label(self.t["no_passages"]))
            else:
                sources = self._section(
                    claim["id"],
                    "sources",
                    self.t["passages"].format(count=len(claim["passages"])),
                    expanded=True,
                )
                for passage in claim["passages"]:
                    quote = QFrame()
                    quote.setProperty("role", "quote")
                    content = QVBoxLayout(quote)
                    content.setContentsMargins(12, 10, 12, 10)
                    content.setSpacing(8)
                    content.addWidget(_label(passage["quote"]))
                    state = passage["location"]["state"]
                    location = _label(self.t[state])
                    location.setProperty("role", "meta")
                    content.addWidget(location)
                    if state == "located":
                        source = QPushButton(self.t["source"])
                        source.setProperty(
                            "exact_source", exact and self.source_callback is not None
                        )
                        source.setProperty("passage_id", passage["id"])
                        source.clicked.connect(lambda _=False, p=passage: self.open_source(p))
                        content.addWidget(source, 0, Qt.AlignmentFlag.AlignLeft)
                        self.source_buttons.append(source)
                        if passage_focus == passage["id"]:
                            source.setFocus()
                    sources.content.addWidget(quote)
                inner.addWidget(sources)
            self.cards_layout.addWidget(card)
        self.cards_layout.addStretch()
        self.cards_layout.activate()
        self.scroll.verticalScrollBar().setValue(scroll)
        self.status.setText(self.t["count"].format(shown=len(claims), total=len(report["claims"])))
        self.more_button.setVisible(not self._all and len(report["claims"]) > 5)
        self._controls()

    def open_original(self):
        if (
            self.busy
            or self._refresh_pending
            or self.owner is None
            or self._closing
            or not self._check()
            or not self.saved
            or "report" not in self.saved
        ):
            return False
        if self._original_viewer is not None and not self._original_viewer.disposed:
            self._original_viewer.show()
            self._original_viewer.raise_()
            return False
        from paper_daily.desktop.original_version import prepare

        expected, owner = self.saved, self.owner
        self._original_expected = expected
        self.status.setText(self.t["original_check"])
        return self._start(
            "original", lambda cancelled: prepare(owner, expected, cancelled=cancelled)
        )

    @Slot()
    def _original_closed(self):
        viewer = self.sender()
        if self._original_viewer is viewer:
            self._original_viewer = None
        viewer.deleteLater()
        if self._closing and not self.busy:
            self.close()

    @Slot()
    def _original_invalidated(self):
        if not self.disposed and not self._invalid:
            self.status.setText(self.t["original_changed"])

    def show_all(self):
        if not self.busy:
            self._all = True
            self._render()

    def open_source(self, passage):
        if (
            self.busy
            or self._refresh_pending
            or self.owner is None
            or not self._check()
            or not self.saved
            or "report" not in self.saved
            or self.source_callback is None
        ):
            return False
        if passage["location"]["state"] != "located" or not any(
            passage == item
            for claim in self.saved["report"]["claims"]
            for item in claim["passages"]
        ):
            return False
        digest = self.saved["report"]["source"]["document_hash"]
        self._source_request = {
            "kind": "claims",
            "document_hash": digest,
            "anchor": passage["location"]["anchor"],
            "page": passage["location"]["page"],
            "text": passage["quote"],
        }
        owner, document = self.owner, self.document
        self.status.setText(self.t["source_check"])
        expected = self.saved

        def verify(cancelled):
            if annotation_reader.saved(self.path, self.paper_id, "claims") != expected:
                return False
            return (
                verify_source(owner, document, digest, cancelled)
                and annotation_reader.saved(self.path, self.paper_id, "claims") == expected
            )

        return self._start("source", verify)

    def cancel(self):
        if self._worker is not None:
            self._worker.cancelled.set()
            if not self._closing and not self._invalid:
                self.status.setText(self.t["stopping"])

    def reject(self):
        self.close()

    def closeEvent(self, event):
        if (
            self._original_viewer is not None
            and not self._original_viewer.disposed
            and not self._original_viewer.close()
        ):
            self._closing = True
            self.cancel()
            self._controls()
            event.ignore()
            return
        if self.busy:
            self._closing = True
            self.cancel()
            self._controls()
            event.ignore()
            return
        self.disposed = True
        self.poll.stop()
        self.freshness.stop()
        self.done(QDialog.DialogCode.Rejected)
        event.accept()


def open_report(reader):
    """One optional task entry; the reader's loaded owner and drafts stay intact."""
    from paper_daily import store
    from paper_daily.config import PDF_DIR

    paper = reader.paper
    if paper is None:
        return None
    host = getattr(reader, "win", reader.window())
    existing = getattr(host, "_claim_dialog", None)
    if existing is not None and not existing.disposed:
        if (
            existing.path == Path(store.DB_PATH).resolve()
            and existing.paper_id == paper.id
            and existing.document is getattr(reader, "_active_document", None)
            and existing._check()
            and not existing._closing
        ):
            existing.show()
            existing.raise_()
            return existing
        if not existing.close():
            existing.raise_()
            return existing

    def current():
        return (
            Path(store.DB_PATH).resolve(),
            reader.paper.id if reader.paper else None,
            getattr(reader, "_qa_epoch", None),
            getattr(reader, "_active_document", None),
            getattr(reader, "_pdf_fingerprint", None),
        )

    def focus(source):
        from paper_daily.desktop.research_source_navigation import focus as focus_source

        return focus_source(
            reader,
            source,
            document=dialog.document,
            current=lambda: current() == dialog.view,
        )

    try:
        dialog = ClaimEvidenceDialog(
            store.DB_PATH,
            paper.id,
            reader,
            legacy_root=PDF_DIR,
            current_path=lambda: store.DB_PATH,
            current_view=current,
            document=getattr(reader, "_active_document", None),
            owner=getattr(reader, "_highlight_owner", None),
            source_callback=focus,
            changes=getattr(host, "workspace_changes", None),
        )
    except (OSError, ValueError):
        reader.ask_status.setText(
            "\u7121\u6cd5\u958b\u555f\u8ad6\u8b49\u6838\u5c0d\uff0c\u8acb\u91cd\u65b0\u958b\u555f\u8ad6\u6587\u5f8c\u91cd\u8a66\u3002"
        )
        return None
    host._claim_dialog = dialog
    dialog.open()
    return dialog
