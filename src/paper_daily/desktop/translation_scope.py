"""Source-bound transient translations; no translation writes or identity creation.

Only the worker reads research SQL or hashes bytes. GUI delivery compares captured
view intent and cheap native file revisions, including the database WAL.
"""

from __future__ import annotations

import hashlib
import os
from contextlib import closing
from dataclasses import dataclass, field
from pathlib import Path
from threading import Event

from PySide6.QtCore import QEvent, QObject, QTimer
from shiboken6 import isValid

from paper_daily import audit_inputs, file_change, llm, store, translate

STALE = "The paper, selection or AI connection changed. Select the passage and try again."


def _version(path):
    return file_change.version(path) if path.exists() else None


def _versions(database, source):
    wal = _version(Path(str(database) + "-wal"))
    # SQLite may create an empty WAL while opening an otherwise read-only DB.
    # Zero bytes cannot hold a frame; actual frames and checkpointed DB changes
    # retain their native revisions and still invalidate the proof.
    return _version(database), wal if wal is not None and wal[2] else None, _version(source)


def _routing_revision():
    # Actual capture call graph: llm._stored -> ai_profiles.load reads this file;
    # resolve consumes the captured dict/environment and derives account paths.
    # Provider-private login stores are not read by this capture operation.
    path = Path(llm.SETTINGS_PATH).resolve()
    return path, _version(path), tuple(sorted(os.environ.items()))


def _capture_route():
    before = _routing_revision()
    connections = llm.capture_connections()
    try:
        with llm.connection_scope(connections):
            cfg = llm.settings(task="translate")
    except (OSError, ValueError):
        cfg = None  # Free translation does not require an AI connection.
    if before != _routing_revision():
        raise ValueError(STALE)
    return connections, cfg, before


@dataclass
class Translation:
    owner: object
    document: object
    digest: str
    source: Path
    text: str
    connections: object = field(repr=False)
    model_cfg: object = field(repr=False)
    stopped: Event = field(default_factory=Event, repr=False)
    proof: tuple | None = None
    stale: bool = False

    def verify(self):
        before = _versions(self.owner.database, self.source)
        if self.stopped.is_set():
            raise ValueError(STALE)
        # Use the maintained RO connection factory; closing cannot checkpoint WAL.
        # Unlike audit's desired-source helper, an intact already-loaded A may
        # remain selected after B becomes the desired primary document.
        with closing(audit_inputs._connect(self.owner.database)) as conn:
            self.owner.check(conn)
        document = self.document
        if (
            document.local_id != self.owner.paper_id
            or document._owner.db_path.resolve() != self.owner.database
            or document.sha256 != self.digest
            or not document._owner.intact(document)
        ):
            raise ValueError(STALE)
        digest = hashlib.sha256()
        with self.source.open("rb") as stream:
            while chunk := stream.read(1024 * 1024):
                if self.stopped.is_set():
                    raise ValueError(STALE)
                digest.update(chunk)
        if digest.hexdigest() != self.digest:
            raise ValueError(STALE)
        with closing(audit_inputs._connect(self.owner.database)) as conn:
            self.owner.check(conn)
        if not document._owner.intact(document):
            raise ValueError(STALE)
        after = _versions(self.owner.database, self.source)
        if before != after or self.stopped.is_set():
            raise ValueError(STALE)
        return after

    def call(self, prompt, *, model):
        """AskWorker's custom call protocol; no widget is accessed on this thread."""
        if model:
            from paper_daily import feedback

            with feedback.flow("translate") as outcome:
                answer, reason = self._call(prompt, model=True)
                outcome["success"] = bool(answer)
                return answer, reason
        return self._call(prompt, model=False)

    def _call(self, prompt, *, model):
        try:
            self.verify()
        except Exception:
            self.stale = True
            return None, STALE
        try:
            if model:
                with llm.connection_scope(self.connections):
                    if self.model_cfg is None:
                        answer, reason = None, "AI translation is not configured. Open AI settings."
                    else:
                        answer, reason = llm.complete(
                            prompt, cfg=self.model_cfg, task="translate", timeout=300
                        )
            else:
                answer, reason = translate.machine(prompt)
        except Exception:
            answer, reason = None, "Translation failed. Please try again."
        try:
            self.proof = self.verify()
        except Exception:
            self.stale = True
            return None, STALE
        return answer, reason

    def metadata_current(self):
        return (
            self.proof is not None
            and not self.stopped.is_set()
            and self.proof == _versions(self.owner.database, self.source)
        )


class TranslationController(QObject):
    def __init__(self, reader):
        super().__init__(reader)
        self.reader = reader
        self.request = None
        self.intent = None
        self._watch = QTimer(self)
        self._watch.setInterval(50)
        self._watch.timeout.connect(self._poll)
        reader.installEventFilter(self)

    def eventFilter(self, watched, event):
        if watched is self.reader and event.type() in (QEvent.Type.Hide, QEvent.Type.Close):
            self.cancel()
        return False

    def cancel(self):
        if self.request is not None:
            self.request.stopped.set()
        self._watch.stop()
        self._clear_placeholder()

    def _clear_placeholder(self, request=None):
        if request is not None and self.request is not request:
            return
        if self.request is None:
            return
        panel = self.reader.pdf.selection.result
        expected = getattr(self, "_placeholder", None)
        if expected == (panel.head.text(), panel.body.text()):
            panel.hide()

    def _intent(self):
        r = self.reader
        selection = r.pdf.selection
        return (
            Path(store.DB_PATH).resolve(),
            getattr(r.paper, "id", None),
            r._qa_epoch,
            getattr(r, "_highlight_owner", None),
            getattr(r, "_active_document", None),
            getattr(r, "_pdf_fingerprint", None),
            r.pdf.position_identity(),
            selection,
            selection.selection_epoch(),
            selection.anchor(),
            selection.selected_text(),
            _routing_revision(),
        )

    def current(self, request, *, verified=False):
        try:
            return (
                isValid(self.reader)
                and self.reader.isVisible()
                and self.request is request
                and not request.stopped.is_set()
                and self.intent == self._intent()
                and (not verified or request.metadata_current())
            )
        except (OSError, RuntimeError, ValueError):
            return False

    def _poll(self):
        if self.request is not None and not self.current(self.request):
            self.cancel()

    def start(self, text, *, model=False):
        r = self.reader
        if not text.strip() or r.translate_runner.busy or r.refine_runner.busy:
            return
        if self.request is not None and not self.request.stopped.is_set():
            return
        try:
            intent = self._intent()
            owner, document, digest = intent[3:6]
            if (
                owner is None
                or document is None
                or not document.available
                or owner.database != intent[0]
                or owner.paper_id != intent[1]
                or not intent[9]
                or text != intent[10]
            ):
                return
            connections, cfg, revision = _capture_route()
            if revision != intent[-1]:
                return
            request = Translation(owner, document, digest, document.path, text, connections, cfg)
        except (OSError, RuntimeError, ValueError):
            return
        self.request, self.intent = request, intent
        self._watch.start()
        self._dispatch(request, model=model)

    def _dispatch(self, request, *, model):
        r = self.reader
        overlay = r.pdf.selection
        overlay.show_result(
            "AI \u7cbe\u8b6f\u4e2d\u2026" if model else "\u7ffb\u8b6f\u4e2d\u2026",
            request.text[:160],
        )
        self._placeholder = (overlay.result.head.text(), overlay.result.body.text())
        runner = r.refine_runner if model else r.translate_runner
        prompt = (
            (
                "把下面這段論文原文翻成繁體中文。技術名詞、模型名稱、資料集名稱保留英文,"
                "數學用 Unicode 純文字,絕不使用 LaTeX。只輸出譯文,不要前言。\n\n" + request.text
            )
            if model
            else request.text
        )

        def finished(answer):
            if not self.current(request, verified=True):
                runner.activity.finish(cancelled=True)
                self._clear_placeholder(request)
                self._finish(request)
                return
            overlay.show_result(
                "AI \u7cbe\u8b6f" if model else "Google \u7ffb\u8b6f",
                answer.strip(),
                refinable=not model,
            )
            self._finish(request)

        def failed(reason):
            if not self.current(request, verified=True) or request.stale:
                self._clear_placeholder(request)
                self._finish(request)
                return
            if not model:
                # The original frozen route is retained across the free-to-AI handoff.
                self._dispatch(request, model=True)
            else:
                overlay.show_result("Unable to translate", str(reason)[:600])
                self._finish(request)

        runner.start(
            prompt,
            finished,
            failed,
            call=lambda value: request.call(value, model=model),
            task="translate",
        )

    def _finish(self, request):
        if self.request is request:
            request.stopped.set()
            self._watch.stop()


def controller(reader):
    existing = getattr(reader, "_translation_controller", None)
    if existing is None:
        existing = TranslationController(reader)
        reader._translation_controller = existing
    return existing
