"""Explicit native-package destinations and worker-owned review before publication."""

from concurrent.futures import ThreadPoolExecutor

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from paper_daily import store
from paper_daily.desktop import activity
from paper_daily.package_review import PackageReview
from paper_daily.workspace_service import Ticket

COPY = dict(
    title="Import research package",
    destination="Destination list",
    new="New list",
    separate="New paper",
    choose="Choose existing paper...",
    reset="Reset",
    review="Review changes",
    apply="Import reviewed changes",
    close="Close",
    working="Checking package and selected destinations...",
    instructions="Choose destinations, then review the changes before importing.",
    papers="New papers",
    notes="Notes",
    chat="Q&A entries",
    files="Included files",
    lineage_reports="New lineage analyses",
    lineage_reused="Unchanged lineage analyses",
    lineage_replaced="Incoming versions adopted; prior versions kept in history",
    lineage_preserved="Current lineage analyses kept",
    lineage_adopted="Identical saved analyses included in sync",
    pdf_kept="Local PDF versions kept",
    pdf_needed="PDFs still needed",
    stopped="Import canceled.",
    search="Find an existing paper by title or exact ID",
    select="Choose the destination paper",
    none="No active papers found. Try a more specific title or exact ID.",
    more="Showing the first 50 matches. Refine the search if your paper is missing.",
    stale="The workspace changed. Reopen import from the intended workspace.",
    ready="Review complete. Import only if these destinations are correct.",
    saved="Research saved locally.",
    error="Unable to finish. Review the choices and retry.",
    incoming="Incoming paper",
    target="Destination paper",
    canceling="Canceling; waiting for work...",
)
ZH = dict(
    title="\u532f\u5165\u7814\u7a76\u8cc7\u6599\u5305",
    instructions="\u9078\u64c7\u76ee\u7684\u6e05\u55ae\u8207\u914d\u5c0d\u5f8c\uff0c\u518d\u9810\u89bd\u532f\u5165\u5167\u5bb9\u3002",
    papers="\u65b0\u589e\u8ad6\u6587",
    notes="\u7b46\u8a18",
    chat="\u554f\u7b54",
    files="\u5167\u542b\u6a94\u6848",
    lineage_reports="\u65b0\u589e\u8108\u7d61\u5206\u6790",
    lineage_reused="\u6cbf\u7528\u8108\u7d61\u5206\u6790",
    pdf_kept="\u4fdd\u7559\u672c\u6a5f PDF \u7248\u672c",
    pdf_needed="\u4ecd\u7f3a\u5c11 PDF",
    destination="\u76ee\u7684\u6e05\u55ae",
    new="\u5efa\u7acb\u65b0\u6e05\u55ae",
    separate="\u65b0\u8ad6\u6587",
    choose="\u914d\u5c0d\u65e2\u6709\u8ad6\u6587...",
    reset="\u91cd\u8a2d",
    review="\u9810\u89bd\u532f\u5165\u5167\u5bb9",
    apply="\u78ba\u8a8d\u532f\u5165",
    close="\u95dc\u9589",
    working="\u6b63\u5728\u6838\u5c0d\u8cc7\u6599\u5305\u8207\u914d\u5c0d...",
    ready="\u8acb\u6838\u5c0d\u76ee\u7684\u6e05\u55ae\u8207\u8ad6\u6587\u914d\u5c0d\u5f8c\u78ba\u8a8d\u532f\u5165\u3002",
    saved="\u7814\u7a76\u5167\u5bb9\u5df2\u5132\u5b58\u65bc\u672c\u6a5f\u3002",
    incoming="\u8cc7\u6599\u5305\u8ad6\u6587",
    target="\u672c\u6a5f\u76ee\u7684\u8ad6\u6587",
)


class PackageReviewDialog(QDialog):
    def __init__(self, database, data_root, source, parent=None, *, language="zh-TW"):
        super().__init__(parent)
        self.language = language
        self.t = {**COPY, **(ZH if language.startswith("zh") else {})}
        self.database, self.data_root, self.source = database, data_root, source
        self.result_data = None
        self.session = None
        self.mapping = {}
        self.rows = []
        self.reviewed = False
        self._closing = False
        self._stale = False
        self._comparison = None
        self._future = None
        self._ticket = Ticket()
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="package-review")
        self._handle = activity.Handle()
        self.setWindowTitle(self.t["title"])
        self.resize(760, 620)
        layout = QVBoxLayout(self)
        self.name = QLabel(self.t["working"])
        self.name.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self.name)
        layout.addWidget(QLabel(self.t["destination"]))
        self.destination = QComboBox()
        self.destination.addItem(self.t["new"], None)
        self.destination.currentIndexChanged.connect(self._changed)
        layout.addWidget(self.destination)
        self.table = QTableWidget(0, 2)
        self.table.setHorizontalHeaderLabels([self.t["incoming"], self.t["target"]])
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setWordWrap(False)
        self.table.setColumnWidth(0, 320)
        self.table.verticalHeader().setDefaultSectionSize(38)
        layout.addWidget(self.table, 2)
        self.preview = QPlainTextEdit()
        self.preview.setReadOnly(True)
        layout.addWidget(self.preview, 1)
        self.bar = QProgressBar()
        self.bar.setRange(0, 0)
        layout.addWidget(self.bar)
        self.status = QLabel(self.t["working"])
        self.status.setWordWrap(True)
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self.status)
        buttons = QHBoxLayout()
        self.review_button = QPushButton(self.t["review"])
        self.apply_button = QPushButton(self.t["apply"])
        self.close_button = QPushButton(self.t["close"])
        self.review_button.clicked.connect(self.review)
        self.apply_button.clicked.connect(self.apply)
        self.close_button.clicked.connect(self.reject)
        for button in (self.review_button, self.apply_button, self.close_button):
            buttons.addWidget(button)
        layout.addLayout(buttons)
        self._poller = QTimer(self)
        self._poller.setInterval(25)
        self._poller.timeout.connect(self._poll)
        self._controls()
        QTimer.singleShot(0, self, self.load)

    @property
    def busy(self):
        return self._future is not None

    def _controls(self):
        ready = self.session is not None and not self.busy and not self._closing and not self._stale
        self.destination.setEnabled(ready and self.result_data is None)
        self.table.setEnabled(ready and self.result_data is None)
        self.review_button.setEnabled(
            not self.busy and not self._closing and not self._stale and self.result_data is None
        )
        self.apply_button.setEnabled(ready and self.reviewed and self.result_data is None)
        self.bar.setVisible(self.busy)

    def _start(self, phase, call, done):
        if self.busy or self._closing or self._stale:
            return False
        self._ticket = Ticket()
        self._handle = activity.begin(
            self,
            self.t["title"],
            task="bundle_import",
            key=f"package-review:{self.database}:{self.source}",
            cancel=self.reject,
        )
        if not self._handle.accepted:
            self._controls()
            return False
        self._phase, self._done = phase, done
        self._future = self._executor.submit(call, self._ticket)
        self.status.setText(self.t["working"])
        self._poller.start()
        self._controls()
        return True

    def load(self):
        if self.session is not None:
            return self.review()
        database, root, source = self.database, self.data_root, self.source

        def read(ticket):
            session = PackageReview(database, root, source, current_path=lambda: store.DB_PATH)
            try:
                return session, session.inspect(ticket)
            except BaseException:
                session.close()
                session.discard()
                raise

        return self._start("inspect", read, self._loaded)

    def _loaded(self, value):
        self.session, info = value
        self.name.setText(info["name"])
        for listing in info["lists"]:
            self.destination.addItem(listing["name"], listing["id"])
        self.rows = info["papers"]
        self.table.setRowCount(len(self.rows))
        for index, paper in enumerate(self.rows):
            item = QTableWidgetItem(paper["title"])
            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            item.setToolTip(paper["id"])
            self.table.setItem(index, 0, item)
            holder = QWidget()
            row = QHBoxLayout(holder)
            row.setContentsMargins(2, 2, 2, 2)
            choose = QPushButton(self.t["separate"] + " - " + self.t["choose"])
            choose.clicked.connect(lambda _checked=False, i=index: self.choose(i))
            reset = QPushButton(self.t["reset"])
            reset.clicked.connect(lambda _checked=False, i=index: self.reset(i))
            row.addWidget(choose, 1)
            row.addWidget(reset)
            self.table.setCellWidget(index, 1, holder)
        self.status.setText(self.t["instructions"])

    def _changed(self, *_args):
        self.reviewed = False
        self.preview.clear()
        self._controls()

    def reset(self, index):
        if self.busy or self._closing:
            return
        self.mapping.pop(self.rows[index]["id"], None)
        self.table.cellWidget(index, 1).findChildren(QPushButton)[0].setText(self.t["choose"])
        self._changed()

    def choose(self, index):
        if self.busy or self._closing or self.session is None:
            return
        query, accepted = QInputDialog.getText(self, self.t["title"], self.t["search"])
        if not accepted or not self.session.current():
            return
        session = self.session

        def found(result):
            if not result["papers"]:
                self.status.setText(self.t["none"])
                return
            labels = [
                f"{index + 1}. {' '.join(p['title'].split())[:80]} "
                f"({p['year'] or '?'}) [{p['id'][:32]}]"
                for index, p in enumerate(result["papers"])
            ]
            label, accepted = QInputDialog.getItem(
                self,
                self.t["title"],
                self.t["select"],
                labels,
                0,
                False,
            )
            if not accepted or not session.current() or self._closing:
                return
            selected = result["papers"][labels.index(label)]
            self.mapping[self.rows[index]["id"]] = selected["id"]
            button = self.table.cellWidget(index, 1).findChildren(QPushButton)[0]
            button.setText(" ".join(selected["title"].split())[:80])
            button.setToolTip(selected["title"] + "\n" + selected["id"])
            self._changed()
            if result["more"]:
                self.status.setText(self.t["more"])

        self._start("search", lambda _ticket: session.search(query), found)

    def review(self, _checked=False, *, lineage_choices=None):
        if self.session is None:
            return self.load()
        session, destination, mapping = (
            self.session,
            self.destination.currentData(),
            dict(self.mapping),
        )
        self.reviewed = False

        def ready(result):
            if result.get("state") == "needs_lineage_review":
                from paper_daily.desktop.lineage_import_dialog import LineageImportDialog

                comparison = LineageImportDialog(result["conflicts"], self, language=self.language)
                self._comparison = comparison
                accepted = comparison.exec() == QDialog.DialogCode.Accepted
                self._comparison = None
                choices = dict(comparison.choices)
                comparison.deleteLater()
                if self._closing:
                    return
                if not session.current():
                    self._stale = True
                    self.status.setText(self.t["stale"])
                elif accepted:
                    QTimer.singleShot(0, self, lambda: self.review(lineage_choices=choices))
                else:
                    self.status.setText(self.t["stopped"])
                return
            destination = self.destination.currentText()
            if self.destination.currentData() is None:
                destination += ": " + result["name"]
            labels = {
                key: self.t[key]
                for key in (
                    "papers",
                    "notes",
                    "chat",
                    "files",
                    "lineage_reports",
                    "lineage_reused",
                    "lineage_replaced",
                    "lineage_preserved",
                    "lineage_adopted",
                )
            }
            lines = [self.t["destination"] + ": " + destination]
            for key, label in labels.items():
                value = result.get(key, 0)
                if type(value) is int and value:
                    lines.append(f"{label}: {value}")
            lines.extend(
                [
                    f"{self.t['pdf_kept']}: {len(result.get('pdf_conflicts', []))}",
                    f"{self.t['pdf_needed']}: {len(result.get('pdf_needed', []))}",
                ]
            )
            self.preview.setPlainText("\n".join(lines))
            self.reviewed = True
            self.status.setText(self.t["ready"])

        self._start(
            "prepare",
            lambda ticket: session.prepare(
                target_list_id=destination,
                paper_mapping=mapping,
                ticket=ticket,
                lineage_choices=lineage_choices,
            ),
            ready,
        )

    def apply(self):
        if self.busy or not self.reviewed or self.session is None:
            return
        session = self.session

        def saved(result):
            self.result_data = result
            self.reviewed = False
            self.status.setText(self.t["saved"])

        self._start("apply", lambda ticket: session.apply(ticket), saved)

    def _poll(self):
        if self._future is None or not self._future.done():
            return
        future, self._future = self._future, None
        self._poller.stop()
        if self._phase == "cleanup":
            try:
                future.result()
            except Exception:
                import logging

                logging.getLogger(__name__).warning("Private package review cleanup is pending")
            self._executor.shutdown(wait=False)
            super().reject()
            return
        try:
            value = future.result()
            if self._phase == "inspect":
                self.session = value[0]
            if self._closing:
                self._handle.finish(False, self.t["stopped"], cancelled=True)
            elif self.session is not None and not self.session.current():
                self._mark_stale()
            else:
                self._done(value)
                self._handle.finish(not self._closing, cancelled=self._closing)
        except Exception as error:
            self.reviewed = False
            if (not self._closing and self.session is not None
                    and not self.session.current()):
                self._mark_stale()
            else:
                message = str(error) if isinstance(error, ValueError) else self.t["error"]
                self.status.setText(message)
                self._handle.finish(False, self.status.text(), cancelled=self._ticket.cancelled)
        if self._closing:
            self._cleanup()
        self._controls()

    def _mark_stale(self):
        message = self.t["stale"]
        if self._phase == "apply" and self._ticket.published:
            message = self.t["saved"] + " " + message
        self.status.setText(message)
        self._stale = True
        self.reviewed = False
        self._handle.finish(False, message)

    def _cleanup(self):
        if self.busy:
            return
        if self.session is None:
            self._executor.shutdown(wait=False)
            super().reject()
            return
        self.session.close()
        self._phase = "cleanup"
        self._future = self._executor.submit(self.session.discard)
        self._poller.start()

    def reject(self):
        if self._closing:
            return
        self._closing = True
        if self._comparison is not None:
            self._comparison.reject()
        self._ticket.cancel()
        if self.session is not None:
            self.session.close()
        self.status.setText(self.t["canceling"])
        self._controls()
        if not self.busy:
            self._cleanup()

    def closeEvent(self, event):
        event.ignore()
        self.reject()
