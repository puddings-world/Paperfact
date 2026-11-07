"""Observed local highlight edits; the displayed PDF and workspace own the write.

Legacy pdf_highlights helpers remain compatibility APIs. Actual reader actions use
this explicit owner/view contract, including when synchronization is not enrolled.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import closing, contextmanager
from dataclasses import dataclass
from pathlib import Path

from paper_daily import pdf_highlights, sync_capture
from paper_daily import research_generation as generation
from paper_daily.research_lifecycle import ensure_lifecycle, parent_lifecycle
from paper_daily.store import now
from paper_daily.sync_documents import MAX_PDF_BYTES

MAX_MARKS = 5000
MAX_SNAPSHOT_BYTES = 4 * 1024 * 1024
ANCHOR_KEYS = {"p0", "o0", "p1", "o1"}


def _json(value):
    result = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    if len(result.encode()) > MAX_SNAPSHOT_BYTES:
        raise ValueError("Highlight view exceeds its local snapshot budget")
    return result


def _parent_graph(conn, paper_id):
    if not sync_capture.enabled(conn):
        if conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='research_sync_binding'"
        ).fetchone() and conn.execute("SELECT 1 FROM research_sync_binding").fetchone():
            raise ValueError("Sync capture is not installed; finish workspace setup before editing")
        return None
    row = conn.execute(
        "SELECT sync_id FROM research_paper_identity WHERE local_id=?", (paper_id,)
    ).fetchone()
    if row is None:
        raise ValueError("The paper has no synchronized identity")
    token = sync_capture.observe(conn, "paper", row[0])
    if not token["active"]:
        raise ValueError("The synchronized paper is no longer active")
    return {key: token[key] for key in ("entity_id", "incarnation", "active")}


@dataclass(frozen=True)
class HighlightOwner:
    database: Path
    paper_id: str
    _json: str

    def check(self, conn):
        expected = json.loads(self._json)
        if (generation._path(conn) != str(self.database)
                or generation._identity(self.database) != expected["database_identity"]
                or generation._binding(conn) != expected["binding"]
                or parent_lifecycle(conn, "paper", self.paper_id) != expected["parent"]
                or not conn.execute("SELECT 1 FROM papers WHERE id=?", (self.paper_id,)).fetchone()
                or _parent_graph(conn, self.paper_id) != expected["graph"]):
            raise ValueError("Loaded paper or workspace changed; reopen the paper before editing")


def capture_owner_in(conn, paper_id, *, expected_identity=None, initialize=True):
    """Capture actual owner metadata in the caller's transaction; never commit."""
    if not conn.in_transaction:
        raise ValueError("Highlight owner capture requires a caller transaction")
    database = Path(generation._path(conn)).resolve(strict=True)
    identity = generation._identity(database)
    if expected_identity is not None and identity != expected_identity:
        raise ValueError("Highlight owner changed during capture")
    if not conn.execute("SELECT 1 FROM papers WHERE id=?", (paper_id,)).fetchone():
        raise ValueError("Highlight paper is no longer present")
    if initialize:
        ensure_lifecycle(conn)
    data = dict(
        database_identity=identity, binding=generation._binding(conn),
        parent=parent_lifecycle(conn, "paper", paper_id),
        graph=_parent_graph(conn, paper_id),
    )
    if not data["parent"] or generation._identity(database) != identity:
        raise ValueError("Highlight owner changed during capture")
    return HighlightOwner(database, paper_id, _json(data))


def capture_owner(database, paper_id):
    """Capture at actual ReaderPage.load, before PDF loading or selection is possible."""
    database = Path(database).resolve(strict=True)
    identity = generation._identity(database)
    with closing(generation._connect(database)) as conn:
        conn.execute("BEGIN IMMEDIATE")
        try:
            owner = capture_owner_in(conn, paper_id, expected_identity=identity)
            if generation._identity(database) != identity:
                raise ValueError("Highlight owner changed during capture")
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
    return owner


def _readonly_connection(database):
    conn = sqlite3.connect(
        Path(database).as_uri() + "?mode=ro", uri=True,
        factory=sync_capture.CaptureConnection, timeout=0.05,
    )
    conn.row_factory = sqlite3.Row
    return conn


def observe_owner(database, paper_id, *, expected_native):
    """Read an existing native paper lifetime; create no schema, identity or receipt."""
    database = Path(database).resolve(strict=True)
    expected = list(expected_native)
    if (len(expected) != 2 or any(type(n) is not int for n in expected)
            or expected[0] < 0 or expected[1] <= 0
            or generation._identity(database) != expected):
        raise ValueError("Observed paper database changed")
    with closing(_readonly_connection(database)) as conn:
        conn.execute("BEGIN")
        owner = capture_owner_in(conn, paper_id, expected_identity=expected, initialize=False)
        owner.check(conn)
        conn.rollback()
    if generation._identity(database) != expected:
        raise ValueError("Observed paper database changed")
    return owner


def _file_identity(path):
    info = path.stat()
    if not 0 < info.st_size <= MAX_PDF_BYTES:
        raise ValueError("Displayed PDF exceeds the supported verification budget")
    return [info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns]



@contextmanager
def _pdf_document(path):
    import pymupdf

    try:
        with pymupdf.open(path) as pdf:
            yield pdf
    except RuntimeError as exc:
        raise ValueError("PDF verification failed; reopen the original before editing") from exc


def _source(view):
    if _file_identity(view.path) != view.file_identity:
        raise ValueError("The displayed PDF changed; reload before editing highlights")
    if view.document is not None:
        resolver = getattr(view.document, "_owner", None)
        if resolver is None or not resolver.intact(view.document):
            raise ValueError("The displayed PDF no longer belongs to this workspace")
    if pdf_highlights.document_hash(view.path) != view.fingerprint:
        raise ValueError("The displayed PDF hash no longer matches")


def _read(conn, owner, fingerprint):
    data = []
    for table, sign in (("pdf_highlights", 1), ("pdf_ai_highlights", -1)):
        fields = ("quote", "anchor", "created_at") if sign > 0 else (
            "quote", "anchor", "source_key", "analysis_hash", "reason"
        )
        lengths = "+".join(f"COALESCE(length(CAST({name} AS BLOB)),0)" for name in fields)
        count, size = conn.execute(
            f"SELECT COUNT(*),COALESCE(SUM({lengths}),0) FROM {table} "
            "WHERE paper_id=? AND document_hash=?", (owner.paper_id, fingerprint),
        ).fetchone()
        if count > MAX_MARKS or size > MAX_SNAPSHOT_BYTES // 2:
            raise ValueError("Highlight rows exceed the local view budget")
        rows = conn.execute(
            f"SELECT * FROM {table} WHERE paper_id=? AND document_hash=? ORDER BY id LIMIT ?",
            (owner.paper_id, fingerprint, MAX_MARKS + 1),
        ).fetchall()
        if len(rows) > MAX_MARKS:
            raise ValueError("Too many highlights to safely edit this view")
        for row in rows:
            row = dict(row)
            data.append(dict(table=table, id=sign * row["id"], row=row,
                             observation=sync_capture.observe_content(conn, table, row)))
    _json(data)
    return data



def _analysis(conn, paper_id):
    from paper_daily import annotation_content

    tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if "paper_highlight_analysis" in tables:
        size = conn.execute(
            "SELECT length(CAST(body_json AS BLOB)) FROM paper_highlight_analysis WHERE paper_id=?",
            (paper_id,),
        ).fetchone()
        if size and size[0] > annotation_content.MAX_BYTES:
            raise ValueError("Highlight analysis exceeds its view budget")
    row = (conn.execute("SELECT * FROM paper_highlight_analysis WHERE paper_id=?", (paper_id,))
           .fetchone() if "paper_highlight_analysis" in tables else None)
    if row is not None:
        data = annotation_content.validate_row("highlight_analysis", dict(row))
        items = json.loads(data["body_json"])["items"]
        keys = {
            hashlib.sha256(f"{item['page']}:{item['text']}".encode()).hexdigest(): item["text"]
            for item in items if type(item["page"]) is int
        }
        return dict(known=True, source_hash=data["source_hash"],
                    document_hash=data["document_hash"], keys=keys)
    known = ("paper_annotation_known" in tables and conn.execute(
        "SELECT 1 FROM paper_annotation_known WHERE feature='highlight_analysis' AND paper_id=?",
        (paper_id,),
    ).fetchone() is not None)
    return dict(known=bool(known), source_hash=None, document_hash=None, keys={})


@dataclass(frozen=True)
class HighlightView:
    owner: HighlightOwner
    path: Path
    fingerprint: str
    _json: str
    _identity_json: str
    document: object = None
    _analysis_json: str = '{"known":false}'

    @property
    def file_identity(self):
        return json.loads(self._identity_json)

    @property
    def records(self):
        return json.loads(self._json)

    @property
    def marks(self):
        result = []
        analysis = json.loads(self._analysis_json)
        for record in self.records:
            row = record["row"]
            if record["id"] < 0:
                if row["hidden"]:
                    continue
                if analysis["known"] and (
                        analysis["document_hash"] != self.fingerprint
                        or analysis["source_hash"] != row["analysis_hash"]
                        or analysis["keys"].get(row["source_key"]) != row["quote"]):
                    continue
            mark = dict(id=record["id"], anchor=json.loads(row["anchor"]), quote=row["quote"],
                        origin="manual" if record["id"] > 0 else "ai")
            if record["id"] < 0:
                mark["reason"] = row["reason"]
            result.append(mark)
        return result


def load(owner, path, fingerprint, *, document=None, readonly=False):
    """Load displayed mark rows and their exact observations, not the current global DB."""
    if not isinstance(owner, HighlightOwner):
        raise ValueError("Reopen a stored paper before editing its highlights")
    if (not isinstance(fingerprint, str) or len(fingerprint) != 64
            or any(char not in "0123456789abcdef" for char in fingerprint)):
        raise ValueError("A verified displayed PDF hash is required")
    path = Path(path).resolve(strict=True)
    if document is not None and (
            document.path != path or document.sha256 != fingerprint
            or document.local_id != owner.paper_id):
        raise ValueError("Displayed document does not match the loaded paper")
    view = HighlightView(owner, path, fingerprint, "[]", _json(_file_identity(path)), document)
    _source(view)
    with _pdf_document(path) as pdf:
        page_count = len(pdf)
    connection = _readonly_connection if readonly else generation._connect
    with closing(connection(owner.database)) as conn:
        conn.execute("BEGIN")
        owner.check(conn)
        records = _read(conn, owner, fingerprint)
        analysis = _analysis(conn, owner.paper_id)
        for record in records:
            anchor = json.loads(record["row"]["anchor"])
            if (not isinstance(anchor, dict) or not set(anchor) >= ANCHOR_KEYS
                    or any(type(anchor[key]) is not int or anchor[key] < 0 for key in ANCHOR_KEYS)
                    or anchor["p1"] >= page_count or anchor["p1"] - anchor["p0"] > 100
                    or (anchor["p0"], anchor["o0"]) > (anchor["p1"], anchor["o1"])
                    or anchor.get("document_hash", fingerprint) != fingerprint):
                raise ValueError("Saved highlight coordinates are not valid for this PDF")
        owner.check(conn)
        conn.rollback()
    return HighlightView(owner, path, fingerprint, _json(records), view._identity_json,
                         document, _json(analysis))


def _anchor(view, anchor, quote):
    from paper_daily.pdf_selection_text import level_words

    if (not isinstance(anchor, dict) or set(anchor) - (ANCHOR_KEYS | {"document_hash"})
            or not set(anchor) >= ANCHOR_KEYS
            or any(type(anchor[key]) is not int or not 0 <= anchor[key] <= 1000000
                   for key in ANCHOR_KEYS)
            or anchor.get("document_hash", view.fingerprint) != view.fingerprint
            or (anchor["p0"], anchor["o0"]) > (anchor["p1"], anchor["o1"])):
        raise ValueError("Invalid highlight coordinates")
    if not isinstance(quote, str) or not quote.strip() or len(quote.encode()) > 32768:
        raise ValueError("Invalid highlight quotation")
    lines = []
    with _pdf_document(view.path) as pdf:
        if anchor["p1"] >= len(pdf) or anchor["p1"] - anchor["p0"] > 100:
            raise ValueError("Highlight page range is outside the displayed PDF")
        for page in range(anchor["p0"], anchor["p1"] + 1):
            words = level_words(pdf[page])
            indices = {index for index, _word in words}
            if ((page == anchor["p0"] and anchor["o0"] not in indices)
                    or (page == anchor["p1"] and anchor["o1"] not in indices)):
                raise ValueError("Highlight word range is outside the displayed PDF")
            for index, word in words:
                if ((page == anchor["p0"] and index < anchor["o0"])
                        or (page == anchor["p1"] and index > anchor["o1"])):
                    continue
                if lines and lines[-1][-1][0] == page and abs(lines[-1][-1][1] - word[1]) < 3:
                    lines[-1].append((page, word[1], word[4]))
                else:
                    lines.append([(page, word[1], word[4])])
    text = ""
    for line in lines:
        part = " ".join(word[2] for word in line)
        text = (text[:-1] + part if text.endswith("-")
                else text + " " + part if text else part)
    if " ".join(text.split()) != " ".join(quote.split()):
        raise ValueError("Highlight text does not match the displayed PDF coordinates")
    return json.dumps({key: anchor[key] for key in sorted(ANCHOR_KEYS)}, sort_keys=True)


def add(view, anchor, quote):
    """Idempotently add one exact selection; never relabel a stale PDF selection."""
    _source(view)
    encoded = _anchor(view, anchor, quote)
    with closing(generation._connect(view.owner.database)) as conn:
        conn.execute("BEGIN IMMEDIATE")
        try:
            view.owner.check(conn)
            _source(view)
            existing = conn.execute(
                "SELECT quote FROM pdf_highlights "
                "WHERE paper_id=? AND document_hash=? AND anchor=?",
                (view.owner.paper_id, view.fingerprint, encoded),
            ).fetchone()
            if existing is not None and existing[0] != quote:
                raise ValueError("This highlight changed; reload its current text")
            if existing is None:
                conn.execute(
                    "INSERT INTO pdf_highlights(paper_id,document_hash,anchor,quote,created_at) "
                    "VALUES(?,?,?,?,?)",
                    (view.owner.paper_id, view.fingerprint, encoded, quote, now()),
                )
            _source(view)
            view.owner.check(conn)
            conn.commit()
        except BaseException:
            conn.rollback()
            raise


def remove(view, ids):
    """Delete manual marks or hide AI marks using their displayed row/graph bases."""
    if (not isinstance(ids, list) or len(ids) > MAX_MARKS
            or any(type(value) is not int or not value for value in ids)):
        raise ValueError("Invalid highlight selection")
    visible_ids = {mark["id"] for mark in view.marks}
    selected = {record["id"]: record for record in view.records if record["id"] in visible_ids}
    if any(value not in selected for value in ids):
        raise ValueError("A selected highlight does not belong to this displayed view")
    _source(view)
    with closing(generation._connect(view.owner.database)) as conn:
        conn.execute("BEGIN IMMEDIATE")
        try:
            view.owner.check(conn)
            _source(view)
            changes = []
            for ident in dict.fromkeys(ids):
                record = selected[ident]
                table, before = record["table"], record["row"]
                row = conn.execute(f"SELECT * FROM {table} WHERE id=?", (abs(ident),)).fetchone()
                if row is None:
                    continue  # Repeated removal already accomplished the requested action.
                current = dict(row)
                if current != before:
                    if ident < 0 and current == {**before, "hidden": 1}:
                        continue
                    raise ValueError("A selected highlight changed; reload before editing")
                if ident < 0 and current["hidden"]:
                    continue
                changes.append(record)
            with sync_capture.expecting(conn, [record["observation"] for record in changes]):
                for record in changes:
                    if record["id"] > 0:
                        conn.execute("DELETE FROM pdf_highlights WHERE id=?", (record["id"],))
                    else:
                        conn.execute("UPDATE pdf_ai_highlights SET hidden=1 WHERE id=?",
                                     (-record["id"],))
                _source(view)
                view.owner.check(conn)
                conn.commit()
        except BaseException:
            conn.rollback()
            raise
