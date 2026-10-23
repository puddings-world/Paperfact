"""One stable notice row for slow work, with truthful progress and focus leases."""

import queue
import threading
import time
import weakref
from collections import deque
from dataclasses import dataclass, field
from uuid import uuid4

from PySide6.QtCore import QEvent, QObject, QProcessEnvironment, QSize, Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QAbstractButton,
    QApplication,
    QDialog,
    QHBoxLayout,
    QLabel,
    QMenu,
    QProgressBar,
    QPushButton,
    QStackedLayout,
    QWidget,
)
from shiboken6 import isValid

from paper_daily import work_progress

TASKS = dict(ask="論文問答", translate="翻譯", dive="深入分析", list_parse="建立研究清單",
             citations="引用分析", followups="後續研究", overview="研究脈絡", compare="比較論文",
             survey="清單綜覽", slides="製作簡報", paper_highlights="分析原文重點")
OWNER_LABELS = dict(BundleDialog="研究資料包匯入／匯出", ImportListDialog="建立研究清單",
                    AIPickerDialog="AI 帳號登入", AIAccess="檢查 AI 登入",
                    AIUsageDialog="更新 AI 用量", AIDialog="檢查 AI 連線")


def widget_for(owner):
    while isinstance(owner, QObject) and isValid(owner):
        if isinstance(owner, QWidget):
            return owner
        owner = owner.parent()
    return None


def hub_for(owner):
    while isinstance(owner, QObject) and isValid(owner):
        hub = getattr(owner, "activity_hub", None)
        if hub is not None:
            return hub
        win = getattr(owner, "win", None)
        if win is not None and getattr(win, "activity_hub", None) is not None:
            return win.activity_hub
        owner = owner.parent()
    return None


def begin(owner, label=None, *, task="ask", key=None, result=None, paper_id=None):
    hub = hub_for(owner)
    if hub is None:
        return Handle()
    widget = widget_for(owner)
    label = label or OWNER_LABELS.get(type(widget).__name__, TASKS.get(task, "背景工作"))
    return hub.begin(widget, label, key or f"{id(owner)}:{task}", result, paper_id)


@dataclass
class Job:
    token: str
    key: str
    label: str
    owner: object
    context: tuple
    epoch: int
    result: object = None
    paper_id: str | None = None
    stage: str = "準備資料與啟動工作"
    started: float = field(default_factory=time.monotonic)
    ended: float | None = None
    state: str = "running"
    completed: int | None = None
    total: int | None = None
    warning: bool = False
    history: deque = field(default_factory=lambda: deque(maxlen=12))


class Handle:
    def __init__(self, hub=None, token=None, accepted=True):
        self.hub, self.token, self.accepted = hub, token, accepted

    def update(self, event):
        if self.hub is not None and isValid(self.hub):
            self.hub.events.put((self.token, event))

    def stage(self, text):
        self.update(dict(stage=text))

    def finish(self, ok=True, message=None, *, cancelled=False):
        if self.hub is not None and isValid(self.hub):
            self.hub.finish(self.token, ok, message, cancelled=cancelled)


class ActivityHub(QObject):
    changed = Signal()

    def __init__(self, window):
        super().__init__(window)
        self.window = window
        self.jobs, self.events = {}, queue.Queue()
        self.epoch = 0
        self.selected = None
        self.selected_explicit = False
        self.boards = []
        self._processes = {}
        self._poll = QTimer(self)
        self._poll.setInterval(250)
        self._poll.timeout.connect(self.tick)
        self._poll.start()
        from paper_daily.desktop import window_events

        window_events.watch(self)

    def context(self):
        reader = getattr(self.window, "reader_page", None)
        paper = getattr(reader, "paper", None)
        tabs = getattr(reader, "tabs", None)
        stack = getattr(self.window, "stack", None)
        return (getattr(paper, "id", None), getattr(self.window, "active_list", None),
                tabs.currentIndex() if tabs else None, stack.currentIndex() if stack else None)

    def eventFilter(self, obj, event):
        if (event.type() in (QEvent.Type.MouseButtonPress, QEvent.Type.KeyPress, QEvent.Type.Wheel)
                and not any(isValid(b) and (obj is b or isinstance(obj, QWidget)
                                           and b.isAncestorOf(obj)) for b in self.boards)):
            self.epoch += 1
        return False

    @property
    def busy(self):
        return any(j.state == "running" for j in self.jobs.values())

    def begin(self, owner, label, key, result=None, paper_id=None):
        old = next((j for j in self.jobs.values() if j.key == key and j.state == "running"), None)
        if old:
            self.selected = old.token
            self.changed.emit()
            return Handle(self, old.token, accepted=False)
        token = uuid4().hex
        job = Job(token, key, label, weakref.ref(owner) if owner is not None else lambda: None,
                  self.context(), self.epoch, result, paper_id)
        self.jobs[token] = job
        # Bounded session history; never stored or uploaded.
        for previous in list(self.jobs.values()):
            if len(self.jobs) <= 30:
                break
            if previous.state != "running":
                self.jobs.pop(previous.token)
        self.selected = token
        self.selected_explicit = False
        surface = owner.window() if owner is not None else None
        if (isinstance(surface, QDialog) and hasattr(surface.layout(), "insertWidget")
                and not hasattr(surface, "_activity_board")):
            surface._activity_board = ActivityBoard(self, None, self.window.pal, height=34)
            surface.layout().insertWidget(0, surface._activity_board)
        self.changed.emit()
        # Draw attention immediately, without taking the cursor out of text edits.
        focused = QApplication.focusWidget()
        if isinstance(focused, QAbstractButton):
            boards = [b for b in self.boards if isValid(b) and b.isVisible()]
            if boards:
                boards[-1].setFocus(Qt.FocusReason.OtherFocusReason)
        return Handle(self, token)

    def update(self, token, event):
        job = self.jobs.get(token)
        if job is None or job.state != "running":
            return
        stage = event.get("stage")
        if isinstance(stage, str) and stage.strip():
            job.stage = stage.strip()[:240]
            if not job.history or job.history[-1] != job.stage:
                job.history.append(job.stage)
        done, total = event.get("completed"), event.get("total")
        scope = event.get("paper_id")
        if (type(done) is int and type(total) is int and 0 <= done <= total and total > 0
                and (not scope or scope == job.paper_id)):
            job.completed, job.total = done, total
        job.warning |= event.get("outcome") in ("partial", "error")

    def tick(self):
        if not self.busy and self.events.empty() and not self._processes:
            return
        while not self.events.empty():
            token, event = self.events.get_nowait()
            self.update(token, event)
        for token, process in list(self._processes.items()):
            code = process.poll()
            # Do not finish until the output reader has enqueued the last event.
            if code is not None and getattr(process, "_paperfact_output_done", False):
                self._processes.pop(token)
                self.finish(token, code == 0, cancelled=code < 0)
        self.changed.emit()

    def finish(self, token, ok=True, message=None, *, cancelled=False):
        # Deliver queued stage events before terminal status (including partial failure).
        while not self.events.empty():
            queued_token, event = self.events.get_nowait()
            self.update(queued_token, event)
        job = self.jobs.get(token)
        if job is None or job.state != "running":
            return
        job.state = "cancelled" if cancelled else "error" if not ok else (
            "partial" if job.warning else "done")
        job.ended = time.monotonic()
        job.stage = message or {"done": "內容已更新", "partial": "部分完成，請查看尚缺項目",
                                "error": "未完成，請查看原操作區的原因後重試",
                                "cancelled": "工作已停止"}[job.state]
        self.changed.emit()
        if (ok and not cancelled and self.selected == token and job.epoch == self.epoch
                and job.context == self.context()):
            QTimer.singleShot(0, self, lambda: self.goto(token, automatic=True))

    def goto(self, token, *, automatic=False):
        job = self.jobs.get(token)
        if job is None or (automatic and (
                self.selected != token or job.epoch != self.epoch
                or job.context != self.context())):
            return
        owner = job.owner()
        if owner is not None and not isValid(owner):
            return
        if callable(job.result):
            job.result()
        elif (owner is not None and isValid(owner) and job.context == self.context()
              and owner.isVisible()):
            owner.setFocus(Qt.FocusReason.OtherFocusReason)

    def watch_popen(self, handle, process):
        self._processes[handle.token] = process
        if getattr(process, "stdout", None) is None:
            process._paperfact_output_done = True
            return

        def read():
            try:
                for line in process.stdout:
                    event = work_progress.parse(line.strip())
                    if event:
                        handle.update(event)
            finally:
                process.stdout.close()
                process._paperfact_output_done = True

        threading.Thread(target=read, daemon=True).start()


class ActivityBoard(QWidget):
    def __init__(self, hub, baseline, palette, height=34):
        super().__init__()
        self.hub, self.baseline, self.pal = hub, baseline, palette
        hub.boards.append(self)
        self.setFixedHeight(height)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.stack = QStackedLayout(self)
        self.stack.setContentsMargins(0, 0, 0, 0)
        if baseline is not None:
            self.stack.addWidget(baseline)
        self.running = QWidget()
        row = QHBoxLayout(self.running)
        row.setContentsMargins(16, 3, 16, 1)
        self.text = QLabel()
        self.text.setMinimumWidth(0)
        self.text.setTextFormat(Qt.TextFormat.PlainText)
        from PySide6.QtWidgets import QSizePolicy

        self.text.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        row.addWidget(self.text, 1)
        self.bar = QProgressBar()
        self.bar.setFixedSize(QSize(110, 15))
        row.addWidget(self.bar)
        self.result = QPushButton("查看結果")
        self.result.clicked.connect(self._goto)
        row.addWidget(self.result)
        self.more = QPushButton("工作")
        self.more.clicked.connect(self._menu)
        row.addWidget(self.more)
        self.dismiss = QPushButton("×")
        self.dismiss.setFixedWidth(24)
        self.dismiss.clicked.connect(self._dismiss)
        row.addWidget(self.dismiss)
        self.stack.addWidget(self.running)
        hub.changed.connect(self.refresh)
        self.refresh()

    def job(self):
        selected = self.hub.jobs.get(self.hub.selected)
        active = [j for j in self.hub.jobs.values() if j.state == "running"]
        return selected if selected and (
            selected.state == "running" or self.hub.selected_explicit) else (
            active[-1] if active else selected)

    def refresh(self):
        job = self.job()
        if job is None:
            if self.baseline is not None:
                self.stack.setCurrentWidget(self.baseline)
            else:
                self.hide()
            return
        self.show()
        self.stack.setCurrentWidget(self.running)
        seconds = max(0, int((job.ended or time.monotonic()) - job.started))
        active = job.state == "running"
        pulse = "◐◓◑◒"[int(time.monotonic() * 2) % 4] if active else (
            "✓" if job.state == "done" else "!")
        label = f"{pulse} {job.label} · {job.stage} · {seconds // 60}:{seconds % 60:02d}"
        self.text.setText(label)
        self.text.setToolTip(label + "\n" + "\n".join(job.history))
        self.setAccessibleName(label)
        self.more.setText(f"工作 ({sum(j.state == 'running' for j in self.hub.jobs.values())})")
        self.result.setVisible(not active)
        self.dismiss.setVisible(not active)
        if active and job.total is None:
            self.bar.setRange(0, 0)
        else:
            self.bar.setRange(0, 100)
            percent = int(job.completed * 100 / job.total) if job.total else 0
            self.bar.setValue(100 if job.state == "done" else min(99, percent))
        self.bar.setVisible(active or job.total is not None or job.state == "done")
        self.bar.setToolTip("依實際完成項目計算；不是剩餘時間估計" if job.total else "等待工作回覆")
        color = self.pal["accent"] if active else self.pal["done"] if job.state == "done" else (
            self.pal["warn"])
        self.running.setStyleSheet(f"QWidget{{background:{self.pal['sunk']};}}"
                                   f"QLabel{{color:{color};font-size:12px;}}")

    def _goto(self):
        if job := self.job():
            self.hub.goto(job.token)

    def _dismiss(self):
        self.hub.selected = None
        self.hub.changed.emit()

    def _menu(self):
        menu = QMenu(self)
        for job in reversed(list(self.hub.jobs.values())):
            action = menu.addAction(f"{job.label} · {job.stage}")
            action.triggered.connect(lambda _checked=False, token=job.token: self._select(token))
        menu.exec(self.more.mapToGlobal(self.more.rect().bottomLeft()))

    def _select(self, token):
        self.hub.selected = token
        self.hub.selected_explicit = True
        self.hub.changed.emit()


def process_environment(process):
    env = process.processEnvironment()
    if env.isEmpty():
        env = QProcessEnvironment.systemEnvironment()
    env.insert("PAPERFACT_PROGRESS", "1")
    env.insert("PYTHONUNBUFFERED", "1")
    env.insert("PYTHONIOENCODING", "utf-8")
    process.setProcessEnvironment(env)


def consume(handle, chunk, pending=""):
    lines = (pending + chunk).split("\n")
    for line in lines[:-1]:
        if event := work_progress.parse(line.strip()):
            handle.update(event)
    return lines[-1][-8192:]
