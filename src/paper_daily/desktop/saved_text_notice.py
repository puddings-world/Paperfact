"""Non-disruptive saved-text updates using the window's owned revision worker."""

import sqlite3
from contextlib import closing
from pathlib import Path

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QFrame, QHBoxLayout, QLabel, QPushButton

from paper_daily import reading_change_inputs as inputs
from paper_daily import store
from paper_daily.audit_inputs import _connect
from paper_daily.desktop.window_workspace import current_for

TEXT = {
    "en": {
        "updated": "Saved {features} changed. Your original and drafts stay open.",
        "load": "Load saved updates",
        "later": "Later",
        "failed": "Updates were not loaded. Your drafts are retained; retry.",
        "changed": "Paper or workspace changed. Reopen it to load saved updates.",
        "notes": "notes",
        "chat": "Q&A",
        "dive": "explanations",
    },
    "zh-TW": {
        "updated": "已存{features}有更新；原文與草稿維持開啟。",
        "load": "載入已存更新",
        "later": "稍後",
        "failed": "更新未載入；草稿已保留，可重試。",
        "changed": "論文或工作區已變更，請重新開啟後載入更新。",
        "notes": "筆記",
        "chat": "問答",
        "dive": "講解"
    },
}


class SavedTextNotice(QFrame):
    def __init__(self, reader, *, language="zh-TW"):
        super().__init__(reader)
        self.reader = reader
        self.t = TEXT.get(language, TEXT["en"])
        self._owner = self._watcher = self._token = None
        self._baseline, self._latest, self._dismissed = {}, {}, {}
        self._sequence = 0
        self.setObjectName("savedTextUpdates")
        p = reader.win.pal
        self.setStyleSheet(f"""
            QFrame#savedTextUpdates {{background:{p["accentSoft"]};}}
            QLabel {{color:{p["ink"]};background:transparent;}}
            QPushButton {{color:{p["ink"]};background:{p["surface"]};
                border:1px solid {p["firm"]};border-radius:6px;padding:5px 10px;}}
            QPushButton:hover {{border-color:{p["accent"]};}}
            QPushButton:pressed {{background:{p["sunk"]};}}
            QPushButton:focus {{border:2px solid {p["accent"]};}}
            QPushButton:disabled {{color:{p["faint"]};border-color:{p["border"]};}}
        """)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 8, 16, 8)
        layout.setSpacing(8)
        self.label = QLabel()
        self.label.setWordWrap(True)
        layout.addWidget(self.label, 1)
        self.reload = QPushButton(self.t["load"])
        self.reload.setAutoDefault(False)
        self.reload.clicked.connect(self.load_updates)
        layout.addWidget(self.reload)
        self.later = QPushButton(self.t["later"])
        self.later.setAutoDefault(False)
        self.later.clicked.connect(self.dismiss)
        layout.addWidget(self.later)
        self.timer = QTimer(self)
        self.timer.setInterval(250)
        self.timer.timeout.connect(self._controls)
        self.hide()

    def set_watcher(self, watcher):
        if self._watcher is watcher:
            return
        if self._watcher is not None:
            self._watcher.research.disconnect(self.observe)
            self._watcher.watch_research(None)
        self._watcher = watcher
        watcher.research.connect(self.observe)
        if self._owner is not None:
            watcher.watch_research(self._owner, self._token)

    def reset(self):
        self._sequence += 1
        self._owner = self._token = None
        self._baseline, self._latest, self._dismissed = {}, {}, {}
        if self._watcher is not None:
            self._watcher.watch_research(None)
        self.timer.stop()
        self.hide()

    def bind(self, owner):
        self.reset()
        self._owner = owner
        self._token = (id(self), self._sequence, self.reader._qa_epoch)
        if self._watcher is not None:
            self._watcher.watch_research(owner, self._token)

    def _same(self):
        owner, reader = self._owner, self.reader
        return bool(
            owner is not None
            and self._token is not None
            and reader._qa_epoch == self._token[2]
            and getattr(reader, "_highlight_owner", None) is owner
            and getattr(getattr(reader, "paper", None), "id", None) == owner.paper_id
            and Path(store.DB_PATH).resolve() == owner.database
            and current_for(reader.win)
        )

    def accept_notes(self, rows):
        if self._same():
            self._baseline["notes"] = inputs.notes(rows)
            self._render()

    def accept_snapshot(self, snapshot, targets):
        if self._same():
            self._baseline.update(inputs.snapshot(snapshot, targets))
            self._render()

    def observe(self, value):
        if (
            not self._same()
            or value["token"] != self._token
            or value["paper_id"] != self._owner.paper_id
        ):
            return
        self._latest = dict(value["signatures"])
        self._render()

    def _pending(self):
        return [
            key
            for key, baseline in self._baseline.items()
            if key in self._latest
            and baseline != self._latest[key]
            and self._dismissed.get(key) != self._latest[key]
        ]

    def _render(self):
        pending = self._pending()
        if not self._same() or not pending:
            self.timer.stop()
            self.hide()
            return
        self.label.setText(
            self.t["updated"].format(features=" / ".join(self.t[key] for key in pending))
        )
        self.show()
        self.timer.start()
        self._controls()

    def _blocked(self):
        if QApplication.activeModalWidget() is not None:
            return True
        return any(
            getattr(getattr(self.reader, key, None), "busy", False)
            for key in ("preparation", "runner", "key_runner", "refine_runner", "_claims_work")
        )

    def _controls(self):
        self.reload.setEnabled(self._same() and not self._blocked() and bool(self._pending()))

    def dismiss(self):
        self._dismissed.update({key: self._latest[key] for key in self._pending()})
        self._render()

    def load_updates(self):
        if not self._same() or self._blocked() or not self._pending():
            return False
        try:
            with closing(_connect(self._owner.database)) as conn:
                conn.execute("BEGIN")
                self._owner.check(conn)
            self.reload.setEnabled(False)
            self.reader._load_notes()
            self.reader._load_dive()
            self.reader._load_chat()
        except (OSError, ValueError, sqlite3.Error):
            self.label.setText(self.t["failed"] if self._same() else self.t["changed"])
            self._controls()
            return False
        self._controls()
        return True
