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
    retained_proof: object | None = field(default=None, repr=False)
    active_proof: object | None = field(default=None, repr=False)
    material_proof: object | None = field(default=None, repr=False)
    draft_proof: object | None = field(default=None, repr=False)
    claim_read_proof: object | None = field(default=None, repr=False)
    highlight_read_proof: object | None = field(default=None, repr=False)


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
        if getattr(snapshot, "highlight_read_proof", None) is not None:
            return highlight_read_status(snapshot) == "ready"
        if getattr(snapshot, "claim_read_proof", None) is not None:
            return claim_read_status(snapshot) == "ready"
        proof = getattr(snapshot, "draft_proof", None)
        if proof is not None:
            return draft_status(snapshot) == "ready"
        proof = getattr(snapshot, "material_proof", None)
        if proof is not None:
            return material_status(snapshot) == "ready"
        proof = getattr(snapshot, "active_proof", None)
        if proof is not None:
            return active_status(snapshot) == "ready"
        proof = getattr(snapshot, "retained_proof", None)
        if proof is not None:
            from paper_daily import retained_originals

            return bool(
                snapshot.data is proof.data
                and snapshot.source == proof.source
                and snapshot.document_hash == proof.document_hash
                and snapshot.file_version == proof.file_version
                and retained_originals.metadata_current(proof)
            )
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


def active_status(snapshot):
    """Native-only status for the separately sealed active saved-deck adapter."""
    from paper_daily import active_deck_originals

    proof = getattr(snapshot, "active_proof", None)
    if (
        not isinstance(snapshot, OriginalSnapshot)
        or getattr(snapshot, "_seal", None) is not _SNAPSHOT_SEAL
        or getattr(snapshot, "claim_read_proof", None) is not None
        or getattr(snapshot, "highlight_read_proof", None) is not None
        or proof is None
        or snapshot.data is not proof.data
        or snapshot.document_hash != proof.document_hash
        or snapshot.pages != proof.pages
        or snapshot.source != proof.source_path
    ):
        return "revoked"
    return active_deck_originals.gui_status(proof)


def material_status(snapshot):
    from paper_daily import material_sources

    proof = getattr(snapshot, "material_proof", None)
    if (
        not isinstance(snapshot, OriginalSnapshot)
        or getattr(snapshot, "_seal", None) is not _SNAPSHOT_SEAL
        or not isinstance(proof, material_sources.OriginalProof)
        or getattr(snapshot, "claim_read_proof", None) is not None
        or getattr(snapshot, "highlight_read_proof", None) is not None
        or getattr(snapshot, "active_proof", None) is not None
        or snapshot.data is not proof.data
        or snapshot.document_hash != proof.document_hash
        or snapshot.pages != proof.pages
        or snapshot.source != proof.source_path
    ):
        return "revoked"
    return material_sources.gui_status(proof)


def draft_status(snapshot):
    from paper_daily import resumed_draft_originals

    proof = getattr(snapshot, "draft_proof", None)
    if (
        not isinstance(snapshot, OriginalSnapshot)
        or getattr(snapshot, "_seal", None) is not _SNAPSHOT_SEAL
        or not isinstance(proof, resumed_draft_originals.OriginalProof)
        or any(
            getattr(snapshot, name, None) is not None
            for name in (
                "local_proof",
                "retained_proof",
                "active_proof",
                "material_proof",
                "claim_read_proof",
                "highlight_read_proof",
            )
        )
        or snapshot.data is not proof.data
        or snapshot.document_hash != proof.document_hash
        or snapshot.pages != proof.pages
        or snapshot.source != proof.source_path
        or snapshot.file_version != proof.file_version
    ):
        return "revoked"
    return resumed_draft_originals.gui_status(proof)


def _read_status(snapshot, domain):
    """Only a separately sealed typed read can enter this native-only admission."""
    from paper_daily import claim_draft_originals, highlight_draft_originals
    from paper_daily.review_draft_originals import DraftReadProof

    if domain not in {"claim_resume", "highlight_resume"}:
        return "revoked"
    field_name = "claim_read_proof" if domain == "claim_resume" else "highlight_read_proof"
    proof = getattr(snapshot, field_name, None)
    excluded = {
        "owner",
        "portable_id",
        "operation",
        "claim",
        "registry",
        "local_proof",
        "retained_proof",
        "active_proof",
        "material_proof",
        "draft_proof",
        "claim_read_proof",
        "highlight_read_proof",
    } - {field_name}
    if (
        not isinstance(snapshot, OriginalSnapshot)
        or getattr(snapshot, "_seal", None) is not _SNAPSHOT_SEAL
        or not isinstance(proof, DraftReadProof)
        or proof.domain != domain
        or any(getattr(snapshot, name, None) is not None for name in excluded)
        or snapshot.data is not proof.data
        or snapshot.document_hash != proof.document_hash
        or snapshot.pages != proof.pages
        or snapshot.source != proof.source_path
        or snapshot.file_version != proof.file_version
    ):
        return "revoked"
    adapter = claim_draft_originals if domain == "claim_resume" else highlight_draft_originals
    return adapter.gui_status(proof)


def claim_read_status(snapshot):
    return _read_status(snapshot, "claim_resume")


def highlight_read_status(snapshot):
    return _read_status(snapshot, "highlight_resume")


def _read_snapshot(proof, domain):
    snapshot = object.__new__(OriginalSnapshot)
    values = dict(
        owner=None,
        portable_id=None,
        document_hash=proof.document_hash,
        data=proof.data,
        pages=proof.pages,
        source=proof.source_path,
        file_version=proof.file_version,
        operation=None,
        claim=None,
        registry=None,
        local_proof=None,
        retained_proof=None,
        active_proof=None,
        material_proof=None,
        draft_proof=None,
        claim_read_proof=None,
        highlight_read_proof=None,
        _seal=_SNAPSHOT_SEAL,
    )
    if domain not in {"claim_resume", "highlight_resume"} or proof.domain != domain:
        raise OriginalUnavailable("Independent original has a different review domain")
    values["claim_read_proof" if domain == "claim_resume" else "highlight_read_proof"] = proof
    for name, value in values.items():
        object.__setattr__(snapshot, name, value)
    if not metadata_current(snapshot):
        raise OriginalUnavailable("Original changed before delivery")
    return snapshot


def _claim_read_snapshot(proof):
    return _read_snapshot(proof, "claim_resume")


def prepare_highlight_draft_read(
    service, preview, document_hash, *, reference=None, cancelled=lambda: False
):
    from paper_daily import highlight_draft_originals

    if cancelled():
        return None
    try:
        proof = highlight_draft_originals.prepare(
            service, preview, document_hash, reference=reference, cancelled=cancelled
        )
        return None if cancelled() else _read_snapshot(proof, "highlight_resume")
    except (OSError, ValueError, RuntimeError, sqlite3.Error) as error:
        if cancelled():
            return None
        raise OriginalUnavailable("Highlight original is not independently available") from error


def refresh_highlight_draft_read(snapshot, cancelled):
    from paper_daily import highlight_draft_originals

    if cancelled():
        return None
    try:
        proof = highlight_draft_originals.revalidate(
            snapshot.highlight_read_proof, cancelled=cancelled
        )
        return None if cancelled() else _read_snapshot(proof, "highlight_resume")
    except (OSError, ValueError, RuntimeError, sqlite3.Error) as error:
        if cancelled():
            return None
        raise OriginalUnavailable("Highlight original read permission changed") from error


def prepare_claim_draft_read(
    service, preview, document_hash, *, reference=None, cancelled=lambda: False
):
    from paper_daily import claim_draft_originals

    if cancelled():
        return None
    try:
        proof = claim_draft_originals.prepare(
            service, preview, document_hash, reference=reference, cancelled=cancelled
        )
        return None if cancelled() else _claim_read_snapshot(proof)
    except (OSError, ValueError, RuntimeError, sqlite3.Error) as error:
        if cancelled():
            return None
        raise OriginalUnavailable("Claim original is not independently available") from error


def refresh_claim_draft_read(snapshot, cancelled):
    from paper_daily import claim_draft_originals

    if cancelled():
        return None
    try:
        proof = claim_draft_originals.revalidate(snapshot.claim_read_proof, cancelled=cancelled)
        return None if cancelled() else _claim_read_snapshot(proof)
    except (OSError, ValueError, RuntimeError, sqlite3.Error) as error:
        if cancelled():
            return None
        raise OriginalUnavailable("Claim original read permission changed") from error


def _draft_snapshot(proof):
    from paper_daily import resumed_draft_originals

    if resumed_draft_originals.gui_status(proof) != "ready":
        raise OriginalUnavailable("Resumed draft original changed before delivery")
    snapshot = object.__new__(OriginalSnapshot)
    for name, value in dict(
        owner=None,
        portable_id=None,
        document_hash=proof.document_hash,
        data=proof.data,
        pages=proof.pages,
        source=proof.source_path,
        file_version=proof.file_version,
        operation=None,
        claim=None,
        registry=None,
        local_proof=None,
        retained_proof=None,
        active_proof=None,
        material_proof=None,
        draft_proof=proof,
        _seal=_SNAPSHOT_SEAL,
    ).items():
        object.__setattr__(snapshot, name, value)
    if not metadata_current(snapshot):
        raise OriginalUnavailable("Resumed draft original changed before delivery")
    return snapshot


def prepare_resumed_draft(service, preview, document_hash, *, cancelled=lambda: False):
    from paper_daily import resumed_draft_originals

    if cancelled():
        return None
    try:
        proof = resumed_draft_originals.prepare(
            service, preview, document_hash, cancelled=cancelled
        )
        return None if cancelled() else _draft_snapshot(proof)
    except (OSError, ValueError, RuntimeError, sqlite3.Error) as error:
        if cancelled():
            return None
        raise OriginalUnavailable(
            "Resumed draft original unavailable; verify draft sources and retry"
        ) from error


def refresh_draft(snapshot, cancelled):
    from paper_daily import resumed_draft_originals

    if cancelled():
        return None
    try:
        proof = resumed_draft_originals.revalidate(snapshot.draft_proof, cancelled=cancelled)
        return None if cancelled() else _draft_snapshot(proof)
    except (OSError, ValueError, RuntimeError, sqlite3.Error) as error:
        if cancelled():
            return None
        raise OriginalUnavailable(
            "Resumed draft original unavailable; verify draft sources and retry"
        ) from error


def prepare_material(proof):
    """Worker adapter for its own collected-material permission; no deck or claim."""
    from paper_daily import material_sources

    if material_sources.gui_status(proof) != "ready":
        raise OriginalUnavailable("Collected original changed before delivery")
    snapshot = object.__new__(OriginalSnapshot)
    for name, value in dict(
        owner=None,
        portable_id=None,
        document_hash=proof.document_hash,
        data=proof.data,
        pages=proof.pages,
        source=proof.source_path,
        file_version=file_change.version(proof.source_path),
        operation=None,
        claim=None,
        registry=None,
        local_proof=None,
        retained_proof=None,
        active_proof=None,
        material_proof=proof,
        _seal=_SNAPSHOT_SEAL,
    ).items():
        object.__setattr__(snapshot, name, value)
    if not metadata_current(snapshot):
        raise OriginalUnavailable("Collected original changed before delivery")
    return snapshot


def refresh_material(snapshot, cancelled):
    from paper_daily import material_sources

    proof = material_sources.revalidate(snapshot.material_proof, current=lambda: not cancelled())
    return None if cancelled() else prepare_material(proof)


def prepare_active(proof):
    """Worker-only adapter; the active reader, claims and retained grants stay separate."""
    from paper_daily import active_deck_originals

    if active_deck_originals.gui_status(proof) != "ready":
        raise OriginalUnavailable("Saved-deck original changed before delivery")
    snapshot = object.__new__(OriginalSnapshot)
    for name, value in dict(
        owner=None,
        portable_id=None,
        document_hash=proof.document_hash,
        data=proof.data,
        pages=proof.pages,
        source=proof.source_path,
        file_version=file_change.version(proof.source_path),
        operation=None,
        claim=None,
        registry=None,
        local_proof=None,
        retained_proof=None,
        active_proof=proof,
        _seal=_SNAPSHOT_SEAL,
    ).items():
        object.__setattr__(snapshot, name, value)
    if not metadata_current(snapshot):
        raise OriginalUnavailable("Saved-deck original changed before delivery")
    return snapshot


def refresh_active(snapshot, cancelled):
    from paper_daily import active_deck_originals

    proof = active_deck_originals.revalidate(snapshot.active_proof, current=lambda: not cancelled())
    return None if cancelled() else prepare_active(proof)


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


def prepare_retained(service, preview, document_hash, *, cancelled=lambda: False):
    """Worker adapter for a declared proposal original; never read a current PDF."""
    from paper_daily import retained_originals

    try:
        proof = retained_originals.prepare(service, preview, document_hash, cancelled=cancelled)
        if proof is None or cancelled():
            return None
        with pymupdf.open(stream=proof.data, filetype="pdf") as document:
            if document.is_encrypted or document.page_count < 1:
                raise OriginalUnavailable("The retained original is not a readable PDF")
            pages = document.page_count
        if cancelled():
            return None
        snapshot = object.__new__(OriginalSnapshot)
        for name, value in dict(
            owner=service,
            portable_id=None,
            document_hash=proof.document_hash,
            data=proof.data,
            pages=pages,
            source=proof.source,
            file_version=proof.file_version,
            operation=proof.operation,
            claim=None,
            registry=None,
            local_proof=None,
            retained_proof=proof,
            _seal=_SNAPSHOT_SEAL,
        ).items():
            object.__setattr__(snapshot, name, value)
        if not metadata_current(snapshot):
            raise OriginalUnavailable("The retained original changed before opening")
        return snapshot
    except (OSError, ValueError, RuntimeError, sqlite3.Error) as error:
        if cancelled():
            return None
        raise OriginalUnavailable(
            "Retained original unavailable; refresh or check retained files"
        ) from error


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

    def __init__(self, snapshot, parent, *, current, language="en", native=None, palette=None):
        if not metadata_current(snapshot):
            raise OriginalUnavailable("Original ownership changed before opening")
        super().__init__(parent)
        self.snapshot = snapshot
        self.current = current
        self.disposed = self._closing = False
        self._worker = None
        self._wanted_page, self._rendered_page = 0, -1
        self._needs_check = False
        self._native_loaded = False
        self._pixmap = None
        self.native = HAVE_QTPDF if native is None else native and HAVE_QTPDF
        zh = language == "zh-TW"
        self.zh = zh
        self.setWindowTitle("原始版本 · 唯讀" if zh else "Original version · read-only")
        self.resize(860, 820)
        self.setFont(parent.font())
        p = parent.pal if palette is None else palette
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

    def _admit(self):
        """Pause a changed metadata fence for worker revalidation; never adopt new authority."""
        if not self.current():
            self._invalidate()
            return False
        material = getattr(self.snapshot, "material_proof", None) is not None
        draft = getattr(self.snapshot, "draft_proof", None) is not None
        claim_read = getattr(self.snapshot, "claim_read_proof", None) is not None
        highlight_read = getattr(self.snapshot, "highlight_read_proof", None) is not None
        if (
            highlight_read
            or claim_read
            or draft
            or material
            or getattr(self.snapshot, "active_proof", None) is not None
        ):
            state = (
                highlight_read_status(self.snapshot)
                if highlight_read
                else claim_read_status(self.snapshot)
                if claim_read
                else draft_status(self.snapshot)
                if draft
                else material_status(self.snapshot)
                if material
                else active_status(self.snapshot)
            )
            if state == "recheck":
                self.view.setEnabled(False)
                self.status.setText(
                    "正在重新核對引用來源…" if self.zh else "Rechecking cited source…"
                )
                if not self.busy:
                    snapshot = self.snapshot
                    refresh = (
                        refresh_highlight_draft_read
                        if highlight_read
                        else refresh_claim_draft_read
                        if claim_read
                        else refresh_draft
                        if draft
                        else refresh_material
                        if material
                        else refresh_active
                    )
                    self._start("refresh", lambda cancelled: refresh(snapshot, cancelled))
                return False
            if state == "revoked":
                self._invalidate()
                return False
        elif not metadata_current(self.snapshot):
            self._invalidate()
            return False
        self.view.setEnabled(True)
        return True

    @Slot()
    def _load_native(self):
        if not self.disposed and not self._closing:
            if not self._admit():
                return
            self._native_loaded = True
            self.pdf.load(self._buffer)

    @Slot(object)
    def _native_status(self, status):
        if self.disposed or self._closing:
            return
        if (
            status == QPdfDocument.Status.Error
            or status == QPdfDocument.Status.Ready
            and self.pdf.pageCount() != self.snapshot.pages
        ):
            self._invalidate()
        elif status == QPdfDocument.Status.Ready and self._admit():
            self.status.clear()
            self.view.pageNavigator().jump(self._wanted_page, QPointF(0, 0))

    @Slot(int)
    def _native_page(self, page):
        self.page.blockSignals(True)
        self.page.setValue(page + 1)
        self.page.blockSignals(False)

    @Slot(int)
    def _page_changed(self, value):
        self._wanted_page = value - 1
        if self.native:
            if self._admit():
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
        if self.busy or self.disposed or self._closing or not self._admit():
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
        if not self._admit():
            return
        if self.busy:
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
        if worker.kind == "refresh" and not self._closing:
            if worker.error or not worker.result:
                self._invalidate()
            else:
                self.snapshot = worker.result
        if not self._closing:
            if not self._admit():
                pass
            elif worker.error or not worker.result or not self.current():
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
            elif worker.kind == "refresh":
                self.status.clear()
                if self.native and not self._native_loaded:
                    self._load_native()
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
