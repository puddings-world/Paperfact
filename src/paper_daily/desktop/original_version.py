"""Exact owned historical PDFs: immutable bytes and a separate read-only window."""

from __future__ import annotations

import hashlib
import sqlite3
import threading
from contextlib import closing
from dataclasses import dataclass, field
from pathlib import Path

import pymupdf
from PySide6.QtCore import (
    QBuffer,
    QByteArray,
    QIODevice,
    QPointF,
    Qt,
    QThread,
    QTimer,
    Signal,
    Slot,
)
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
)

from paper_daily import annotation_content, file_change, sync_capture, sync_source_files
from paper_daily.sync_artifacts import desired_file, paper_current
from paper_daily.sync_documents import MAX_PDF_BYTES
from paper_daily.sync_files import canonical_json, file_id

try:
    from PySide6.QtPdf import QPdfDocument
    from PySide6.QtPdfWidgets import QPdfView

    HAVE_QTPDF = True
except ImportError:
    HAVE_QTPDF = False


class OriginalUnavailable(ValueError):
    pass


_SNAPSHOT_SEAL = object()


@dataclass(frozen=True, init=False)
class OriginalSnapshot:
    owner: object = field(repr=False)
    portable_id: str | None
    document_hash: str
    data: bytes = field(repr=False)
    pages: int
    source: Path = field(repr=False)
    file_version: tuple = field(repr=False)
    operation: bytes | None = field(repr=False)
    claim: tuple | None = field(repr=False)
    registry: tuple | None = field(repr=False)
    local_proof: object | None = field(repr=False)
    _seal: object = field(repr=False)


def _connection(owner):
    return sqlite3.connect(
        owner.database.as_uri() + "?mode=ro",
        uri=True,
        factory=sync_capture.CaptureConnection,
        timeout=0.025,
    )


def _claim(conn, paper_id):
    row = conn.execute(
        "SELECT paper_id,CASE WHEN length(CAST(body_json AS BLOB))<=? THEN body_json END "
        "AS body_json,source_hash,document_hash,written_at FROM paper_claim_sets WHERE paper_id=?",
        (annotation_content.MAX_BYTES, paper_id),
    ).fetchone()
    if row is None or row["body_json"] is None:
        raise OriginalUnavailable("The displayed claim set is unavailable")
    return tuple(row)


def _registry(conn):
    row = conn.execute(
        "SELECT workspace,blob_root,version_root FROM research_file_paths WHERE id=1"
    ).fetchone()
    if row is None:
        raise OriginalUnavailable("Original source storage is not registered")
    return tuple(row)


def metadata_current(snapshot):
    """A short final metadata check; never rehashes or parses a PDF on the GUI thread."""
    if (
        not isinstance(snapshot, OriginalSnapshot)
        or getattr(snapshot, "_seal", None) is not _SNAPSHOT_SEAL
    ):
        return False
    try:
        if snapshot.local_proof is not None:
            from paper_daily import local_source_owners

            proof = snapshot.local_proof
            return bool(
                snapshot.data is proof.data
                and snapshot.source == proof.source
                and snapshot.file_version == proof.file_version
                and snapshot.document_hash == proof.document_hash
                and local_source_owners.metadata_current(proof)
            )
        with closing(_connection(snapshot.owner)) as conn:
            conn.execute("BEGIN")
            snapshot.owner.check(conn)
            identity = file_id(snapshot.portable_id, "original_source", snapshot.document_hash)
            target = desired_file(conn, identity)
            return bool(
                target
                and canonical_json(target) == snapshot.operation
                and paper_current(conn, target)
                and _claim(conn, snapshot.owner.paper_id) == snapshot.claim
                and _registry(conn) == snapshot.registry
                and file_change.version(snapshot.source) == snapshot.file_version
            )
    except (OSError, sqlite3.Error, ValueError):
        return False


def prepare(owner, expected, *, cancelled=lambda: False):
    """Inspect the existing owner's local or portable source without enrollment."""
    if cancelled():
        return None
    with closing(_connection(owner)) as conn:
        conn.execute("BEGIN")
        owner.check(conn)
        enrolled = sync_capture.enabled(conn)
    if enrolled:
        # Damage/retirement in a declared portable source never falls through to another cache.
        return _portable_prepare(owner, expected, cancelled=cancelled)
    return _local_prepare(owner, expected, cancelled=cancelled)


def _local_prepare(owner, expected, *, cancelled):
    from paper_daily import local_source_owners

    try:
        proof = local_source_owners.prepare(owner, expected, cancelled=cancelled)
        if proof is None or cancelled():
            return None
        if not isinstance(proof.data, bytes) or not 0 < len(proof.data) <= MAX_PDF_BYTES:
            raise OriginalUnavailable("Owned local original exceeds the PDF byte boundary")
        # The service has already verified SHA/native identity; only PDF parsing remains here.
        with pymupdf.open(stream=proof.data, filetype="pdf") as document:
            if document.is_encrypted or document.page_count < 1:
                raise OriginalUnavailable("Owned local original is not readable")
            pages = document.page_count
        if cancelled():
            return None
        snapshot = object.__new__(OriginalSnapshot)
        for name, value in dict(
            owner=owner,
            portable_id=None,
            document_hash=proof.document_hash,
            data=proof.data,
            pages=pages,
            source=proof.source,
            file_version=proof.file_version,
            operation=None,
            claim=None,
            registry=None,
            local_proof=proof,
            _seal=_SNAPSHOT_SEAL,
        ).items():
            object.__setattr__(snapshot, name, value)
        if not metadata_current(snapshot):
            raise OriginalUnavailable("Local original ownership changed before opening")
        return snapshot
    except (OSError, ValueError, sqlite3.Error) as error:
        raise OriginalUnavailable("No current owned local original is available") from error


def _portable_prepare(owner, expected, *, cancelled=lambda: False):
    """Resolve exactly one current owned source; no account, network, enrollment or write."""
    if cancelled():
        return None
    with closing(_connection(owner)) as conn:
        conn.execute("BEGIN")
        owner.check(conn)
        raw = _claim(conn, owner.paper_id)
        row = dict(
            zip(
                ("paper_id", "body_json", "source_hash", "document_hash", "written_at"),
                raw,
                strict=True,
            )
        )
        annotation_content.validate_row("claims", row)
        saved = {
            **annotation_content.decode("claims", row["body_json"]),
            "paper_id": owner.paper_id,
            "source_hash": row["source_hash"],
            "document_hash": row["document_hash"],
            "known": True,
        }
        if saved != expected:
            raise OriginalUnavailable("Displayed research changed")
        if not conn.execute(
            "SELECT 1 FROM sqlite_master WHERE name='research_paper_identity'"
        ).fetchone():
            raise OriginalUnavailable("No owned portable source is available")
        mapping = conn.execute(
            "SELECT sync_id FROM research_paper_identity WHERE local_id=?", (owner.paper_id,)
        ).fetchone()
        if mapping is None:
            raise OriginalUnavailable("No owned portable source is available")
        portable, digest = mapping[0], saved["document_hash"]
        source = sync_source_files.inspectable(conn, portable, digest)
        if source is None:
            raise OriginalUnavailable("Original version is not available on this device")
        target = desired_file(conn, file_id(portable, "original_source", digest))
        operation, registry = canonical_json(target), _registry(conn)
    if cancelled():
        return None
    with source.open("rb") as stream:
        version = file_change.version(source, stream=stream)
        if not 0 < version[2] <= MAX_PDF_BYTES:
            raise OriginalUnavailable("Original PDF exceeds its bounded size")
        data = stream.read(MAX_PDF_BYTES + 1)
        if version != file_change.version(source, stream=stream):
            raise OriginalUnavailable("Original version changed while reading")
    if len(data) != version[2] or hashlib.sha256(data).hexdigest() != digest:
        raise OriginalUnavailable("Original bytes differ from the displayed claim source")
    if cancelled():
        return None
    with pymupdf.open(stream=data, filetype="pdf") as document:
        if document.is_encrypted or document.page_count < 1:
            raise OriginalUnavailable("Original PDF is not readable")
        pages = document.page_count
    snapshot = object.__new__(OriginalSnapshot)
    for name, value in dict(
        owner=owner,
        portable_id=portable,
        document_hash=digest,
        data=data,
        pages=pages,
        source=source,
        file_version=version,
        operation=operation,
        claim=raw,
        registry=registry,
        local_proof=None,
        _seal=_SNAPSHOT_SEAL,
    ).items():
        object.__setattr__(snapshot, name, value)
    if cancelled():
        return None
    if not metadata_current(snapshot):
        raise OriginalUnavailable("Original ownership changed before opening")
    return snapshot


def render_page(snapshot, page, cancelled):
    """Fallback renders one bounded page off-thread, retaining only the current raster."""
    if cancelled() or not metadata_current(snapshot):
        return None
    with pymupdf.open(stream=snapshot.data, filetype="pdf") as document:
        source = document.load_page(page)
        area = max(source.rect.width * source.rect.height, 1)
        scale = min(1.6, (4_000_000 / area) ** 0.5)
        raster = source.get_pixmap(
            matrix=pymupdf.Matrix(scale, scale), colorspace=pymupdf.csRGB, alpha=False
        )
        result = (raster.samples, raster.width, raster.height, raster.stride, page)
    return None if cancelled() else result


class ViewerWorker(QThread):
    def __init__(self, call, parent):
        super().__init__(parent)
        self.call = call
        self.cancelled = threading.Event()
        self.result = self.error = None

    def run(self):
        try:
            self.result = self.call(self.cancelled.is_set)
        except Exception as error:
            self.error = type(error).__name__


class OriginalVersionDialog(QDialog):
    closed = Signal()
    invalidated = Signal()

    def __init__(self, snapshot, parent, *, current, language="en", native=None):
        if not metadata_current(snapshot):
            raise OriginalUnavailable("Original ownership changed before opening")
        super().__init__(parent)
        self.snapshot = snapshot
        self.current = current
        self.disposed = self._closing = False
        self._worker = None
        self._wanted_page, self._rendered_page = 0, -1
        self._needs_check = False
        self._pixmap = None
        self.native = HAVE_QTPDF if native is None else native and HAVE_QTPDF
        zh = language == "zh-TW"
        self.zh = zh
        self.setWindowTitle("原始版本 · 唯讀" if zh else "Original version · read-only")
        self.resize(860, 820)
        self.setFont(parent.font())
        p = parent.pal
        self.setStyleSheet(
            parent.styleSheet()
            + f"""
            QSpinBox, QComboBox {{ background:{p["surface"]}; color:{p["ink"]};
                border:1px solid {p["firm"]}; border-radius:6px; padding:5px 8px; }}
            QSpinBox:focus, QComboBox:focus {{ border:2px solid {p["accent"]}; }}
            QComboBox QAbstractItemView {{ background:{p["surface"]}; color:{p["ink"]};
                selection-background-color:{p["accentSoft"]}; }}
        """
        )
        layout = QVBoxLayout(self)
        heading = QLabel(
            ("原始版本 · " if zh else "Original version · ") + snapshot.document_hash[:12]
        )
        heading.setProperty("role", "title")
        layout.addWidget(heading)
        notice = QLabel(
            "唯讀原始快照；目前閱讀的文件維持原樣。"
            if zh
            else "Read-only original snapshot; the current reader keeps its document."
        )
        notice.setProperty("role", "meta")
        layout.addWidget(notice)
        tools = QHBoxLayout()
        tools.addWidget(QLabel("頁面" if zh else "Page"))
        self.page = QSpinBox()
        self.page.setRange(1, snapshot.pages)
        self.page.setSuffix(f" / {snapshot.pages}")
        self.page.valueChanged.connect(self._page_changed)
        tools.addWidget(self.page)
        self.zoom = QComboBox()
        self.zoom.addItems(["符合寬度" if zh else "Fit width", "100%", "125%", "150%"])
        self.zoom.currentIndexChanged.connect(self._zoom_changed)
        tools.addWidget(self.zoom)
        tools.addStretch()
        layout.addLayout(tools)
        self.status = QLabel("正在開啟原始版本…" if zh else "Opening original version…")
        self.status.setProperty("role", "meta")
        layout.addWidget(self.status)
        if self.native:
            self.pdf = QPdfDocument(self)
            self.view = QPdfView(self)
            self.view.setDocument(self.pdf)
            self.view.setPageMode(QPdfView.PageMode.MultiPage)
            self.view.setZoomMode(QPdfView.ZoomMode.FitToWidth)
            self._buffer = QBuffer(self)
            self._buffer.setData(QByteArray(snapshot.data))
            self._buffer.open(QIODevice.OpenModeFlag.ReadOnly)
            self.pdf.statusChanged.connect(self._native_status)
            self.view.pageNavigator().currentPageChanged.connect(self._native_page)
            layout.addWidget(self.view, 1)
            QTimer.singleShot(0, self._load_native)
        else:
            self.view = QScrollArea()
            self.image = QLabel()
            self.image.setAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop)
            self.view.setWidget(self.image)
            layout.addWidget(self.view, 1)
            QTimer.singleShot(0, self._render)
        close = QPushButton("關閉" if zh else "Close")
        close.clicked.connect(self.close)
        layout.addWidget(close, 0, Qt.AlignmentFlag.AlignRight)
        self.timer = QTimer(self)
        self.timer.setInterval(2000)
        self.timer.timeout.connect(self.check)
        self.timer.start()

    @property
    def busy(self):
        return self._worker is not None

    def _start(self, kind, call):
        if self.disposed or self._closing or self.busy:
            return False
        worker = ViewerWorker(call, self)
        worker.kind = kind
        self._worker = worker
        worker.finished.connect(self._finished)
        worker.start()
        return True

    @Slot()
    def _load_native(self):
        if not self.disposed and not self._closing:
            if not self.current() or not metadata_current(self.snapshot):
                self._invalidate()
                return
            self.pdf.load(self._buffer)

    @Slot(object)
    def _native_status(self, status):
        if self.disposed or self._closing:
            return
        if (
            status == QPdfDocument.Status.Error
            or status == QPdfDocument.Status.Ready
            and (self.pdf.pageCount() != self.snapshot.pages or not metadata_current(self.snapshot))
        ):
            self._invalidate()
        elif status == QPdfDocument.Status.Ready:
            self.status.clear()

    @Slot(int)
    def _native_page(self, page):
        self.page.blockSignals(True)
        self.page.setValue(page + 1)
        self.page.blockSignals(False)

    @Slot(int)
    def _page_changed(self, value):
        self._wanted_page = value - 1
        if self.native:
            self.view.pageNavigator().jump(value - 1, QPointF(0, 0))
        else:
            self._render()

    @Slot(int)
    def _zoom_changed(self, index):
        if self.native:
            self.view.setZoomMode(
                QPdfView.ZoomMode.FitToWidth if index == 0 else QPdfView.ZoomMode.Custom
            )
            if index:
                self.view.setZoomFactor([1.0, 1.0, 1.25, 1.5][index])
        elif self._pixmap is not None:
            width = (
                self.view.viewport().width()
                if index == 0
                else round(self._pixmap.width() * [1, 1, 1.25, 1.5][index])
            )
            width = min(
                width, round((4_000_000 * self._pixmap.width() / self._pixmap.height()) ** 0.5)
            )
            shown = self._pixmap.scaledToWidth(
                max(width - 4, 1), Qt.TransformationMode.SmoothTransformation
            )
            self.image.setPixmap(shown)
            self.image.resize(shown.size())

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if not self.native and self._pixmap is not None and self.zoom.currentIndex() == 0:
            self._zoom_changed(0)

    def _render(self):
        if self.busy or self.disposed or self._closing:
            return
        snapshot, page = self.snapshot, self._wanted_page
        self.status.setText(
            f"正在繪製第 {page + 1} 頁…" if self.zh else f"Rendering page {page + 1}…"
        )
        self._start("render", lambda cancelled: render_page(snapshot, page, cancelled))

    @Slot()
    def check(self):
        if self.disposed or self._closing:
            return
        if not self.current():
            self._invalidate()
        elif self.busy:
            self._needs_check = True
        else:
            snapshot = self.snapshot
            self._start("check", lambda cancelled: not cancelled() and metadata_current(snapshot))

    @Slot()
    def _finished(self):
        worker = self.sender()
        if worker is not self._worker:
            return
        self._worker = None
        if not self._closing:
            if (
                worker.error
                or not worker.result
                or not self.current()
                or not metadata_current(self.snapshot)
            ):
                self._invalidate()
            elif worker.kind == "render":
                raw, width, height, stride, page = worker.result
                if page == self._wanted_page:
                    self._pixmap = QPixmap.fromImage(
                        QImage(raw, width, height, stride, QImage.Format.Format_RGB888).copy()
                    )
                    self._rendered_page = page
                    self.status.clear()
                    self._zoom_changed(self.zoom.currentIndex())
        worker.deleteLater()
        if self._closing:
            self.close()
        elif not self.native and self._wanted_page != self._rendered_page:
            self._render()
        elif self._needs_check:
            self._needs_check = False
            self.check()

    def _invalidate(self):
        if not self.disposed and not self._closing:
            self.invalidated.emit()
            self.close()

    def reject(self):
        self.close()

    def closeEvent(self, event):
        self.timer.stop()
        if self.busy:
            self._closing = True
            self._worker.cancelled.set()
            event.ignore()
            return
        if self.native:
            self.pdf.close()
            self._buffer.close()
            self._buffer.setData(QByteArray())
        if not self.native:
            self.image.clear()
        self.snapshot = None
        self._pixmap = None
        self.disposed = True
        self.done(QDialog.DialogCode.Rejected)
        event.accept()
        self.closed.emit()
