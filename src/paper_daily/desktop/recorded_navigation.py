"""Explicit activity navigation, with no reader replacement on a passage action."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from paper_daily import file_change
from paper_daily.activity_projection import resume_matches


def blocked(window):
    reader = window.reader_page
    if reader.note_edit.toPlainText().strip() or reader.ask_box.text().strip():
        return True
    pane = reader.presentation_pane
    if (
        getattr(reader, "_pending", None) is not None
        or getattr(reader, "_passage", None) is not None
        or getattr(reader, "_qa_starting", False)
        or getattr(pane, "_dirty", False)
        or getattr(pane, "_canvas_dirty", False)
    ):
        return True
    for item in (
        reader.runner,
        pane,
        *(
            getattr(reader, name, None)
            for name in ("document_runner", "fetcher", "translate_runner", "refine_runner")
        ),
    ):
        value = getattr(item, "busy", False)
        if value() if callable(value) else value:
            return True
    return window.analysis_running()


def can_locate(window, row, *, database=None):
    reader = window.reader_page
    if database is not None and getattr(reader, "_qa_view_database", None) != Path(database):
        return False
    status = getattr(getattr(reader, "paper", None), "_document_status", None)
    return bool(
        status
        and getattr(status, "managed", False)
        and resume_matches(
            row,
            paper_id=getattr(status, "paper_id", None),
            loaded_hash=getattr(reader, "_pdf_fingerprint", None),
            current_hash=getattr(status, "sha256", None),
        )
    )


_SEAL = object()


@dataclass(frozen=True)
class ReaderCapture:
    reader: object
    paper: object
    local_id: object
    epoch: object
    database: object
    digest: object
    document: object
    owner: object
    pdf: object
    selection: object
    portable_id: object
    file_version: object
    status_digest: object
    managed: bool
    resolver: object
    source_generation: object
    source_closed: bool


def _capture(window):
    reader = window.reader_page
    paper = getattr(reader, "paper", None)
    document = getattr(reader, "_active_document", None)
    status = getattr(paper, "_document_status", None)
    pdf = getattr(reader, "pdf", None)
    return ReaderCapture(
        reader,
        paper,
        getattr(paper, "id", None),
        getattr(reader, "_qa_epoch", None),
        getattr(reader, "_qa_view_database", None),
        getattr(reader, "_pdf_fingerprint", None),
        document,
        getattr(reader, "_highlight_owner", None),
        pdf,
        getattr(pdf, "selection", None),
        getattr(status, "paper_id", None),
        file_change.version(document.path) if getattr(document, "path", None) else None,
        getattr(status, "sha256", None),
        bool(getattr(status, "managed", False)),
        getattr(paper, "_document_reader", None),
        getattr(getattr(document, "_owner", None), "_generation", None),
        bool(getattr(getattr(document, "_owner", None), "_closed", False)),
    )


@dataclass(frozen=True)
class PreparedNavigation:
    proof: object
    view: ReaderCapture
    locate: bool
    source_verified: bool
    _seal: object


def capture(window, service, observed, *, locate=False):
    """GUI capability capture only; returned task performs SQL and hashes off-thread."""
    view = _capture(window)
    observed = json.loads(json.dumps(observed))

    def prepare(ticket):
        from paper_daily.audit_inputs import verify_loaded_source

        selected = service.resolve(observed, locate=locate, ticket=ticket)
        verified = False
        if locate and (
            view.managed
            and view.status_digest == view.digest
            and view.owner is not None
            and view.document is not None
            and view.local_id == selected["local_paper_id"]
            and view.database == service.path
            and selected["note_anchor"] == selected["row"]["resume"]["anchor"]
            and resume_matches(
                selected["row"],
                paper_id=view.portable_id,
                loaded_hash=view.digest,
                current_hash=selected["current_hash"],
            )
        ):
            verified = verify_loaded_source(
                view.owner, view.document, view.digest, lambda: ticket.cancelled
            )
            if verified:
                verified = file_change.version(view.document.path) == view.file_version
        ticket.check()
        service.check(selected)
        return PreparedNavigation(selected, view, locate, bool(verified), _SEAL)

    return prepare


def activate(window, service, prepared, *, locate=None):
    """GUI-only delivery. The ordinary open callback retains its legacy I/O boundary."""
    if blocked(window):
        return "drafts"
    if (
        not isinstance(prepared, PreparedNavigation)
        or prepared._seal is not _SEAL
        or locate is not None
        and locate != prepared.locate
    ):
        return "changed"
    service.check(prepared.proof)  # Native DB/WAL versions, never SQLite.
    view = prepared.view
    current = _capture(window)
    objects = ("reader", "paper", "document", "owner", "pdf", "selection", "resolver")
    if any(getattr(current, key) is not getattr(view, key) for key in objects) or any(
        getattr(current, key) != getattr(view, key)
        for key in ReaderCapture.__dataclass_fields__
        if key not in objects
    ):
        return "source" if prepared.locate else "changed"
    selected = prepared.proof
    if prepared.locate:
        if not prepared.source_verified:
            return "source"
        anchor = selected["note_anchor"]
        return (
            "located" if view.selection is not None and view.selection.focus(anchor) else "missing"
        )
    if view.paper and view.local_id == selected["local_paper_id"] and view.database == service.path:
        window.stack.setCurrentWidget(view.reader)
        return "opened"
    previous = getattr(window, "_recorded_navigation", False)
    window._recorded_navigation = True
    try:
        return "opened" if window.open_anywhere(selected["local_paper_id"]) else "missing"
    finally:
        window._recorded_navigation = previous
