"""Browse grounded suggestions separately from the conversation; selection drafts only."""

import json
import sqlite3
from pathlib import Path

from PySide6.QtCore import QSize, Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from paper_daily import llm, research_questions
from paper_daily.desktop.ask import AskRunner
from paper_daily.desktop.flow_layout import FlowLayout
from paper_daily.desktop.question_adoption_job import AdoptionRunner


class _QuestionBrowser(QDialog):
    def resizeEvent(self, event):
        super().resizeEvent(event)
        split = getattr(self, "split", None)
        if split is not None:
            split.setOrientation(Qt.Orientation.Vertical if self.width() < 720
                                 else Qt.Orientation.Horizontal)


class _QuestionStatus(QLabel):
    """Keep diagnostics available without expanding the conversation layout."""

    def __init__(self, text):
        super().__init__(text)
        self.setMaximumHeight(40)

    def setText(self, text):
        super().setText(text)
        self.setToolTip(text)


class _QuestionDetails(QScrollArea):
    def minimumSizeHint(self):
        return QSize(0, 32)


def question_preview(question):
    """A bounded navigation label; the full question is always in the preview."""
    text = " ".join(question.split())
    return text if len(text) <= 64 else text[:63] + "…"


def _retry_hint(reason, kept=False):
    state = "本文建議未更新，保留先前建議" if kept else "本文建議未產生"
    return f"{state}：{reason.rstrip('。')}。可按「AI 更新建議」重試。"


class ResearchQuestions(QWidget):
    chosen = Signal(str)
    return_to_draft = Signal()
    source_requested = Signal(dict)

    def __init__(self, parent=None, *, palette=None, database=None):
        super().__init__(parent)
        self.paper_id = None
        self._database_source = database
        self._database = None
        self._document_hash = None
        self._legacy_unverified = False
        self._load_epoch = 0
        self._saved_known = False
        self._has_saved = False
        self._read_failed = False
        self._browser_context = None
        self._prepared_adoption = None
        self._prepared_context = None
        self.adoption_runner = AdoptionRunner(self)
        self.runner = AskRunner(self)
        self.runner.activity_label = "整理研究問題"
        self._attempted = set()
        self._browser_paper = None
        self._switching_paper = False
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        row = QHBoxLayout()
        self.browse = QPushButton("瀏覽本文建議（0）")
        self.browse.setToolTip("根據這篇論文產生的問題；與下方已送出的對話分開。")
        self.browse.clicked.connect(self.open_browser)
        row.addWidget(self.browse)
        self.refresh_button = QPushButton("AI 更新建議")
        if palette:
            from paper_daily.desktop import ai_style
            ai_style.mark(self.refresh_button, palette)
        self.refresh_button.clicked.connect(lambda: self.generate(force=True))
        row.addWidget(self.refresh_button)
        self.verify_button = QPushButton("核對舊版來源")
        self.verify_button.setToolTip("核對既有問題與原文，不呼叫 AI；預覽後可採用至此工作區。")
        self.verify_button.clicked.connect(self.verify_legacy)
        self.verify_button.hide()
        row.addWidget(self.verify_button)
        row.addStretch(1)
        layout.addLayout(row)
        self.status = _QuestionStatus("選擇建議只會帶入草稿；按「送出」才會詢問 AI。")
        self.status.setWordWrap(True)
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self.status)

        self.browser = _QuestionBrowser(self)
        self.browser.rejected.connect(self._dismissed)
        self.browser.setWindowTitle("本文建議問題 · 選擇後可編輯")
        self.browser.setWindowModality(Qt.WindowModality.WindowModal)
        self.browser.resize(940, 580)
        browser_layout = QVBoxLayout(self.browser)
        hint = QLabel("這些是根據原文產生的提問建議，不是已送出的對話。"
                      "先選題、讀完整內容，再帶入草稿。")
        hint.setWordWrap(True)
        browser_layout.addWidget(hint)
        self.adoption_status = QLabel()
        self.adoption_status.setWordWrap(True)
        # A full SHA-256 is an unbroken word. It must wrap within the dialog,
        # rather than becoming the dialog's minimum width under platform fonts.
        self.adoption_status.setSizePolicy(QSizePolicy.Policy.Ignored,
                                          QSizePolicy.Policy.Preferred)
        self.adoption_status.setTextFormat(Qt.TextFormat.PlainText)
        self.adoption_status.hide()
        browser_layout.addWidget(self.adoption_status)
        self.browser.split = QSplitter(Qt.Orientation.Horizontal)
        self.picker = QListWidget()
        self.picker.setAccessibleName("本文建議問題清單")
        self.picker.setWordWrap(True)
        self.picker.setTextElideMode(Qt.TextElideMode.ElideRight)
        self.picker.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.picker.setMinimumWidth(0)
        self.picker.currentRowChanged.connect(self._selected)
        self.browser.split.addWidget(self.picker)
        self.details_scroll = _QuestionDetails()
        self.details_scroll.setWidgetResizable(True)
        self.details_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.details_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.details_scroll.setAccessibleName("完整問題與提問理由")
        details = QWidget()
        details_layout = QVBoxLayout(details)
        self.detail = QLabel()
        self.detail.setWordWrap(True)
        self.detail.setTextFormat(Qt.TextFormat.PlainText)
        self.detail.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse
                                           | Qt.TextInteractionFlag.TextSelectableByKeyboard)
        details_layout.addWidget(self.detail)
        self.source = QPushButton("在原文中查看依據")
        self.source.clicked.connect(self._source)
        details_layout.addWidget(self.source)
        details_layout.addStretch(1)
        self.details_scroll.setWidget(details)
        self.browser.split.addWidget(self.details_scroll)
        self.browser.split.setChildrenCollapsible(False)
        self.browser.split.setSizes([300, 600])
        browser_layout.addWidget(self.browser.split, 1)
        buttons = FlowLayout()
        self.verify_in_browser = QPushButton("核對舊版來源")
        self.verify_in_browser.clicked.connect(self.verify_legacy)
        self.verify_in_browser.hide()
        buttons.addWidget(self.verify_in_browser)
        self.adopt_button = QPushButton("採用已核對建議")
        self.adopt_button.clicked.connect(self.adopt_legacy)
        self.adopt_button.hide()
        buttons.addWidget(self.adopt_button)
        self.cancel = QPushButton("返回對話")
        self.cancel.clicked.connect(self.browser.reject)
        buttons.addWidget(self.cancel)
        self.insert = QPushButton("帶入提問草稿")
        self.insert.setDefault(True)
        self.insert.clicked.connect(self._insert)
        buttons.addWidget(self.insert)
        browser_layout.addLayout(buttons)
        self._fill([])

    def load(self, paper_id):
        source = self._database_source
        database = Path(source() if callable(source) else source).resolve() if source else None
        changed = (paper_id, database) != (self.paper_id, self._database)
        if changed and self.browser.isVisible():
            self._switching_paper = True
            try:
                self.browser.reject()
            finally:
                self._switching_paper = False
        self.paper_id, self._database = paper_id, database
        self._load_epoch += 1
        self._prepared_adoption = None
        self._prepared_context = None
        self.adoption_status.clear()
        self.adoption_status.hide()
        try:
            if database is None:
                saved = research_questions.cached(paper_id)
            else:
                from paper_daily.annotation_reader import questions

                saved = questions(database, paper_id,
                                  cache_root=database.parent / "research-questions")
        except (OSError, sqlite3.Error, ValueError):
            self._read_failed = True
            if changed:
                self._document_hash = None
                self._legacy_unverified = False
                self._saved_known = self._has_saved = False
                self._fill([])
            self._adoption_controls()
            self.status.setText("建議暫時無法讀取；請稍後按更新重試。現有草稿不受影響。")
            return
        self._read_failed = False
        self._document_hash = saved.get("document_hash")
        self._legacy_unverified = bool(saved.get("legacy_unverified"))
        self._saved_known = bool(saved.get("known"))
        self._has_saved = bool(saved.get("items"))
        self._fill(saved.get("items", []))
        # Suggestions are made by 深入分析, or when the reader presses 更新建議. Showing
        # the tab used to start an AI job on its own: a model call nobody asked for on
        # analysed papers, and a failed job on every paper not yet analysed.
        self.status.setText("已保存本文建議；選擇後可編輯，送出才會詢問 AI。"
                            if self.picker.count()
                            else "還沒有本文的提問建議：深入分析會一併產生；"
                                 "已分析過的論文可按「AI 更新建議」。")
        if saved.get("reason") and not self._has_saved:
            self.status.setText(_retry_hint(saved["reason"]))
        if self._legacy_unverified:
            self.status.setText("舊版建議尚未核對原文版本；更新建議前不會自動呼叫 AI。")
        self._adoption_controls()

    def open_browser(self):
        if self.browser.isVisible():
            self.browser.raise_()
            return
        self._browser_paper = self.paper_id
        self._browser_context = (self.paper_id, self._database)
        screen = self.screen()
        if screen:
            area = screen.availableGeometry()
            self.browser.resize(min(940, max(320, area.width() - 80)),
                                min(580, max(300, area.height() - 80)))
        self.browser.open()
        self.picker.setFocus()

    def _dismissed(self):
        if (not self._switching_paper
                and self._browser_context == (self.paper_id, self._database)):
            self.return_to_draft.emit()

    def _item(self):
        item = self.picker.currentItem()
        return item.data(Qt.ItemDataRole.UserRole) if item is not None else None

    def _fill(self, items):
        selected = self._item()
        self.picker.clear()
        index = 0
        for number, item in enumerate(items):
            entry = QListWidgetItem(f"{number + 1}. {question_preview(item['question'])}")
            entry.setData(Qt.ItemDataRole.UserRole, item)
            entry.setToolTip(item["question"])
            entry.setSizeHint(QSize(240, self.picker.fontMetrics().lineSpacing() * 3 + 16))
            self.picker.addItem(entry)
            if selected and item["question"] == selected["question"]:
                index = number
        self.picker.setCurrentRow(index if items else -1)
        self.browse.setText(f"瀏覽本文建議（{len(items)}）")
        self._selected()

    def _selected(self, _index=0):
        item = self._item()
        self.insert.setEnabled(bool(item))
        self.source.setVisible(bool(item and item.get("page")
                                    and (self._database is None or self._document_hash)))
        source_label = "原文依據"
        if self._database is not None and not self._document_hash:
            source_label += "（來源版本未確認）"
        page_label = f"第 {item['page']} 頁" if item and item.get("page") else "頁碼未確認"
        self.detail.setText(
            f"問題\n{item['question']}\n\n為什麼值得問\n{item['why']}"
            f"\n\n{source_label} · {page_label}\n{item['evidence']}"
            if item else "目前沒有本文建議。你仍可直接在底部輸入自己的問題。"
        )
        self.details_scroll.verticalScrollBar().setValue(0)

    def _insert(self):
        if (self.browser.isVisible()
                and self._browser_context != (self.paper_id, self._database)):
            self.browser.reject()
            return
        item = self._item()
        if item:
            self.browser.accept()
            self.chosen.emit(item["question"])

    def _source(self):
        item = self._item()
        if item and (self._database is None or self._document_hash):
            self.browser.accept()
            source = dict(kind="original", page=item["page"], text=item["evidence"])
            if self._document_hash:
                source["document_hash"] = self._document_hash
            self.source_requested.emit(source)

    def generate(self, *, force=False):
        if self._read_failed:
            if not force:
                return
            self.load(self.paper_id)
            if self._read_failed:
                return
        if not force and (self._saved_known or self._has_saved):
            return
        pid = self.paper_id
        database, epoch = self._database, self._load_epoch
        attempt = (database, pid)
        if not pid or (not force and attempt in self._attempted):
            return
        if self.runner.busy or self.adoption_busy:
            return
        self._attempted.add(attempt)
        connections = llm.capture_connections() if database is not None else None
        self.refresh_button.setEnabled(False)
        self.verify_button.setEnabled(False)
        self.verify_in_browser.setEnabled(False)
        self.adopt_button.setEnabled(False)
        self.status.setText("正在準備本文候選問題（使用論文問答的 AI）…")

        def call(_prompt):
            try:
                if database is None:
                    result, reason = research_questions.ensure(pid, force=force)
                else:
                    from paper_daily.research_question_jobs import ensure

                    result, reason = ensure(database, pid, force=force, connections=connections)
            except ValueError as exc:
                # The job refuses before any model call when its inputs are missing;
                # say which, instead of a bare exception name in the job tray.
                return None, (
                    "需要先完成深入分析（深度講解與逐節精讀），才能產生本文的提問建議。"
                    if "deep explanation" in str(exc) else f"無法產生提問建議：{exc}"
                )
            return json.dumps(result, ensure_ascii=False) if result else None, reason

        def finish(value=None, reason=""):
            self.refresh_button.setEnabled(True)
            QTimer.singleShot(25, self, self._after_generation)
            if (self.paper_id, self._database, self._load_epoch) != (pid, database, epoch):
                return
            if value:
                saved = json.loads(value)
                self._document_hash = saved.get("document_hash")
                self._legacy_unverified = bool(saved.get("legacy_unverified"))
                self._saved_known = bool(saved.get("known"))
                self._has_saved = bool(saved.get("items"))
                self._fill(saved["items"])
            self._prepared_adoption = None
            self._prepared_context = None
            if not value:
                self.status.setText(_retry_hint(reason, kept=bool(self.picker.count())))
            elif self._legacy_unverified:
                self.status.setText("舊版建議尚未核對原文版本；更新建議前不會自動呼叫 AI。")
            else:
                self.status.setText("本文建議已更新；瀏覽並選擇後可編輯，送出才會詢問 AI。")

        self.runner.start(
            "", lambda value: finish(value=value), lambda why: finish(reason=why), call=call
        )

    def _after_generation(self):
        # AskRunner completes queued delivery after invoking its callback.
        if self.runner.busy:
            QTimer.singleShot(25, self, self._after_generation)
        else:
            self._adoption_controls()

    @property
    def adoption_busy(self):
        """The window close/restart guard waits for a bounded local publication."""
        return self.adoption_runner.busy

    def _adoption_controls(self):
        legacy = bool(self._legacy_unverified and self._database)
        idle = not self.adoption_busy and not self.runner.busy
        for button in (self.verify_button, self.verify_in_browser):
            button.setVisible(legacy)
            button.setEnabled(idle and not self._read_failed)
        self.adopt_button.setVisible(legacy and self._prepared_adoption is not None)
        self.adopt_button.setEnabled(idle and not self._read_failed)
        self.refresh_button.setEnabled(idle)

    @staticmethod
    def _database_identity(database):
        try:
            info = database.stat()
            return info.st_dev, info.st_ino
        except (OSError, AttributeError):
            return None

    def _adoption_context(self):
        return (self.paper_id, self._database, self._load_epoch,
                self._database_identity(self._database))

    def _adoption_current(self, context):
        source = self._database_source
        try:
            database = Path(source() if callable(source) else source).resolve() if source else None
        except (OSError, ValueError):
            return False
        return context == self._adoption_context() and database == self._database

    def _adoption_deliverable(self, context):
        if self._adoption_current(context):
            return True
        # A selector/file change without load() must not leave a false running
        # message. Never replace the status of a genuinely newer loaded view.
        if context[:3] == self._adoption_context()[:3]:
            self._prepared_adoption = self._prepared_context = None
            self._adoption_message("工作區已變動，背景結果未套用至目前畫面；請重新載入。")
        return False

    def _adoption_message(self, text):
        self.status.setText(text)
        self.adoption_status.setText(text)
        self.adoption_status.setToolTip(text)
        self.adoption_status.show()

    def verify_legacy(self):
        if (self.adoption_busy or self.runner.busy or self._read_failed
                or not self._legacy_unverified or not self._database):
            return
        context = self._adoption_context()
        if not self._adoption_current(context):
            return
        from paper_daily.question_legacy_adoption import prepare

        _, database, _, identity = context
        paper_id = self.paper_id
        self.open_browser()
        self._prepared_adoption = None
        self._prepared_context = None
        self._adoption_message("正在核對既有問題、原文 PDF 與分析內容… 不會呼叫 AI。")

        def call():
            if ResearchQuestions._database_identity(database) != identity:
                raise ValueError("Workspace file changed before verification")
            prepared = prepare(database, paper_id,
                               cache_root=database.parent / "research-questions",
                               legacy_root=database.parent / "pdf")
            if ResearchQuestions._database_identity(database) != identity:
                raise ValueError("Workspace file changed during verification")
            return prepared

        def done(prepared):
            if self._adoption_deliverable(context):
                self._prepared_adoption = prepared
                self._prepared_context = context
                self._document_hash = prepared.row["document_hash"]
                self._fill(prepared.items)
                self._adoption_message("已核對問題與引用原文。請預覽後按「採用已核對建議」；"
                                       "尚未寫入工作區。PDF SHA-256：" + self._document_hash)
            self._adoption_controls()

        def failed(reason):
            if self._adoption_deliverable(context):
                self._adoption_message("來源核對失敗，原有建議保留：" + reason)
            self._adoption_controls()

        self.adoption_runner.start(call, done, failed)
        self._adoption_controls()

    def adopt_legacy(self):
        if (self.adoption_busy or self.runner.busy or not self._prepared_adoption
                or self._read_failed or not self._legacy_unverified):
            return
        context = self._prepared_context
        if not self._adoption_current(context):
            self._prepared_adoption = None
            self._prepared_context = None
            self._adoption_message("工作區已變動，請重新載入後核對；尚未採用。")
            self._adoption_controls()
            return
        prepared = self._prepared_adoption
        self._adoption_message("正在採用已核對的建議至原工作區…")

        def done(publication):
            if self._adoption_deliverable(context):
                if publication.status == "accepted":
                    self._legacy_unverified = False
                    self._saved_known = self._has_saved = True
                    self._document_hash = prepared.row["document_hash"]
                    self._fill(prepared.items)
                    self._adoption_message("已採用至此工作區；不會重新詢問 AI。")
                else:
                    self._adoption_message("來源或工作區已變動，未覆蓋目前內容；"
                                           "這份核對結果已保留供審閱。請重新載入後核對。")
                self._prepared_adoption = None
            self._prepared_context = None
            self._adoption_controls()

        def failed(reason):
            if self._adoption_deliverable(context):
                self._adoption_message("採用未完成，核對預覽保留，可重試：" + reason)
            self._adoption_controls()

        # The worker captures the prepared operation, never today's workspace.
        self.adoption_runner.start(prepared.adopt, done, failed)
        self._adoption_controls()
