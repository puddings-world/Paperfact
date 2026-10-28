"""深入分析: what the AI has made for the paper on screen, and the button that makes
the rest.

The deep dive, the reading of each reference (承先) and the field's later work with
the research context (啟後) belong together -- the nightly job makes them as one unit
(analyze.py) -- so the reader offers them as one action too, beside the tabs they
fill. While a job runs the bar watches the database and says which tabs have just
been filled, so the reader can redraw them without being reopened.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QWidget

from paper_daily import analyze
from paper_daily.desktop import ai_style
from paper_daily.desktop.off_thread import OffThread
from paper_daily.store import connect

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
    state: dict[str, bool], running: bool, failures: dict[str, str]
) -> dict[str, object]:
    """What the bar says for a paper: the chips, the button (None for none) and
    whether the button is the one the view is waiting on."""
    chips = []
    for step, name in SHOWN:
        if state.get(step):
            chips.append(("done", f"{name} ✓"))
        elif running:
            chips.append(("busy", f"{name} …"))
        elif failures.get(step):
            chips.append(("warn", f"{name} ✗"))
        else:
            chips.append(("todo", name))
    complete = all(state.get(step) for step, _ in SHOWN)
    tip = [f"{analyze.STEPS[s]}：{'已完成' if ok else failures.get(s) or '尚未'}"
           for s, ok in state.items()]
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
        self._status = OffThread(self)

    def show_paper(self, paper_id: str) -> None:
        self.paper_id = paper_id
        self._state = {}
        self._was_running = False
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
        paper_id = self.paper_id

        def read():
            # Whether the marked passages are current is checked against the whole
            # PDF's text: half a second on the window's thread for a long paper.
            with connect() as conn:
                state = analyze.status(conn, paper_id)
                failures = {s: analyze.failed(conn, paper_id, s) or "" for s in state}
            return state, failures

        self._status.run("status", read, lambda found: self._show(paper_id, *found))

    def _show(self, paper_id: str, state: dict, failures: dict) -> None:
        if paper_id != self.paper_id:
            return
        mine = self.win.analysis_running(self.paper_id)
        activity = getattr(self.win, "_analysis_activity", None)
        if mine and activity is not None:
            activity.update(dict(completed=sum(bool(v) for v in state.values()),
                                 total=len(state), paper_id=self.paper_id))
        # Idle work on the papers ahead can include this one, so any job is watched.
        busy = self.win.analysis_running()
        new = [s for s, ok in state.items() if ok and self._state and not self._state.get(s)]
        self._state = state
        self._render(describe(state, mine, failures))
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
