"""Saved-deck source authority, using the common owned original-view lifecycle."""
from __future__ import annotations

import threading
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path

from shiboken6 import isValid

from paper_daily import active_deck_originals, file_change, presentations
from paper_daily.desktop.original_controller import OriginalController
from paper_daily.desktop.original_version import prepare_active


@dataclass(frozen=True)
class Context:
    paper_id: str
    deck: object
    source: dict
    document: object
    fingerprint: object
    document_file: tuple | None
    slot: tuple
    stop: threading.Event



class ActiveOriginalController(OriginalController):
    def __init__(self, reader):
        super().__init__(reader)
        self.presentation_root = Path(presentations.DECK_DIR).absolute()

    def _matches(self, context):
        """GUI-only native/context admission; never inspect SQL, JSON or PDF bytes."""
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
            pane = reader.presentation_pane
            paper = reader.paper
            sources = [s for s in context.deck.sources if s.get("id") == context.source["id"]]
            document = getattr(reader, "_active_document", None)
            if (
                paper is None
                or paper.id != context.paper_id
                or pane.deck is not context.deck
                or sources != [context.source]
                or document is not context.document
                or getattr(reader, "_pdf_fingerprint", None) != context.fingerprint
                or file_change.version(context.slot[0]) != context.slot[1]
            ):
                return False
            if context.document_file is not None:
                path, version = context.document_file
                if file_change.version(path) != version:
                    return False
            return True
        except (OSError, ValueError, TypeError, AttributeError, RuntimeError):
            return False


    def open(self, source):
        """Only a source emitted by the current saved deck receives this authority."""
        reader = self._reader()
        if self._disposed or reader is None or not isValid(reader) or not self.owner.current():
            return False
        pane, paper = reader.presentation_pane, reader.paper
        deck = pane.deck
        if (
            paper is None
            or deck is None
            or not isinstance(source, dict)
            or [s for s in deck.sources if s.get("id") == source.get("id")] != [source]
        ):
            return False
        document_hash = source.get("document_hash")
        if (
            not isinstance(document_hash, str)
            or len(document_hash) != 64
            or any(c not in "0123456789abcdef" for c in document_hash)
        ):
            return False
        if (
            self._context is not None
            and self._matches(self._context)
            and self._context.source == source
        ):
            if self._worker is not None:
                return True
            if self.viewer is not None and not self.viewer.disposed and not self.viewer._closing:
                self.viewer.check()
                if not self.viewer._closing:
                    self.viewer.show()
                    self.viewer.raise_()
                return True
        # Do not replace a still-draining preparation or renderer with another job.
        self.invalidate()
        if self.busy:
            self._status("checking")
            return True
        try:
            if getattr(deck, "_file_operation", None):
                slot = Path(deck._file_directory) / "deck.json"
            else:
                # Actual configured local root, not a sender's arbitrary path.
                slot = presentations._path(paper.id, deck.mode)
                if Path(presentations.DECK_DIR).absolute() != self.presentation_root:
                    raise ValueError("Presentation root changed")
            slot = Path(slot).absolute()
            slot_witness = (slot, file_change.version(slot))
            document = getattr(reader, "_active_document", None)
            document_file = None
            if document is not None:
                path = Path(document.path)
                document_file = path, file_change.version(path)
            context = Context(
                paper.id,
                deck,
                deepcopy(source),
                document,
                getattr(reader, "_pdf_fingerprint", None),
                document_file,
                slot_witness,
                threading.Event(),
            )
            copied = deepcopy(deck)
            self._context = context
            self._status("checking")

            def prepare(cancelled):
                def current():
                    return not cancelled() and not context.stop.is_set() and self.owner.current()

                captured = active_deck_originals.capture(
                    self.owner.database,
                    context.paper_id,
                    copied,
                    context.source["id"],
                    expected_native=self.owner.identity,
                    presentation_root=self.presentation_root,
                    expected_slot=context.slot,
                    current=current,
                )
                proof = active_deck_originals.prepare(captured, current=current)
                # Extract a small locator on the worker, not through proof.source in Qt.
                return prepare_active(proof), proof.source

            self._launch(context, prepare)
            return True
        except (OSError, ValueError, TypeError, AttributeError):
            self._context = None
            self._status("failed")
            return True

