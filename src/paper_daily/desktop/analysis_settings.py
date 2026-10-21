"""分析排程: the settings for the nightly 深入分析, and the note that it finished.

The note sits above the page rather than in a dialog: it arrives while something
else may be on screen, and it should be dismissable with a glance, not a click
that interrupts reading.
"""

from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
)

from paper_daily import analysis_schedule
from paper_daily.store import connect, get_kv, set_kv

# The window's own top-up while it is open (MainWindow.top_up_dives), opt-in.
IDLE_KEY = "ui.background_analysis"


class AnalysisSettings(QDialog):
    def __init__(self, parent, palette: dict[str, str]):
        super().__init__(parent)
        self.setWindowTitle("分析排程")
        self.setMinimumWidth(460)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 16)
        layout.setSpacing(12)
        lead = QLabel(
            "每晚 00:00 的排程會對接下來要讀的論文做深入分析：深度講解與逐節精讀、"
            "原文重點，以及承先（參考文獻）與啟後（後續研究）。這裡決定多久做一次、一次做幾篇。"
        )
        lead.setWordWrap(True)
        lead.setStyleSheet(f"color:{palette['muted']};font-size:12px;")
        layout.addWidget(lead)

        form = QFormLayout()
        form.setSpacing(10)
        self.every = QComboBox()
        for days, label in analysis_schedule.EVERY.items():
            self.every.addItem(label, days)
        form.addRow("多久分析一次", self.every)
        self.lists = QSpinBox()
        self.lists.setRange(0, analysis_schedule.MAX_PAPERS)
        self.lists.setSuffix(" 篇")
        form.addRow("所有清單合計，每次最多", self.lists)
        self.notify = QCheckBox("分析完成後，在視窗上方提醒我有哪些論文可以讀")
        form.addRow("", self.notify)
        self.idle = QCheckBox("App 開著時，先分析目前清單接下來 3 篇")
        self.idle.setToolTip("打開或讀完一篇時補上；會用掉 AI 額度，所以預設關閉。")
        form.addRow("", self.idle)
        layout.addLayout(form)

        self.preview = QLabel()
        self.preview.setWordWrap(True)
        self.preview.setStyleSheet(
            f"background:{palette['accentSoft']};color:{palette['ink']};"
            f"padding:8px 10px;border-radius:4px;font-size:12px;"
        )
        layout.addWidget(self.preview)
        cost = QLabel("每篇大約 3–6 分鐘，會用到目前「深入分析」所選的 AI。")
        cost.setStyleSheet(f"color:{palette['faint']};font-size:11px;")
        layout.addWidget(cost)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Save).setText("儲存")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        with connect() as conn:
            settings = analysis_schedule.load(conn)
            self._last_run = get_kv(conn, analysis_schedule.LAST_RUN)
            idle = get_kv(conn, IDLE_KEY) == "1"
        self.every.setCurrentIndex(self.every.findData(settings["every"]))
        self.lists.setValue(settings["lists"])
        self.notify.setChecked(settings["notify"])
        self.idle.setChecked(idle)
        self.every.currentIndexChanged.connect(self._update)
        self.lists.valueChanged.connect(self._update)
        self._update()

    def settings(self) -> dict:
        return {
            "every": self.every.currentData(),
            "queue": 0,
            "lists": self.lists.value(),
            "notify": self.notify.isChecked(),
        }

    def _update(self) -> None:
        manual = not self.every.currentData()
        self.lists.setEnabled(not manual)
        self.preview.setText(
            analysis_schedule.describe(self.settings(), self._last_run, datetime.now().date())
        )

    def accept(self) -> None:
        with connect() as conn:
            analysis_schedule.save(conn, self.settings())
            set_kv(conn, IDLE_KEY, "1" if self.idle.isChecked() else "0")
        super().accept()


class ReadyBanner(QFrame):
    """「已深入分析 3 篇，可以讀了」 with the titles, a way in, and a dismiss."""

    open_paper = Signal(str)

    def __init__(self, palette: dict[str, str]):
        super().__init__()
        self.ids: list[str] = []
        self.setObjectName("readyBanner")
        self.setStyleSheet(
            f"#readyBanner{{background:{palette['aiSoft']};"
            f"border-bottom:1px solid {palette['ai']};}}"
        )
        row = QHBoxLayout(self)
        row.setContentsMargins(16, 6, 12, 6)
        row.setSpacing(10)
        self.label = QLabel()
        self.label.setWordWrap(True)
        self.label.setTextFormat(Qt.TextFormat.PlainText)
        self.label.setStyleSheet(f"color:{palette['ink']};font-size:12px;")
        row.addWidget(self.label, 1)
        self.read = QPushButton("開始讀")
        self.read.setStyleSheet(
            f"QPushButton{{background:{palette['ai']};color:{palette['onAi']};"
            f"border:1px solid {palette['ai']};border-radius:4px;padding:4px 12px;"
            f"font-weight:600;}}"
        )
        self.read.clicked.connect(self._read)
        row.addWidget(self.read)
        self.dismiss = QPushButton("知道了")
        self.dismiss.clicked.connect(self._dismiss)
        row.addWidget(self.dismiss)
        self.hide()

    def show_batch(self, ids: list[str], titles: dict[str, str]) -> None:
        self.ids = ids
        names = "、".join(f"《{titles.get(pid, pid)[:48]}》" for pid in ids[:3])
        more = f"等 {len(ids)} 篇" if len(ids) > 3 else ""
        self.label.setText(f"已深入分析 {len(ids)} 篇，可以讀了：{names}{more}")
        self.show()

    def _read(self) -> None:
        first = self.ids[0] if self.ids else None
        self._dismiss()
        if first:
            self.open_paper.emit(first)

    def _dismiss(self) -> None:
        with connect() as conn:
            analysis_schedule.mark_seen(conn)
        self.hide()
