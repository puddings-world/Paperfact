"""One login gate for desktop model calls and subprocess workflows."""

import time
from functools import wraps

from PySide6.QtCore import QObject, QTimer, Signal, Slot
from shiboken6 import isValid

from paper_daily import ai_accounts, ai_choices, llm
from paper_daily.desktop.ask import AskRunner

_bridge = None
ANALYSIS_TASKS = ("dive", "paper_highlights", "citations", "followups", "overview", "ask")


def readiness(cfg):
    if cfg.backend in ai_choices.LABELS:
        answer, reason = ai_accounts.auth(cfg, "status")
        if answer:
            ai_choices.remember_identity(cfg, answer)
            return ""
        return reason
    if cfg.backend == "none":
        return "尚未選擇 AI 服務，請先登入 Claude、Codex 或 Gemini。"
    if cfg.requires_key and not cfg.api_key:
        return "此 API 連線尚未設定金鑰；也可以改用已登入的 AI 帳號。"
    return ""


def _scope(owner):
    paper = getattr(owner, "paper", None)
    return (
        getattr(owner, "paper_id", None),
        getattr(paper, "id", None),
        getattr(owner, "active_list", getattr(getattr(owner, "win", None), "active_list", None)),
    )


class AccessBridge(QObject):
    needed = Signal(str, str)

    def __init__(self, parent):
        super().__init__(parent)
        self.runner = AskRunner(self)
        self.runner.activity_label = "檢查 AI 登入"
        self.good = {}
        self.dialog = None
        self._queue = []
        self._current = None
        self.needed.connect(self.show_login)

    def check(self, cfg, task):
        key = (ai_choices.account_key(cfg), cfg.cli_home, cfg.api_key)
        if self.good.get(key, 0) > time.monotonic():
            return ""
        reason = readiness(cfg)
        if reason:
            self.needed.emit(task, reason)
            return "請先完成 AI 登入，再重新執行此功能。"
        self.good[key] = time.monotonic() + 30
        return ""

    @Slot(str, str)
    def show_login(self, task, reason):
        if self.dialog is not None:
            self.dialog.raise_()
            return
        from paper_daily.desktop.ai_dialog import TASK_LABELS
        from paper_daily.desktop.ai_picker import AIPickerDialog

        self.dialog = AIPickerDialog(self.parent(), task=task)
        self.dialog.setWindowTitle("需要 AI 登入 · " + TASK_LABELS.get(task, task))
        self.dialog.notice.setText(reason + "\n登入並選好模型後，回原功能再按一次即可。")

        def closed(_):
            self.good.clear()
            dialog, self.dialog = self.dialog, None
            dialog.deleteLater()
            refresh = getattr(self.parent(), "_refresh_ai_summary", None)
            if refresh:
                refresh(check=True)

        self.dialog.finished.connect(closed)
        self.dialog.open()

    def run(self, owner, tasks, callback):
        key = (id(owner), tuple(tasks))
        if self._current is not None and not self.runner.busy:
            # The runner was stopped (window closing) without delivering a result.
            self._current = None
        # Another feature's request waits for the running check instead of being
        # dropped; a repeated click of the same feature is the only thing ignored.
        if key != self._current and all(key != queued[0] for queued in self._queue):
            scope = _scope(owner)
            was_visible = owner.isVisible() if hasattr(owner, "isVisible") else False
            self._queue.append((key, owner, tasks, callback, scope, was_visible))
        self._drain()

    def _drain(self):
        if self._current is not None or not self._queue:
            return
        if self.runner.busy:
            QTimer.singleShot(20, self, self._drain)
            return
        key, owner, tasks, callback, scope, was_visible = self._queue.pop(0)
        self._current = key

        def call(_):
            for task in tasks:
                reason = self.check(llm.settings(task=task), task)
                if reason:
                    return None, reason
            return "ready", "ok"

        def finished():
            self._current = None
            self._drain()

        def done(_):
            finished()
            if isValid(owner) and _scope(owner) == scope and (not was_visible or owner.isVisible()):
                callback()

        self.runner.start("", done, lambda _reason: finished(), call=call)


def install(parent):
    global _bridge
    _bridge = AccessBridge(parent)
    llm.ACCESS_CHECK = _bridge.check
    return _bridge


def requires_ai(*tasks):
    def decorate(method):
        @wraps(method)
        def wrapped(owner, *args, **kwargs):
            if _bridge is None:
                return method(owner, *args, **kwargs)
            _bridge.run(owner, tasks, lambda: method(owner, *args, **kwargs))

        return wrapped

    return decorate


def login(parent, task, reason):
    if _bridge is not None:
        _bridge.show_login(task, reason)
