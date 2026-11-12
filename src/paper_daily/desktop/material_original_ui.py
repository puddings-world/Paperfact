"""Material selection reads use their own collection authority, never a deck grant."""

from __future__ import annotations

import threading
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import Qt
from shiboken6 import isValid

from paper_daily import file_change, material_sources
from paper_daily.desktop import activity
from paper_daily.desktop.original_controller import OriginalController
from paper_daily.desktop.original_version import prepare_material


@dataclass(frozen=True)
class Context:
    paper: object
    collection: object
    selection: object
    epoch: int
    document: object
    fingerprint: object
    path: Path | None
    version: tuple | None
    stop: threading.Event


class MaterialOriginalController(OriginalController):
    def __init__(self, reader):
        super().__init__(reader)
        self._pending = self._handle = None

    @property
    def busy(self):
        return super().busy or self._pending is not None

    def _matches(self, context):
        reader = self._reader()
        try:
            if (
                self._disposed
                or context is not self._context
                or context.stop.is_set()
                or reader is None
                or not isValid(reader)
                or not self.owner.current()
            ):
                return False
            panel = reader.presentation_pane.materials_panel
            selected = panel.tree.currentItem()
            native = reader.pdf.position_identity()
            return bool(
                reader.paper is context.paper
                and panel._source_collection is context.collection
                and panel._collection_epoch == context.epoch
                and selected is not None
                and selected.data(0, Qt.ItemDataRole.UserRole + 1) == context.selection.item.key
                and selected.data(0, Qt.ItemDataRole.UserRole) == context.selection.payload
                and getattr(reader, "_active_document", None) is context.document
                and getattr(reader, "_pdf_fingerprint", None) == context.fingerprint
                and (Path(native[1]) if native[1] is not None else None) == context.path
                and reader.pdf.position_source_version() == context.version
                and (context.path is None or file_change.version(context.path) == context.version)
            )
        except (OSError, ValueError, TypeError, AttributeError, RuntimeError):
            return False

    def open(self, selection):
        if not isinstance(selection, material_sources.Selection):
            return False
        reader = self._reader()
        if self._disposed or reader is None or not isValid(reader) or not self.owner.current():
            return False
        panel = reader.presentation_pane.materials_panel
        collection = selection.collection
        paper = reader.paper
        if (
            paper is None
            or collection is not panel._source_collection
            or collection.database != self.owner.database
            or collection.paper_id != paper.id
        ):
            return False
        source = selection.payload
        if source.get("document_hash") == getattr(reader, "_pdf_fingerprint", None):
            return False  # The existing bare/current-reader action already navigated.
        if not collection.historical_available:
            self._status("unavailable")
            return True
        if (
            self._context is not None
            and self._matches(self._context)
            and self._context.selection.item.key == selection.item.key
        ):
            if self._worker is not None:
                return True
            if self.viewer is not None and not self.viewer.disposed and not self.viewer._closing:
                self.viewer.check()
                if not self.viewer._closing:
                    self.viewer.show()
                    self.viewer.raise_()
                return True
        self.invalidate()
        if super().busy:
            self._pending = selection
            self._status("checking")
            return True
        native = reader.pdf.position_identity()
        context = Context(
            paper,
            collection,
            selection,
            panel._collection_epoch,
            getattr(reader, "_active_document", None),
            getattr(reader, "_pdf_fingerprint", None),
            Path(native[1]) if native[1] is not None else None,
            reader.pdf.position_source_version(),
            threading.Event(),
        )
        self._context = context
        if not self._matches(context):
            self._context = None
            return False
        self._status("checking")
        self._handle = activity.begin(
            reader,
            "核對素材原文",
            task="material_original",
            key=f"material-source:{id(self)}",
            paper_id=paper.id,
            result=self._focus_result,
        )

        def prepare(cancelled):
            def current():
                return not cancelled() and not context.stop.is_set() and self.owner.current()

            proof = material_sources.prepare(selection, current=current)
            return prepare_material(proof), proof.source

        self._launch(context, prepare)
        return True

    def _status(self, key, **values):
        if key == "unavailable":
            reader = self._reader()
            if reader is not None and isValid(reader):
                reader.presentation_pane.status.setText(
                    "這份素材沒有可核對的保存原文；素材內容仍保留。"
                )
            return
        super()._status(key, **values)

    def _focus_result(self):
        if (
            self.viewer is not None
            and not self.viewer.disposed
            and not self.viewer._closing
            and self._context is not None
            and self._matches(self._context)
        ):
            self.viewer.show()
            self.viewer.raise_()

    def _complete(self, worker):
        if worker is not self._worker:
            return
        handle, self._handle = self._handle, None
        valid = self._matches(worker.context)
        super()._complete(worker)
        if handle is not None:
            handle.finish(bool(valid and self.viewer is not None), cancelled=not valid)
        self._run_pending()

    def _closed_view(self, viewer):
        super()._closed_view(viewer)
        self._run_pending()

    def _run_pending(self):
        if self._pending is not None and not super().busy:
            pending, self._pending = self._pending, None
            if not self._disposed:
                self.open(pending)

    def invalidate(self):
        self._pending = None
        super().invalidate()
