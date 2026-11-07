"""Read-only rescue preview and explicit receiver-side retained-draft import.

Workers belong to the application, not the disposable dialog. Actual incomplete
results reach the app's pending-result owner before any GUI delivery guards.
"""

from __future__ import annotations

import sqlite3
import threading
from contextlib import closing
from uuid import uuid4

from PySide6.QtCore import QObject, QSize, Qt, QTimer, Signal, Slot
from PySide6.QtGui import QIcon, QImage, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QSplitter,
    QTabWidget,
    QVBoxLayout,
)
from shiboken6 import isValid

from paper_daily.desktop.activity import begin
from paper_daily.desktop.integration_dialog import OperationWorker
from paper_daily.desktop.pending_generation import hub
from paper_daily.desktop.review_deck_text import deck_text
from paper_daily.desktop.review_dialog import ReviewDialog

COPY = {
    "en": {
        "entry": "Import rescued presentation…",
        "title": "Import rescued presentation",
        "intro": (
            "Open a Paperfact rescue copy, inspect its content, then choose a local paper. "
            "It is retained for review before any existing presentation changes."
        ),
        "choose": "Open rescue copy…",
        "file": "No rescue copy selected",
        "filter": "Paperfact rescue copy (*.paperfact-draft.zip *.paperfact-draft.json)",
        "content": "Slides and speaker notes",
        "images": "Captured images",
        "sources": "Source evidence",
        "target": "Choose the local paper",
        "search_hint": "Search title or DOI",
        "search": "Search",
        "retain": "Retain draft for review",
        "retry": "Retry saving completed import",
        "review": "Review retained draft…",
        "close": "Close",
        "reading": "Reading and verifying the rescue copy…",
        "preparing": "Checking the selected paper and original sources…",
        "saving": "Retaining the verified imported draft…",
        "searching": "Reading local papers…",
        "ready": "Read-only preview. Choose a local paper to retain this draft.",
        "saved": "Retained locally for review. Your current presentation is unchanged.",
        "unsaved": (
            "Not saved. The actual completed result is held in the app; retry saving without AI."
        ),
        "changed": "The original workspace or selection changed. Current content is unchanged.",
        "canceling": "Cancelling; waiting for the admitted work to finish…",
        "failed": "Could not complete this action: {reason}",
        "limit": "Showing the first 50 matches; refine your search.",
        "empty": "No local papers match. Add a paper or change the search.",
        "shortened": "Preview shortened; the complete rescue copy is unchanged.",
        "review_busy": "Finish the existing review window first.",
    },
    "zh-TW": {
        "entry": "匯入救援簡報草稿…",
        "title": "匯入救援簡報草稿",
        "intro": (
            "開啟 Paperfact 救援副本，預覽內容並選擇本機論文。"
            "先保留為待核對草稿，核對後才變更現有簡報。"
        ),
        "choose": "開啟救援副本…",
        "file": "尚未選擇救援副本",
        "filter": "Paperfact 救援副本 (*.paperfact-draft.zip *.paperfact-draft.json)",
        "content": "內容與講稿",
        "images": "已擷取圖片",
        "sources": "來源證據",
        "target": "選擇要接回的本機論文",
        "search_hint": "搜尋標題或 DOI",
        "search": "搜尋",
        "retain": "保留為待核對草稿",
        "retry": "重試儲存已完成的匯入",
        "review": "核對保留稿…",
        "close": "關閉",
        "reading": "正在讀取並核對救援副本…",
        "preparing": "正在核對所選論文與原文來源…",
        "saving": "正在保留已核對的匯入草稿…",
        "searching": "正在讀取本機論文…",
        "ready": "目前為唯讀預覽。選擇本機論文後，可保留這份草稿。",
        "saved": "已保留為本機待核對草稿，目前簡報未被替換。",
        "unsaved": "尚未儲存；實際結果仍保留在 App 中，可重試儲存，不會呼叫 AI。",
        "changed": "原工作區或選擇已變更，目前內容未變動。",
        "canceling": "正在取消，等候已開始的工作結束…",
        "failed": "這次操作未完成：{reason}",
        "limit": "目前顯示前 50 筆，請縮小搜尋範圍。",
        "empty": "沒有符合的本機論文，請先新增論文或修改搜尋。",
        "shortened": "預覽已縮短，救援副本的完整內容未變動。",
        "review_busy": "請先完成已開啟的核對視窗。",
    },
}


class _Lease:
    def __init__(self, owner):
        self.owner = owner
        self.closed = threading.Event()

    def current(self):
        return not self.closed.is_set() and self.owner.current()


def _papers(lease, query):
    if not lease.current():
        raise ValueError("Original workspace changed")
    path = lease.owner.database
    escaped = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    pattern = "%" + escaped + "%"
    with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT id,title,year,venue,doi FROM papers "
            "WHERE title LIKE ? ESCAPE '\\' OR doi LIKE ? ESCAPE '\\' OR id=? "
            "ORDER BY title COLLATE NOCASE,id LIMIT 51",
            (pattern, pattern, query),
        ).fetchall()
    if not lease.current():
        raise ValueError("Original workspace changed")
    return [dict(row) for row in rows[:50]], len(rows) > 50


def _preview_payload(preview, *, chinese):
    from paper_daily.portable_deck_archive import RescueArchive

    data = preview.content if isinstance(preview, RescueArchive) else preview.preview_data
    deck = data["deck"]
    thumbnails = []
    figures = {row["id"]: row for row in deck["figures"]}
    for row in (data.get("evidence") or {}).get("figures", []):
        figures.setdefault(row["id"], row)
    for row in figures.values():
        image = QImage.fromData(data["image_bytes"][row["id"]], "PNG")
        if image.isNull():
            raise ValueError("Captured PNG could not be displayed")
        thumbnail = image.scaled(
            QSize(150, 100),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        thumbnails.append((dict(row), thumbnail))
    evidence = data.get("evidence") or {}
    source_text = []
    for source in evidence.get("sources", deck["sources"]):
        source_text += [
            source["label"],
            str(source.get("page") or ""),
            str(source.get("document_hash") or ""),
            source.get("text", ""),
            "",
        ]
        if sum(len(line) for line in source_text) > 200_000:
            break
    return dict(
        source=preview,
        title=deck["title"],
        paper_title=deck["paper_title"],
        mode=deck["mode"],
        text=deck_text(deck, chinese=chinese),
        thumbnails=thumbnails,
        sources="\n".join(source_text)[:200_000],
    )


class _Worker(OperationWorker):
    progress = Signal(str)

    def __init__(self, call, parent):
        super().__init__("rescue.local", {}, parent)
        self.call = call

    def run(self):
        try:
            self.response = (True, self.call(self.progress.emit))
        except (ValueError, OSError, sqlite3.Error) as exc:
            self.response = (False, str(exc))
        except Exception as exc:  # noqa: BLE001 - keep native thread teardown observable
            self.response = (False, type(exc).__name__)


class _Completion(QObject):
    delivered = Signal(object)

    def __init__(self, handle, kind, lease):
        super().__init__(QApplication.instance())
        self.handle, self.kind, self.lease = handle, kind, lease
        self.worker = None
        self.context = None

    @Slot()
    def finish(self):
        worker = self.worker
        worker.wait()
        ok, result = worker.response or (False, "Worker returned no result")
        worker.response = (ok, result)
        saved = ok and (self.kind != "retain" or bool(result["durable"]))
        self.handle.finish(saved, cancelled=self.lease.closed.is_set())
        self.delivered.emit(self)
        worker.deleteLater()
        self.deleteLater()


class _FocusedReview(ReviewDialog):
    def __init__(self, database, candidate_id, *, parent, language, origin="file_draft"):
        super().__init__(database, parent=parent, language=language)
        item = QListWidgetItem(self.words["retained_slides"])
        item.setData(Qt.ItemDataRole.UserRole, (origin, candidate_id))
        self.list.insertItem(0, item)
        self.list.setCurrentItem(item)

    def _page(self, page):
        existing = {
            self.list.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.list.count())
        }
        for row in page["items"]:
            if row.get("summary") and (row["origin"], row["id"]) in existing:
                for index in range(self.list.count()):
                    item = self.list.item(index)
                    if item.data(Qt.ItemDataRole.UserRole) == (row["origin"], row["id"]):
                        item.setText(self.words["retained_slides"] + " ? " + row["summary"])
        fresh = [row for row in page["items"] if (row["origin"], row["id"]) not in existing]
        super()._page(dict(page, items=fresh))


class RescueImportDialog(QDialog):
    def __init__(self, owner, parent=None, *, language="en", selected_paper=None):
        if not owner.current():
            raise ValueError("Original workspace changed")
        super().__init__(parent)
        self.lease = _Lease(owner)
        self.words = COPY.get(language, COPY["en"])
        self.language = language
        self.selected_paper = selected_paper
        self.disposed = self.busy = False
        self._closing = False
        self._choosing = False
        self._attempt_paper_id = None
        self._task = None
        self.source = self.job = self.result = None
        self.pending_key = None
        self.request_id = str(uuid4())
        self.pending = hub()
        self.setWindowTitle(self.words["title"])
        self.resize(940, 740)
        layout = QVBoxLayout(self)
        intro = QLabel(self.words["intro"])
        intro.setWordWrap(True)
        layout.addWidget(intro)
        file_row = QHBoxLayout()
        self.choose_button = QPushButton(self.words["choose"])
        self.choose_button.clicked.connect(self.choose)
        self.file_label = QLabel(self.words["file"])
        self.file_label.setMinimumWidth(0)
        self.file_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        file_row.addWidget(self.choose_button)
        file_row.addWidget(self.file_label, 1)
        layout.addLayout(file_row)
        self.tabs = QTabWidget()
        self.text = QPlainTextEdit()
        self.text.setReadOnly(True)
        self.images = QListWidget()
        self.images.setViewMode(QListWidget.ViewMode.IconMode)
        self.images.setIconSize(QSize(150, 100))
        self.images.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.images.setWordWrap(True)
        self.images.setGridSize(QSize(180, 145))
        self.image_detail = QPlainTextEdit()
        self.image_detail.setReadOnly(True)
        image_split = QSplitter(Qt.Orientation.Vertical)
        image_split.addWidget(self.images)
        image_split.addWidget(self.image_detail)
        image_split.setSizes([230, 100])
        self.images.currentItemChanged.connect(self._image_selected)
        self.sources = QPlainTextEdit()
        self.sources.setReadOnly(True)
        self.tabs.addTab(self.text, self.words["content"])
        self.tabs.addTab(image_split, self.words["images"])
        self.tabs.addTab(self.sources, self.words["sources"])
        layout.addWidget(self.tabs, 2)
        layout.addWidget(QLabel(self.words["target"]))
        search_row = QHBoxLayout()
        self.query = QLineEdit()
        self.query.setPlaceholderText(self.words["search_hint"])
        self.query.setMaxLength(512)
        self.query.textChanged.connect(self._filter_changed)
        self.query.returnPressed.connect(self.search)
        self.search_button = QPushButton(self.words["search"])
        self.search_button.clicked.connect(self.search)
        search_row.addWidget(self.query, 1)
        search_row.addWidget(self.search_button)
        layout.addLayout(search_row)
        self.targets = QListWidget()
        self.targets.setMinimumHeight(70)
        self.targets.setTextElideMode(Qt.TextElideMode.ElideRight)
        self.targets.currentItemChanged.connect(self._target_changed)
        layout.addWidget(self.targets, 1)
        self.target_label = QLabel()
        self.target_label.setTextFormat(Qt.TextFormat.PlainText)
        self.target_label.setMinimumWidth(0)
        self.target_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        layout.addWidget(self.target_label)
        self.status = QLabel()
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.hide()
        layout.addWidget(self.progress)
        actions = QHBoxLayout()
        self.retain_button = QPushButton(self.words["retain"])
        self.review_button = QPushButton(self.words["review"])
        self.close_button = QPushButton(self.words["close"])
        self.retain_button.clicked.connect(self.retain)
        self.review_button.clicked.connect(self.review)
        self.close_button.clicked.connect(self.reject)
        for button in (
            self.choose_button,
            self.search_button,
            self.retain_button,
            self.review_button,
            self.close_button,
        ):
            button.setAutoDefault(False)
            button.setDefault(False)
        actions.addWidget(self.retain_button)
        actions.addWidget(self.review_button)
        actions.addStretch(1)
        actions.addWidget(self.close_button)
        layout.addLayout(actions)
        self._controls()
        QTimer.singleShot(0, self.search)
        closed = self.lease.closed
        self.destroyed.connect(lambda: closed.set())

    def _target_id(self):
        item = self.targets.currentItem()
        return item.data(Qt.ItemDataRole.UserRole)["id"] if item is not None else None

    def _controls(self):
        current = not self.disposed and self.lease.current()
        for widget in (self.choose_button, self.search_button, self.targets):
            widget.setEnabled(current and not self.busy and not self._choosing)
        self.retain_button.setEnabled(
            current
            and not self.busy
            and self.source is not None
            and self._target_id() is not None
            and self.result is None
        )
        self.review_button.setEnabled(
            current
            and not self.busy
            and self.result is not None
            and self.result["paper_id"] == self._target_id()
        )
        self.progress.setVisible(self.busy)
        self.retain_button.setText(self.words["retry" if self.pending_key else "retain"])

    def _start(self, kind, call, context=None):
        if self.disposed or self.busy or self._choosing:
            return False
        if not self.lease.current():
            self.status.setText(self.words["changed"])
            self._controls()
            return False
        handle = begin(
            self,
            self.words[{"preview": "reading", "papers": "searching", "retain": "saving"}[kind]],
            task="local_recovery",
        )
        if not handle.accepted:
            return False
        completion = _Completion(handle, kind, self.lease)
        worker = _Worker(call, completion)
        completion.worker, completion.context = worker, context
        completion.delivered.connect(self._finished)
        worker.progress.connect(self.status.setText)
        worker.progress.connect(handle.stage)
        worker.finished.connect(completion.finish)
        self._task = completion
        self.busy = True
        self._controls()
        worker.start()
        return True

    def choose(self):
        if self.busy or self.disposed or self._choosing:
            return
        self._choosing = True
        self._controls()
        try:
            path, _kind = QFileDialog.getOpenFileName(
                self, self.words["choose"], "", self.words["filter"]
            )
        finally:
            self._choosing = False
            self._controls()
        if not path:
            return
        lease, chinese = self.lease, self.language == "zh-TW"
        words = self.words

        def call(report):
            from paper_daily import rescue_deck_import

            report(words["reading"])
            import zipfile

            from paper_daily import portable_deck_archive

            reader = (
                portable_deck_archive
                if zipfile.is_zipfile(portable_deck_archive._path(path))
                else rescue_deck_import
            )
            preview = reader.inspect_file(path, current=lease.current)
            return _preview_payload(preview, chinese=chinese)

        self._start("preview", call, path)

    def search(self):
        query, lease = self.query.text().strip(), self.lease
        self._start("papers", lambda _report: _papers(lease, query), query)

    def _filter_changed(self):
        self.targets.setCurrentRow(-1)
        self._controls()

    def _target_changed(self):
        item = self.targets.currentItem()
        identity = item.data(Qt.ItemDataRole.UserRole)["id"] if item else None
        if identity is not None and identity != self._attempt_paper_id:
            self._attempt_paper_id = identity
            self.job = self.result = None
            self.pending_key = None
            self.request_id = str(uuid4())
        self.target_label.setText(item.text() if item is not None else "")
        self.target_label.setToolTip(item.text() if item is not None else "")
        self._controls()

    def _image_selected(self, item):
        if item is None:
            self.image_detail.clear()
            return
        row = item.data(Qt.ItemDataRole.UserRole)
        page = ("頁碼：" if self.language == "zh-TW" else "Page: ") + str(row.get("page") or "—")
        original = "原文版本：" if self.language == "zh-TW" else "Original version: "
        text = "\n\n".join(
            (
                row["label"],
                row.get("caption", ""),
                page,
                original + str(row.get("document_hash") or "—"),
            )
        )
        self.image_detail.setPlainText(text)

    @Slot(object)
    def _finished(self, completion):
        if completion is not self._task or self.disposed:
            return
        self._task = None
        self.busy = False
        if self._closing:
            self.disposed = True
            super().reject()
            return
        ok, value = completion.worker.response
        if not self.lease.current():
            self.status.setText(self.words["changed"])
        elif not ok:
            self.status.setText(self.words["failed"].format(reason=value))
        elif completion.kind == "papers":
            if completion.context == self.query.text().strip():
                self.targets.clear()
                for row in value[0]:
                    item = QListWidgetItem(
                        f"{row['title']} · {row['year'] or ''} · {row['doi'] or row['id']}"
                    )
                    item.setData(Qt.ItemDataRole.UserRole, row)
                    self.targets.addItem(item)
                self.targets.setCurrentRow(-1)
                self.status.setText(
                    self.words["limit"] if value[1] else self.words["empty"] if not value[0] else ""
                )
        elif completion.kind == "preview":
            self.source, self.job, self.result = value["source"], None, None
            self.pending_key = None
            self.request_id = str(uuid4())
            self.mode = value["mode"]
            self.file_label.setText(value["paper_title"] + " · " + value["title"])
            self.file_label.setToolTip(str(completion.context))
            self.text.setPlainText(value["text"])
            self.sources.setPlainText(value["sources"])
            self.images.clear()
            for row, image in value["thumbnails"]:
                item = QListWidgetItem(QIcon(QPixmap.fromImage(image)), row["label"][:80])
                item.setData(Qt.ItemDataRole.UserRole, row)
                item.setToolTip(row.get("caption", row["label"]))
                self.images.addItem(item)
            self.tabs.setTabText(1, self.words["images"] + f" ({self.images.count()})")
            self.status.setText(self.words["ready"])
            if not self.targets.count():
                QTimer.singleShot(0, self.search)
        elif completion.kind == "retain":
            if completion.context != (self._target_id(), self.mode, self.request_id):
                self.status.setText(self.words["changed"])
                self._controls()
                return
            self.job = value["job"]
            if value["durable"]:
                self.result = value
                self.pending_key = None
                self.status.setText(
                    self.words["saved"] if value["current"] else self.words["changed"]
                )
            else:
                self.pending_key = value["pending_key"]
                self.status.setText(self.words["unsaved"])
        self._controls()

    def retain(self):
        if self.busy or self.disposed or self.source is None or self.result is not None:
            return
        paper_id = self._target_id()
        if paper_id is None:
            return
        source, job, mode = self.source, self.job, self.mode
        lease, request = self.lease, self.request_id
        pending, key, words = self.pending, self.pending_key, self.words

        def call(report):
            from paper_daily import local_rescue_import, rescue_deck_import

            actual_job = job
            if key and any(k == key for k, _result in pending.results.items()):
                report(words["saving"])
                retained = pending.results.retry(key)
                pending.changed.emit()
                current = lease.current()
            else:
                if actual_job is None:
                    report(words["preparing"])
                    from paper_daily import local_rescue_import, portable_deck_archive

                    if isinstance(source, portable_deck_archive.RescueArchive):
                        actual_job = local_rescue_import.prepare(
                            lease.owner.database, paper_id, source,
                            expected_native=lease.owner.identity, request_id=request,
                            current=lease.current,
                        )
                    else:
                        target = rescue_deck_import.capture(
                            lease.owner.database,
                            paper_id,
                            mode,
                            expected_native=lease.owner.identity,
                            request_id=request,
                            current=lease.current,
                        )
                        actual_job = rescue_deck_import.prepare(
                            target, source, current=lease.current
                        )
                report(words["saving"])
                from paper_daily import local_rescue_import

                if isinstance(actual_job, local_rescue_import.LocalImport):
                    retained = local_rescue_import.run(actual_job, current=lease.current)
                    current = lease.current()
                else:
                    result = rescue_deck_import.run(actual_job, current=lease.current)
                    retained, current = result.retention, result.context_current
            pending_key = pending.hold(retained) if not retained.durable else None
            return dict(
                job=actual_job,
                durable=retained.durable,
                current=current,
                pending_key=pending_key,
                candidate_id=retained.candidate_id,
                paper_id=paper_id,
                origin=("local_deck" if isinstance(retained, local_rescue_import.LocalRetention)
                        else "file_draft"),
            )

        self._start("retain", call, (paper_id, mode, request))

    def review(self):
        if self.busy or self.result is None or not self.lease.current():
            return
        parent = self.parentWidget()
        previous = getattr(parent, "_review_dialog", None)
        if (
            previous is not None
            and isValid(previous)
            and not previous.disposed
            and not previous.close()
        ):
            self.status.setText(self.words["review_busy"])
            return
        options = dict(parent=parent, language=self.language)
        if self.result.get("origin") == "local_deck":
            options["origin"] = "local_deck"
        dialog = _FocusedReview(
            self.lease.owner.database, self.result["candidate_id"], **options
        )
        if parent is not None:
            parent._review_dialog = dialog
        self.review_dialog = dialog
        self.reject()
        dialog.open()

    def reject(self):
        if self.busy:
            self._closing = True
            self.lease.closed.set()
            self.status.setText(self.words["canceling"])
            return
        self.disposed = True
        self.lease.closed.set()
        super().reject()

    def closeEvent(self, event):
        if self.busy:
            self.reject()
            event.ignore()
        else:
            self.disposed = True
            self.lease.closed.set()
            super().closeEvent(event)
