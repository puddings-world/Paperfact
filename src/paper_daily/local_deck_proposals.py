"""Explicit local-only scientific proposals; no enrollment, active deck or outbox.

Prepare stages verified content before catalog ownership. New-target imports must
use the before-insert grant in their own transaction. Serialized records never
provide process publication authority or choose a filesystem root.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import closing, contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from uuid import NAMESPACE_URL, uuid4, uuid5

from paper_daily import file_change
from paper_daily import portable_deck_proposal as codec
from paper_daily.research_lifecycle import ensure_lifecycle, parent_lifecycle
from paper_daily.sync_blobs import BlobManifest, BlobStore, _no_link
from paper_daily.sync_files import canonical_json, closed, identifier, read_json, text

TABLE = "research_local_deck_proposals"
COLUMNS = "proposal_id request_id paper_id captured_json owner_json manifest_json fingerprint"
SCHEMA = (
    "CREATE TABLE research_local_deck_proposals(proposal_id TEXT PRIMARY KEY,"
    "request_id TEXT NOT NULL UNIQUE,paper_id TEXT NOT NULL,captured_json TEXT NOT NULL,"
    "owner_json TEXT NOT NULL,manifest_json TEXT NOT NULL,fingerprint TEXT NOT NULL)"
)
MAX_RECORDS = 2000
MAX_CATALOG_BYTES = 64 * 1024**2
MAX_OWNER_BYTES = 256 * 1024
CAS_QUOTA_BYTES = 4 * 1024**3
_SEAL = object()
_MARKERS = {
    "paperfact_sync_identity",
    "research_sync_binding",
    "research_capture_binding",
    "document_reader_paths",
    "research_file_paths",
    "recovery_identity",
}


def _path(value):
    path = Path(value).absolute()
    for part in (path, *path.parents):
        _no_link(part)
    return path.resolve(strict=True)


def _native(value):
    path = _path(value)
    info = path.stat()
    if not info.st_ino:
        raise ValueError("Local proposal requires known native identity")
    return info.st_dev, info.st_ino


def _expected(value):
    if (
        not isinstance(value, (tuple, list))
        or len(value) != 2
        or any(type(n) is not int or n < 0 for n in value)
        or not value[1]
    ):
        raise ValueError("Capture the original native workspace before preparation")
    return tuple(value)


def _check(current):
    if not current():
        raise ValueError("Local proposal was cancelled or caller scope changed")


def _connect(path, *, write=False):
    conn = sqlite3.connect(
        path.as_uri() + ("?mode=rw" if write else "?mode=ro"), uri=True, cached_statements=0
    )
    conn.row_factory = sqlite3.Row
    return conn


def _database(conn, path, native):
    actual = next(row[2] for row in conn.execute("PRAGMA database_list") if row[1] == "main")
    if _path(actual) != path or _native(path) != tuple(native):
        raise ValueError("Original local proposal workspace was replaced")
    names = {row[0] for row in conn.execute("SELECT name FROM sqlite_master")}
    if names & _MARKERS or any(
        name.startswith(("paperfact_sync_", "research_capture_")) for name in names
    ):
        raise ValueError("Local-only proposal requires a genuinely unenrolled workspace")


def _paper(conn, paper_id):
    columns = [row[1] for row in conn.execute("PRAGMA table_info(papers)")]
    if not columns:
        raise ValueError("Actual paper table is required")
    quoted = ['"' + name.replace('"', '""') + '"' for name in columns]
    length = "+".join("COALESCE(length(CAST(" + name + " AS BLOB)),0)" for name in quoted)
    size = conn.execute("SELECT " + length + " FROM papers WHERE id=?", (paper_id,)).fetchone()
    if size is not None and size[0] > MAX_OWNER_BYTES // 2:
        raise ValueError("Local target row exceeds its bound")
    row = conn.execute("SELECT * FROM papers WHERE id=?", (paper_id,)).fetchone()
    return None if row is None else dict(zip(columns, row, strict=True))


def _schema(conn, *, create=False):
    row = conn.execute("SELECT type,sql FROM sqlite_master WHERE name=?", (TABLE,)).fetchone()
    if row is None:
        if not create:
            return False
        conn.execute(SCHEMA)
        row = conn.execute("SELECT type,sql FROM sqlite_master WHERE name=?", (TABLE,)).fetchone()

    def normalize(value):
        return "".join(value.split()).lower()

    expected = [
        (n, name, "TEXT", int(n != 0), None, int(n == 0)) for n, name in enumerate(COLUMNS.split())
    ]
    if (
        row[0] != "table"
        or normalize(row[1]) != normalize(SCHEMA)
        or [tuple(r) for r in conn.execute("PRAGMA table_info(" + TABLE + ")")] != expected
    ):
        raise ValueError("Local proposal catalog schema requires explicit repair")
    if conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='trigger' AND tbl_name=?", (TABLE,)
    ).fetchone():
        raise ValueError("Local proposal catalog has an unsupported writer")
    return True


def _root(database, native):
    namespace = hashlib.sha256(
        canonical_json(dict(database=str(database), native=list(native), binding=None))
    ).hexdigest()
    root = database.parent / ".paperfact-local-deck-proposals" / namespace / "blobs"
    for path in (root, *root.parents):
        _no_link(path)
    return root


def _storage_native(root):
    root = _path(root)
    result = {name: list(_native(root / name)) for name in ("index.sqlite", "objects", "partial")}
    result["root"] = list(_native(root))
    for suffix in ("-journal", "-wal", "-shm"):
        _no_link(Path(str(root / "index.sqlite") + suffix))
    return result


def _storage(root):
    result = _storage_native(root)
    with closing(_connect(root / "index.sqlite")) as conn:
        if conn.execute("SELECT 1 FROM sqlite_master WHERE name='transfer_binding'").fetchone():
            raise ValueError("Local proposal cache was rebound to synchronized storage")
    if list(_native(root / "index.sqlite")) != result["index.sqlite"]:
        raise ValueError("Local proposal index changed during verification")
    return result


class _LocalStore(BlobStore):
    def __init__(self, root, proof):
        self._proof = proof
        super().__init__(root, quota_bytes=CAS_QUOTA_BYTES, max_blob_bytes=codec.MAX_PDF_BYTES)
        after = _storage(root)
        if proof is not None and proof != after:
            raise ValueError("Original local proposal CAS changed during initialization")
        self._proof = after

    @contextmanager
    def _transaction(self):
        if self._proof is None:
            with super()._transaction() as conn:
                yield conn
            return
        if _storage(self.root) != self._proof:
            raise ValueError("Original local proposal CAS changed before write")
        conn = _connect(self.root / "index.sqlite", write=True)
        try:
            conn.execute("BEGIN IMMEDIATE")
            actual = next(r[2] for r in conn.execute("PRAGMA database_list") if r[1] == "main")
            if (
                _path(actual) != _path(self.root / "index.sqlite")
                or _storage_native(self.root) != self._proof
            ):
                raise ValueError("Original local proposal CAS changed at write admission")
            if conn.execute("SELECT 1 FROM sqlite_master WHERE name='transfer_binding'").fetchone():
                raise ValueError("Local proposal CAS acquired another store binding")
            yield conn
            if _storage_native(self.root) != self._proof:
                raise ValueError("Original local proposal CAS changed before commit")
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
        finally:
            conn.close()


def _owner(conn, database, native, paper_id):
    _database(conn, database, native)
    paper = _paper(conn, paper_id)
    token = parent_lifecycle(conn, "paper", paper_id)
    if paper is not None and token is None:
        raise ValueError("Actual target lifecycle is unavailable")
    result = dict(
        database=str(database),
        native=list(native),
        binding=None,
        paper_id=paper_id,
        paper=paper,
        parent_token=token,
    )
    if len(canonical_json(result)) > MAX_OWNER_BYTES:
        raise ValueError("Local proposal owner exceeds its bound")
    return result


def _scope(conn, captured, *, parent=True, exact_row=True):
    path = Path(captured["database"])
    _database(conn, path, captured["native"])
    root = _root(path, captured["native"])
    if _storage(root) != captured["storage"]:
        raise ValueError("Original local proposal storage changed")
    now = _owner(conn, path, captured["native"], captured["paper_id"])
    if parent and (
        now["parent_token"] != captured["parent_token"]
        or (now["paper"] is None) != (captured["paper"] is None)
        or (exact_row and now["paper"] != captured["paper"])
    ):
        raise ValueError("Original local proposal parent/absence changed")
    return now


def _references(manifest):
    result = {}
    for row in [manifest["research"], *manifest["images"], *manifest["originals"]]:
        result[row["sha256"]] = {key: row[key] for key in ("sha256", "size", "media_type")}
    return list(result.values())


def _files_current(files):
    for path, version in files:
        if file_change.version(_path(path)) != tuple(version):
            raise ValueError("Staged proposal source bytes changed")


def _read_content(root, manifest, current):
    files = []

    def read_blob(row):
        _check(current)
        path = _path(root / "objects" / row["sha256"])
        before = file_change.version(path)
        if before[2] != row["size"]:
            raise ValueError("Local proposal object size changed")
        with closing(_connect(root / "index.sqlite")) as conn:
            saved = conn.execute(
                "SELECT size,complete FROM blobs WHERE digest=?", (row["sha256"],)
            ).fetchone()
            if saved is None or tuple(saved) != (row["size"], 1):
                raise ValueError("Local proposal object is not durably complete")
        with path.open("rb") as stream:
            if file_change.version(path, stream=stream) != before:
                raise ValueError("Local proposal changed before read")
            data = stream.read(row["size"] + 1)
            if file_change.version(path, stream=stream) != before:
                raise ValueError("Local proposal changed during read")
        if file_change.version(path) != before:
            raise ValueError("Local proposal changed after read")
        files.append((str(path), tuple(before)))
        return data

    value = codec.decode(manifest, read_blob)
    _files_current(files)
    _check(current)
    return value, tuple(files)


def _fingerprint(captured, manifest, request_id):
    return hashlib.sha256(
        canonical_json(
            dict(captured=captured, content=codec.fingerprint(manifest), request_id=request_id)
        )
    ).hexdigest()


def _identity(fingerprint):
    return "local-deck:" + str(
        uuid5(NAMESPACE_URL, "paperfact.local-deck-proposal.v1:" + fingerprint)
    )


@dataclass(frozen=True)
class Prepared:
    _json: str = field(repr=False)
    _files: tuple = field(repr=False)
    _seal: object = field(repr=False, compare=False)

    @property
    def data(self):
        return json.loads(self._json)

    @property
    def proposal_id(self):
        return self.data["proposal_id"]

    @property
    def manifest(self):
        return self.data["manifest"]

    @property
    def expected_absent(self):
        return self.data["captured"]["paper"] is None


def prepare(
    database,
    paper_id,
    manifest,
    read_blob,
    *,
    request_id,
    expected_native,
    current=lambda: True,
    allow_absent=False,
):
    """Explicit worker operation; install local metadata before capturing target state."""
    _check(current)
    text(paper_id, 4096)
    identifier(request_id)
    if type(allow_absent) is not bool:
        raise ValueError("allow_absent must be explicit")
    path = _path(database)
    native = _expected(expected_native)
    if _native(path) != native:
        raise ValueError("Original local workspace changed before preparation")
    with closing(_connect(path, write=True)) as conn:
        conn.execute("BEGIN IMMEDIATE")
        try:
            _database(conn, path, native)
            _schema(conn, create=True)
            ensure_lifecycle(conn)
            captured = _owner(conn, path, native, paper_id)
            if captured["paper"] is None and not allow_absent:
                raise ValueError("Choose an existing local paper")
            _check(current)
            _database(conn, path, native)
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
    # Freeze the manifest before a supplied reader can mutate its caller object.
    manifest = json.loads(canonical_json(manifest))
    codec.fingerprint(manifest)
    # The callback sees only codec descriptors. Capture immutable verified bytes.
    blobs = {}

    def capture_blob(row):
        _check(current)
        value = read_blob(dict(row))
        _check(current)
        if type(value) is bytes:
            blobs[row["sha256"]] = value
        return value

    codec.decode(manifest, capture_blob)
    root = _root(path, native)
    before = _storage(root) if (root / "index.sqlite").exists() else None
    if root.exists() and before is None:
        with closing(_connect(path)) as conn:
            if conn.execute("SELECT 1 FROM " + TABLE + " LIMIT 1").fetchone():
                raise ValueError(
                    "Owned proposal index is missing; no replacement may be initialized"
                )
    store = _LocalStore(root, before)
    storage = _storage(root)
    if before is not None and before != storage:
        raise ValueError("Local proposal store changed during preparation")
    captured["storage"] = storage
    with closing(_connect(path)) as conn:
        _scope(conn, captured)
    for row in _references(manifest):
        _check(current)
        if _storage(root) != storage:
            raise ValueError("Local proposal store changed before staging")
        target = BlobManifest(row["sha256"], row["size"])
        status = store.begin(target)
        _check(current)
        if not status["complete"]:
            offset = status["offset"]
            value = blobs[row["sha256"]]
            while offset < len(value):
                _check(current)
                offset = store.append(target, offset, value[offset : offset + store.chunk_bytes])
                _check(current)
            store.finalize(target)
            _check(current)
    _content, files = _read_content(root, manifest, current)
    with closing(_connect(path)) as conn:
        _scope(conn, captured)
    _files_current(files)
    _check(current)
    fp = _fingerprint(captured, manifest, request_id)
    data = dict(
        captured=captured,
        manifest=manifest,
        request_id=request_id,
        fingerprint=fp,
        proposal_id=_identity(fp),
    )
    return Prepared(canonical_json(data).decode(), files, _SEAL)


def _prepared(value):
    if not isinstance(value, Prepared) or value._seal is not _SEAL:
        raise ValueError("An actual sealed local preparation is required")
    data = value.data
    if data["fingerprint"] != _fingerprint(
        data["captured"], data["manifest"], data["request_id"]
    ) or data["proposal_id"] != _identity(data["fingerprint"]):
        raise ValueError("Local proposal preparation changed")
    return data


def _owner_valid(owner):
    closed(owner, {"database", "native", "binding", "paper_id", "paper", "parent_token", "storage"})
    text(owner["database"], 4096)
    text(owner["paper_id"], 4096)
    _expected(owner["native"])
    if owner["binding"] is not None:
        raise ValueError("Local proposal cannot contain enrolled ownership")
    closed(owner["storage"], {"root", "index.sqlite", "objects", "partial"})
    for identity in owner["storage"].values():
        _expected(identity)
    if owner["paper"] is None:
        if owner["parent_token"] is not None:
            raise ValueError("Absent local parent cannot have an epoch")
    elif (
        not isinstance(owner["paper"], dict)
        or owner["paper"].get("id") != owner["paper_id"]
        or not isinstance(owner["parent_token"], str)
        or len(owner["parent_token"]) != 32
        or any(c not in "0123456789abcdef" for c in owner["parent_token"])
    ):
        raise ValueError("Invalid actual local proposal parent")


def validate_record(row):
    closed(row, COLUMNS.split())
    identifier(row["request_id"])
    identifier(row["proposal_id"])
    text(row["paper_id"], 4096)
    for name in ("captured_json", "owner_json"):
        if not isinstance(row[name], str) or len(row[name].encode()) > MAX_OWNER_BYTES:
            raise ValueError("Local proposal owner exceeds its bound")
    captured = read_json(row["captured_json"].encode())
    owner = read_json(row["owner_json"].encode())
    _owner_valid(captured)
    _owner_valid(owner)
    if owner["paper"] is None:
        raise ValueError("A retained proposal requires a real adopted parent")
    if any(
        captured[key] != owner[key]
        for key in ("database", "native", "binding", "paper_id", "storage")
    ) or (captured["paper"] is not None and captured["parent_token"] != owner["parent_token"]):
        raise ValueError("Local proposal changed its original owner")
    if not isinstance(row["manifest_json"], str):
        raise ValueError("Invalid local proposal manifest")
    manifest = read_json(row["manifest_json"].encode())
    fp = _fingerprint(captured, manifest, row["request_id"])
    if (
        row["fingerprint"] != fp
        or row["proposal_id"] != _identity(fp)
        or row["paper_id"] != owner["paper_id"]
    ):
        raise ValueError("Local proposal identity differs from captured content")
    return row


def record(conn, proposal_id):
    """Read-only closed catalog access; no lifecycle/schema initialization."""
    identifier(proposal_id)
    if not _schema(conn):
        return None
    columns = COLUMNS.split()
    fields = []
    for name in columns:
        bound = codec.MAX_METADATA_BYTES if name == "manifest_json" else MAX_OWNER_BYTES
        fields.append(
            "CASE WHEN length(CAST(" + name + " AS BLOB))<=" + str(bound) + " THEN " + name + " END"
        )
    value = conn.execute(
        "SELECT " + ",".join(fields) + " FROM " + TABLE + " WHERE proposal_id=?", (proposal_id,)
    ).fetchone()
    if value is None:
        return None
    return validate_record(dict(zip(columns, value, strict=True)))


def _replay(conn, data):
    found = conn.execute(
        "SELECT proposal_id FROM " + TABLE + " WHERE request_id=?", (data["request_id"],)
    ).fetchone()
    if found is None:
        return None
    row = record(conn, found[0])
    if (
        row["proposal_id"] != data["proposal_id"]
        or row["fingerprint"] != data["fingerprint"]
        or row["captured_json"] != canonical_json(data["captured"]).decode()
        or row["manifest_json"] != canonical_json(data["manifest"]).decode()
    ):
        raise ValueError("Local proposal request ID was reused for changed input/target")
    _scope(conn, json.loads(row["owner_json"]), exact_row=False)
    return row


def _insert(conn, prepared, *, new_parent=False, allow_updates=False, current=lambda: True):
    if not conn.in_transaction:
        raise ValueError("Local proposal adoption requires caller transaction")
    data = _prepared(prepared)
    captured = data["captured"]
    _check(current)
    if not _schema(conn):
        raise ValueError("Explicit local proposal preparation is required")
    _files_current(prepared._files)
    previous = _replay(conn, data)
    if previous is not None:
        _check(current)
        return previous["proposal_id"]
    now = _scope(conn, captured, parent=not new_parent, exact_row=not allow_updates)
    if new_parent:
        if captured["paper"] is not None or now["paper"] is None or not now["parent_token"]:
            raise ValueError("New local target was not actually created in this import")
    elif captured["paper"] is None:
        raise ValueError("Use the before-insert import grant for an absent local target")
    owner = {**now, "storage": captured["storage"]}
    row = dict(
        proposal_id=data["proposal_id"],
        request_id=data["request_id"],
        paper_id=captured["paper_id"],
        captured_json=canonical_json(captured).decode(),
        owner_json=canonical_json(owner).decode(),
        manifest_json=canonical_json(data["manifest"]).decode(),
        fingerprint=data["fingerprint"],
    )
    validate_record(row)
    existing = conn.execute(
        "SELECT proposal_id FROM " + TABLE + " WHERE request_id=?", (row["request_id"],)
    ).fetchone()
    if existing is not None:
        old = record(conn, existing[0])
        if old != row:
            raise ValueError("Local proposal request ID was reused for changed input/target")
        return row["proposal_id"]
    expression = "+".join("length(CAST(" + name + " AS BLOB))" for name in COLUMNS.split())
    count, size = conn.execute(
        "SELECT COUNT(*),COALESCE(SUM(" + expression + "),0) FROM " + TABLE
    ).fetchone()
    if (
        count >= MAX_RECORDS
        or size + sum(len(value.encode()) for value in row.values()) > MAX_CATALOG_BYTES
    ):
        raise ValueError("Local proposal catalog exceeds its bounded capacity")
    _check(current)
    _files_current(prepared._files)
    _scope(conn, captured, parent=not new_parent, exact_row=not allow_updates)
    conn.execute(
        "INSERT INTO " + TABLE + " VALUES(" + ",".join("?" for _ in row) + ")",
        tuple(row[name] for name in COLUMNS.split()),
    )
    _files_current(prepared._files)
    _scope(conn, owner)
    _check(current)
    return row["proposal_id"]


def adopt_in(conn, prepared, *, current=lambda: True):
    """Existing-parent adoption only; never commit the caller's research transaction."""
    if not conn.in_transaction:
        raise ValueError("Local adoption requires caller transaction")
    name = "local_adopt_" + uuid4().hex
    conn.execute("SAVEPOINT " + name)
    try:
        result = _insert(conn, prepared, current=current)
        conn.execute("RELEASE " + name)
        return result
    except BaseException:
        if conn.in_transaction:
            conn.execute("ROLLBACK TO " + name)
            conn.execute("RELEASE " + name)
        raise


def retain(prepared, *, current=lambda: True):
    data = _prepared(prepared)
    path = Path(data["captured"]["database"])
    with closing(_connect(path, write=True)) as conn:
        conn.execute("BEGIN IMMEDIATE")
        try:
            result = adopt_in(conn, prepared, current=current)
            _check(current)
            conn.commit()
            return result
        except BaseException:
            conn.rollback()
            raise


class _Grant:
    __slots__ = (
        "_conn",
        "_prepared",
        "_current",
        "_active",
        "_adopted",
        "_allow_updates",
        "_post_scopes",
    )

    def __init__(self, conn, prepared, current, seal, allow_updates):
        if seal is not _SEAL:
            raise ValueError("Use the actual before-insert grant context")
        self._conn, self._prepared, self._current = conn, prepared, current
        self._active, self._adopted = True, False
        self._allow_updates, self._post_scopes = allow_updates, {}

    @property
    def adopted(self):
        return self._adopted

    def _close(self):
        self._active = False
        self._conn, self._prepared, self._current = None, (), None
        self._post_scopes = {}

    def adopt(self):
        if not self._active or not self._conn.in_transaction:
            raise ValueError("Local import grant is no longer active")
        _check(self._current)
        # An explicit second call is idempotent, not a way to refresh a late edit.
        for encoded in self._post_scopes.values():
            _scope(self._conn, json.loads(encoded))
        result = []
        for item in self._prepared:
            allow_update = self._allow_updates and not item.expected_absent
            identity = _insert(
                self._conn,
                item,
                new_parent=item.expected_absent,
                allow_updates=allow_update,
                current=self._current,
            )
            result.append(identity)
            if allow_update and identity not in self._post_scopes:
                saved = record(self._conn, identity)
                owner = json.loads(saved["owner_json"])
                actual = _scope(self._conn, owner, exact_row=False)
                self._post_scopes[identity] = canonical_json(
                    {**actual, "storage": owner["storage"]}
                ).decode()
        self._adopted = True
        return result


@contextmanager
def import_targets_in(conn, prepared_collection, *, current=lambda: True, allow_updates=False):
    """Validate captured rows/absence BEFORE trusted caller inserts new paper rows.

    The caller must keep its transaction open. The savepoint rolls back all work
    within this scope on failure; this helper never owns the outer commit.
    Explicit allow_updates permits metadata updates after exact entry validation
    only for an existing same-epoch parent; captured before-state stays intact.
    """
    if type(allow_updates) is not bool:
        raise ValueError("allow_updates must be an explicit boolean")
    values = tuple(prepared_collection)
    if not conn.in_transaction or not 1 <= len(values) <= MAX_RECORDS:
        raise ValueError("Import grant requires bounded preparations and caller transaction")
    name = "local_proposals_" + uuid4().hex
    conn.execute("SAVEPOINT " + name)
    grant = None
    try:
        requests = set()
        for item in values:
            data = _prepared(item)
            _check(current)
            if _replay(conn, data) is None:
                _scope(conn, data["captured"])
            _files_current(item._files)
            if data["request_id"] in requests:
                raise ValueError("Duplicate local import request")
            requests.add(data["request_id"])
        grant = _Grant(conn, values, current, _SEAL, allow_updates)
        yield grant
        if not conn.in_transaction:
            raise RuntimeError("Caller committed during local proposal import")
        _check(current)
        if not grant.adopted:
            raise ValueError("Import proposal grant must be explicitly adopted")
        for item in values:
            data = _prepared(item)
            saved = record(conn, data["proposal_id"])
            displayed = grant._post_scopes.get(data["proposal_id"], saved["owner_json"])
            _scope(conn, json.loads(displayed))
            _files_current(item._files)
        conn.execute("RELEASE " + name)
    except BaseException:
        if conn.in_transaction:
            conn.execute("ROLLBACK TO " + name)
            conn.execute("RELEASE " + name)
        raise
    finally:
        if grant is not None:
            grant._close()


@dataclass(frozen=True)
class ReadProposal:
    _record: str = field(repr=False)
    _research: str = field(repr=False)
    _images: tuple = field(repr=False)
    _originals: tuple = field(repr=False)
    _files: tuple = field(repr=False)
    current_parent: bool
    _seal: object = field(repr=False, compare=False)

    @property
    def record(self):
        return json.loads(self._record)

    @property
    def content(self):
        return {
            **json.loads(self._research),
            "image_bytes": dict(self._images),
            "original_bytes": dict(self._originals),
        }

    @property
    def witnesses(self):
        return tuple((Path(path), tuple(version)) for path, version in self._files)

    def native_current(self):
        try:
            owner = json.loads(self.record["owner_json"])
            path = Path(owner["database"])
            if (
                _native(path) != tuple(owner["native"])
                or _storage_native(_root(path, owner["native"])) != owner["storage"]
            ):
                return False
            _files_current(self._files)
            return True
        except (OSError, ValueError, sqlite3.Error):
            return False


def read(database, proposal_id, *, expected_native, current=lambda: True):
    """Worker-only verified historical preview in its original native workspace."""
    _check(current)
    path = _path(database)
    native = _expected(expected_native)
    with closing(_connect(path)) as conn:
        _database(conn, path, native)
        row = record(conn, proposal_id)
        if row is None:
            raise ValueError("Local proposal is unavailable")
        owner = json.loads(row["owner_json"])
        now = _scope(conn, owner, parent=False)
    if owner["database"] != str(path) or owner["native"] != list(native):
        raise ValueError("Local proposal belongs to another original native workspace")
    manifest = json.loads(row["manifest_json"])
    content, files = _read_content(_root(path, native), manifest, current)
    with closing(_connect(path)) as conn:
        after = record(conn, proposal_id)
        if after != row:
            raise ValueError("Local proposal catalog changed during preview")
        now = _scope(conn, owner, parent=False)
    same = now["paper"] is not None and now["parent_token"] == owner["parent_token"]
    scientific = {
        key: value for key, value in content.items() if key not in {"image_bytes", "original_bytes"}
    }
    _check(current)
    return ReadProposal(
        canonical_json(row).decode(),
        canonical_json(scientific).decode(),
        tuple(content["image_bytes"].items()),
        tuple(content["original_bytes"].items()),
        files,
        same,
        _SEAL,
    )


def assert_current_in(conn, proposal):
    """Worker/commit guard for parent Review; no active deck writer is supplied here."""
    if not isinstance(proposal, ReadProposal) or proposal._seal is not _SEAL:
        raise ValueError("Use an actual verified local proposal preview")
    row = proposal.record
    if record(conn, row["proposal_id"]) != row:
        raise ValueError("Local proposal changed after preview")
    _scope(conn, json.loads(row["owner_json"]), exact_row=False)
    _files_current(proposal._files)
    return True
