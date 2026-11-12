"""Read-only snapshot adapter for saved paper analysis; no implicit schema migration."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import closing
from dataclasses import dataclass, field
from pathlib import Path

from paper_daily import annotation_content, claim_content, file_change, research_audit, sync_capture
from paper_daily import research_evidence as evidence
from paper_daily import research_generation as generation
from paper_daily.document_reader import ResolvedDocument, document_current
from paper_daily.research_lifecycle import parent_lifecycle

MAX_ROWS = research_audit.MAX_ITEMS
_SEAL = object()


def _versions(database):
    return tuple(
        (str(path), file_change.version(path) if path.exists() else None)
        for path in (database, Path(str(database) + "-wal"))
    )


def _connect(database):
    conn = sqlite3.connect(
        database.as_uri() + "?mode=ro",
        uri=True,
        timeout=0.25,
        factory=sync_capture.CaptureConnection,
    )
    conn.row_factory = sqlite3.Row
    return conn


def _state(conn, database, paper_id):
    if not conn.execute("SELECT 1 FROM papers WHERE id=?", (paper_id,)).fetchone():
        raise research_audit.AuditError("paper_unavailable")
    return {
        "identity": generation._identity(database),
        "binding": generation._binding(conn),
        "parent": parent_lifecycle(conn, "paper", paper_id),
    }


def _rows(conn, table, columns, paper_id):
    # Only fixed in-module table/column names reach this SQL.
    fields = columns.split()
    length = "+".join('COALESCE(length(CAST("' + key + '" AS BLOB)),0)' for key in fields)
    count, size = conn.execute(
        f'SELECT count(*),COALESCE(SUM({length}),0) FROM "{table}" WHERE paper_id=?',
        (paper_id,),
    ).fetchone()
    if count > MAX_ROWS or size > research_audit.MAX_BYTES:
        raise research_audit.AuditError("input_limit")
    return [
        dict(row)
        for row in conn.execute(
            "SELECT "
            + ",".join('"' + key + '"' for key in fields)
            + f' FROM "{table}" WHERE paper_id=? '
            + "ORDER BY "
            + ",".join('"' + key + '"' for key in fields[:1])
            + " LIMIT ?",
            (paper_id, MAX_ROWS + 1),
        )
    ]


def _item(identity, feature, text, digest=None, passages=(), reference=None):
    return dict(
        id=identity,
        feature=feature,
        text=text,
        document_hash=digest,
        passages=list(passages),
        reference=reference,
    )


def _passage(quote, digest, page=None, anchor=None):
    return dict(quote=quote, document_hash=digest, page=page, anchor=anchor)


def _contexts(value):
    rows = json.loads(value or "[]")
    if not isinstance(rows, list) or len(rows) > 32:
        raise research_audit.AuditError("invalid_saved_content")
    texts = []
    for row in rows:
        if isinstance(row, str):
            texts.append(row)
        elif isinstance(row, dict) and isinstance(row.get("sentence"), str):
            texts.append(row["sentence"])
        elif isinstance(row, dict) and isinstance(row.get("text"), str):
            texts.append(row["text"])
        else:
            raise research_audit.AuditError("invalid_saved_content")
    return texts


def _note_source(row):
    """Association with a recorded original is not a claim that note prose is quoted."""
    from paper_daily.note_positions import validate as validate_note_anchor

    if row["anchor"] is None:
        return None
    try:
        anchor = json.loads(row["anchor"])
        validate_note_anchor(anchor)
        if anchor is None:
            return None
        if row["page"] not in (None, anchor["p0"] + 1):
            raise ValueError("Note page and anchor disagree")
        return anchor.get("document_hash")
    except (ValueError, TypeError, RecursionError, KeyError):
        raise research_audit.AuditError("invalid_saved_content") from None


def _chat_source(conn, local_id):
    from paper_daily.research_chat import validate_link

    fields = ["local_id", "message_id", "exchange_id", "reply_to", "source_hash"]
    size = conn.execute(
        "SELECT COALESCE(length(CAST(message_id AS BLOB)),0)+"
        "COALESCE(length(CAST(exchange_id AS BLOB)),0)+"
        "COALESCE(length(CAST(reply_to AS BLOB)),0)+"
        "COALESCE(length(CAST(source_hash AS BLOB)),0) FROM research_chat_links WHERE local_id=?",
        (local_id,),
    ).fetchone()
    if size is None:
        return None
    if size[0] > 512:
        raise research_audit.AuditError("input_limit")
    row = conn.execute(
        "SELECT local_id,message_id,exchange_id,reply_to,source_hash "
        "FROM research_chat_links WHERE local_id=?",
        (local_id,),
    ).fetchone()
    link = dict(zip(fields, row, strict=True))
    try:
        validate_link(link)
    except (ValueError, TypeError):
        raise research_audit.AuditError("invalid_saved_content") from None
    return link["source_hash"]


def _saved_rows(conn, table, fields, paper_id):
    expected = set(fields.split())
    actual = {row[1] for row in conn.execute(f'PRAGMA table_info("{table}")')}
    if actual != expected:
        raise research_audit.AuditError("invalid_saved_content")
    return _rows(conn, table, fields, paper_id)


def read_items(conn, paper_id):
    """Versionless legacy text stays unversioned; no old cache becomes authority."""
    tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    items = []
    for table, feature in (("dives", "dive"), ("close_readings", "close_reading")):
        for row in _rows(conn, table, "paper_id body", paper_id):
            items.append(_item(feature, feature, row["body"]))
    for row in _rows(conn, "notes", "id body kind page anchor", paper_id):
        items.append(_item("notes:" + str(row["id"]), "note", row["body"], _note_source(row)))
    for row in _rows(conn, "chat", "id body role", paper_id):
        if row["role"] != "assistant":
            continue
        digest = _chat_source(conn, row["id"]) if "research_chat_links" in tables else None
        items.append(_item("chat:" + str(row["id"]), "answer", row["body"], digest))
    for feature in ("claims", "highlight_analysis"):
        table = annotation_content.FEATURES[feature]
        if table not in tables:
            continue
        for row in _rows(
            conn, table, "paper_id body_json document_hash source_hash written_at", paper_id
        ):
            annotation_content.validate_row(feature, row)
            body = annotation_content.decode(feature, row["body_json"])
            digest = row["document_hash"]
            if feature == "claims":
                for claim in body["report"]["claims"]:
                    passages = [
                        _passage(p["quote"], digest, p["location"]["page"], p["location"]["anchor"])
                        for p in claim["passages"]
                    ]
                    items.append(
                        _item("claims:" + claim["id"], "claims", claim["text"], digest, passages)
                    )
            else:
                for index, highlight in enumerate(body["items"]):
                    items.append(
                        _item(
                            "highlights:" + str(index),
                            "highlights",
                            highlight["reason"],
                            digest,
                            [_passage(highlight["text"], digest, highlight["page"])],
                        )
                    )
    for row in _rows(conn, "pdf_highlights", "id document_hash quote anchor", paper_id):
        items.append(
            _item(
                "mark:" + str(row["id"]),
                "highlights",
                row["quote"],
                row["document_hash"],
                [_passage(row["quote"], row["document_hash"], anchor=json.loads(row["anchor"]))],
            )
        )
    for table, key in (("cites", "ref_key"), ("followups", "work_id")):
        columns = (
            f"{key} title doi s2_id basis contexts_json purpose"
            if table == "cites"
            else f"{key} title doi contexts_json relation"
        )
        for row in _rows(conn, table, columns, paper_id):
            other = conn.execute(
                "SELECT title,doi FROM papers WHERE id=?", (row.get("s2_id") or row[key],)
            ).fetchone()
            reference = dict(
                basis=row.get("basis", "unknown"),
                contexts=_contexts(row["contexts_json"]),
                proposed_title=row["title"] or None,
                resolved_title=other["title"] if other else None,
                proposed_doi=row["doi"] or None,
                resolved_doi=other["doi"] if other else None,
                relation=row.get("purpose") or row.get("relation") or None,
            )
            items.append(
                _item(
                    table + ":" + row[key],
                    "citations" if table == "cites" else "followups",
                    reference["relation"] or "",
                    reference=reference,
                )
            )
    from paper_daily.audit_saved_outputs import annotation_items, context_items

    try:
        related = None
        table = annotation_content.FEATURES["highlight_analysis"]
        if table in tables:
            matches = _saved_rows(conn, table, "paper_id " + annotation_content.FIELDS, paper_id)
            related = matches[0] if matches else None
        from paper_daily.reading_links import sections as explanation_sections

        explanation = []
        for name in ("dives", "close_readings"):
            saved = _rows(conn, name, "paper_id body", paper_id) if name in tables else []
            explanation.append(saved[0]["body"] if saved else "")
        parts = explanation_sections(*explanation)
        for feature in ("reading_links", "research_questions"):
            table = annotation_content.FEATURES[feature]
            if table in tables:
                for row in _saved_rows(
                    conn, table, "paper_id " + annotation_content.FIELDS, paper_id
                ):
                    items.extend(annotation_items(feature, row, related=related, sections=parts))
        if "paper_context" in tables:
            for row in _saved_rows(
                conn, "paper_context", "paper_id summary reading_json written_at edited", paper_id
            ):
                items.extend(context_items(row))
    except sqlite3.Error:
        raise research_audit.AuditError("invalid_saved_content") from None
    return research_audit.validate(items)


@dataclass(frozen=True)
class AuditCapture:
    database: Path
    paper_id: str
    _state_json: str = field(repr=False)
    _items_json: str = field(repr=False)
    _versions: tuple = field(repr=False)
    snapshot: evidence.EvidenceSnapshot = field(repr=False)
    _seal: object = field(repr=False)

    @classmethod
    def capture(cls, database, paper_id, *, document, owner=None):
        database = Path(database).resolve(strict=True)
        if (
            not isinstance(document, ResolvedDocument)
            or document.local_id != paper_id
            or document._owner.db_path.resolve() != database
        ):
            raise research_audit.AuditError("source_identity_mismatch")
        with closing(_connect(database)) as conn:
            conn.execute("BEGIN")
            if owner is not None:
                owner.check(conn)
            state = _state(conn, database, paper_id)
            items = read_items(conn, paper_id)
        snapshot = evidence.capture(document)
        # A completed WAL checkpoint can change physical bytes without changing
        # research. Recheck exact bounded semantic inputs, then require a native
        # stable observation THROUGH the final read/close, not a blind stat retry.
        versions = _versions(database)
        with closing(_connect(database)) as conn:
            conn.execute("BEGIN")
            if owner is not None:
                owner.check(conn)
            final_state = _state(conn, database, paper_id)
            final_items = read_items(conn, paper_id)
        if state != final_state or items != final_items or versions != _versions(database):
            raise research_audit.AuditError("saved_content_changed")
        return cls(
            database,
            paper_id,
            generation._json(state),
            generation._json(items),
            versions,
            snapshot,
            _SEAL,
        )

    def current(self):
        try:
            return self._seal is _SEAL and _versions(self.database) == self._versions
        except (ValueError, OSError):
            return False

    def run(self, *, cancelled=lambda: False, progress=lambda done, total: None):
        if not self.current():
            raise research_audit.AuditError("saved_content_changed")
        report = research_audit.run(
            self.snapshot, json.loads(self._items_json), cancelled=cancelled, progress=progress
        )
        if not self.current():
            raise research_audit.AuditError("saved_content_changed")
        # Explicit coverage is as important as the returned findings.
        report.pop("id")
        report["not_checked"] += ["editable_decks", "list_surveys", "grounded_lineage"]
        return {**report, "id": claim_content.hashed(report)}


def verify_loaded_source(owner, document, digest, cancelled):
    """Read-only owner/byte verification; do not checkpoint a sealed audit's WAL."""
    if cancelled() or not isinstance(document, ResolvedDocument):
        return False
    database = owner.database
    with closing(_connect(database)) as conn:
        owner.check(conn)
    if (
        document.local_id != owner.paper_id
        or document._owner.db_path.resolve() != database
        or not document.available
        or document.sha256 != digest
        or not document_current(document)
    ):
        return False
    with document.path.open("rb") as stream:
        if hashlib.file_digest(stream, "sha256").hexdigest() != digest:
            return False
    with closing(_connect(database)) as conn:
        owner.check(conn)
    return not cancelled() and document_current(document)
