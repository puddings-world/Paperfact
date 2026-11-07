"""Exact originals for an actually displayed saved deck; worker-only read operation.

No schema, source owner, publication or current-PDF activation is created here.
Catalog ownership proves local original bytes, never that it generated the deck.
GUI admission is native metadata only: recheck requires worker revalidation.
"""

from __future__ import annotations

import hashlib
import json
from contextlib import closing
from dataclasses import dataclass, field
from pathlib import Path

import pymupdf

from paper_daily import file_change, local_blob_binding, presentations, research_file_review
from paper_daily import local_deck_proposals as local
from paper_daily.enrolled_deck_proposals import _runtime, _target
from paper_daily.local_deck_review import _slot
from paper_daily.research_lifecycle import parent_lifecycle
from paper_daily.sync_artifacts import applied_file, desired_file, paper_current, version_directory
from paper_daily.sync_deck_publication import runtime
from paper_daily.sync_documents import MAX_PDF_BYTES
from paper_daily.sync_files import (
    MAX_BODY,
    canonical_json,
    digest,
    file_id,
    read_json,
    validate_closure,
)

MAX_CATALOG_ROWS = local.MAX_RECORDS
MAX_CATALOG_BYTES = local.MAX_CATALOG_BYTES
_SEAL = object()


def _check(current):
    if not current():
        raise ValueError("Original read cancelled or caller retired")


def _native(path):
    return local._native(path)


def _connect(path):
    return local._connect(path)


def _version(path):
    return file_change.version(local._path(path))


def _fence(paths):
    # Interference hints, not research revision/source ownership authority.
    values = []
    for path in paths:
        for p in (Path(path), Path(str(path) + "-wal")):
            for part in (p, *p.parents):
                local_blob_binding._no_link(part)
            values.append((str(p), _version(p) if p.exists() else None))
    return tuple(values)


def _read(path, size, files, current):
    _check(current)
    path = local._path(path)
    before = _version(path)
    if before[2] != size:
        raise ValueError("Original/deck size changed")
    with path.open("rb") as stream:
        if file_change.version(path, stream=stream) != before:
            raise ValueError("Original/deck changed before read")
        value = stream.read(size + 1)
        if len(value) != size or file_change.version(path, stream=stream) != before:
            raise ValueError("Original/deck changed during read")
    if str(path) in files and files[str(path)] != before:
        raise ValueError("Original/deck changed between reads")
    files[str(path)] = before
    _check(current)
    return value


def _blob(store, row, files, current):
    sha, size = row["sha256"], row["size"]
    index = store.root / "index.sqlite"
    with closing(local_blob_binding._read(index)) as conn:
        actual = conn.execute("SELECT size,complete FROM blobs WHERE digest=?", (sha,)).fetchone()
        if actual is None or tuple(actual) != (size, 1):
            raise ValueError("Owned source/artifact blob is incomplete")
    path = local._path(store.root / "objects" / sha)
    value = _read(path, size, files, current)
    if hashlib.sha256(value).hexdigest() != sha:
        raise ValueError("Owned source/artifact bytes are corrupt")
    return value


def _saved_json(raw):
    # Canonical artifact JSON and public legacy editable JSON are distinct codecs.
    def pairs(values):
        result = {}
        for key, value in values:
            if key in result:
                raise ValueError("Duplicate saved deck JSON key")
            result[key] = value
        return result

    def invalid(_value):
        raise ValueError("Non-finite saved deck JSON")

    if len(raw) > MAX_BODY:
        raise ValueError("Saved active deck exceeds its bound")
    try:
        value = json.loads(raw.decode("utf8"), object_pairs_hook=pairs, parse_constant=invalid)
        if not isinstance(value, dict):
            raise ValueError("Saved active deck JSON must be an object")
        return read_json(canonical_json(value))
    except (RecursionError, UnicodeError, TypeError) as error:
        raise ValueError("Invalid bounded saved deck JSON") from error


def _slot_witness(data, slot, files):
    expected = data["expected_slot"]
    if expected is not None and (
        str(local._path(slot)) != expected[0]
        or canonical_json(files[str(local._path(slot))]) != canonical_json(expected[1])
    ):
        raise ValueError("The displayed saved slot version changed before worker capture")


def _displayed(deck, paper_id):
    value = presentations.deck_from_dict(deck)
    value.paper_id = paper_id
    return value.to_dict()


def _local_source(conn, path, native, paper_id, document_hash):
    if not local._schema(conn):
        raise ValueError("No owned local original catalog")
    ids = conn.execute(
        "SELECT proposal_id FROM " + local.TABLE + " WHERE paper_id=? ORDER BY proposal_id LIMIT ?",
        (paper_id, MAX_CATALOG_ROWS + 1),
    ).fetchall()
    if len(ids) > MAX_CATALOG_ROWS:
        raise ValueError("Local original catalog exceeds its row bound")
    found, total = [], 0
    for identity in ids:
        row = local.record(conn, identity[0])
        total += len(canonical_json(row))
        if total > MAX_CATALOG_BYTES:
            raise ValueError("Local original catalog exceeds its byte bound")
        owner = read_json(row["owner_json"].encode())
        if (
            owner["database"] != str(path)
            or owner["native"] != list(native)
            or owner["paper_id"] != paper_id
        ):
            raise ValueError("Local original belongs to another native owner")
        if owner["parent_token"] != parent_lifecycle(conn, "paper", paper_id):
            continue  # Historical content does not authorize a recreated parent.
        local._scope(conn, owner, exact_row=False)
        manifest = read_json(row["manifest_json"].encode())
        matches = [entry for entry in manifest["originals"] if entry["sha256"] == document_hash]
        if matches:
            found.append((row, matches[0]))
    if len(found) != 1:
        raise ValueError("Local original ownership is unavailable or ambiguous")
    return found[0]


def _observe(data, current):
    _check(current)
    path = Path(data["database"])
    if _native(path) != tuple(data["native"]):
        raise ValueError("Original workspace was replaced")
    files, natives = {}, {str(path): tuple(data["native"])}
    with closing(_connect(path)) as conn:
        actual = next(row[2] for row in conn.execute("PRAGMA database_list") if row[1] == "main")
        if local._path(actual) != path:
            raise ValueError("Original read opened another database")
        paper = local._paper(conn, data["paper_id"])
        epoch = parent_lifecycle(conn, "paper", data["paper_id"])
        if paper is None or epoch is None:
            raise ValueError("Original local parent is unavailable")
        if data["mode"] == "managed":
            client = runtime(database=path)
            if client is None:
                raise ValueError("Managed original binding is missing")
            store, root, storage = research_file_review._storage(conn)
            owner, scope = _runtime(client, store, data["native"])
            operation = data["operation"]
            portable = operation["payload"]["paper_id"]
            target = _target(conn, owner, scope, data["paper_id"], portable)
            expected_loaded = dict(
                database=target["database"],
                database_identity=target["native"],
                workspace_id=target["binding"][0],
                device_id=target["binding"][1],
                local_id=target["local_id"],
                paper_id=target["portable_id"],
                mode=data["deck"]["mode"],
                local_parent_lifecycle=target["parent_token"],
            )
            if data["loaded_owner"] != expected_loaded:
                raise ValueError("Loaded managed deck owner/binding/lifetime changed")
            if applied_file(conn, operation["entity_id"]) != operation or not paper_current(
                conn, operation
            ):
                raise ValueError("Displayed applied deck changed or retired")
            if desired_file(conn, operation["entity_id"]) is None:
                raise ValueError("Displayed deck was removed")
            body = validate_closure(
                operation["payload"], lambda row: _blob(store, row, files, current)
            )["deck"]
            descriptors = {row["id"]: row for row in operation["payload"]["assets"]}
            for figure in body["figures"]:
                figure["asset"] = descriptors[figure.pop("asset_id")]["sha256"] + ".png"
            slot = version_directory(root, operation) / "deck.json"
            if not 0 < slot.stat().st_size <= MAX_BODY:
                raise ValueError("Saved active artifact body exceeds its bound")
            raw = _read(slot, slot.stat().st_size, files, current)
            if read_json(raw) != body:
                raise ValueError("Materialized active deck differs from its artifact")
            _slot_witness(data, slot, files)
            if _displayed(body, data["paper_id"]) != data["deck"]:
                raise ValueError("Displayed deck is not its exact saved artifact")
            source = desired_file(conn, file_id(portable, "original_source", data["document_hash"]))
            if source is None or not paper_current(conn, source):
                raise ValueError("Declared original source is unavailable or retired")
            descriptor = source["payload"]["assets"][0]
            if (
                source["payload"]["feature"] != "original_source"
                or descriptor["sha256"] != data["document_hash"]
            ):
                raise ValueError("Declared original source identity differs")
            authority = dict(target=target, source=source, storage=storage)
            for p in (
                store.root,
                store.root / "index.sqlite",
                store.root / "objects",
                store.root / "partial",
                root,
                slot.parent,
            ):
                natives[str(p)] = _native(p)
            for row in (source["payload"]["body"], *source["payload"]["assets"]):
                original = local._path(store.root / "objects" / row["sha256"])
                files[str(original)] = _version(original)
                if files[str(original)][2] != row["size"]:
                    raise ValueError("Original closure file size changed")
            index = store.root / "index.sqlite"
        else:
            local._database(conn, path, data["native"])
            slot = _slot(Path(data["presentation_root"]), data["paper_id"], data["deck"]["mode"])
            if not 0 < slot.stat().st_size <= MAX_BODY:
                raise ValueError("Saved active deck exceeds its bound")
            body = _saved_json(_read(slot, slot.stat().st_size, files, current))
            if body.get("paper_id") != data["paper_id"]:
                raise ValueError("Saved active slot belongs to another local paper owner")
            _slot_witness(data, slot, files)
            if _displayed(body, data["paper_id"]) != data["deck"]:
                raise ValueError("Displayed deck differs from its actual saved slot")
            row, descriptor = _local_source(
                conn, path, data["native"], data["paper_id"], data["document_hash"]
            )
            from paper_daily.workspace_service import _ReadOnlyStore

            root = local._root(path, data["native"])
            store = _ReadOnlyStore(root)
            authority = dict(paper=paper, parent_token=epoch, catalog=row)
            for p in (
                root,
                root / "index.sqlite",
                root / "objects",
                root / "partial",
                Path(data["presentation_root"]),
                slot.parent,
            ):
                natives[str(p)] = _native(p)
            index = root / "index.sqlite"
        source_path = local._path(store.root / "objects" / data["document_hash"])
        files[str(source_path)] = _version(source_path)
        if files[str(source_path)][2] != descriptor["size"]:
            raise ValueError("Declared original size differs")
    _check(current)
    if _native(path) != tuple(data["native"]):
        raise ValueError("Original workspace changed during observation")
    return authority, files, natives, source_path, descriptor, store, index


@dataclass(frozen=True, init=False)
class Capture:
    _database: Path = field(repr=False)
    _json: str = field(repr=False)
    _authority: str = field(repr=False)
    _files: tuple = field(repr=False)
    _natives: tuple = field(repr=False)
    _seal: object = field(repr=False)

    @property
    def source(self):
        return json.loads(self._json)["source"]


def _sealed(cls, **fields):
    result = object.__new__(cls)
    for key, value in fields.items():
        object.__setattr__(result, key, value)
    object.__setattr__(result, "_seal", _SEAL)
    return result


def capture(
    database,
    paper_id,
    deck,
    source_id,
    *,
    expected_native,
    presentation_root=None,
    expected_slot=None,
    current=lambda: True,
):
    """Worker: bind the actual displayed saved slot and same-parent owned original.

    An unbound caller must supply its actual configured presentation root. No
    global root, mutable selection, title match or sender path is consulted.
    """
    _check(current)
    path = local._path(database)
    native = local._expected(expected_native)
    if _native(path) != native:
        raise ValueError("Capture requires the originally observed native database")
    value = read_json(canonical_json(deck.to_dict()))
    if len(canonical_json(value)) > MAX_BODY or value["paper_id"] != paper_id:
        raise ValueError("Displayed active deck has another owner or exceeds its bound")
    sources = [row for row in value["sources"] if row["id"] == source_id]
    if len(sources) != 1:
        raise ValueError("Displayed source is missing or ambiguous")
    source = sources[0]
    document_hash = source.get("document_hash")
    digest(document_hash)
    operation = getattr(deck, "_file_operation", None)
    if operation is None and presentation_root is None:
        raise ValueError("Unbound reading requires the actual configured presentation root")
    if expected_slot is not None:
        if not isinstance(expected_slot, (tuple, list)) or len(expected_slot) != 2:
            raise ValueError("Expected slot requires its actual path/native version")
        expected_slot = [str(Path(expected_slot[0]).absolute()), expected_slot[1]]
        if len(canonical_json(expected_slot)) > 4096:
            raise ValueError("Expected slot witness exceeds its bound")
    loaded_owner = None
    if operation is not None:
        observed = getattr(deck, "_file_observation", None)
        keys = (
            "database",
            "database_identity",
            "workspace_id",
            "device_id",
            "local_id",
            "paper_id",
            "mode",
            "local_parent_lifecycle",
        )
        if not isinstance(observed, dict) or not set(keys) <= set(observed):
            raise ValueError("Loaded managed deck needs its actual original owner observation")
        loaded_owner = {key: observed[key] for key in keys}
    data = dict(
        database=str(path),
        native=list(native),
        paper_id=paper_id,
        deck=value,
        source=source,
        expected_slot=expected_slot,
        loaded_owner=loaded_owner,
        document_hash=document_hash,
        mode="managed" if operation else "local",
        operation=read_json(canonical_json(operation)) if operation else None,
        presentation_root=str(local._path(presentation_root)) if not operation else None,
    )
    authority, files, natives, *_ = _observe(data, current)
    result = _sealed(
        Capture,
        _database=path,
        _json=canonical_json(data).decode(),
        _authority=canonical_json(authority).decode(),
        _files=tuple(files.items()),
        _natives=tuple(natives.items()),
    )
    _verify(result, current)
    return result


def _verify(captured, current):
    if not isinstance(captured, Capture) or captured._seal is not _SEAL:
        raise ValueError("Use an actual sealed active-deck capture")
    _check(current)
    for path, native in captured._natives:
        if _native(path) != native:
            raise ValueError("Original database/storage/root native identity changed")
    local._files_current(captured._files)
    observed = _observe(json.loads(captured._json), current)
    if canonical_json(observed[0]).decode() != captured._authority:
        raise ValueError("Original active deck/source/owner changed")
    if (
        tuple(observed[1].items()) != captured._files
        or tuple(observed[2].items()) != captured._natives
    ):
        raise ValueError("Original source/body native version changed")
    return observed


@dataclass(frozen=True, init=False)
class OriginalProof:
    capture: Capture = field(repr=False)
    document_hash: str
    data: bytes = field(repr=False)
    pages: int
    source_path: Path = field(repr=False)
    _fence: tuple = field(repr=False)
    _seal: object = field(repr=False)

    @property
    def source(self):
        return self.capture.source


def prepare(captured, *, current=lambda: True):
    """Worker: verify PDF bytes and semantics, closing every SQL/PDF/file handle."""
    authority, _files, _natives, path, descriptor, store, index = _verify(captured, current)
    data = json.loads(captured._json)
    before = _fence((data["database"], index))
    files = dict(captured._files)
    if data["mode"] == "managed":
        source = authority["source"]
        values = {}

        def read(row):
            value = _blob(store, row, files, current)
            values[row["sha256"]] = value
            return value

        validate_closure(source["payload"], read)
        pdf = values[data["document_hash"]]
    else:
        pdf = _blob(store, descriptor, files, current)
    if not 0 < len(pdf) <= MAX_PDF_BYTES:
        raise ValueError("Original PDF exceeds its read bound")
    with pymupdf.open(stream=pdf, filetype="pdf") as document:
        if document.needs_pass or document.page_count < 1:
            raise ValueError("Original PDF is unavailable")
        pages = document.page_count
        document.load_page(0)
    _check(current)
    _verify(captured, current)
    if before != _fence((data["database"], index)):
        raise ValueError("Research metadata interfered; recheck in the worker")
    _check(current)
    return _sealed(
        OriginalProof,
        capture=captured,
        document_hash=data["document_hash"],
        data=pdf,
        pages=pages,
        source_path=path,
        _fence=before,
    )


def revalidate(proof, *, current=lambda: True):
    """Worker: revalidate original authority, never recapture changed content/owner."""
    if not isinstance(proof, OriginalProof) or proof._seal is not _SEAL:
        raise ValueError("Use an actual verified active original")
    return prepare(proof.capture, current=current)


def gui_status(proof, *, current=lambda: True):
    """No SQL/hash/PDF work. ready is admission after prior worker semantic proof.

    DB/index content interference returns recheck; only worker revalidation may
    issue a replacement proof. Changed native owners/source/body return revoked.
    Caller still checks actual window/view/loaded-document epochs and drafts.
    """
    if not isinstance(proof, OriginalProof) or proof._seal is not _SEAL or not current():
        return "revoked"
    try:
        for path, native in proof.capture._natives:
            if _native(path) != native:
                return "revoked"
        local._files_current(proof.capture._files)
        indexes = [p for p, _ in proof.capture._natives if Path(p).name == "index.sqlite"]
        database = proof.capture._database
        state = "ready" if _fence((database, *indexes)) == proof._fence else "recheck"
        return state if current() else "revoked"
    except (OSError, ValueError):
        return "revoked"
