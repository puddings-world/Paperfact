"""Actual-reader position capture, original retention and caller-owned CAS saves.

All methods perform storage/verification work and belong on a worker, never Qt.
Native viewport intent and view epochs are admitted by the separate UI boundary.
"""

from __future__ import annotations

import hashlib
import json
from contextlib import closing, contextmanager
from dataclasses import dataclass, field
from uuid import uuid4

from paper_daily import file_change, local_source_owners, source_snapshots, sync_capture
from paper_daily import reading_positions as positions
from paper_daily import research_generation as generation
from paper_daily.manual_highlight_ops import HighlightView
from paper_daily.store import now
from paper_daily.sync_files import canonical_json, closed, read_json

_SEAL = object()
_NATIVE_SEAL = object()
MAX_RECEIPT = 64 * 1024


class PositionSchemaRequired(ValueError):
    """A read-only reader cannot install an optional workspace capability."""


class LoadedSourceChanged(ValueError):
    """Native load completion could not prove the worker's exact source version."""


@contextmanager
def _admitting(conn, row):
    previous = getattr(conn, "_reading_position_admission", None)
    conn._reading_position_admission = (_SEAL, canonical_json(row))
    try:
        yield
    finally:
        conn._reading_position_admission = previous


def admitted(conn, row):
    expected = getattr(conn, "_reading_position_admission", None)
    encoded = canonical_json(row)
    return bool(
        expected
        and expected[0] is _SEAL
        and (
            expected[1] == encoded or isinstance(expected[1], frozenset) and encoded in expected[1]
        )
    )


@contextmanager
def admit_enrollment(conn, rows):
    """Private new-copy capture of exact rows whose source inventory was verified.

    Enrollment validates every owned original/page before entering this scope and
    rechecks the same file hashes before publication. Ordinary capture_existing
    receives no bypass; the whitelist cannot admit another row or a changed page.
    """
    selected = set()
    for row in rows:
        positions.validate_row(row)
        if canonical_json(
            positions.read(conn, row["paper_id"], row["document_hash"])
        ) != canonical_json(row):
            raise ValueError("Staged enrollment position changed after inventory")
        selected.add(canonical_json(row))
    previous = getattr(conn, "_reading_position_admission", None)
    conn._reading_position_admission = (_SEAL, frozenset(selected))
    try:
        yield
    finally:
        conn._reading_position_admission = previous


def _decode(value):
    if not isinstance(value, str) or len(value.encode("utf-8")) > MAX_RECEIPT:
        raise ValueError("Position receipt exceeds its bound")
    return read_json(value.encode("utf-8"))


def _owner_data(owner):
    captured = json.loads(owner._json)
    return {
        "format": "paperfact.position-source-owner.v1",
        "database_identity": captured["database_identity"],
        "binding": captured["binding"],
        "paper_id": owner.paper_id,
        "parent_lifecycle": captured["parent"],
        "source_owner_id": owner.paper_id,
    }


def _source_receipt(owner, fingerprint, size):
    metadata = dict(
        _owner_data(owner), format="paperfact.position-source-owner.v2", position_key=fingerprint
    )
    return local_source_owners.validate(
        {
            "request_id": "position:" + hashlib.sha256(canonical_json(metadata)).hexdigest(),
            "owner_json": canonical_json(metadata).decode(),
            "sha256": fingerprint,
            "size": size,
            "media_type": "application/pdf",
        }
    )


@dataclass(frozen=True, init=False)
class PositionView:
    highlight: object = field(repr=False)
    page_count: int
    base_json: str = field(repr=False)
    observation_json: str = field(repr=False)
    receipt_json: str = field(repr=False)
    original_version: tuple = field(repr=False)
    cached_path: object = field(repr=False)
    cached_version: tuple = field(repr=False)
    shared_source: object = field(repr=False)
    seal: object = field(repr=False)


def capture(view, *, cancelled=lambda: False):
    """Verify the actual loaded owner/hash and page count, without granting ownership."""
    from paper_daily.manual_highlight_ops import _source

    if not isinstance(view, HighlightView):
        raise ValueError("A verified actual loaded reader view is required")
    if cancelled():
        return None
    _source(view)
    verified = local_source_owners._read_pdf(
        view.path, view.fingerprint, view.path.stat().st_size, cancelled
    )
    if verified is None:
        return None
    data, original_version = verified
    import pymupdf

    with pymupdf.open(stream=data, filetype="pdf") as pdf:
        if pdf.needs_pass or not 1 <= pdf.page_count <= positions.MAX_PAGE:
            raise ValueError("Position requires a readable bounded PDF page count")
        page_count = pdf.page_count
    with closing(generation._connect(view.owner.database)) as conn:
        conn.execute("BEGIN")
        view.owner.check(conn)
        if not positions.ready(conn):
            raise PositionSchemaRequired("Reading-position schema migration is required")
        base = positions.read(conn, view.owner.paper_id, view.fingerprint)
        observation = sync_capture.observe_target(
            conn, "paper", view.owner.paper_id, "reading_position", view.fingerprint
        )
    if cancelled():
        return None
    receipt = _source_receipt(view.owner, view.fingerprint, len(data))
    result = object.__new__(PositionView)
    for key, value in dict(
        highlight=view,
        page_count=page_count,
        base_json=canonical_json(base).decode(),
        observation_json=canonical_json(observation).decode(),
        receipt_json=canonical_json(receipt).decode(),
        original_version=original_version,
        cached_path=None,
        cached_version=None,
        shared_source=None,
        seal=_SEAL,
    ).items():
        object.__setattr__(result, key, value)
    _current_source(result)
    return result


def _current_source(view):
    if not isinstance(view, PositionView) or getattr(view, "seal", None) is not _SEAL:
        raise ValueError("Position has no actual reader source proof")
    if file_change.version(view.highlight.path) != view.original_version or (
        view.cached_path is not None
        and file_change.version(view.cached_path) != view.cached_version
    ):
        raise LoadedSourceChanged("Position original changed after verification")
    document = view.highlight.document
    if document is not None and not document._owner.intact(document):
        raise LoadedSourceChanged("Loaded original no longer belongs to this workspace")


@dataclass(frozen=True, init=False)
class NativeObservation:
    view: PositionView = field(repr=False)
    page: int
    request_id: str
    recorded_at: str
    seal: object = field(repr=False)


def _native_observation(view, page):
    """Private native-input boundary; never decode this proof from a wire record."""
    if not isinstance(view, PositionView) or getattr(view, "seal", None) is not _SEAL:
        raise ValueError("Native observation requires a verified loaded view")
    if type(page) is not int or not 1 <= page <= view.page_count:
        raise ValueError("Native observation is outside the loaded original")
    result = object.__new__(NativeObservation)
    for key, value in dict(
        view=view, page=page, request_id=str(uuid4()), recorded_at=now(), seal=_NATIVE_SEAL
    ).items():
        object.__setattr__(result, key, value)
    return result


@dataclass(frozen=True, init=False)
class PositionSave:
    view: PositionView = field(repr=False)
    request_id: str
    request_json: str = field(repr=False)
    seal: object = field(repr=False)


def prepare(view, page, *, method, request_id=None, recorded_at=None, observation=None):
    """Freeze one admitted native observation or explicit entered-page intent."""
    from paper_daily.sync_content import _uuid

    _current_source(view)
    if method == "observed":
        if (
            not isinstance(observation, NativeObservation)
            or getattr(observation, "seal", None) is not _NATIVE_SEAL
            or observation.view is not view
            or observation.page != page
            or request_id not in (None, observation.request_id)
            or recorded_at not in (None, observation.recorded_at)
        ):
            raise ValueError("Observed position requires genuine native page input evidence")
        request_id, recorded_at = observation.request_id, observation.recorded_at
    elif observation is not None:
        raise ValueError("Entered position must not relabel a native observation")
    data = positions.validate_data(dict(page=page, recorded_at=recorded_at or now(), method=method))
    if page > view.page_count:
        raise ValueError("Position page is outside this verified PDF")
    request_id = request_id or str(uuid4())
    _uuid(request_id)
    request = dict(
        version=1,
        owner=_owner_data(view.highlight.owner),
        document_hash=view.highlight.fingerprint,
        page_count=view.page_count,
        data=data,
        base=_decode(view.base_json),
        observation=_decode(view.observation_json),
    )
    view = _retain(view)
    result = object.__new__(PositionSave)
    for key, value in dict(
        view=view, request_id=request_id, request_json=canonical_json(request).decode(), seal=_SEAL
    ).items():
        object.__setattr__(result, key, value)
    return result


def _retain(view):
    """Retain provenance only for an admitted save intent, never initial loading."""
    from paper_daily import position_source_snapshots
    from paper_daily.sync_blobs import BlobStore
    from paper_daily.sync_source_files import prepare_source
    from paper_daily.workspace_service import _binding, _paths, _tables

    _current_source(view)
    if view.cached_path is not None:
        return view
    verified = local_source_owners._read_pdf(
        view.highlight.path, view.highlight.fingerprint, view.original_version[2]
    )
    data, original_version = verified
    if original_version != view.original_version:
        raise ValueError("Loaded original changed before admitting the position")
    receipt = local_source_owners.validate(_decode(view.receipt_json))
    cached, version = position_source_snapshots.publish(
        view.highlight.owner.database, receipt, data=data
    )
    shared = None
    with closing(generation._connect(view.highlight.owner.database)) as conn:
        conn.execute("BEGIN")
        view.highlight.owner.check(conn)
        client = conn._capture_client if sync_capture.enabled(conn) else None
        tables = _tables(conn)
        roots = _paths(conn, tables, _binding(conn, tables)) if client else None
    if client:
        blob_root, _legacy, registrations = roots
        store = BlobStore(blob_root or view.highlight.owner.database.parent / "blobs")
        registered = dict(registrations)
        version_root = (
            registered["research_file_paths"][2]
            if "research_file_paths" in registered
            else store.root / "research-versions"
        )
        parent = json.loads(view.highlight.owner._json)["graph"]
        shared = prepare_source(
            client,
            parent["entity_id"],
            cached,
            document_hash=view.highlight.fingerprint,
            parent_incarnation=parent["incarnation"],
            store=store,
            version_root=version_root,
            request_id="position-source:" + hashlib.sha256(canonical_json(receipt)).hexdigest(),
        )
    result = object.__new__(PositionView)
    for name in PositionView.__dataclass_fields__:
        object.__setattr__(result, name, getattr(view, name))
    object.__setattr__(result, "cached_path", cached)
    object.__setattr__(result, "cached_version", version)
    object.__setattr__(result, "shared_source", shared)
    _current_source(result)
    return result


def save_in(conn, prepared):
    """Position/retained candidate, retry receipt and original ownership commit together."""
    from paper_daily.sync_source_files import publish_source_in

    if (
        not conn.in_transaction
        or not isinstance(prepared, PositionSave)
        or getattr(prepared, "seal", None) is not _SEAL
    ):
        raise ValueError("Position save requires its prepared intent and caller transaction")
    view = prepared.view
    _current_source(view)
    owner = view.highlight.owner
    owner.check(conn)
    old = conn.execute(
        "SELECT request_json,result_json FROM research_reading_position_receipts "
        "WHERE request_id=?",
        (prepared.request_id,),
    ).fetchone()
    if old:
        if old[0] != prepared.request_json:
            raise ValueError("Position retry changed its captured content")
        validate_receipt(
            dict(request_id=prepared.request_id, request_json=old[0], result_json=old[1])
        )
        return _decode(old[1])
    if (
        conn.execute("SELECT COUNT(*) FROM research_reading_position_receipts").fetchone()[0]
        >= source_snapshots.MAX_RECEIPTS
    ):
        raise ValueError("Position retry history exceeds its bounded receipt budget")
    request = _decode(prepared.request_json)
    if (
        canonical_json(request["base"]).decode() != view.base_json
        or canonical_json(request["observation"]).decode() != view.observation_json
    ):
        raise ValueError("Position request changed its captured base")
    if request["document_hash"] != view.highlight.fingerprint or request["owner"] != _owner_data(
        owner
    ):
        raise ValueError("Position save differs from its captured owner")
    positions.validate_data(request["data"])
    if request["data"]["page"] > view.page_count or request["page_count"] != view.page_count:
        raise ValueError("Position page is outside the verified original")
    current = positions.read(conn, owner.paper_id, view.highlight.fingerprint)
    observation = sync_capture.observe_target(
        conn, "paper", owner.paper_id, "reading_position", view.highlight.fingerprint
    )
    stale = (
        canonical_json(current).decode() != view.base_json
        or canonical_json(observation).decode() != view.observation_json
    )
    row = dict(paper_id=owner.paper_id, document_hash=view.highlight.fingerprint, **request["data"])
    positions.validate_row(row)
    status = "retained" if stale else "saved"
    if not stale and current and all(current[key] == row[key] for key in ("page", "method")):
        status = "unchanged"
    receipt = local_source_owners.validate(_decode(view.receipt_json))
    with sync_capture.suppress_capture(conn):
        if view.shared_source is not None:
            publish_source_in(conn, conn._capture_client, view.shared_source)
        conn.execute(local_source_owners.SCHEMA)
        prior = conn.execute(
            "SELECT owner_json,sha256,size,media_type FROM research_local_source_owners "
            "WHERE request_id=?",
            (receipt["request_id"],),
        ).fetchone()
        expected = tuple(receipt[key] for key in ("owner_json", "sha256", "size", "media_type"))
        if prior is not None and tuple(prior) != expected:
            raise ValueError("Position source ownership changed")
        if (
            prior is None
            and conn.execute("SELECT COUNT(*) FROM research_local_source_owners").fetchone()[0]
            >= source_snapshots.MAX_RECEIPTS
        ):
            raise ValueError("Position original ownership exceeds its receipt budget")
        conn.execute(
            "INSERT OR IGNORE INTO research_local_source_owners VALUES(?,?,?,?,?)",
            tuple(receipt[key] for key in local_source_owners.COLUMNS.split()),
        )
    if status == "saved":
        with sync_capture.expecting(conn, [observation]), _admitting(conn, row):
            conn.execute(
                "INSERT INTO reading_positions VALUES(?,?,?,?,?) "
                "ON CONFLICT(paper_id,document_hash) DO UPDATE SET page=excluded.page,"
                "recorded_at=excluded.recorded_at,method=excluded.method",
                tuple(row[key] for key in positions.FIELDS.split()),
            )
            # Keep the explicit base attached through the caller's eventual commit.
            # The trigger already captured it at mutation time; no commit is owned here.
    result = dict(
        request_id=prepared.request_id,
        status=status,
        position=current if status == "unchanged" else row,
    )
    record = dict(
        request_id=prepared.request_id,
        request_json=prepared.request_json,
        result_json=canonical_json(result).decode(),
    )
    validate_receipt(record)
    with sync_capture.suppress_capture(conn):
        conn.execute(
            "INSERT INTO research_reading_position_receipts VALUES(?,?,?)",
            tuple(record[key] for key in positions.RECEIPT_FIELDS.split()),
        )
    _current_source(view)
    owner.check(conn)
    return result


@dataclass(frozen=True, init=False)
class CommittedPosition:
    prepared: PositionSave = field(repr=False)
    result_json: str = field(repr=False)
    observation_json: str = field(repr=False)
    seal: object = field(repr=False)

    @property
    def result(self):
        return _decode(self.result_json)


def save(prepared, *, cancelled=lambda: False, with_proof=False):
    if cancelled():
        return None
    with closing(generation._connect(prepared.view.highlight.owner.database)) as conn:
        conn.execute("BEGIN IMMEDIATE")
        try:
            result = save_in(conn, prepared)
            if cancelled():
                conn.rollback()
                return None
            observed = None
            if with_proof:
                if sync_capture.enabled(conn):
                    # Flush inside this same caller transaction, before recording
                    # the exact head. A later identical received value is still a
                    # different predecessor and must not be silently rebased.
                    with sync_capture.suppress_capture(conn):
                        sync_capture._flush(conn)
                view = prepared.view
                observed = sync_capture.observe_target(
                    conn,
                    "paper",
                    view.highlight.owner.paper_id,
                    "reading_position",
                    view.highlight.fingerprint,
                )
                if cancelled():
                    conn.rollback()
                    return None
            conn.commit()
            if with_proof:
                proof = object.__new__(CommittedPosition)
                for name, value in dict(
                    prepared=prepared,
                    result_json=canonical_json(result).decode(),
                    observation_json=canonical_json(observed).decode(),
                    seal=_SEAL,
                ).items():
                    object.__setattr__(proof, name, value)
                return proof
            return result
        except BaseException:
            conn.rollback()
            raise


def current(view):
    """Read an explicit resume suggestion for this already-loaded exact original."""
    _current_source(view)
    with closing(generation._connect(view.highlight.owner.database)) as conn:
        conn.execute("BEGIN")
        view.highlight.owner.check(conn)
        row = positions.read(conn, view.highlight.owner.paper_id, view.highlight.fingerprint)
        if row and row["page"] > view.page_count:
            raise ValueError("Saved position exceeds this verified original")
    _current_source(view)
    return row


def refresh(view):
    """Refresh CAS metadata for the same verified loaded source, off the Qt thread."""
    _current_source(view)
    with closing(generation._connect(view.highlight.owner.database)) as conn:
        conn.execute("BEGIN")
        view.highlight.owner.check(conn)
        if not positions.ready(conn):
            raise PositionSchemaRequired("Reading-position schema migration is required")
        base = positions.read(conn, view.highlight.owner.paper_id, view.highlight.fingerprint)
        if base and base["page"] > view.page_count:
            raise ValueError("Saved position exceeds this verified original")
        observed = sync_capture.observe_target(
            conn,
            "paper",
            view.highlight.owner.paper_id,
            "reading_position",
            view.highlight.fingerprint,
        )
    result = object.__new__(PositionView)
    for name in PositionView.__dataclass_fields__:
        object.__setattr__(result, name, getattr(view, name))
    object.__setattr__(result, "base_json", canonical_json(base).decode())
    object.__setattr__(result, "observation_json", canonical_json(observed).decode())
    _current_source(result)
    return result


def follow_native(observation, previous, refreshed, *, with_status=False):
    """Chain real input only over this controller's proven committed predecessor.

    A concurrent/received change retains the original stale base instead. Neither
    the page, timestamp nor identity of the native input is synthesized here.
    The worker may request a satisfied-tail flag after these same exact checks;
    it is not a general save/retry shortcut and carries no persistent authority.
    """

    def returned(value, satisfied=False):
        return (value, satisfied) if with_status else value

    if (
        not isinstance(observation, NativeObservation)
        or getattr(observation, "seal", None) is not _NATIVE_SEAL
        or not isinstance(previous, CommittedPosition)
        or getattr(previous, "seal", None) is not _SEAL
    ):
        raise ValueError("Native continuation requires its actual input and prior intent")
    committed = previous
    previous = committed.prepared
    old = observation.view
    _current_source(old)
    _current_source(refreshed)
    if (
        old.highlight.owner._json != refreshed.highlight.owner._json
        or old.highlight.path != refreshed.highlight.path
        or old.highlight.fingerprint != refreshed.highlight.fingerprint
        or old.original_version != refreshed.original_version
        or old.page_count != refreshed.page_count
        or not (
            old.base_json == canonical_json(_decode(previous.request_json)["base"]).decode()
            or (
                old.base_json == refreshed.base_json
                and old.observation_json == refreshed.observation_json
            )
        )
    ):
        return returned(observation)
    with closing(generation._connect(old.highlight.owner.database)) as conn:
        conn.execute("BEGIN")
        old.highlight.owner.check(conn)
        found = conn.execute(
            "SELECT request_json,result_json FROM research_reading_position_receipts "
            "WHERE request_id=?",
            (previous.request_id,),
        ).fetchone()
        if not found or found[0] != previous.request_json:
            return returned(observation)
        validate_receipt(
            dict(request_id=previous.request_id, request_json=found[0], result_json=found[1])
        )
        result = _decode(found[1])
        actual = positions.read(conn, old.highlight.owner.paper_id, old.highlight.fingerprint)
        actual_observation = sync_capture.observe_target(
            conn,
            "paper",
            old.highlight.owner.paper_id,
            "reading_position",
            old.highlight.fingerprint,
        )
    if (
        result["status"] not in ("saved", "unchanged")
        or canonical_json(result["position"]).decode() != refreshed.base_json
        or canonical_json(actual).decode() != refreshed.base_json
        or canonical_json(result).decode() != committed.result_json
        or canonical_json(actual_observation).decode() != committed.observation_json
        or refreshed.observation_json != committed.observation_json
    ):
        return returned(observation)
    rebound = object.__new__(NativeObservation)
    for name in NativeObservation.__dataclass_fields__:
        object.__setattr__(rebound, name, getattr(observation, name))
    object.__setattr__(rebound, "view", refreshed)
    satisfied = (
        observation.page == result["position"]["page"]
        and result["position"]["method"] == "observed"
    )
    return returned(rebound, satisfied)


def navigate(view, expected, visit, *, cancelled=lambda: False):
    """Explicit exact-row navigation, with source/parent checks on its worker.

    The bounded GUI callback must only compare its live view/draft epoch and move
    the native reader. Holding the caller's write reservation through that pure
    callback prevents a paper lifecycle mutation between validation and the jump.
    No saved position or resume is queued for a future document load.
    """
    if expected is None:
        return False
    positions.validate_row(expected)
    _current_source(view)
    if cancelled():
        return False
    with closing(generation._connect(view.highlight.owner.database)) as conn:
        conn.execute("BEGIN IMMEDIATE")
        try:
            view.highlight.owner.check(conn)
            actual = positions.read(conn, view.highlight.owner.paper_id, view.highlight.fingerprint)
            if canonical_json(actual) != canonical_json(expected):
                raise ValueError("Recorded position changed; check the suggestion again")
            if expected["page"] > view.page_count:
                raise ValueError("Recorded position exceeds the loaded original")
            _current_source(view)
            if cancelled():
                return False
            return bool(visit(expected["page"]))
        finally:
            conn.rollback()


def prepare_resolution(view, candidate_id, *, request_id=None):
    """Explicitly choose a retained page against a freshly captured current base."""
    with closing(generation._connect(view.highlight.owner.database)) as conn:
        conn.execute("BEGIN")
        view.highlight.owner.check(conn)
        found = conn.execute(
            "SELECT request_id,request_json,result_json FROM research_reading_position_receipts "
            "WHERE request_id=?",
            (candidate_id,),
        ).fetchone()
    if not found:
        raise ValueError("Retained position is unavailable")
    row = dict(zip(positions.RECEIPT_FIELDS.split(), found, strict=True))
    validate_receipt(row)
    source, result = _decode(row["request_json"]), _decode(row["result_json"])
    if (
        result["status"] != "retained"
        or source["owner"] != _owner_data(view.highlight.owner)
        or source["document_hash"] != view.highlight.fingerprint
    ):
        raise ValueError("Retained position belongs to another original or paper lifetime")
    return prepare(view, source["data"]["page"], method="entered", request_id=request_id)


def validate_receipt(record):
    """Closed archive-only reading intent; original observations grant no new owner."""
    from paper_daily.sync_content import _hash, _integer, _text, _uuid
    from paper_daily.sync_journal import _identifier

    closed(record, positions.RECEIPT_FIELDS.split())
    _uuid(record["request_id"])
    request, result = _decode(record["request_json"]), _decode(record["result_json"])
    closed(
        request, {"version", "owner", "document_hash", "page_count", "data", "base", "observation"}
    )
    if type(request["version"]) is not int or request["version"] != 1:
        raise ValueError("Unsupported position request")
    closed(
        request["owner"],
        {
            "format",
            "database_identity",
            "binding",
            "paper_id",
            "parent_lifecycle",
            "source_owner_id",
        },
    )
    if request["owner"]["format"] != "paperfact.position-source-owner.v1":
        raise ValueError("Unsupported position request owner")
    _hash(request["document_hash"])
    owner = dict(request["owner"], position_key=request["document_hash"])
    local_source_owners.validate(
        dict(
            request_id="position:" + hashlib.sha256(canonical_json(owner)).hexdigest(),
            owner_json=canonical_json(owner).decode(),
            sha256=request["document_hash"],
            size=1,
            media_type="application/pdf",
        )
    )
    _integer(request["page_count"], maximum=positions.MAX_PAGE)
    positions.validate_data(request["data"])
    if request["data"]["page"] > request["page_count"]:
        raise ValueError("Archived position exceeds its verified page count")
    if request["base"] is not None:
        positions.validate_row(request["base"])
        if (request["base"]["paper_id"], request["base"]["document_hash"]) != (
            owner["paper_id"],
            request["document_hash"],
        ):
            raise ValueError("Position base belongs to another owner")
    observed = request["observation"]
    if owner["binding"] is None:
        if observed is not None:
            raise ValueError("Unbound position invented a synchronized observation")
    else:
        from paper_daily.sync_content import content_id

        closed(
            observed,
            {
                "workspace_id",
                "kind",
                "entity_id",
                "revision",
                "predecessor",
                "incarnation",
                "active",
                "parents",
            },
        )
        if (
            observed["workspace_id"] != owner["binding"]["workspace_id"]
            or observed["kind"] != "research_content"
        ):
            raise ValueError("Position observation belongs to another workspace/feature")
        _integer(observed["revision"])
        if type(observed["active"]) is not bool:
            raise ValueError("Invalid position observation activity")
        for key in ("predecessor", "incarnation"):
            if observed[key] is not None:
                _identifier(observed[key])
        if not isinstance(observed["parents"], list) or len(observed["parents"]) != 1:
            raise ValueError("Position observation requires its exact paper lifetime")
        parent = observed["parents"][0]
        closed(parent, {"kind", "id", "incarnation", "active"})
        _uuid(parent["id"])
        _identifier(parent["incarnation"])
        if parent["kind"] != "paper" or parent["active"] is not True:
            raise ValueError("Position observation requires an active paper")
        if observed["entity_id"] != content_id(
            {"kind": "paper", "id": parent["id"]}, "reading_position", request["document_hash"]
        ):
            raise ValueError("Position observation has another identity")
    closed(result, {"request_id", "status", "position"})
    if result["request_id"] != record["request_id"] or result["status"] not in (
        "saved",
        "retained",
        "unchanged",
    ):
        raise ValueError("Invalid position result")
    positions.validate_row(result["position"])
    if result["status"] == "unchanged" and any(
        result["position"][key] != request["data"][key] for key in ("page", "method")
    ):
        raise ValueError("Unchanged position differs from the requested page/method")
    if (result["position"]["paper_id"], result["position"]["document_hash"]) != (
        owner["paper_id"],
        request["document_hash"],
    ):
        raise ValueError("Position result belongs to another owner")
    if result["status"] != "unchanged" and result["position"] != dict(
        paper_id=owner["paper_id"], document_hash=request["document_hash"], **request["data"]
    ):
        raise ValueError("Position result differs from its captured request")
    _text(record["request_json"], MAX_RECEIPT, nullable=False)
    return {request["document_hash"]}


def add_enrollment_sources(conn, rows, receipts, inventory, *, ticket):
    """Retain only exact position owners; no filename/current-PDF association."""
    from paper_daily.research_lifecycle import parent_lifecycle

    if rows and not positions.ready(conn):
        raise ValueError("Reading-position source schema requires explicit migration")
    for row in rows:
        ticket.check()
        positions.validate_row(row)
        candidates = []
        for receipt in receipts:
            metadata = json.loads(local_source_owners.validate(receipt)["owner_json"])
            if (
                metadata["format"] in source_snapshots.POSITION_FORMATS
                and metadata["paper_id"] == row["paper_id"]
                and metadata["parent_lifecycle"] == parent_lifecycle(conn, "paper", row["paper_id"])
                and receipt["sha256"] == row["document_hash"]
                and metadata["database_identity"] == generation._identity(generation._path(conn))
                and metadata["binding"] == generation._binding(conn)
            ):
                candidates.append(receipt)
        if not candidates:
            from paper_daily.reading_position_received_sources import current_source

            inventory[(row["paper_id"], row["document_hash"])] = current_source(
                conn, row, ticket=ticket
            )
            continue
        receipt = candidates[0]
        path = source_snapshots.source_path(
            generation._path(conn), receipt, max_pdf_bytes=local_source_owners.MAX_PDF_BYTES
        )
        # Read/hash verification belongs to the enrollment worker, never the UI.
        verified = local_source_owners._read_pdf(
            path, receipt["sha256"], receipt["size"], lambda: False
        )
        positions.verify_page(row, verified[0])
        inventory[(row["paper_id"], row["document_hash"])] = dict(
            path=str(path), sha256=receipt["sha256"], size=receipt["size"]
        )
