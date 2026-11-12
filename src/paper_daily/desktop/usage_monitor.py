"""Start with the app; refresh only changed accounts and expired snapshots.

Each look reads the AI settings and every account, on the window's thread. It runs
when the window is brought forward and every 15 s while it stays in front; a window
in the background does none of it. The 2-second poll it replaced kept doing that
work all day, and it was one of the things that made a long-open window slow.
"""

from PySide6.QtCore import QEvent, QObject, QTimer

from paper_daily import ai_choices, llm, usage_cache
from paper_daily.desktop.off_thread import OffThread

ACTIVE_SECONDS = 15


class UsageMonitor(QObject):
    def __init__(self, parent):
        super().__init__(parent)
        self._model_label = None
        # Every two seconds the accounts are read back from the settings files and
        # checked for an installed CLI. On the window's thread that was up to two
        # seconds frozen whenever the disk was busy, again and again for as long
        # as the app stayed open.
        self._reads = OffThread(self, lane="usage-monitor")
        self.timer = QTimer(self)
        self.timer.setInterval(ACTIVE_SECONDS * 1000)
        self.timer.timeout.connect(self.tick_in_background)
        if parent is not None:
            parent.installEventFilter(self)
            if parent.isActiveWindow():
                self.timer.start()
        QTimer.singleShot(0, self.tick_in_background)

    def eventFilter(self, watched, event):
        if event.type() == QEvent.Type.WindowActivate:
            self.tick_in_background()
            self.timer.start()
        elif event.type() == QEvent.Type.WindowDeactivate:
            self.timer.stop()
        return False

    def tick(self):
        """One check, waited for here; the timer uses `tick_in_background`."""
        label = self._check()
        if label is not None:
            self._show(label)

    def tick_in_background(self):
        self._reads.run("usage", self._check, self._show)

    def _check(self):
        try:
            return self._refresh()
        except (OSError, ValueError):
            # The settings entry offers recovery; background polling must not
            # repeatedly surface errors or prevent opening that recovery view.
            return None

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
        return ai_choices.connection_label(llm.settings())

    def _show(self, label):
        if label is None or label == self._model_label:
            return
        self._model_label = label
        button = getattr(self.parent(), "ai_picker", None)
        if button is not None:
            button.refresh()
