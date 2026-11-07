"""Archive-only common proposals, explicit final-path Verify, then ordinary Apply.

An archive ID is never a native catalog row. Only explicit verification on the
published receiver creates an inactive local owner, with exact originals checked.
"""

from __future__ import annotations

import hashlib
import tempfile
from contextlib import closing

from paper_daily import enrolled_deck_proposals as catalog
from paper_daily import local_deck_proposals as local
from paper_daily import proposal_recovery as carrier
from paper_daily import recovery_provenance
from paper_daily.sync_deck_publication import runtime
from paper_daily.sync_files import canonical_json, closed, digest, identifier, read_json

CONTENT_PROTOCOL = carrier.TABLE
LINK_PROTOCOL = "common_proposal_adoption_v1"
LINK_FIELDS = "source_id proposal_id receiver_json fingerprint"
PREFIX = "recovered-deck:"


def virtual(identity):
    return isinstance(identity, str) and identity.startswith(PREFIX)


def all_carriers(records):
    selected = {}

    def visit(group):
        for row in [*group.common_proposals.values(), *group.archived_common_proposals.values()]:
            carrier.validate_row(row)
            previous = selected.setdefault(row["record_id"], row)
            if previous != row:
                raise ValueError("Archived proposal observations conflict; preserve both archives")
            if len(selected) > carrier.MAX_ROWS:
                raise ValueError("Recovered common proposal inventory exceeds its bound")
        for child in getattr(group, "_recovered_groups", ()):
            visit(child)

    visit(records)
    return [selected[key] for key in sorted(selected)]


def validate_link(row):
    closed(row, LINK_FIELDS.split())
    digest(row["source_id"])
    identifier(row["proposal_id"])
    if (
        not isinstance(row["receiver_json"], str)
        or len(row["receiver_json"].encode()) > catalog.MAX_OWNER_BYTES
    ):
        raise ValueError("Common proposal adoption owner exceeds its bound")
    owner = read_json(row["receiver_json"].encode())
    catalog._owner_valid(owner)
    if owner["paper"] is None:
        raise ValueError("An adoption link needs its actual receiver parent")
    expected = hashlib.sha256(
        canonical_json({key: row[key] for key in LINK_FIELDS.split() if key != "fingerprint"})
    ).hexdigest()
    if row["fingerprint"] != expected:
        raise ValueError("Common proposal adoption link differs from its scope")
    return set()


def inventory(conn, database, ticket):
    """First-enrollment content inventory; never install source native catalog rows."""
    database = local._path(database)
    native = local._native(database)
    with tempfile.TemporaryDirectory(prefix="paperfact-common-enrollment-") as temporary:
        collected = carrier.collect(
            database,
            conn,
            temporary,
            expected_native=native,
            current=lambda: ticket.check() or True,
        )
        rows, objects, private = collected.rows, {}, set()
        for row in rows:
            kind = read_json(row["provenance_json"].encode())["source_kind"]
            if kind == "local":
                root = local._root(database, native)
            else:
                from paper_daily.research_file_review import _storage

                root = _storage(conn)[0].root
            root = local._path(root)
            for suffix in ("", "-wal", "-shm", "-journal"):
                path = root / ("index.sqlite" + suffix)
                if path.exists():
                    private.add(str(local._path(path)))
            for item in carrier.references(row):
                path = local._path(root / "objects" / item["sha256"])
                if not any(p == path for p, _version in collected.witnesses):
                    raise ValueError("Enrolled content object lacks its actual source witness")
                objects[item["sha256"]] = dict(
                    path=str(path), sha256=item["sha256"], size=item["size"]
                )
        collected.check(current=lambda: ticket.check() or True)
    return {
        "rows": rows,
        "objects": [objects[key] for key in sorted(objects)],
        "private": sorted(private),
    }


def archive_in(conn, rows):
    from paper_daily import enrollment_history as history

    history.retain_in(conn, [history.wrap(CONTENT_PROTOCOL, row) for row in rows])


def _history_rows(conn, protocol):
    from paper_daily import enrollment_history as history

    if not conn.execute("SELECT 1 FROM sqlite_master WHERE name=?", (history.TABLE,)).fetchone():
        return []
    rows, total = [], 0
    for raw in conn.execute(
        "SELECT record_id,protocol,CASE WHEN length(CAST(body_json AS BLOB))<=? "
        "THEN body_json ELSE NULL END FROM research_history_archive WHERE protocol=? "
        "ORDER BY record_id LIMIT ?",
        (history.MAX_ROW, protocol, history.MAX_RECORDS + 1),
    ):
        row = dict(zip(history.COLUMNS.split(), raw, strict=True))
        total += len((row["body_json"] or "").encode())
        if len(rows) >= history.MAX_RECORDS or total > history.MAX_TOTAL:
            raise ValueError("Common proposal history exceeds its bounded inventory")
        rows.append(row)
    return rows


def contents(conn):
    """Closed archive groups only; no stored source path is read or activated."""
    from paper_daily import enrollment_history as history

    selected = {}
    for wrapped in _history_rows(conn, CONTENT_PROTOCOL):
        row, _sources = history.validate(wrapped)
        selected[row["record_id"]] = row
    if conn.execute(
        "SELECT 1 FROM sqlite_master WHERE name=?", (recovery_provenance.TABLE,)
    ).fetchone():
        rows, total = [], 0
        from paper_daily import sync_recovery

        for record_id, raw in conn.execute(
            "SELECT record_id,CASE WHEN length(CAST(body_json AS BLOB))<=? THEN body_json "
            "ELSE NULL END FROM research_recovery_provenance ORDER BY record_id LIMIT ?",
            (sync_recovery.MAX_ROW, sync_recovery.MAX_RECORDS + 1),
        ):
            if not isinstance(raw, str):
                raise ValueError("Recovered common provenance exceeds its row bound")
            total += len(raw.encode())
            rows.append({"record_id": record_id, "body_json": raw})
            if len(rows) > sync_recovery.MAX_RECORDS or total > sync_recovery.MAX_METADATA:
                raise ValueError("Recovered common provenance exceeds its inventory bound")
        for group in recovery_provenance.validate_groups(rows):
            for row in all_carriers(group):
                previous = selected.setdefault(row["record_id"], row)
                if previous != row:
                    raise ValueError("Recovered common proposal observations conflict")
    if len(selected) > carrier.MAX_ROWS:
        raise ValueError("Recovered common content exceeds its row bound")
    return selected


def _context(service):
    from paper_daily.research_file_review import _storage

    with closing(service._connect()) as conn:
        service._check(conn)
        client = runtime(database=service.path)
        if client is None:
            raise ValueError("Verify recovered proposals in the actual final editable workspace")
        store, root, _proof = _storage(conn)
        owner, scope = catalog._runtime(client, store, service.identity)
    return client, store, root, owner, scope


def _science(service, row):
    client, store, root, owner, scope = _context(service)
    manifest = carrier.validate_row(row)["manifest"]
    science, files = local._read_content(store.root, manifest, lambda: not service.closed)
    catalog._runtime_current(owner, scope)
    return science, files, client, store, root, owner, scope


def _linked(service, conn, row):
    """Malformed/foreign/retired links grant nothing and cannot hide source content."""
    from paper_daily import enrollment_history as history

    client, store, _root, _owner, _scope = _context(service)
    for wrapped in _history_rows(conn, LINK_PROTOCOL):
        try:
            link, _sources = history.validate(wrapped)
            if link["source_id"] != row["record_id"]:
                continue
            proposal = catalog.read(
                client,
                store,
                link["proposal_id"],
                expected_native=service.identity,
                current=lambda: not service.closed,
            )
            owner = read_json(proposal.record["owner_json"].encode())["target"]
            if (
                canonical_json(owner).decode() != link["receiver_json"]
                or not proposal.current_parent
                or proposal.record["local_id"] != row["paper_id"]
                or proposal.record["manifest_json"] != row["manifest_json"]
            ):
                continue
            return proposal
        except (ValueError, OSError, KeyError):
            continue
    return None


def entries(service, conn):
    rows = []
    for identity, row in contents(conn).items():
        if not service.recovery and _linked(service, conn, row) is not None:
            continue
        parent = conn.execute("SELECT title FROM papers WHERE id=?", (row["paper_id"],)).fetchone()
        rows.append(
            {
                "origin": "enrolled_deck",
                "id": PREFIX + identity,
                "decision": None,
                "summary": parent[0] if parent else row["paper_id"],
            }
        )
    return rows


def record(conn, identity):
    if not virtual(identity):
        raise ValueError("Select an actual archive-backed proposal identity")
    key = identity[len(PREFIX) :]
    digest(key)
    row = contents(conn).get(key)
    if row is None:
        raise ValueError("Recovered proposal content is unavailable")
    return row


def preview(service, conn, row):
    science, files, client, _store, _root, owner, scope = _science(service, row)
    local_id = row["paper_id"]
    mapping = conn.execute(
        "SELECT sync_id FROM research_paper_identity WHERE local_id=?", (local_id,)
    ).fetchone()
    if mapping is None:
        raise ValueError("Recovered proposal target has no actual receiver mapping")
    target = catalog._target(conn, owner, scope, local_id, mapping[0])
    service._check(conn)
    manifest = read_json(row["manifest_json"].encode())
    return {
        "retained": science["deck"],
        "retained_evidence": science["evidence"],
        "image_manifest": manifest["images"],
        "original_manifest": manifest["originals"],
        "source_hash": science["source_document_hash"],
        "scope": {"kind": "paper", "id": local_id},
        "target": {
            "id": local_id,
            "title": target["paper"]["title"],
            "slot": science["deck"]["mode"],
            "restoring": False,
        },
        "parent_token": target["parent_token"],
        "parent_row": target["paper"],
        "reason": (
            "Archived scientific content; explicit Verify creates an inactive "
            "final receiver proposal"
        ),
        "expected": {"archived_target": target, "files": [[p, v] for p, v in files]},
        "apply": False,
        "editable": False,
        "requires_confirmation": True,
    }


def _guard(service, conn, data, owner, scope):
    service._check(conn)
    target = data["expected"]["archived_target"]
    catalog._scope(conn, owner, scope, target)
    from paper_daily.research_file_review import _check_files

    _check_files({path: version for path, version in data["expected"]["files"]})


def verify(service, data):
    """User Verify: fresh actual final-path inactive owner and stable archival link."""
    from paper_daily import enrolled_deck_review
    from paper_daily import enrollment_history as history
    from paper_daily.research_review import digest as record_digest

    with closing(service._connect()) as conn:
        row = record(conn, data["id"])
        if record_digest(row) != data["record_hash"]:
            raise ValueError("Displayed recovered scientific content changed")
    science, files, client, store, _root, owner, scope = _science(service, row)
    with closing(service._connect()) as conn:
        _guard(service, conn, data, owner, scope)
        existing = _linked(service, conn, row)
    if existing is not None:
        adopted = existing
    else:
        if not read_json(row["provenance_json"].encode())["current_parent"]:
            raise ValueError("Historical source parent needs a separately confirmed reattachment")
        manifest = read_json(row["manifest_json"].encode())
        encoded, blobs = carrier.codec.encode(
            science["deck"],
            science["evidence"],
            science["image_bytes"],
            science["original_bytes"],
            source_document_hash=science["source_document_hash"],
        )
        if encoded != manifest:
            raise ValueError("Recovered scientific manifest changed")
        target = data["expected"]["archived_target"]
        prepared = catalog.prepare(
            client,
            store,
            target["local_id"],
            target["portable_id"],
            manifest,
            lambda item: blobs[item["sha256"]],
            request_id="recovered-proposal:" + row["record_id"],
            expected_native=service.identity,
            current=lambda: not service.closed,
        )
        # The journal transaction is real final receiver authority. Capture service
        # guards remain on maintained captured read handles, never fake instrumentation.
        with client.journal.transaction() as conn:
            with closing(service._connect()) as checked:
                _guard(service, checked, data, owner, scope)
            catalog._scope(conn, owner, scope, target)
            identity = catalog.adopt_in(conn, prepared, current=lambda: not service.closed)
            native_row = catalog.record(conn, identity)
            receiver = read_json(native_row["owner_json"].encode())["target"]
            link = {
                "source_id": row["record_id"],
                "proposal_id": identity,
                "receiver_json": canonical_json(receiver).decode(),
            }
            link["fingerprint"] = hashlib.sha256(canonical_json(link)).hexdigest()
            history.retain_in(conn, [history.wrap(LINK_PROTOCOL, link)])
            local._files_current(files)
            catalog._scope(conn, owner, scope, target)
            with closing(service._connect()) as checked:
                service._check(checked)
        adopted = catalog.read(
            client,
            store,
            identity,
            expected_native=service.identity,
            current=lambda: not service.closed,
        )
    value = dict(data)
    value.update(id=adopted.record["proposal_id"], record_hash=record_digest(adopted.record))
    value.update(enrolled_deck_review.prepare(service, adopted.record))
    return value
