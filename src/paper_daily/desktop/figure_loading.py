"""One figure worker with one in-flight image; widgets/QPixmap stay in its owner."""

from __future__ import annotations

import hashlib
import weakref
from dataclasses import dataclass, field
from pathlib import Path
from threading import Event

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, Qt, QThread, QTimer, Signal
from PySide6.QtGui import QImage, QImageReader
from shiboken6 import isValid

from paper_daily import figures, file_change

MAX_WIDTH = 720
MAX_IMAGE_BYTES = 32 * 1024 * 1024
MAX_IMAGE_PIXELS = 32_000_000
_LIVE = set()


def version(path):
    return file_change.version(path) if Path(path).exists() else None


def decode(path, expected=None):
    """No QPixmap, widget, SQL or unbounded image decode on this worker boundary."""
    path = Path(path)
    before = version(path)
    if before is None or not 0 < before[2] <= MAX_IMAGE_BYTES:
        return QImage(), before
    with path.open("rb") as stream:
        data = stream.read(MAX_IMAGE_BYTES + 1)
    if len(data) != before[2] or (
        expected is not None and hashlib.sha256(data).hexdigest() != expected
    ):
        raise ValueError("Figure asset differs from its generated source")
    device = QBuffer()
    device.setData(QByteArray(data))
    device.open(QIODevice.OpenModeFlag.ReadOnly)
    reader = QImageReader(device)
    size = reader.size()
    if size.width() <= 0 or size.height() <= 0 or size.width() * size.height() > MAX_IMAGE_PIXELS:
        return QImage(), before
    image = reader.read()
    if not image.isNull() and image.width() > MAX_WIDTH:
        image = image.scaledToWidth(MAX_WIDTH, Qt.TransformationMode.SmoothTransformation)
    if version(path) != before:
        raise ValueError("Figure asset changed during decode")
    return image, before


@dataclass(frozen=True)
class Context:
    view: object
    document: object
    native_version: tuple
    root: Path
    legacy_root: Path
    current: object = field(repr=False, compare=False)
    key: tuple = ()


@dataclass
class Entry:
    worker: object
    index: int
    figure: object
    image: QImage
    version: object
    ack: Event = field(default_factory=Event)
    proof: object = None
    recheck: bool = False


class Worker(QThread):
    begun = Signal(object)
    entry = Signal(object)

    def __init__(self, paper_id, path, generation, context, extractor, *, lease=None):
        super().__init__()
        self.paper_id, self.path, self.generation = paper_id, Path(path), generation
        self.context, self.extractor = context, extractor
        self.stopped = Event()
        self.waiting = None
        self.priority = None
        self.figures = []
        self.source = None
        self.success = False
        self.failed = False
        self.revoked = False
        self.lease = lease
        self.mode = "check" if lease is not None else "extract"
        self.proof = None
        self.ready_emitted = False
        self.target_frame = None
        _LIVE.add(self)
        self.finished.connect(self._release)

    def cancel(self):
        self.stopped.set()
        if self.waiting is not None:
            self.waiting.ack.set()

    def run(self):
        try:
            context = self.context
            if self.mode == "check":
                self.proof = figures.recheck_loaded_lease(self.lease, cancelled=self.stopped.is_set)
                self.success = not self.stopped.is_set()
                return
            if context is not None:
                self.source = figures.capture_loaded(
                    context.view,
                    context.document,
                    context.native_version,
                    cancelled=self.stopped.is_set,
                )
                self.figures = self.extractor(
                    self.paper_id,
                    self.path,
                    root=context.root,
                    legacy_root=context.legacy_root,
                    loaded_source=self.source,
                    cancelled=self.stopped.is_set,
                )
            else:
                # Compatibility callers without a native reader do not gain an owned source.
                self.figures = self.extractor(self.paper_id, self.path)
            if self.stopped.is_set():
                return
            if self.source is not None:
                self.lease = figures.retain_loaded_lease(self.source)
                self.proof = figures.recheck_loaded_lease(self.lease, cancelled=self.stopped.is_set)
            self.begun.emit(self)
            pending = set(range(len(self.figures)))
            while pending and not self.stopped.is_set():
                index = self.priority if self.priority in pending else min(pending)
                self.priority = None
                pending.remove(index)
                if self.source is not None:
                    figures.loaded_current(self.source)
                figure = self.figures[index]
                if self.source is not None:
                    digest = figure.meta.get("asset_sha256")
                    if (
                        not isinstance(digest, str)
                        or len(digest) != 64
                        or any(c not in "0123456789abcdef" for c in digest)
                    ):
                        raise ValueError("Figure has no generated asset proof")
                image, revision = decode(
                    figure.path,
                    figure.meta.get("asset_sha256") if self.source is not None else None,
                )
                if self.stopped.is_set():
                    return
                if self.lease is not None:
                    self.proof = figures.recheck_loaded_lease(
                        self.lease, cancelled=self.stopped.is_set
                    )
                row = Entry(self, index, self.figures[index], image, revision, proof=self.proof)
                self.waiting = row
                for attempt in range(2):
                    row.recheck = False
                    row.ack.clear()
                    self.entry.emit(row)
                    while not row.ack.wait(0.05):
                        if self.stopped.is_set():
                            return
                    if self.stopped.is_set():
                        return
                    if not row.recheck:
                        break
                    if attempt or self.lease is None:
                        raise figures.LeaseInterference("Figure delivery remained unstable")
                    row.proof = self.proof = figures.recheck_loaded_lease(
                        self.lease, cancelled=self.stopped.is_set
                    )
                self.waiting = None
            if self.lease is not None:
                self.proof = figures.recheck_loaded_lease(self.lease, cancelled=self.stopped.is_set)
            self.success = not self.stopped.is_set()
        except figures.SourceRevoked:
            self.failed = self.revoked = True
        except Exception:
            self.failed = True
        finally:
            self.waiting = None

    def _release(self):
        # Lifetime retained independently of a deleted parent widget until native drain.
        if not self.wait(0):
            QTimer.singleShot(10, self, self._release)
            return
        _LIVE.discard(self)
        owner = getattr(self, "owner_ref", lambda: None)()
        if owner is None or not isValid(owner) or owner._disposed:
            self.source = None
            self.deleteLater()


def capture(reader):
    """Capture only original loaded intent and native metadata on GUI; no SQL/hash."""
    from paper_daily import store

    view = getattr(reader, "_highlight_view", None)
    if view is None or view.owner is not getattr(reader, "_highlight_owner", None):
        return None
    owner = view.owner
    native = reader.pdf.position_identity()
    witness = reader.pdf.position_source_version()
    document = getattr(reader, "_active_document", None)
    if (
        native[1] is None
        or witness is None
        or Path(native[1]).resolve() != view.path
        or view.fingerprint != getattr(reader, "_pdf_fingerprint", None)
        or view.document is not document
    ):
        return None
    ref = weakref.ref(reader)
    database = owner.database

    def intent():
        r = ref()
        if r is None or not isValid(r) or Path(store.DB_PATH).resolve() != database:
            return None
        outer = getattr(r.win, "_workspace_owner", None)
        if outer is not None and not outer.current():
            return None
        if r.paper is None:
            return None
        actual = r.pdf.position_identity()
        active = getattr(r, "_active_document", None)
        database_version = version(database)
        if database_version is None or database_version[1] <= 0:
            return None
        return (
            id(r.paper),
            r.paper.id,
            r._qa_epoch,
            id(getattr(r, "_highlight_owner", None)),
            id(getattr(r, "_highlight_view", None)),
            id(active),
            id(getattr(active, "_owner", None)),
            getattr(getattr(active, "_owner", None), "_generation", None),
            getattr(getattr(active, "_owner", None), "_closed", False),
            r._pdf_fingerprint,
            actual[0],
            actual[1],
            id(actual[2]),
            r.pdf.position_source_version(),
            version(view.path),
            database_version[:2],
        )

    expected = intent()
    if expected is None or expected[-2] != witness:
        return None
    return Context(
        view,
        document,
        witness,
        Path(figures.FIG_DIR).resolve(),
        view.path.parent,
        lambda: intent() == expected,
        expected,
    )
