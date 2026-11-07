"""Add a paper to whatever is on screen: the main queue, or a reading list.

Two different problems wearing one button. The main queue is the three conferences
and nothing else, so adding to it means finding one of the 63,000 papers already
crawled -- a local search, instant. A reading list is arbitrary, so adding to it
means resolving a citation against Semantic Scholar and hunting for a PDF, which
takes seconds and runs as a subprocess, like the import it shares its code with.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from PySide6.QtCore import QProcess, Qt, QTimer
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
)

from paper_daily import runtime
from paper_daily.store import connect, search_papers


def _style(dialog: QDialog, pal: dict[str, str]) -> None:
    dialog.setStyleSheet(
        f"QDialog{{background:{pal['ground']};}}"
        f"QLabel{{color:{pal['ink']};}}"
        f"QLineEdit,QPlainTextEdit,QListWidget{{background:{pal['surface']};"
        f"color:{pal['ink']};border:1px solid {pal['firm']};padding:8px;}}"
        f"QPushButton{{background:{pal['surface']};color:{pal['ink']};"
        f"border:1px solid {pal['firm']};padding:7px 14px;}}"
    )


class AddToQueueDialog(QDialog):
    """Search the whole corpus and put a paper at the front of the queue."""

    def __init__(self, palette: dict[str, str], parent=None) -> None:
        super().__init__(parent)
        self.pal = palette
        self.added: str | None = None

        self.setWindowTitle("加入佇列")
        self.resize(820, 560)
        _style(self, palette)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(10)

        heading = QLabel("從語料庫加一篇到佇列")
        heading.setStyleSheet(f"color:{palette['ink']};font-size:17px;font-weight:600;")
        layout.addWidget(heading)

        blurb = QLabel(
            "搜尋的是全部 63,000 篇,不只是佇列裡的 5,000 篇。選中的會插到佇列最前面,"
            "並且標記成手動加入 —— 每晚重排不會把它移走。"
            "非 ICLR / ICML / NeurIPS 的論文請用清單。"
        )
        blurb.setWordWrap(True)
        blurb.setStyleSheet(f"color:{palette['muted']};font-size:12px;")
        layout.addWidget(blurb)

        self.search = QLineEdit()
        self.search.setPlaceholderText("輸入標題的幾個字…")
        self.search.setClearButtonEnabled(True)
        layout.addWidget(self.search)

        self.results = QListWidget()
        self.results.itemDoubleClicked.connect(lambda _i: self._add())
        layout.addWidget(self.results, 1)

        self.status = QLabel("")
        self.status.setWordWrap(True)
        self.status.setStyleSheet(f"color:{palette['faint']};font-size:12px;")
        layout.addWidget(self.status)

        buttons = QHBoxLayout()
        self.go = QPushButton("加入佇列")
        self.go.setStyleSheet(
            f"background:{palette['accent']};color:#ffffff;"
            f"border:1px solid {palette['accent']};padding:7px 16px;font-weight:600;"
        )
        self.go.clicked.connect(self._add)
        buttons.addWidget(self.go)
        close = QPushButton("關閉")
        close.clicked.connect(self.reject)
        buttons.addWidget(close)
        buttons.addStretch(1)
        layout.addLayout(buttons)

        # Same reason as the queue screen: a keystroke should not cost a query over
        # 63,000 rows while the next keystroke is already on its way.
        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(160)
        self._debounce.timeout.connect(self._refresh)
        self.search.textChanged.connect(lambda _t: self._debounce.start())

    def _refresh(self) -> None:
        text = self.search.text().strip()
        self.results.clear()
        if len(text) < 3:
            return
        with connect() as conn:
            rows = search_papers(conn, text, 60)
        for r in rows:
            award = f" · {r['award']}" if r["award"] else ""
            where = {"read": "讀過", "delivered": "已送出", "pending": "已在佇列",
                     "skipped": "已移除"}.get(r["state"] or "", "不在佇列")
            item = QListWidgetItem(
                f"{r['venue']} {r['year']}{award}  ·  {where}\n{r['title']}"
            )
            item.setData(Qt.ItemDataRole.UserRole, r["id"])
            self.results.addItem(item)
        self.status.setText(f"{len(rows)} 筆符合")

    def _add(self) -> None:
        item = self.results.currentItem()
        if item is None:
            self.status.setText("先選一篇。")
            return
        from paper_daily import queue as qmod

        paper_id = item.data(Qt.ItemDataRole.UserRole)
        with connect() as conn:
            qmod.add(conn, paper_id, reason="你自己加進來的")
        self.added = paper_id
        self.accept()


class AddToListDialog(QDialog):
    """Resolve a citation and append it to a reading list."""

    def __init__(
        self, palette: dict[str, str], list_id: str, list_name: str, repo_root: Path, parent=None
    ) -> None:
        super().__init__(parent)
        self.pal = palette
        self.list_id = list_id
        self.repo_root = repo_root
        from paper_daily.desktop.window_workspace import WindowWorkspace

        self._workspace_owner = WindowWorkspace.capture()
        self.process: QProcess | None = None
        self._temp: Path | None = None
        self.added = False

        self.setWindowTitle("加入清單")
        self.resize(760, 460)
        _style(self, palette)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(10)

        heading = QLabel(f"加一篇到「{list_name}」")
        heading.setStyleSheet(f"color:{palette['ink']};font-size:17px;font-weight:600;")
        layout.addWidget(heading)

        blurb = QLabel(
            "貼一整筆參考文獻,或只打標題都可以。會送去 Semantic Scholar 對作者、"
            "摘要與引用數,再找原文 PDF。已經在清單裡的不會重複加,也不會被搬到最後面。"
        )
        blurb.setWordWrap(True)
        blurb.setStyleSheet(f"color:{palette['muted']};font-size:12px;")
        layout.addWidget(blurb)

        self.body = QPlainTextEdit()
        self.body.setPlaceholderText(
            "例如:\n\nGPTQ: Accurate post-training quantization for generative "
            "pre-trained transformers"
        )
        layout.addWidget(self.body, 1)

        self.status = QLabel("")
        self.status.setWordWrap(True)
        self.status.setStyleSheet(f"color:{palette['faint']};font-size:12px;")
        layout.addWidget(self.status)

        buttons = QHBoxLayout()
        self.go = QPushButton("加入")
        self.go.setStyleSheet(
            f"background:{palette['accent']};color:#ffffff;"
            f"border:1px solid {palette['accent']};padding:7px 16px;font-weight:600;"
        )
        self.go.clicked.connect(self._start)
        buttons.addWidget(self.go)
        self.close_btn = QPushButton("關閉")
        self.close_btn.clicked.connect(self.reject)
        buttons.addWidget(self.close_btn)
        buttons.addStretch(1)
        layout.addLayout(buttons)

    def _start(self) -> None:
        from paper_daily.desktop.ai_access import requires_ai

        requires_ai("list_parse")(type(self)._start_ready)(self)

    def _start_ready(self) -> None:
        if not self._workspace_owner.current():
            self.status.setText("The workspace changed; reopen the original list.")
            return
        with connect() as conn:
            exists = conn.execute("SELECT 1 FROM lists WHERE id=?", (self.list_id,)).fetchone()
        if not exists:
            self.status.setText("This list is no longer available. Your draft remains here.")
            return
        raw = self.body.toPlainText().strip()
        if len(raw) < 8:
            self.status.setText("標題太短了,再多打幾個字。")
            return
        if self.process is not None:
            return

        # Through a file, like the import dialog: a pasted citation can carry quotes
        # and newlines that have no business on a command line.
        with tempfile.NamedTemporaryFile(
            "w", suffix=".txt", delete=False, encoding="utf-8"
        ) as handle:
            handle.write(raw)
            self._temp = Path(handle.name)

        from paper_daily.desktop.activity import begin, process_environment

        self._activity = begin(self, "新增論文", key=f"list-add:{self.list_id}")
        if not self._activity.accepted:
            self._clear_temp()
            return
        self._activity_pending = ""
        self.go.setEnabled(False)
        self.status.setText("正在比對,並找程式碼和資料集…幾秒鐘。")
        self.process = job = QProcess(self)
        process_environment(job)
        environment = job.processEnvironment()
        environment.insert("PAPERFACT_DATA", str(self._workspace_owner.database.parent))
        job.setProcessEnvironment(environment)
        job.setWorkingDirectory(str(self.repo_root))
        job.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        job.readyReadStandardOutput.connect(lambda: self._progress(expected=job))
        job.finished.connect(lambda code, status: self._finished(code, status, expected=job))
        job.errorOccurred.connect(lambda error: self._error(error, expected=job))
        from paper_daily.desktop.cli_job import prepare

        try:
            program, *rest = prepare(
                job, ["list-add", self.list_id, "--file", str(self._temp)], ("list_parse",),
            )
        except (OSError, ValueError):
            self._error(QProcess.ProcessError.FailedToStart, expected=job)
            return
        job.start(program, rest)

    def _progress(self, *, expected=None) -> None:
        if self.process is None or expected is not None and self.process is not expected:
            return
        raw = bytes(self.process.readAllStandardOutput())
        handoff = getattr(self.process, "_ai_job_handoff", None)
        if handoff is not None:
            raw = handoff.filter_output(raw)
        chunk = raw.decode("utf-8", "replace")
        from paper_daily.desktop.activity import consume

        self._activity_pending = consume(self._activity, chunk, self._activity_pending)
        lines = [ln.strip() for ln in chunk.splitlines()
                 if ln.strip() and not ln.startswith("@paperfact-progress ")]
        if lines:
            self.status.setText(lines[-1][:160])

    def _finished(self, code: int, _status, *, expected=None) -> None:
        if self.process is None or expected is not None and self.process is not expected:
            return
        self._progress(expected=self.process)
        handoff = getattr(self.process, "_ai_job_handoff", None)
        if handoff is not None:
            code = handoff.complete(code)
        self._activity.finish(code == 0, cancelled=code < 0)
        self.go.setEnabled(True)
        if self.process is not None:
            self.process.deleteLater()
        self.process = None
        self._clear_temp()
        if not self._workspace_owner.current():
            self.status.setText("The workspace changed; reopen the original list.")
            return
        if code == 0:
            self.added = True
            self.accept()
        else:
            self.status.setText(
                f"沒有加進去(exit {code})。上面那行是最後的輸出。"
                "若提到登入,跑一次 paperfact doctor。"
            )

    def _clear_temp(self):
        if self._temp:
            Path(self._temp).unlink(missing_ok=True)
            self._temp = None

    def _error(self, error, *, expected=None):
        if expected is not None and self.process is not expected:
            return
        if error == QProcess.ProcessError.FailedToStart and self.process is not None:
            self.process.deleteLater()
            self.process = None
            self._activity.finish(False)
            self._clear_temp()
            self.go.setEnabled(True)
            self.status.setText("無法啟動新增論文工作；輸入已保留，可重試。")

    def _cancel_pending(self) -> None:
        job, self.process = self.process, None
        if job is not None:
            self._activity.finish(cancelled=True)
            handoff = getattr(job, "_ai_job_handoff", None)
            job.finished.connect(job.deleteLater)
            if handoff is not None:
                handoff.cancel()
            if job.state() == QProcess.ProcessState.NotRunning:
                job.deleteLater()
            else:
                job.kill()
        self._clear_temp()

    def reject(self) -> None:
        self._cancel_pending()
        super().reject()

    def closeEvent(self, event) -> None:
        self._cancel_pending()
        super().closeEvent(event)


def run_add(window) -> bool:
    """Show the right dialog for whatever the window is showing. True if anything changed."""
    pal = window.pal
    repo_root = runtime.bundle_root()
    if window.active_list:
        name = window.list_picker.currentText().rsplit(" (", 1)[0]
        dialog = AddToListDialog(pal, window.active_list, name, repo_root, window)
        dialog.setWindowModality(Qt.WindowModality.WindowModal)
        dialog.exec()
        return dialog.added
    dialog = AddToQueueDialog(pal, window)
    dialog.setWindowModality(Qt.WindowModality.WindowModal)
    dialog.exec()
    return dialog.added is not None


__all__ = ["AddToListDialog", "AddToQueueDialog", "run_add"]
