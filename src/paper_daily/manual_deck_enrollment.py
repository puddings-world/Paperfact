"""Explicit first-enrollment manual baseline; source content is never a job.

The private source inventory is sealed and read-only. Only an actual fresh target
journal publishes its editable baseline; archived source epochs grant no authority.
"""

from __future__ import annotations

import hashlib
import json
import re
import tempfile
from contextlib import closing, contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from uuid import UUID, uuid5

from paper_daily import local_deck_proposals as local
from paper_daily import proposal_recovery_current as observed
from paper_daily.research_lifecycle import parent_lifecycle
from paper_daily.sync_files import canonical_json, file_id
from paper_daily.workspace_service import SnapshotChanged, _ReadOnlyStore

_SEAL = object()


@dataclass(frozen=True)
class Inventory:
    database: Path
    native: tuple
    _rows: tuple = field(repr=False)
    _locations: tuple = field(repr=False)
    _private: tuple = field(repr=False)
    _originals: tuple = field(repr=False)
    _witnesses: tuple = field(repr=False)
    _proof: object = field(repr=False, compare=False)
    _seal: object = field(repr=False, compare=False)

    @property
    def rows(self):
        return [json.loads(value) for value in self._rows]

    @property
    def objects(self):
        return [dict(path=path, sha256=sha, size=size) for sha, size, path in self._locations]

    @property
    def private(self):
        return list(self._private)

    @property
    def sources(self):
        return {
            (paper, sha): dict(path=path, sha256=sha, size=size)
            for paper, sha, size, path in self._originals
        }

    def check(self, ticket):
        if self._seal is not _SEAL:
            raise ValueError("Use an actual sealed manual enrollment inventory")
        ticket.check()
        try:
            self._proof.check(current=lambda: ticket.check() or True)
            local._files_current(self._witnesses)
        except (ValueError, OSError) as error:
            # This proof was already admitted; later liveness failures use the
            # maintained enrollment boundary, including when no manual slots exist.
            raise SnapshotChanged(
                "Original manual source changed; review a fresh snapshot"
            ) from error
        ticket.check()

    def _read(self, item, ticket):
        self.check(ticket)
        path = next(
            (
                path
                for sha, size, path in self._locations
                if (sha, size) == (item["sha256"], item["size"])
            ),
            None,
        )
        if path is None:
            raise ValueError("Manual baseline object is outside its captured closure")
        files = []
        data = observed._read(path, item["size"], files)
        if len(data) != item["size"] or hashlib.sha256(data).hexdigest() != item["sha256"]:
            raise ValueError("Manual enrollment bytes changed")
        local._files_current(self._witnesses)
        ticket.check()
        return data


def inventory(conn, database, sources, ticket):
    """Observe canonical manual slots and exact same-paper declared originals.

    sources is the maintained enrollment inventory keyed by (paper_id, digest),
    not serialized source paths or a global hash lookup. No schema is created.
    """
    database = local._path(database)
    native = local._native(database)
    ticket.check()
    by_hash = {}
    for (_paper, sha), item in sources.items():
        if item["sha256"] != sha:
            raise ValueError("Manual original inventory hash mismatch")
        by_hash[sha] = local._path(item["path"])
    with tempfile.TemporaryDirectory(prefix="paperfact-manual-enrollment-") as temporary:
        proof = observed.collect(
            database,
            conn,
            temporary,
            expected_native=native,
            source_objects=by_hash,
            current=lambda: ticket.check() or True,
        )
        locations, private, witnesses, originals = {}, set(), [], {}
        for row in proof.rows:
            manifest = observed.validate(row)
            science = observed.read(row, lambda item: proof.objects[item["sha256"]].read_bytes())
            folder = (
                database.parent
                / "presentations"
                / hashlib.sha256(row["paper_id"].encode()).hexdigest()[:24]
            )
            paths = [(manifest["body"], folder / (row["slot"] + ".json"))]
            paths.extend(
                (item, folder / "assets" / (item["sha256"] + ".png"))
                for item in manifest["figures"].values()
            )
            if manifest["evidence"]:
                paths.append(
                    (
                        manifest["evidence"],
                        folder / "evidence" / (science["deck"].source_hash + ".json"),
                    )
                )
            for item in manifest["originals"]:
                source = sources.get((row["paper_id"], item["sha256"]))
                if source is None or source["size"] != item["size"]:
                    raise ValueError("Manual original requires its actual same-paper source scope")
                paths.append((item, Path(source["path"])))
                originals[
                    (
                        row["paper_id"],
                        item["sha256"],
                        item["size"],
                        str(local._path(source["path"])),
                    )
                ] = None
            for item, location in paths:
                data = observed._read(location, item["size"], witnesses)
                if len(data) != item["size"] or hashlib.sha256(data).hexdigest() != item["sha256"]:
                    raise ValueError("Manual declared object differs from its source bytes")
                key = item["sha256"], item["size"], str(local._path(location))
                locations[key] = None
            write_lock = folder / ".deck-write.lock"
            job_locks = folder / ".research-jobs"
            locks = [(write_lock, b"")] if write_lock.exists() else []
            if job_locks.exists():
                local._path(job_locks)
                locks.extend((path, b"0") for path in job_locks.iterdir())
            for path, expected in locks:
                if path != write_lock and not re.fullmatch(r"[0-9a-f]{64}\.lock", path.name):
                    raise ValueError("Unknown manual coordination entry")
                if observed._read(path, 1, witnesses) != expected:
                    raise ValueError(
                        "Unknown manual coordination bytes require explicit preservation"
                    )
                private.add(str(local._path(path)))
        proof.check(current=lambda: ticket.check() or True)
    result = Inventory(
        database,
        native,
        tuple(canonical_json(row).decode() for row in proof.rows),
        tuple(sorted(locations)),
        tuple(sorted(private)),
        tuple(sorted(originals)),
        tuple(witnesses),
        proof,
        _SEAL,
    )
    result.check(ticket)
    return result


class _StageStore(_ReadOnlyStore):
    """Guard the actual index transaction, including its intentionally absent binding."""

    def __init__(self, actual, scope, guard):
        super().__init__(scope.root)
        self.quota_bytes = actual.quota_bytes
        self.max_blob_bytes = actual.max_blob_bytes
        self.chunk_bytes = actual.chunk_bytes
        self.scope, self.guard = scope, guard

    @contextmanager
    def _transaction(self):
        self.guard()
        conn = local._connect(self.scope.index, write=True)
        try:
            conn.execute("BEGIN IMMEDIATE")
            self.guard(conn)
            yield conn
            self.guard(conn)
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
        finally:
            conn.close()


def publish(client, blobs, version_root, captured, *, request_id, ticket):
    """Publish only into the actual trusted private candidate, never source paths.

    Each current is a real file operation with unknown producer input versions.
    The caller retains atomic publication of candidate+backup and source checks.
    """
    from paper_daily import sync_artifacts, sync_deck_files
    from paper_daily.sync_source_files import input_versions

    if not isinstance(captured, Inventory) or captured._seal is not _SEAL:
        raise ValueError("Manual publication requires the captured source inventory")
    request = UUID(request_id)
    if str(request) != request_id:
        raise ValueError("Use the original explicit enrollment request UUID")
    captured.check(ticket)
    if not captured.rows:
        return []
    from paper_daily import local_blob_binding

    owner = local_blob_binding._owner(client)
    store_scope = local_blob_binding._store(blobs)
    binding = (owner.workspace, owner.device, str(owner.database))
    with closing(local_blob_binding._read(store_scope.index)) as checked:
        bound = local_blob_binding._binding(checked, binding)
    database = local._path(client.journal.path)
    if database == captured.database or local._native(database) == captured.native:
        raise ValueError("First enrollment must never publish into its source workspace")
    native = local._native(database)
    index = local._path(blobs.root / "index.sqlite")
    index_native = local._native(index)
    root = Path(version_root).absolute()
    local._no_link(root)
    root.mkdir(parents=True, exist_ok=True)
    root = local._path(root)
    root_native = local._native(root)

    def store_guard(index_conn=None):
        captured.check(ticket)
        local_blob_binding._owner_current(owner)
        local_blob_binding._store_current(store_scope, index_conn)
        if index_conn is None:
            with closing(local_blob_binding._read(store_scope.index)) as checked:
                if local_blob_binding._binding(checked, binding) != bound:
                    raise ValueError("Candidate artifact binding changed during publication")
        elif local_blob_binding._binding(index_conn, binding) != bound:
            raise ValueError("Candidate artifact binding changed during publication")
        ticket.check()

    guarded = _StageStore(blobs, store_scope, store_guard)

    def check(conn=None):
        store_guard()
        if (
            local._native(database) != native
            or local._native(index) != index_native
            or local._native(root) != root_native
        ):
            raise ValueError("Actual enrollment database/artifact roots changed")
        if conn is not None:
            configured = sync_artifacts.paths(conn)
            if (
                configured is None
                or local._path(configured[0].root) != local._path(blobs.root)
                or Path(configured[1]).resolve() != root
            ):
                raise ValueError("Actual candidate artifact registration changed")
        ticket.check()

    published = []
    source_parents = {
        identity: json.loads(paper) for identity, paper, _token in captured._proof._parents
    }
    for row in captured.rows:
        ticket.check()
        science = observed.read(row, lambda item: captured._read(item, ticket))
        deck = science["deck"]
        deck._revision_figures = science["images"]
        with client.journal.transaction() as conn:
            check(conn)
            actual = local._paper(conn, row["paper_id"])
            token = parent_lifecycle(conn, "paper", row["paper_id"])
            mapping = conn.execute(
                "SELECT m.sync_id,p.incarnation FROM research_paper_identity m "
                "JOIN research_paper_projection p ON p.sync_id=m.sync_id WHERE m.local_id=?",
                (row["paper_id"],),
            ).fetchone()
            if actual != source_parents[row["paper_id"]] or token is None or mapping is None:
                raise ValueError("Fresh candidate paper differs from the captured source")
            portable, incarnation = mapping
            target = file_id(portable, "deck", row["slot"])
            before = sync_artifacts.desired_file(conn, target)
        payload, encoded = sync_deck_files.encode_deck(
            deck,
            portable,
            input_versions=input_versions(),
            source_document_hash=None,
            evidence=science["evidence"],
        )
        operation_id = str(uuid5(request, "manual-current:" + row["paper_id"] + ":" + row["slot"]))
        if before is not None:
            if before["operation_id"] != operation_id or before["payload"] != payload:
                raise ValueError("Manual enrollment may not overwrite another current deck")
            published.append(operation_id)
            continue
        sync_artifacts.stage_bytes(guarded, encoded)
        with client.journal.transaction() as conn:
            check(conn)
            now = conn.execute(
                "SELECT m.sync_id,p.incarnation FROM research_paper_identity m "
                "JOIN research_paper_projection p ON p.sync_id=m.sync_id WHERE m.local_id=?",
                (row["paper_id"],),
            ).fetchone()
            if (
                now is None
                or tuple(now) != (portable, incarnation)
                or local._paper(conn, row["paper_id"]) != actual
                or parent_lifecycle(conn, "paper", row["paper_id"]) != token
                or sync_artifacts.desired_file(conn, target) != before
            ):
                raise ValueError("Fresh manual target changed during staging")
            operation = client.new_graph_operation_in(
                conn, "research_file", target, payload, operation_id=operation_id
            )
            client.journal.apply_in(conn, operation, client.writer)
            check(conn)
        materialized = sync_artifacts.materialize(blobs, root, operation)
        with client.journal.transaction() as conn:
            check(conn)
            if (
                local._paper(conn, row["paper_id"]) != actual
                or parent_lifecycle(conn, "paper", row["paper_id"]) != token
                or not sync_artifacts.activate(conn, operation, materialized)
            ):
                raise ValueError("Fresh manual target changed before activation")
            check(conn)
        published.append(operation_id)
    captured.check(ticket)
    return published
