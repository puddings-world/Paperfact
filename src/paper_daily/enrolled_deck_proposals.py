"""Full scientific proposals in an explicitly owned enrolled CAS, never active decks.

All research writes belong to the caller transaction. Preparations observe the
target before content work; absent targets require a before-insert import grant.
Portable content never supplies receiver provenance or chooses a local path.
"""

from __future__ import annotations

import hashlib
import json
from contextlib import closing, contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from uuid import NAMESPACE_URL, uuid4, uuid5

from paper_daily import local_blob_binding as binding
from paper_daily import local_deck_proposals as shared
from paper_daily import portable_deck_proposal as codec
from paper_daily.research_lifecycle import parent_lifecycle
from paper_daily.sync_artifacts import stage_bytes
from paper_daily.sync_deck_publication import _observation
from paper_daily.sync_files import canonical_json, closed, identifier, read_json, text, uuid
from paper_daily.sync_source_files import inspectable
from paper_daily.workspace_service import _ReadOnlyStore

TABLE = "research_enrolled_deck_proposals"
COLUMNS = (
    "proposal_id request_id local_id portable_id captured_json owner_json manifest_json fingerprint"
)
SCHEMA = (
    "CREATE TABLE research_enrolled_deck_proposals(proposal_id TEXT PRIMARY KEY,"
    "request_id TEXT NOT NULL UNIQUE,local_id TEXT NOT NULL,portable_id TEXT NOT NULL,"
    "captured_json TEXT NOT NULL,owner_json TEXT NOT NULL,manifest_json TEXT NOT NULL,"
    "fingerprint TEXT NOT NULL)"
)
MAX_RECORDS = 2000
MAX_CATALOG_BYTES = 64 * 1024**2
MAX_OWNER_BYTES = 256 * 1024
_SEAL = object()


def _schema(conn, *, create=False):
    row = conn.execute("SELECT type,sql FROM sqlite_master WHERE name=?", (TABLE,)).fetchone()
    if row is None:
        if not create:
            return False
        conn.execute(SCHEMA)
        row = conn.execute("SELECT type,sql FROM sqlite_master WHERE name=?", (TABLE,)).fetchone()
    expected = [
        (n, name, "TEXT", int(n != 0), None, int(n == 0)) for n, name in enumerate(COLUMNS.split())
    ]
    if (
        row[0] != "table"
        or not isinstance(row[1], str)
        or binding._normalize(row[1]) != binding._normalize(SCHEMA)
        or [tuple(r) for r in conn.execute("PRAGMA table_info(" + TABLE + ")")] != expected
        or conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='trigger' AND tbl_name=?", (TABLE,)
        ).fetchone()
    ):
        raise ValueError("Enrolled proposal catalog schema requires explicit repair")
    return True


def _storage(scope, conn=None):
    binding._store_current(scope, conn)
    if conn is None:
        with closing(binding._read(scope.index)) as metadata:
            return _storage(scope, metadata)
    return {
        "root": str(scope.root),
        "root_native": list(scope.root_native),
        "index_native": list(scope.index_native),
        "objects_native": list(scope.objects_native),
        "partial_native": list(scope.partial_native),
    }


def _runtime(client, store, expected_native):
    expected = shared._expected(expected_native)
    owner = binding._owner(client)
    if owner.native != expected:
        raise ValueError("Original enrolled workspace was replaced")
    scope = binding._store(store)
    _runtime_current(owner, scope)
    return owner, scope


def _runtime_current(owner, scope):
    binding._owner_current(owner)
    binding._store_current(scope)
    with closing(binding._read(scope.index)) as conn:
        if not binding._binding(conn, (owner.workspace, owner.device, str(owner.database))):
            raise ValueError("Enrolled proposal requires an already owned transfer store")
    binding._owner_current(owner)
    binding._store_current(scope)


def _database(conn, owner):
    main = next(r[2] for r in conn.execute("PRAGMA database_list") if r[1] == "main")
    if shared._path(main) != owner.database or shared._native(owner.database) != owner.native:
        raise ValueError("Original enrolled proposal database changed")
    for table, fields in (
        ("paperfact_sync_identity", "workspace,device"),
        ("research_sync_binding", "workspace,origin"),
        ("research_capture_binding", "workspace,device"),
    ):
        present = conn.execute("SELECT 1 FROM sqlite_master WHERE name=?", (table,)).fetchone()
        if table == "research_capture_binding" and not present:
            continue
        rows = conn.execute("SELECT id," + fields + " FROM " + table + " LIMIT 2").fetchall()
        if len(rows) != 1 or tuple(rows[0]) != (1, owner.workspace, owner.device):
            raise ValueError("Enrolled proposal research bindings changed")


def _target(conn, owner, scope, local_id, portable_id, *, historical=False):
    _database(conn, owner)
    _runtime_current(owner, scope)
    paper = shared._paper(conn, local_id)
    token = parent_lifecycle(conn, "paper", local_id)
    mappings = conn.execute(
        "SELECT local_id,sync_id FROM research_paper_identity WHERE local_id=? OR sync_id=?",
        (local_id, portable_id),
    ).fetchall()
    if paper is None:
        if token is not None or (
            mappings
            and not (historical and [tuple(r) for r in mappings] == [(local_id, portable_id)])
        ):
            raise ValueError("Absent enrolled target has stale identity/lifetime")
        parent = None
    else:
        if token is None or [tuple(r) for r in mappings] != [(local_id, portable_id)]:
            raise ValueError("Enrolled target mapping/lifetime is unavailable")
        graph = owner.client._optimistic_graph(conn)[0]
        parent = graph.get(("paper", portable_id))
        if parent is None or not parent["active"]:
            raise ValueError("Enrolled proposal requires an active mapped paper")
        parent = parent["incarnation"]
    value = dict(
        database=str(owner.database),
        native=list(owner.native),
        binding=[owner.workspace, owner.device],
        storage=_storage(scope),
        local_id=local_id,
        portable_id=portable_id,
        paper=paper,
        parent_token=token,
        parent_incarnation=parent,
    )
    if len(canonical_json(value)) > MAX_OWNER_BYTES:
        raise ValueError("Enrolled proposal owner exceeds its bound")
    return value


def _scope(conn, owner, scope, captured, *, parent=True, exact_row=True):
    now = _target(
        conn, owner, scope, captured["local_id"], captured["portable_id"], historical=not parent
    )
    for key in ("database", "native", "binding", "storage", "local_id", "portable_id"):
        if now[key] != captured[key]:
            raise ValueError("Original enrolled proposal owner/store changed")
    if parent and (
        any(now[k] != captured[k] for k in ("parent_token", "parent_incarnation"))
        or (now["paper"] is None) != (captured["paper"] is None)
        or (exact_row and now["paper"] != captured["paper"])
    ):
        raise ValueError("Original enrolled proposal parent/absence changed")
    return now


class _OwnedStore(_ReadOnlyStore):
    def __init__(self, owner, scope, current):
        super().__init__(scope.root)
        self.owner, self.scope, self.current = owner, scope, current

    @contextmanager
    def _transaction(self):
        shared._check(self.current)
        _runtime_current(self.owner, self.scope)
        conn = shared._connect(self.scope.index, write=True)
        try:
            conn.execute("BEGIN IMMEDIATE")
            binding._store_current(self.scope, conn)
            expected = (self.owner.workspace, self.owner.device, str(self.owner.database))
            if not binding._binding(conn, expected):
                raise ValueError("Owned proposal CAS binding is missing")
            yield conn
            shared._check(self.current)
            binding._owner_current(self.owner)
            binding._store_current(self.scope, conn)
            if not binding._binding(conn, expected):
                raise ValueError("Owned proposal CAS binding changed before commit")
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
        finally:
            conn.close()


def _fingerprint(captured, manifest, request_id):
    return hashlib.sha256(
        canonical_json(
            dict(captured=captured, content=codec.fingerprint(manifest), request_id=request_id)
        )
    ).hexdigest()


def _identity(fingerprint):
    return "enrolled-deck:" + str(
        uuid5(NAMESPACE_URL, "paperfact.enrolled-deck-proposal.v1:" + fingerprint)
    )


@dataclass(frozen=True)
class Prepared:
    _json: str = field(repr=False)
    _files: tuple = field(repr=False)
    _owner: object = field(repr=False, compare=False)
    _store: object = field(repr=False, compare=False)
    _seal: object = field(repr=False, compare=False)

    @property
    def data(self):
        return json.loads(self._json)

    @property
    def proposal_id(self):
        return self.data["proposal_id"]

    @property
    def expected_absent(self):
        return self.data["captured"]["paper"] is None


def prepare(
    client,
    store,
    local_id,
    portable_id,
    manifest,
    read_blob,
    *,
    request_id,
    expected_native,
    current=lambda: True,
    allow_absent=False,
):
    """Worker preparation: readonly research, verified staging, no proposal adoption."""
    shared._check(current)
    text(local_id, 4096)
    uuid(portable_id)
    identifier(request_id)
    if type(allow_absent) is not bool:
        raise ValueError("allow_absent must be explicit")
    owner, scope = _runtime(client, store, expected_native)
    with closing(shared._connect(owner.database)) as conn:
        _schema(conn)
        captured = _target(conn, owner, scope, local_id, portable_id)
    if captured["paper"] is None and not allow_absent:
        raise ValueError("Choose an existing enrolled target or an explicit absent import")
    manifest = json.loads(canonical_json(manifest))
    codec.fingerprint(manifest)
    blobs = {}

    def capture(row):
        shared._check(current)
        value = read_blob(dict(row))
        shared._check(current)
        if type(value) is bytes:
            blobs[row["sha256"]] = value
        return value

    codec.decode(manifest, capture)
    with closing(shared._connect(owner.database)) as conn:
        _scope(conn, owner, scope, captured)
    stage_bytes(_OwnedStore(owner, scope, current), blobs)
    _content, files = shared._read_content(scope.root, manifest, current)
    with closing(shared._connect(owner.database)) as conn:
        _scope(conn, owner, scope, captured)
    shared._files_current(files)
    shared._check(current)
    fp = _fingerprint(captured, manifest, request_id)
    data = dict(
        captured=captured,
        manifest=manifest,
        request_id=request_id,
        fingerprint=fp,
        proposal_id=_identity(fp),
    )
    return Prepared(canonical_json(data).decode(), files, owner, scope, _SEAL)


def _prepared(value):
    if not isinstance(value, Prepared) or value._seal is not _SEAL:
        raise ValueError("Use an actual sealed enrolled proposal preparation")
    data = value.data
    if data["fingerprint"] != _fingerprint(
        data["captured"], data["manifest"], data["request_id"]
    ) or data["proposal_id"] != _identity(data["fingerprint"]):
        raise ValueError("Enrolled proposal preparation changed")
    return data


def _owner_valid(owner):
    closed(
        owner,
        {
            "database",
            "native",
            "binding",
            "storage",
            "local_id",
            "portable_id",
            "paper",
            "parent_token",
            "parent_incarnation",
        },
    )
    text(owner["database"], 4096)
    text(owner["local_id"], 4096)
    uuid(owner["portable_id"])
    shared._expected(owner["native"])
    if not isinstance(owner["binding"], list) or len(owner["binding"]) != 2:
        raise ValueError("Invalid enrolled proposal binding")
    for value in owner["binding"]:
        identifier(value)
    closed(
        owner["storage"],
        {"root", "root_native", "index_native", "objects_native", "partial_native"},
    )
    text(owner["storage"]["root"], 4096)
    for name in ("root_native", "index_native", "objects_native", "partial_native"):
        shared._expected(owner["storage"][name])
    if owner["paper"] is None:
        if owner["parent_token"] is not None or owner["parent_incarnation"] is not None:
            raise ValueError("Absent target has no captured parent authority")
    elif (
        not isinstance(owner["paper"], dict)
        or owner["paper"].get("id") != owner["local_id"]
        or not isinstance(owner["parent_token"], str)
        or len(owner["parent_token"]) != 32
        or any(c not in "0123456789abcdef" for c in owner["parent_token"])
        or not isinstance(owner["parent_incarnation"], str)
    ):
        raise ValueError("Invalid enrolled proposal parent")


def validate_record(row):
    closed(row, COLUMNS.split())
    for key in ("request_id", "proposal_id"):
        identifier(row[key])
    text(row["local_id"], 4096)
    uuid(row["portable_id"])
    for key in ("captured_json", "owner_json", "manifest_json"):
        maximum = codec.MAX_METADATA_BYTES if key == "manifest_json" else MAX_OWNER_BYTES
        if not isinstance(row[key], str) or len(row[key].encode()) > maximum:
            raise ValueError("Enrolled proposal metadata exceeds its bound")
    captured, owner = (read_json(row[k].encode()) for k in ("captured_json", "owner_json"))
    _owner_valid(captured)
    closed(owner, {"target", "observation"})
    _owner_valid(owner["target"])
    target = owner["target"]
    if target["paper"] is None:
        raise ValueError("Adopted proposal needs an actual receiver parent")
    for key in ("database", "native", "binding", "storage", "local_id", "portable_id"):
        if captured[key] != target[key]:
            raise ValueError("Enrolled proposal changed its original scope")
    if captured["paper"] is not None and any(
        captured[k] != target[k] for k in ("parent_token", "parent_incarnation")
    ):
        raise ValueError("Enrolled proposal changed its parent lifetime")
    observation = owner["observation"]
    closed(
        observation,
        {
            "database",
            "database_identity",
            "device_id",
            "workspace_id",
            "local_id",
            "paper_id",
            "entity_id",
            "mode",
            "local_parent_lifecycle",
            "observed",
            "artifact",
            "desired_document",
            "applied_document",
            "inputs_sha256",
            "input_versions",
        },
    )
    if (
        not isinstance(observation, dict)
        or observation.get("database") != target["database"]
        or observation.get("database_identity") != target["native"]
        or observation.get("local_id") != target["local_id"]
        or observation.get("paper_id") != target["portable_id"]
        or observation.get("local_parent_lifecycle") != target["parent_token"]
        or [observation.get("workspace_id"), observation.get("device_id")] != target["binding"]
    ):
        raise ValueError("Enrolled proposal observation differs from actual owner")
    manifest = read_json(row["manifest_json"].encode())
    fp = _fingerprint(captured, manifest, row["request_id"])
    if (
        row["fingerprint"] != fp
        or row["proposal_id"] != _identity(fp)
        or row["local_id"] != target["local_id"]
        or row["portable_id"] != target["portable_id"]
    ):
        raise ValueError("Enrolled proposal identity differs from captured content")
    return row


def record(conn, proposal_id):
    """No DDL, staging, enrollment or source authority on a catalog read."""
    identifier(proposal_id)
    if not _schema(conn):
        return None
    fields = []
    for name in COLUMNS.split():
        bound = codec.MAX_METADATA_BYTES if name == "manifest_json" else MAX_OWNER_BYTES
        fields.append(
            "CASE WHEN length(CAST(" + name + " AS BLOB))<=" + str(bound) + " THEN " + name + " END"
        )
    row = conn.execute(
        "SELECT " + ",".join(fields) + " FROM " + TABLE + " WHERE proposal_id=?", (proposal_id,)
    ).fetchone()
    return None if row is None else validate_record(dict(zip(COLUMNS.split(), row, strict=True)))


def _sources(conn, portable_id, manifest):
    files = []
    for item in manifest["originals"]:
        path = inspectable(conn, portable_id, item["sha256"])
        if path is None:
            raise ValueError("Proposal original is not owned by the exact receiver target")
        # inspectable already verifies closure, PDF digest and actual parent.
        stamp = shared.file_change.version(shared._path(path))
        if stamp[2] != item["size"]:
            raise ValueError("Proposal original source size changed")
        files.append((str(path), tuple(stamp)))
    shared._files_current(files)
    return tuple(files)


def _replay(conn, prepared, data):
    if not _schema(conn):
        return None
    found = conn.execute(
        "SELECT proposal_id FROM " + TABLE + " WHERE request_id=?", (data["request_id"],)
    ).fetchone()
    if found is None:
        return None
    row = record(conn, found[0])
    if (
        row["proposal_id"] != data["proposal_id"]
        or row["captured_json"] != canonical_json(data["captured"]).decode()
        or row["manifest_json"] != canonical_json(data["manifest"]).decode()
    ):
        raise ValueError("Enrolled proposal request ID was reused with changed input/target")
    _scope(
        conn,
        prepared._owner,
        prepared._store,
        json.loads(row["owner_json"])["target"],
        exact_row=False,
    )
    _sources(conn, row["portable_id"], data["manifest"])
    return row


def _insert(conn, prepared, *, new_parent=False, allow_updates=False, current=lambda: True):
    data = _prepared(prepared)
    owner, scope, captured = prepared._owner, prepared._store, data["captured"]
    shared._check(current)
    shared._files_current(prepared._files)
    prior = _replay(conn, prepared, data)
    if prior is not None:
        shared._check(current)
        return prior["proposal_id"]
    now = _scope(conn, owner, scope, captured, parent=not new_parent, exact_row=not allow_updates)
    if new_parent:
        if captured["paper"] is not None or now["paper"] is None:
            raise ValueError("Absent target was not created in this import grant")
    elif captured["paper"] is None:
        raise ValueError("Use the before-insert grant for an absent target")
    sources = _sources(conn, now["portable_id"], data["manifest"])
    content, files = shared._read_content(scope.root, data["manifest"], current)
    observation = _observation(conn, owner.client, now["local_id"], content["deck"]["mode"])
    receiver = dict(target=now, observation=observation)
    row = dict(
        proposal_id=data["proposal_id"],
        request_id=data["request_id"],
        local_id=now["local_id"],
        portable_id=now["portable_id"],
        captured_json=canonical_json(captured).decode(),
        owner_json=canonical_json(receiver).decode(),
        manifest_json=canonical_json(data["manifest"]).decode(),
        fingerprint=data["fingerprint"],
    )
    validate_record(row)
    _schema(conn, create=True)
    expression = "+".join("length(CAST(" + key + " AS BLOB))" for key in COLUMNS.split())
    count, size = conn.execute(
        "SELECT COUNT(*),COALESCE(SUM(" + expression + "),0) FROM " + TABLE
    ).fetchone()
    if (
        count >= MAX_RECORDS
        or size + sum(len(v.encode()) for v in row.values()) > MAX_CATALOG_BYTES
    ):
        raise ValueError("Enrolled proposal catalog exceeds its bounded capacity")
    shared._check(current)
    shared._files_current((*files, *sources))
    _scope(conn, owner, scope, now)
    conn.execute(
        "INSERT INTO " + TABLE + " VALUES(" + ",".join("?" for _ in row) + ")",
        tuple(row[key] for key in COLUMNS.split()),
    )
    _scope(conn, owner, scope, now)
    shared._files_current((*files, *sources))
    shared._check(current)
    return row["proposal_id"]


def adopt_in(conn, prepared, *, current=lambda: True):
    """Existing exact parent only. Never commit the caller transaction."""
    if not conn.in_transaction:
        raise ValueError("Enrolled adoption requires the caller transaction")
    name = "enrolled_adopt_" + uuid4().hex
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


class _Grant:
    def __init__(self, conn, prepared, current, allow_updates, seal):
        if seal is not _SEAL:
            raise ValueError("Use the actual before-insert enrolled grant context")
        self.conn, self.prepared, self.current = conn, prepared, current
        self.allow_updates, self.active, self.adopted = allow_updates, True, False
        self.post = {}

    def adopt(self):
        if not self.active or not self.conn.in_transaction:
            raise ValueError("Enrolled import grant is no longer active")
        for item, target in self.post.values():
            _scope(self.conn, item._owner, item._store, target)
        result = []
        for item in self.prepared:
            identity = _insert(
                self.conn,
                item,
                new_parent=item.expected_absent,
                allow_updates=self.allow_updates,
                current=self.current,
            )
            target = json.loads(record(self.conn, identity)["owner_json"])["target"]
            self.post.setdefault(
                identity,
                (item, _scope(self.conn, item._owner, item._store, target, exact_row=False)),
            )
            result.append(identity)
        self.adopted = True
        return result


@contextmanager
def import_targets_in(conn, prepared_collection, *, current=lambda: True, allow_updates=False):
    """Enter BEFORE trusted importer paper/source writes, adopt in the same transaction."""
    if type(allow_updates) is not bool:
        raise ValueError("allow_updates must be explicit")
    values = tuple(prepared_collection)
    if not conn.in_transaction or not 1 <= len(values) <= MAX_RECORDS:
        raise ValueError("Enrolled grant requires bounded preparations and caller transaction")
    name, grant = "enrolled_import_" + uuid4().hex, None
    conn.execute("SAVEPOINT " + name)
    try:
        requests = set()
        for item in values:
            data = _prepared(item)
            shared._check(current)
            if data["request_id"] in requests:
                raise ValueError("Duplicate enrolled proposal request")
            requests.add(data["request_id"])
            if _replay(conn, item, data) is None:
                _scope(conn, item._owner, item._store, data["captured"])
            shared._files_current(item._files)
        grant = _Grant(conn, values, current, allow_updates, _SEAL)
        yield grant
        if not conn.in_transaction:
            raise RuntimeError("Caller committed during enrolled import grant")
        shared._check(current)
        if not grant.adopted:
            raise ValueError("Enrolled proposal grant must be explicitly adopted")
        for item, target in grant.post.values():
            _scope(conn, item._owner, item._store, target)
            shared._files_current(item._files)
            _sources(conn, target["portable_id"], item.data["manifest"])
        conn.execute("RELEASE " + name)
    except BaseException:
        if conn.in_transaction:
            conn.execute("ROLLBACK TO " + name)
            conn.execute("RELEASE " + name)
        raise
    finally:
        if grant is not None:
            grant.active = False
            grant.conn, grant.prepared, grant.current, grant.post = None, (), None, {}


@dataclass(frozen=True)
class ReadProposal:
    _record: str = field(repr=False)
    _research: str = field(repr=False)
    _images: tuple = field(repr=False)
    _originals: tuple = field(repr=False)
    _files: tuple = field(repr=False)
    current_parent: bool
    _owner: object = field(repr=False, compare=False)
    _store: object = field(repr=False, compare=False)
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


def read(client, store, proposal_id, *, expected_native, current=lambda: True):
    """Worker-only verified full preview. No catalog/schema or source writes."""
    shared._check(current)
    owner, scope = _runtime(client, store, expected_native)
    with closing(shared._connect(owner.database)) as conn:
        row = record(conn, proposal_id)
        if row is None:
            raise ValueError("Enrolled proposal is unavailable")
        target = json.loads(row["owner_json"])["target"]
        now = _scope(conn, owner, scope, target, parent=False)
        manifest = json.loads(row["manifest_json"])
        same = all(now[k] == target[k] for k in ("parent_token", "parent_incarnation"))
        sources = _sources(conn, target["portable_id"], manifest) if same else ()
    content, files = shared._read_content(scope.root, manifest, current)
    with closing(shared._connect(owner.database)) as conn:
        if record(conn, proposal_id) != row:
            raise ValueError("Enrolled proposal changed during preview")
        after = _scope(conn, owner, scope, target, parent=False)
        if now != after:
            raise ValueError("Enrolled proposal parent changed during preview")
        if same:
            _sources(conn, target["portable_id"], manifest)
    shared._files_current((*files, *sources))
    shared._check(current)
    science = {k: v for k, v in content.items() if k not in {"image_bytes", "original_bytes"}}
    return ReadProposal(
        canonical_json(row).decode(),
        canonical_json(science).decode(),
        tuple(content["image_bytes"].items()),
        tuple(content["original_bytes"].items()),
        (*files, *sources),
        same and now["paper"] is not None,
        owner,
        scope,
        _SEAL,
    )


def assert_current_in(conn, proposal):
    """Same-lifetime Review guard, allowing a separately reviewed ordinary rename."""
    if not isinstance(proposal, ReadProposal) or proposal._seal is not _SEAL:
        raise ValueError("Use an actual verified enrolled proposal preview")
    row = proposal.record
    if record(conn, row["proposal_id"]) != row:
        raise ValueError("Enrolled proposal changed after preview")
    _scope(
        conn,
        proposal._owner,
        proposal._store,
        json.loads(row["owner_json"])["target"],
        exact_row=False,
    )
    _sources(conn, row["portable_id"], json.loads(row["manifest_json"]))
    shared._files_current(proposal._files)
    return True
