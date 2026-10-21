"""Account checks never run on the UI thread or trigger model generation."""

import queue
import threading

from PySide6.QtCore import QObject, QTimer

from paper_daily import ai_accounts, ai_choices


class AccountStatus(QObject):
    def __init__(self, parent, changed):
        super().__init__(parent)
        self.changed = changed
        self.results = queue.Queue()
        self.pending = set()
        self.timer = QTimer(self)
        self.timer.setInterval(100)
        self.timer.timeout.connect(self.poll)

    def check(self, configs):
        for cfg in configs:
            key = ai_choices.account_key(cfg)
            if cfg.backend not in ai_choices.LABELS or key in self.pending:
                continue
            self.pending.add(key)

            def work(cfg=cfg):
                try:
                    answer, reason = ai_accounts.auth(cfg, "status")
                    label = answer or reason
                except Exception:
                    label = "帳號暫時無法確認"
                self.results.put((cfg, label))

            threading.Thread(target=work, daemon=True).start()
        if self.pending:
            self.timer.start()

    def poll(self):
        changed = False
        while True:
            try:
                cfg, label = self.results.get_nowait()
            except queue.Empty:
                break
            self.pending.discard(ai_choices.account_key(cfg))
            ai_choices.remember_identity(cfg, label)
            changed = True
        if not self.pending:
            self.timer.stop()
        if changed:
            self.changed()
