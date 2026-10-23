"""Ask about the paper on screen.

The call goes through `paper_daily.llm`, so it lands on whichever backend the machine
has: the local `claude` CLI (no key, no second account), an Anthropic key, or an
OpenAI-compatible endpoint. It runs on a worker thread because an answer takes tens
of seconds and the window has to stay responsive.
"""

from __future__ import annotations

import queue
import threading
from contextvars import copy_context

from PySide6.QtCore import QObject, QThread, QTimer, Signal, Slot

from paper_daily import llm

SYSTEM_RULES = (
    "你是一位嚴謹的研究討論夥伴。以下是一篇論文的內容,回答讀者的問題。\n"
    "規則:用繁體中文回答,技術名詞保留英文;數學用 LaTeX,行內 $...$、獨立式子 $$...$$"
    "(app 用 KaTeX 排版);演算法用 ```pseudocode 區塊,流程圖用 ```mermaid 區塊;"
    "只根據提供的內容作答,內容不足以回答就直說,不要編造數字。\n"
)


class AskWorker(QObject):
    """Runs one model call and emits the answer."""

    finished = Signal(str)
    failed = Signal(str)
    progress = Signal(object)

    def __init__(self, prompt: str, timeout: int = 300, call=None, task: str = "ask") -> None:
        super().__init__()
        self._prompt = prompt
        self._timeout = timeout
        self._call = call
        self._task = task
        self._connections = llm.capture_connections()
        self._context = copy_context()

    def run(self) -> None:
        self._context.run(self._run_scoped)

    def _run_scoped(self):
        from paper_daily.work_progress import observe

        with llm.connection_scope(self._connections), observe(self.progress.emit):
            from paper_daily import feedback

            if self._call is not None:
                self._run()
            else:
                with feedback.flow(self._task) as outcome:
                    outcome["success"] = self._run()

    def _run(self) -> bool:
        if self._call is not None:
            # Not a model: its failures are its own, and the backend line would mislead.
            try:
                answer, reason = self._call(self._prompt)
            except Exception as exc:
                self.failed.emit(f"背景工作失敗：{type(exc).__name__}；可稍後重試。")
                return False
            if answer:
                self.finished.emit(answer)
            else:
                self.failed.emit(reason)
            return bool(answer)
        try:
            cfg = llm.settings(task=self._task)
            answer, reason = llm.complete(
                self._prompt, timeout=self._timeout, cfg=cfg, task=self._task
            )
        except Exception as e:  # noqa: BLE001 - surface whatever the backend did
            self.failed.emit(f"呼叫模型失敗:{type(e).__name__}")
            return False
        if not answer:
            # Which backend answered matters here: "no key" and "expired login" need
            # different fixes, and the pane is the only place the reader sees either.
            self.failed.emit(f"{reason}\n\n目前的後端:{llm.describe(cfg)}"[:600])
            return False
        self.finished.emit(answer)
        return True


def build_prompt(title: str, venue: str, year: int, abstract: str | None,
                 full_text: str | None, history: list[tuple[str, str]],
                 question: str, text_budget: int = 45000) -> str:
    """Assemble the prompt: rules, paper, prior turns, then the question."""
    parts = [SYSTEM_RULES, f"\n論文:{title}\n會議:{venue} {year}"]
    if abstract:
        parts.append(f"\n摘要:\n{abstract}")
    if full_text:
        parts.append(f"\n論文全文(可能被截斷):\n{full_text[:text_budget]}")
    if history:
        parts.append("\n先前的討論:")
        for role, body in history[-6:]:
            who = "讀者" if role == "user" else "你"
            parts.append(f"{who}:{body}")
    parts.append(f"\n讀者的問題:{question}")
    return "\n".join(parts)


class AskRunner(QObject):
    """Owns the thread so callers do not have to. One in flight at a time.

    It is a QObject on purpose. Qt picks a connection type from the *receiver*: a
    bound method of a QObject is delivered on that object's thread, but a plain
    function or lambda has no thread affinity, so it is connected directly and runs
    on the worker thread. A callback that touches a widget then draws from outside
    the GUI thread, which aborts the process with no Python traceback -- which is
    what pressing 翻譯 did. Routing the worker's signals through this object's own
    slots makes every callback arrive on the thread that created the runner,
    whatever the caller passes in.
    """

    def __init__(self, parent: QObject | None = None, *, read_only=False) -> None:
        super().__init__(parent)
        self._thread: QThread | None = None
        self._worker: AskWorker | None = None
        self._on_done = None
        self._on_fail = None
        from paper_daily.desktop.activity import Handle

        self.activity = Handle()
        self.read_only = read_only
        self._reading = False
        self._read_epoch = 0
        self._results = queue.Queue()
        self._poll = QTimer(self)
        self._poll.setInterval(25)
        self._poll.timeout.connect(self._read_results)

    @property
    def busy(self) -> bool:
        return self._reading or (self._thread is not None and self._thread.isRunning())

    def cancel_read(self):
        """Detach UI from a read-only query; no Qt object lives on its daemon thread."""
        if not self.read_only:
            return
        self._read_epoch += 1
        self._reading = False
        self._on_done = self._on_fail = None
        self._poll.stop()

    def _start_read(self, prompt, call):
        if call is None:
            raise ValueError("Read-only runners require an explicit metadata query")
        self._reading = True
        self._read_epoch += 1
        epoch, results = self._read_epoch, self._results
        context = copy_context()
        connections = llm.capture_connections()

        def run():
            try:
                with llm.connection_scope(connections):
                    answer, reason = call(prompt)
                results.put((epoch, answer, reason))
            except Exception:
                results.put((epoch, None, "資料暫時無法取得，請稍後重試。"))

        threading.Thread(target=lambda: context.run(run), daemon=True).start()
        self._poll.start()

    def _read_results(self):
        while True:
            try:
                epoch, answer, reason = self._results.get_nowait()
            except queue.Empty:
                return
            if epoch != self._read_epoch:
                continue
            self._reading = False
            self._poll.stop()
            if answer is not None:
                self._deliver(answer)
            else:
                self._fail(reason)

    def start(self, prompt: str, on_done, on_fail, call=None, task: str = "ask") -> None:
        """Run `prompt` through the model, or through `call` when one is given."""
        if self.busy:
            return
        # The previous thread has finished its event loop but may still be winding
        # down; dropping the last reference to it while that is true destroys a
        # running QThread, which also aborts.
        if self._thread is not None:
            self._thread.wait()
        from paper_daily.desktop.activity import begin

        if not self.read_only:
            self.activity = begin(self, getattr(self, "activity_label", None), task=task,
                                  result=getattr(self, "result_target", None))
            if not self.activity.accepted:
                on_fail("相同工作已在執行，請查看上方進度。")
                return
        self._on_done, self._on_fail = on_done, on_fail
        if self.read_only:
            self._start_read(prompt, call)
            return
        self._thread = QThread()
        self._worker = AskWorker(prompt, call=call, task=task)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.progress.connect(self._progress)
        self._worker.finished.connect(self._deliver)
        self._worker.failed.connect(self._fail)
        self._worker.finished.connect(self._thread.quit)
        self._worker.failed.connect(self._thread.quit)
        self._thread.start()

    @Slot(object)
    def _progress(self, event):
        self.activity.update(event)

    def report(self, message):
        self.activity.stage(message)

    @Slot(str)
    def _deliver(self, answer: str) -> None:
        try:
            if self._on_done:
                self._on_done(answer)
        except Exception:
            self.activity.finish(False)
            raise
        else:
            self.activity.finish()

    @Slot(str)
    def _fail(self, reason: str) -> None:
        self.activity.finish(False)
        if self._on_fail:
            self._on_fail(reason)
