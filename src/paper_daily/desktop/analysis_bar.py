"""深入分析: what the AI has made for the paper on screen, and the button that makes
the rest.

The deep dive, the reading of each reference (承先) and the field's later work with
the research context (啟後) belong together -- the nightly job makes them as one unit
(analyze.py) -- so the reader offers them as one action too, beside the tabs they
fill. While a job runs the bar watches the database and says which tabs have just
been filled, so the reader can redraw them without being reopened.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QWidget

from paper_daily import analyze, store
from paper_daily.desktop import ai_style, analysis_status

# The parts the tabs show, named after the tabs; the PDF and the marked passages
# are listed in the tooltip, where the detail belongs.
SHOWN = (("dive", "講解"), ("cites", "承先"), ("later", "啟後"))

EXPLAIN = (
    "一次做完這篇缺的部分：下載原文、深度講解與逐節精讀、原文重點標註、"
    "參考文獻分析（承先：每一筆為什麼被引用、值不值得讀）、"
    "後續研究與研究脈絡（啟後：整個領域誰引用它、拿它做了什麼）。"
    "講解和引用分析同時進行，大約三到六分鐘；已經有的部分不會重做。"
)


def describe(
    state: dict[str, bool], running: bool, failures: dict[str, str],
    *, later_outcome: str | None = None, later_query_label: str | None = None,
) -> dict[str, object]:
    """What the bar says for a paper: the chips, the button (None for none) and
    whether the button is the one the view is waiting on."""
    empty = (later_outcome == "queried_no_judged_inputs"
             and not state.get("later") and not failures.get("later"))
    chips = []
    for step, name in SHOWN:
        if step == "later" and empty:
            chips.append(("todo", f"{name}: 已查詢，尚無可整理資料"))
        elif state.get(step):
            chips.append(("done", f"{name} ✓"))
        elif running:
            chips.append(("busy", f"{name} …"))
        elif failures.get(step):
            chips.append(("warn", f"{name} ✗"))
        else:
            chips.append(("todo", name))
    complete = all(state.get(step) or (step == "later" and empty) for step, _ in SHOWN)
    tip = [f"{analyze.STEPS[s]}：{'已完成' if ok else failures.get(s) or '尚未'}"
           for s, ok in state.items()]
    if empty:
        tip = [line for step, line in zip(state, tip, strict=True) if step != "later"]
        tip.append(
            "啟後：已查詢，尚無可整理的已判讀資料。"
            " No overview generated: no judged references or later work in the current inputs."
        )
    if empty and later_query_label:
        tip.append(later_query_label)
    if complete and empty and not running:
        return {"lead": "可用項目已處理", "chips": chips, "button": None,
                "primary": False, "tip": "\n".join(tip)}
    if running:
        return {"lead": "深入分析中", "chips": chips, "button": "停止",
                "primary": False, "tip": "\n".join(tip)}
    if complete:
        return {"lead": "已深入分析", "chips": chips, "button": None,
                "primary": False, "tip": "\n".join(tip)}
    return {"lead": "", "chips": chips,
            "button": "重試深入分析" if any(failures.values()) else "深入分析",
            "primary": True, "tip": EXPLAIN + "\n\n" + "\n".join(tip)}


class AnalysisBar(QWidget):
    landed = Signal(list)   # steps that became complete since the last look
    finished = Signal()     # the job for this paper ended, done or not

    def __init__(self, window, palette: dict[str, str], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.win = window
        self.pal = palette
        self.paper_id: str | None = None
        self._state: dict[str, bool] = {}
        self._was_running = False
        self._epoch = 0
        self._status_worker = analysis_status.LatestStatus(self)
        self._status_worker.failed.connect(self.label_error)
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 2, 8, 2)
        row.setSpacing(8)
        self.label = QLabel()
        self.label.setTextFormat(Qt.TextFormat.RichText)
        self.label.setStyleSheet("font-size:12px;background:transparent;")
        row.addWidget(self.label)
        self.button = QPushButton()
        self.button.clicked.connect(self._pressed)
        row.addWidget(self.button)
        self._poll = QTimer(self)
        self._poll.setInterval(2000)
        self._poll.timeout.connect(self.refresh)
        self._render(describe({}, False, {}))

    def show_paper(self, paper_id: str) -> None:
        self._epoch += 1
        self._status_worker.cancel()
        self.paper_id = paper_id
        self._state = {}
        self._was_running = False
        self._render(describe({}, bool(self.win.analysis_running(paper_id)), {}))
        self.refresh()

    def hideEvent(self, event):
        self._status_worker.cancel()
        self._poll.stop()
        super().hideEvent(event)

    def showEvent(self, event):
        super().showEvent(event)
        if self.paper_id:
            self.refresh()

    def _pressed(self) -> None:
        if not self.paper_id:
            return
        if self.win.analysis_running(self.paper_id):
            self.win.stop_analysis()
        else:
            self.win.analyse_now(self.paper_id)
        self.refresh()

    def refresh(self) -> None:
        if not self.paper_id:
            return
        try:
            scope = analysis_status.capture(store.DB_PATH, self.paper_id)
        except (OSError, ValueError, RuntimeError, sqlite3.Error):
            self.label_error("Saved analysis could not be checked; please retry")
            return
        epoch = self._epoch
        visible = self.isVisible()
        self.label.setToolTip("Checking saved analysis...")

        def apply(result):
            if result is None or self._epoch != epoch or self.paper_id != scope[1]:
                return
            if Path(store.DB_PATH).resolve() != Path(scope[0]) or visible and not self.isVisible():
                return
            try:
                if analysis_status.capture(store.DB_PATH, self.paper_id) != scope:
                    return
            except (OSError, ValueError, RuntimeError, sqlite3.Error):
                return
            self._apply_status(*result)

        self._status_worker.run((scope, epoch), lambda: analysis_status.read(scope), apply)

    def label_error(self, message):
        self.label.setToolTip(message)

    def _apply_status(self, state, failures, later_outcome=None):
        mine = self.win.analysis_running(self.paper_id)
        activity = getattr(self.win, "_analysis_activity", None)
        if mine and activity is not None:
            activity.update(dict(completed=sum(bool(v) for v in state.values()),
                                 total=len(state), paper_id=self.paper_id))
        # Idle work on the papers ahead can include this one, so any job is watched.
        busy = self.win.analysis_running()
        new = [s for s, ok in state.items() if ok and self._state and not self._state.get(s)]
        self._state = state
        from paper_daily.desktop.later_outcome_status import PreparedEmptyStatus

        checked = (later_outcome if isinstance(later_outcome, PreparedEmptyStatus)
                   and later_outcome.unchanged() else None)
        self._render(describe(state, mine, failures,
                              later_outcome=checked.state if checked else None,
                              later_query_label=checked.query_label if checked else None))
        if new:
            self.landed.emit(new)
        if busy and not self._poll.isActive():
            self._poll.start()
        elif not busy:
            self._poll.stop()
        if self._was_running and not mine:
            self.finished.emit()
        self._was_running = mine

    def _render(self, view: dict) -> None:
        pal = self.pal
        colour = {"done": pal["done"], "busy": pal["ai"], "warn": pal["warn"], "todo": pal["faint"]}
        chips = "&nbsp;&nbsp;".join(
            f"<span style='color:{colour[kind]};'>{text}</span>" for kind, text in view["chips"]
        )
        lead = f"<span style='color:{pal['muted']};'>{view['lead']}</span>&nbsp;&nbsp;" \
            if view["lead"] else ""
        self.label.setText(lead + chips)
        self.label.setToolTip(view["tip"])
        if view["button"] is None:
            self.button.hide()
            return
        self.button.setText(view["button"])
        self.button.setToolTip(view["tip"])
        if view["button"] == "停止":
            self.button.setIcon(ai_style.spark(pal["faint"]))
            self.button.setStyleSheet(
                f"QPushButton{{background:{pal['surface']};color:{pal['ink']};"
                f"border:1px solid {pal['firm']};border-radius:4px;padding:4px 11px;"
                f"font-size:12px;}}"
            )
        else:
            ai_style.mark(self.button, pal, primary=view["primary"])
        self.button.show()
