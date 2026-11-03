"""Start with the app; refresh only changed accounts and expired snapshots.

Each look reads the AI settings and every account, on the window's thread. It runs
when the window is brought forward and every 15 s while it stays in front; a window
in the background does none of it. The 2-second poll it replaced kept doing that
work all day, and it was one of the things that made a long-open window slow.
"""

from PySide6.QtCore import QEvent, QObject, QTimer

from paper_daily import ai_choices, llm, usage_cache

ACTIVE_SECONDS = 15


class UsageMonitor(QObject):
    def __init__(self, parent):
        super().__init__(parent)
        self._model_label = None
        self.timer = QTimer(self)
        self.timer.setInterval(ACTIVE_SECONDS * 1000)
        self.timer.timeout.connect(self.tick)
        if parent is not None:
            parent.installEventFilter(self)
            if parent.isActiveWindow():
                self.timer.start()
        QTimer.singleShot(0, self.tick)

    def eventFilter(self, watched, event):
        if event.type() == QEvent.Type.WindowActivate:
            self.tick()
            self.timer.start()
        elif event.type() == QEvent.Type.WindowDeactivate:
            self.timer.stop()
        return False

    def tick(self):
        try:
            self._refresh()
        except (OSError, ValueError):
            # The settings entry offers recovery; background polling must not
            # repeatedly surface errors or prevent opening that recovery view.
            return

    def _refresh(self):
        accounts = {ai_choices.account_key(cfg): cfg for cfg in ai_choices.accounts()}
        # Users can browse an existing terminal login before saving a Paperfact
        # profile. Those accounts need the same startup prefetch as saved profiles.
        for backend in ai_choices.LABELS:
            for cfg in ai_choices.choices(backend):
                accounts.setdefault(ai_choices.account_key(cfg), cfg)
        for cfg in accounts.values():
            if cfg.backend in ai_choices.LABELS:
                usage_cache.cache.refresh_background(cfg)
        label = ai_choices.connection_label(llm.settings())
        if label != self._model_label:
            self._model_label = label
            button = getattr(self.parent(), "ai_picker", None)
            if button is not None:
                button.refresh()
