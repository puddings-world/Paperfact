"""One owned material collection lane, pinned before any SQL/PDF work is queued."""

from __future__ import annotations

import threading
import time
import weakref
from dataclasses import dataclass, replace
from pathlib import Path

from PySide6.QtCore import QEvent, QObject, QTimer, Slot
from shiboken6 import isValid

from paper_daily import figures, file_change, material_sources, materials
from paper_daily import manual_highlight_ops as marks
from paper_daily.desktop import activity
from paper_daily.desktop.original_version import ViewerWorker
from paper_daily.desktop.window_workspace import WindowWorkspace
from paper_daily.document_reader import from_workspace

_LIVE = set()


@dataclass(frozen=True)
class Request:
    paper: object
    owner: object
    workspace: object
    path: Path
    fingerprint: str
    document: object
    version: tuple
    paths: materials.MaterialPaths
    panel_epoch: int
    token: int
    stop: threading.Event


@dataclass(frozen=True)
class Publication:
    found: materials.Materials
    lease: object
    proof: object
    rechecks: int = 0


def _release(worker):
    _LIVE.discard(worker)
    worker.deleteLater()


def _collect(request, cancelled, stage):
    def current():
        return not cancelled() and not request.stop.is_set() and request.workspace.current()

    if not current():
        return None
    stage("核對目前閱讀的原文與工作區")
    document = request.document
    if document is None:
        # Legacy readers have no active_document; resolve only the captured path.
        document = from_workspace(request.owner.database, legacy_root=request.path.parent).resolve(
            request.paper.id
        )
        if (
            not document.available
            or document.path.resolve() != request.path.resolve()
            or document.sha256 != request.fingerprint
        ):
            document = None
    view = marks.load(
        request.owner, request.path, request.fingerprint, document=document, readonly=True
    )
    source = figures.capture_loaded(
        view, document, request.version, cancelled=lambda: not current()
    )
    stage("整理原文圖表、段落與已存重點")
    found = materials.collect(
        request.paper.id,
        document=document,
        database=request.owner.database,
        loaded_source=source,
        paths=request.paths,
        cancelled=lambda: not current(),
    )
    stage("綁定素材項目與保存原文")
    if not current():
        return None
    collection = None
    if document is not None:
        collection = material_sources.capture_collection(
            request.owner.database,
            request.paper.id,
            document,
            found,
            expected_native=request.workspace.identity,
            current=current,
        )
    found._source_collection = collection
    found._material_items = (
        collection.items if collection is not None else material_sources.project_items(found)
    )
    found._material_hash = request.fingerprint
    lease = figures.retain_loaded_lease(source)
    proof = figures.recheck_loaded_lease(lease, cancelled=lambda: not current())
    return None if not current() else Publication(found, lease, proof)


class MaterialPreparation(QObject):
    def __init__(self, reader):
        super().__init__(reader)
        self._reader = weakref.ref(reader)
        self.owner = getattr(reader.win, "_workspace_owner", None) or WindowWorkspace.capture()
        self._worker = self._request = self._pending = self._handle = None
        self._epoch = 0
        self._disposed = False
        self._started = 0
        self._highlight_choice = None
        self._selection_epoch = 0
        panel = reader.presentation_pane.materials_panel
        panel.tree.currentItemChanged.connect(self._selection_changed)
        reader.tabs.currentChanged.connect(self._navigation_changed)
        reader.presentation_pane.materials_button.toggled.connect(self._navigation_changed)
        reader.installEventFilter(self)
        reader.destroyed.connect(self.dispose)
        self.timer = QTimer(self)
        self.timer.setInterval(200)
        self.timer.timeout.connect(self._poll)
        self.timer.start()

    @property
    def busy(self):
        return self._worker is not None or self._pending is not None

    def _status(self, text):
        reader = self._reader()
        if reader is not None and isValid(reader):
            reader.presentation_pane.status.setText(text)

    def _capture(self):
        reader = self._reader()
        if self._disposed or reader is None or not isValid(reader) or not self.owner.current():
            raise ValueError("Material window retired")
        paper = reader.paper
        owner = getattr(reader, "_highlight_owner", None)
        native = reader.pdf.position_identity()
        version = reader.pdf.position_source_version()
        fingerprint = getattr(reader, "_pdf_fingerprint", None)
        if (
            paper is None
            or owner is None
            or owner.database != self.owner.database
            or owner.paper_id != paper.id
            or native[1] is None
            or version is None
            or not isinstance(fingerprint, str)
            or len(fingerprint) != 64
            or reader.presentation_pane.paper_id != paper.id
            or file_change.version(native[1]) != version
        ):
            raise ValueError("Reopen the actual loaded paper before collecting materials")
        return Request(
            paper,
            owner,
            self.owner,
            Path(native[1]),
            fingerprint,
            getattr(reader, "_active_document", None),
            version,
            materials.MaterialPaths.capture(),
            reader.presentation_pane.materials_panel._collection_epoch,
            self._epoch,
            threading.Event(),
        )

    def _matches(self, request):
        reader = self._reader()
        try:
            if (
                self._disposed
                or request.token != self._epoch
                or request.stop.is_set()
                or reader is None
                or not isValid(reader)
                or not self.owner.current()
            ):
                return False
            pane = reader.presentation_pane
            native = reader.pdf.position_identity()
            return bool(
                reader.paper is request.paper
                and pane.paper_id == request.paper.id
                and getattr(reader, "_highlight_owner", None) is request.owner
                and getattr(reader, "_active_document", None) is request.document
                and getattr(reader, "_pdf_fingerprint", None) == request.fingerprint
                and native[1] is not None
                and Path(native[1]) == request.path
                and reader.pdf.position_source_version() == request.version
                and file_change.version(request.path) == request.version
                and pane.materials_panel._collection_epoch == request.panel_epoch
                and materials.MaterialPaths.capture() == request.paths
            )
        except (OSError, ValueError, TypeError, AttributeError, RuntimeError):
            return False

    def _selection_changed(self, *_args):
        self._selection_epoch += 1
        self._highlight_choice = None

    def _navigation_changed(self, *_args):
        reader = self._reader()
        if reader is None or not isValid(reader):
            self._highlight_choice = None
            return
        pane = reader.presentation_pane
        if reader.tabs.currentWidget() is not pane or not pane.materials_button.isChecked():
            self._highlight_choice = None

    def _select_highlight(self, mark_id):
        reader = self._reader()
        if reader is None or not isValid(reader) or self._disposed or not self.owner.current():
            return False
        pane = reader.presentation_pane
        if reader.tabs.currentWidget() is not pane or not pane.materials_button.isChecked():
            return False
        if not pane.materials_panel.select_highlight(mark_id):
            reader.highlight_status.setText("此重點目前不在素材中；可重新整理或分析原文。")
            return False
        pane.materials_panel._locate_selected()
        return True

    def show_highlight(self, mark_id=None):
        """Bind an explicit jump to this collection, respecting later navigation."""
        if mark_id is not None and (type(mark_id) is not int or not mark_id):
            return False
        accepted = self.request()
        request = self._pending or self._request
        if self.busy and request is not None and self._matches(request):
            self._highlight_choice = (request.token, mark_id, self._selection_epoch)
            self._status("正在整理目前原文的重點素材；完成後會定位，可繼續閱讀。")
            return True
        return accepted and self._select_highlight(mark_id)

    def _preview_loaded_marks(self):
        """Legacy current-PDF preview from already displayed marks; no source grant.

        A failed real research owner must never fall through to this path. Full
        material collection remains on the owned worker lane.
        """
        reader = self._reader()
        try:
            if (
                self._disposed
                or reader is None
                or not isValid(reader)
                or not self.owner.current()
                or hasattr(reader, "_highlight_owner")
                or getattr(reader, "_active_document", None) is not None
            ):
                raise ValueError("Legacy preview is not current")
            paper = reader.paper
            pane = reader.presentation_pane
            native = reader.pdf.position_identity()
            version = reader.pdf.position_source_version()
            fingerprint = getattr(reader, "_pdf_fingerprint", None)
            selection = getattr(reader.pdf, "selection", None)
            if (
                paper is None
                or pane.paper_id != paper.id
                or native[1] is None
                or version is None
                or selection is None
                or not isinstance(fingerprint, str)
                or len(fingerprint) != 64
                or file_change.version(native[1]) != version
            ):
                raise ValueError("Loaded original changed")
            displayed = selection._marks
            if len(displayed) > marks.MAX_MARKS:
                raise ValueError("Legacy mark preview exceeds its bound")
            sentences, size = [], 0
            for mark, _words in displayed:
                quote, anchor = mark.get("quote"), mark.get("anchor")
                reason = mark.get("reason", "")
                if (
                    not isinstance(quote, str)
                    or not quote.strip()
                    or len(quote.encode("utf-8")) > 32768
                    or not isinstance(reason, str)
                    or len(reason) > 1600
                    or not isinstance(anchor, dict)
                    or set(anchor) != marks.ANCHOR_KEYS
                    or any(
                        type(value) is not int or not 0 <= value <= 1000000
                        for value in anchor.values()
                    )
                    or type(mark.get("id")) is not int
                    or not mark["id"]
                    or mark.get("origin") not in {"manual", "ai"}
                ):
                    raise ValueError("Invalid displayed legacy mark")
                size += len(quote.encode("utf-8")) + len(reason.encode("utf-8"))
                if size > marks.MAX_SNAPSHOT_BYTES:
                    raise ValueError("Legacy mark preview exceeds its text bound")
                sentences.append(
                    dict(
                        text=quote,
                        page=anchor["p0"] + 1,
                        anchor=dict(anchor),
                        mark_id=mark["id"],
                        origin=mark["origin"],
                        reason=reason,
                        document_hash=fingerprint,
                        navigation_available=True,
                    )
                )
            if not self.owner.current() or file_change.version(native[1]) != version:
                raise ValueError("Loaded preview changed")
        except (OSError, ValueError, TypeError, AttributeError):
            self._status("請重新開啟目前原文後查看標記；既有素材保留。")
            return False
        self.invalidate()
        found = materials.Materials(paper.id, sentences=sentences)
        found._material_hash = fingerprint
        pane.materials_panel.load(found)
        pane._materials_for = paper.id
        pane.materials_panel.source_status.setText("目前原文標記預覽；尚未建立獨立來源資格。")
        self._status("已顯示目前原文的標記預覽；研究素材整理仍需已載入的研究項目。")
        return True

    def request(self):
        reader = self._reader()
        if reader is not None and isValid(reader) and not hasattr(reader, "_highlight_owner"):
            return self._preview_loaded_marks()
        try:
            request = self._capture()
        except (OSError, ValueError, TypeError, AttributeError):
            self._status("請先重新開啟原文，再整理素材；既有素材保留原樣。")
            return False
        old = self._pending or self._request
        if (
            old is not None
            and self.busy
            and self._matches(old)
            and old.paper is request.paper
            and old.version == request.version
        ):
            return False
        self._epoch += 1
        request = replace(request, token=self._epoch)
        if self._request is not None:
            self._request.stop.set()
        self._pending = request
        if self._worker is not None:
            self._worker.cancelled.set()
        else:
            self._start_pending()
        return True

    def _start_pending(self):
        if self._worker is not None or self._pending is None or self._disposed:
            return
        request, self._pending = self._pending, None
        if not self._matches(request):
            return
        self._request = request
        reader = self._reader()
        reader.presentation_pane.materials_panel.set_loading(True)
        self._started = time.monotonic()
        self._handle = activity.begin(
            reader,
            "整理論文素材",
            task="materials",
            key=f"materials:{id(self)}:{request.token}",
            paper_id=request.paper.id,
        )
        handle = self._handle
        self._launch(request, lambda cancelled: _collect(request, cancelled, handle.stage))

    def _launch(self, request, call):
        worker = ViewerWorker(call, None)
        worker.request = request
        self._worker = worker
        _LIVE.add(worker)
        worker.finished.connect(self._finished)
        worker.finished.connect(lambda: _release(worker))
        worker.start()

    @Slot()
    def _finished(self):
        worker = self.sender()
        if worker is not self._worker:
            return
        self._worker = None
        request = worker.request
        valid = self._matches(request)
        publication = worker.result
        if (
            valid
            and publication is not None
            and not worker.error
            and not figures.lease_metadata_current(publication.proof)
            and publication.rechecks == 0
        ):
            # One check of the SAME source/owner; do not recollect a new parent.
            self._handle.stage("重新核對來源狀態")

            def recheck(cancelled):
                proof = figures.recheck_loaded_lease(
                    publication.lease,
                    cancelled=lambda: cancelled() or request.stop.is_set(),
                )
                return replace(publication, proof=proof, rechecks=1)

            self._launch(request, recheck)
            return
        ok = bool(
            valid
            and publication is not None
            and not worker.error
            and figures.lease_metadata_current(publication.proof)
        )
        reader = self._reader()
        if reader is not None and isValid(reader):
            pane = reader.presentation_pane
            pane.materials_panel.set_loading(False)
            choice = self._highlight_choice
            if choice is not None and choice[0] == request.token:
                self._highlight_choice = None
            else:
                choice = None
            follow = bool(
                ok
                and choice is not None
                and choice[0] == request.token
                and choice[2] == self._selection_epoch
            )
            if ok:
                pane.materials_panel.load(publication.found)
                pane._materials_for = request.paper.id
                self._status("素材已更新；點選項目核對來源，雙擊或拖曳可加入投影片。")
                self._source_label()
                if follow:
                    self._select_highlight(choice[1])
            elif valid:
                self._status("素材整理未完成；既有內容保留，請按「重新整理」重試。")
        if self._handle is not None:
            self._handle.finish(ok, cancelled=not valid)
            self._handle = None
        self._request = None
        self._start_pending()

    def _source_label(self):
        reader = self._reader()
        if reader is None or not isValid(reader):
            return
        panel = reader.presentation_pane.materials_panel
        fingerprint = panel._material_hash
        if fingerprint:
            older = fingerprint != getattr(reader, "_pdf_fingerprint", None)
            text = ("舊版素材 · " if older else "原文 · ") + fingerprint[:10]
            collection = panel._source_collection
            if collection is None or not collection.historical_available:
                text += " · 舊原文未保留"
            panel.source_status.setText(text)

    @Slot()
    def _poll(self):
        if self._request is not None:
            if not self._matches(self._request):
                if self._pending is not None and self._matches(self._pending):
                    # This retired worker only drains; the newer observed request
                    # and its explicit navigation remain independently current.
                    self._request.stop.set()
                    if self._worker is not None:
                        self._worker.cancelled.set()
                else:
                    self.invalidate()
            elif self._worker is not None:
                seconds = int(time.monotonic() - self._started)
                self._status(f"正在整理素材… 已經過 {seconds} 秒；可繼續閱讀。")

    def source_changed(self):
        self.invalidate()
        QTimer.singleShot(0, self, self._source_label)

    def invalidate(self, *, clear=False):
        self._highlight_choice = None
        self._epoch += 1
        if self._request is not None:
            self._request.stop.set()
        if self._pending is not None:
            self._pending.stop.set()
        self._pending = None
        if self._worker is not None:
            self._worker.cancelled.set()
        if clear:
            reader = self._reader()
            if reader is not None and isValid(reader):
                reader.presentation_pane.materials_panel.clear()
                reader.presentation_pane._materials_for = None

    def request_close(self):
        self.invalidate()
        return not self.busy

    def dispose(self):
        self._disposed = True
        self.invalidate()

    def eventFilter(self, watched, event):
        if (
            watched is self._reader()
            and event.type() == QEvent.Type.Close
            and not self.request_close()
        ):
            event.ignore()
            return True
        return False
