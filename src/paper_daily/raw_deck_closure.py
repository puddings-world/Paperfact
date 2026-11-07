"""Private raw-draft byte closure; source records remain immutable observations.

A closure is not an operation or a writer capability. Reads never follow paths in
serialized drafts. Retention pins bytes from captured producer inputs only.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import closing, contextmanager
from copy import deepcopy
from pathlib import Path
from uuid import uuid4

from paper_daily.sync_blobs import BlobManifest, _no_link
from paper_daily.sync_files import (
    MAX_ASSETS,
    MAX_BODY,
    canonical_json,
    closed,
    descriptor,
    digest,
    file_id,
    identifier,
    read_json,
    text,
    validate_closure,
    validate_payload,
)

TABLE = "research_file_draft_closures"
FIELDS = {"candidate_id", "source_sha256", "payload", "inventory"}
SQL = ("CREATE TABLE research_file_draft_closures("
       "candidate_id TEXT PRIMARY KEY,source_sha256 TEXT NOT NULL,"
       "payload TEXT NOT NULL,inventory TEXT NOT NULL)")
RAW_FIELDS = {"candidate_id", "entity_id", "deck", "observation"}


def _native(path):
    path = Path(path)
    for part in (path, *path.parents):
        _no_link(part)
    info = path.stat()
    return [info.st_dev, info.st_ino]


def source_hash(raw):
    closed(raw, RAW_FIELDS)
    identifier(raw["candidate_id"])
    for field in ("deck", "observation"):
        if not isinstance(raw[field], str) or len(raw[field].encode()) > MAX_BODY:
            raise ValueError("Raw draft exceeds its bounded protocol")
    return hashlib.sha256(canonical_json(raw)).hexdigest()


def normalized_deck(raw, paper_id):
    from paper_daily.presentations import deck_from_dict
    from paper_daily.slide_layout import used_figures
    from paper_daily.sync_deck_files import FIGURE_FIELDS, SOURCE_FIELDS, _source

    value = deepcopy(raw)
    deck = deck_from_dict(value)
    used = used_figures(deck)
    value["paper_id"] = paper_id
    value["generation"] = {k: v for k, v in value["generation"].items()
                           if k in {"inputs", "backend", "model"} and v is not None}
    figures, ids = [], set()
    for figure in value["figures"]:
        item = {k: v for k, v in figure.items() if k in FIGURE_FIELDS}
        item["asset_id"] = figure["id"]
        _source(item, figure=True)
        if figure["id"] in ids:
            raise ValueError("Duplicate raw draft figure identity")
        ids.add(figure["id"])
        if figure["id"] in used:
            figures.append(item)
    value["figures"] = figures
    value["sources"] = [{k: v for k, v in item.items() if k in SOURCE_FIELDS}
                        for item in value["sources"]]
    return value


def validate_row(row):
    closed(row, FIELDS)
    identifier(row["candidate_id"])
    digest(row["source_sha256"])
    if not isinstance(row["payload"], str) or not isinstance(row["inventory"], str):
        raise ValueError("Raw draft closure JSON must be bounded text")
    payload = read_json(row["payload"].encode())
    validate_payload(payload)
    if payload["feature"] != "deck":
        raise ValueError("Raw draft closure supports editable decks only")
    inventory = read_json(row["inventory"].encode())
    closed(inventory, {"version", "images"})
    images = inventory["images"]
    if (type(inventory["version"]) is not int or inventory["version"] != 1
            or not isinstance(images, list) or len(images) > 256):
        raise ValueError("Invalid raw draft image inventory")
    ids, total = set(), 0
    for image in images:
        closed(image, {"id", "sha256", "size", "media_type"})
        text(image["id"], 250)
        digest(image["sha256"])
        if (image["id"] in ids or image["media_type"] != "image/png"
                or type(image["size"]) is not int or not 0 < image["size"] <= 8_000_000):
            raise ValueError("Invalid raw draft image descriptor")
        ids.add(image["id"])
        total += image["size"]
    if total > MAX_ASSETS:
        raise ValueError("Raw draft images exceed 64 MiB")
    return payload, inventory


def summarize(raw, *, strict=True):
    source = source_hash(raw)
    deck, observation = json.loads(raw["deck"]), json.loads(raw["observation"])
    paper = observation.get("paper_id")
    if paper is None and observation.get("artifact"):
        paper = observation["artifact"]["payload"]["paper_id"]
    try:
        expected = normalized_deck(deck, paper) if paper else None
    except (ValueError, KeyError, TypeError):
        if strict:
            raise
        expected = None
    return {
        "candidate_id": raw["candidate_id"], "entity_id": raw["entity_id"],
        "source_sha256": source,
        "deck_sha256": hashlib.sha256(canonical_json(expected)).hexdigest() if expected else None,
        "figures": {row["id"]: row.get("asset") for row in deck["figures"]},
        "documents": sorted({row["document_hash"] for row in [*deck["sources"], *deck["figures"]]
                             if row.get("document_hash")}),
    }


def validate_summary(summary, row):
    payload, inventory = validate_row(row)
    if (summary["deck_sha256"] is None
            or summary["candidate_id"] != row["candidate_id"]
            or summary["source_sha256"] != row["source_sha256"]
            or summary["entity_id"] != file_id(payload["paper_id"], "deck", payload["slot"])
            or set(summary["figures"]) != {item["id"] for item in inventory["images"]}):
        raise ValueError("Raw draft closure differs from its immutable source")
    return payload, inventory


def verify_summary(summary, row, read):
    from paper_daily.sync_deck_files import validate_png

    payload, inventory = validate_summary(summary, row)
    body = validate_closure(payload, read)
    if hashlib.sha256(canonical_json(body["deck"])).hexdigest() != summary["deck_sha256"]:
        raise ValueError("Raw draft body differs from its immutable source")
    images = {image["id"]: image for image in inventory["images"]}
    for image in images.values():
        data = read(image)
        if len(data) != image["size"] or hashlib.sha256(data).hexdigest() != image["sha256"]:
            raise ValueError("Raw draft image bytes changed")
        validate_png(data)
    for image in payload["assets"]:
        if image["role"] == "figure" and any(
            image[key] != images[image["id"]][key] for key in ("sha256", "size", "media_type")
        ):
            raise ValueError("Raw draft figure inventory contradicts its deck")
    return body


def _schema(conn, *, create=False):
    row = conn.execute("SELECT sql FROM sqlite_master WHERE name=? AND type='table'", (TABLE,)
                       ).fetchone()
    if row is None:
        if not create:
            raise ValueError("Raw draft assets are not pinned; explicit preparation is required")
        if not conn.in_transaction:
            raise ValueError("Draft closure schema needs its caller transaction")
        conn.execute(SQL)
    elif row[0] != SQL:
        raise ValueError("Raw draft closure schema differs from its maintained protocol")


def _closure_row(conn, identity, *, missing_ok=False):
    _schema(conn)
    row = conn.execute(
        "SELECT candidate_id,source_sha256,"
        "CASE WHEN length(CAST(payload AS BLOB))<=? THEN payload ELSE NULL END,"
        "CASE WHEN length(CAST(inventory AS BLOB))<=? THEN inventory ELSE NULL END FROM "
        + TABLE + " WHERE candidate_id=?", (MAX_BODY, MAX_BODY, identity),).fetchone()
    if row is None:
        if missing_ok:
            return None
        raise ValueError("Raw draft assets are not pinned; explicit preparation is required")
    result = dict(zip(("candidate_id", "source_sha256", "payload", "inventory"), row, strict=True))
    validate_row(result)
    return result


def candidate_in(conn, raw):
    row = _closure_row(conn, raw["candidate_id"])
    validate_summary(summarize(raw), row)
    return {"candidate_id": raw["candidate_id"], "entity_id": raw["entity_id"],
            "payload": row["payload"], "observation": raw["observation"],
            "closure_sha256": hashlib.sha256(canonical_json(row)).hexdigest()}


def verify_in(conn, raw):
    """Verify all retained draft images once; return local file-version proofs."""
    from paper_daily.research_file_review import _stamp

    candidate = candidate_in(conn, raw)
    row = _closure_row(conn, raw["candidate_id"])
    store, _registration = _storage(conn)
    files = {}
    def read(item):
        manifest = BlobManifest(item["sha256"], item["size"])
        path = store._path(manifest)
        _native(path)
        before = _stamp(path)
        if before[2] != manifest.size:
            raise ValueError("Retained raw draft image size changed")
        with path.open("rb") as stream:
            if _stamp(path, stream=stream) != before:
                raise ValueError("Retained raw draft changed before reading")
            data = stream.read(manifest.size + 1)
            if _stamp(path, stream=stream) != before:
                raise ValueError("Retained raw draft changed while reading")
        if str(path) in files and files[str(path)] != before:
            raise ValueError("Retained raw draft changed between reads")
        files[str(path)] = before
        return data
    verify_summary(summarize(raw), row, read)
    return candidate, files


def _scope(conn, path, observation):
    if _native(path) != observation["database_identity"]:
        raise ValueError("Original workspace was replaced; preserve the open draft")
    main = next(row[2] for row in conn.execute("PRAGMA database_list") if row[1] == "main")
    row = conn.execute("SELECT workspace,origin FROM research_sync_binding WHERE id=1").fetchone()
    if Path(main).resolve() != path or row is None or tuple(row) != (
        observation["workspace_id"], observation["device_id"]
    ):
        raise ValueError("Original workspace binding changed; preserve the open draft")


def _storage(conn):
    from paper_daily.workspace_service import _ReadOnlyStore

    row = conn.execute("SELECT workspace,blob_root,version_root FROM research_file_paths WHERE id=1"
                       ).fetchone()
    if row is None:
        raise ValueError("Original draft has no registered artifact storage")
    store = _ReadOnlyStore(Path(row[1]))
    return store, [list(row), _native(store.root), _native(store.root / "index.sqlite")]


def _owned_store(conn, store):
    from paper_daily.legacy_primary_migration import _store_scope
    from paper_daily.workspace_service import _ReadOnlyStore

    path = Path(next(row[2] for row in conn.execute("PRAGMA database_list")
                     if row[1] == "main")).resolve(strict=True)
    row = conn.execute("SELECT workspace,origin FROM research_sync_binding WHERE id=1").fetchone()
    if row is None:
        raise ValueError("Original draft workspace binding is unavailable")
    binding = (*tuple(row), str(path))
    native = _store_scope(store, path, *tuple(row))

    class OwnedDraftStore(_ReadOnlyStore):
        @contextmanager
        def _transaction(self):
            if tuple(_native(self.root / "index.sqlite")) != native:
                raise ValueError("Original draft store index was replaced")
            with super()._transaction() as metadata:
                owned = metadata.execute(
                    "SELECT workspace,device,research_path FROM transfer_binding WHERE id=1"
                ).fetchone()
                if (owned is None or tuple(owned) != binding
                        or tuple(_native(self.root / "index.sqlite")) != native):
                    raise ValueError("Draft store belongs to another workspace/device/database")
                yield metadata

    return OwnedDraftStore(store.root)


def _encode(conn, observation, deck, evidence):
    from paper_daily import presentations
    from paper_daily.sync_deck_files import encode_deck, validate_png
    from paper_daily.sync_deck_publication import publication_scope, runtime
    from paper_daily.sync_journal import canonical_operation

    tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if "research_file_paths" not in tables:
        raise ValueError("Raw draft has no managed byte storage")
    store, registration = _storage(conn)
    if registration[0][0] != observation["workspace_id"]:
        raise ValueError("Raw draft storage belongs to another workspace")
    client = runtime(database=Path(observation["database"]))
    candidate = deepcopy(deck)
    loaded = getattr(deck, "_file_operation", None)
    if loaded:
        row = conn.execute("SELECT operation FROM research_file_versions WHERE operation_id=?",
                           (loaded["operation_id"],)).fetchone()
        if (row is None or row[0] != canonical_operation(loaded)
                or loaded["workspace_id"] != observation["workspace_id"]
                or loaded["entity_id"] != observation["entity_id"]):
            raise ValueError("Loaded raw draft has no original artifact ownership")
    if (deck.figures and not loaded and getattr(deck, "_revision_figures", None) is None
            and getattr(deck, "_revision_roots", None) is None):
        raise ValueError("Raw draft figures need captured original roots or producer bytes")
    images, blobs, inventory = {}, {}, []
    with publication_scope(client):
        for figure in deck.figures:
            data = presentations.figure_bytes(deck, figure["id"])
            validate_png(data)
            images[figure["id"]] = data
            item = {"id": figure["id"], **descriptor(data, "image/png")}
            inventory.append(item)
            blobs[item["sha256"]] = data
    candidate._revision_figures = images
    provenance = loaded["payload"] if loaded else None
    selected_evidence = deepcopy(evidence)
    if selected_evidence is None and provenance and deck.source_hash:
        body = read_json(store.verified_path(BlobManifest(
            provenance["body"]["sha256"], provenance["body"]["size"])).read_bytes())
        if body["deck"]["source_hash"] == deck.source_hash and body["evidence_asset"]:
            item = next(a for a in provenance["assets"] if a["id"] == body["evidence_asset"])
            selected_evidence = read_json(store.verified_path(
                BlobManifest(item["sha256"], item["size"])).read_bytes())
    inputs = deepcopy(provenance["input_versions"] if provenance else observation["input_versions"])
    if provenance and evidence is None:
        document = provenance["source_document_hash"]
    else:
        hashes = {s["document_hash"] for s in (selected_evidence or {}).get("sources", [])
                  if s.get("kind") in {"original", "figure"} and s.get("document_hash")}
        document = next(iter(hashes)) if len(hashes) == 1 else None
        inputs["documents"] = [item for item in inputs["documents"] if item["sha256"] == document]
    payload, encoded = encode_deck(candidate, observation["paper_id"], input_versions=inputs,
                                  source_document_hash=document, evidence=selected_evidence)
    blobs.update(encoded)
    return store, registration, payload, {"version": 1, "images": inventory}, blobs


def _existing(conn, raw, deck, evidence):
    prior = conn.execute("SELECT candidate_id,entity_id,deck,observation FROM "
                         "research_file_drafts WHERE candidate_id=?", (raw["candidate_id"],)
                         ).fetchone()
    if prior is None:
        return False
    if tuple(raw[key] for key in ("candidate_id", "entity_id", "deck", "observation")) != prior:
        raise ValueError("Raw draft request identity was reused for different content")
    if not conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (TABLE,)
                        ).fetchone():
        return False
    row = _closure_row(conn, raw["candidate_id"], missing_ok=True)
    if row is None:
        return False
    if row["source_sha256"] != source_hash(raw):
        raise ValueError("Retained raw draft closure differs from its original request")
    payload, inventory = validate_row(row)
    if evidence is not None:
        from paper_daily.sync_deck_files import SOURCE_FIELDS

        try:
            snapshot = {"version": 1, "sources": [
                {k: v for k, v in item.items() if k in SOURCE_FIELDS}
                for item in evidence["sources"]], "coverage": evidence["coverage"],
                "source_hash": evidence["source_hash"]}
        except (KeyError, TypeError, AttributeError) as error:
            raise ValueError(
                "Raw request was reused with different or malformed evidence") from error
        expected = descriptor(canonical_json(snapshot), "application/json")
        declared = [a for a in payload["assets"] if a["role"] == "evidence"]
        if len(declared) != 1 or any(declared[0][key] != value for key, value in expected.items()):
            raise ValueError("Raw request was reused with different evidence")
    images = getattr(deck, "_revision_figures", None)
    if images is not None:
        if not isinstance(images, dict):
            raise ValueError("Raw request was reused with different captured images")
        for image in inventory["images"]:
            if image["id"] in images:
                data = images[image["id"]]
                if (not isinstance(data, bytes) or len(data) != image["size"]
                        or hashlib.sha256(data).hexdigest() != image["sha256"]):
                    raise ValueError("Raw request was reused with different captured images")
    return True


def retain(observation, deck, *, evidence=None, request_id=None):
    """Legacy identity-only helper; callers needing durability use retain_outcome."""
    return retain_outcome(observation, deck, evidence=evidence, request_id=request_id).candidate_id


def retain_outcome(observation, deck, *, evidence=None, request_id=None, _captured=None):
    from paper_daily import raw_deck_receipts as receipts
    from paper_daily.sync_artifacts import stage_bytes
    from paper_daily.sync_deck_publication import DraftRetention

    requested = Path(observation["database"])
    _native(requested)
    path = requested.resolve(strict=True)
    if _native(path) != observation["database_identity"]:
        raise ValueError("Original workspace was replaced; preserve the open draft")
    raw = {"candidate_id": request_id or str(uuid4()), "entity_id": observation["entity_id"],
           "deck": canonical_json(deck.to_dict()).decode(),
           "observation": canonical_json(observation).decode()}
    fingerprint = source_hash(raw)
    reason, capture, ready, receipt_ready = None, None, False, False
    try:
        with closing(sqlite3.connect(path.as_uri() + "?mode=rw", uri=True)) as conn, conn:
            _scope(conn, path, observation)
            prior_ready = _existing(conn, raw, deck, evidence)
            prior = conn.execute("SELECT 1 FROM research_file_drafts WHERE candidate_id=?",
                                 (raw["candidate_id"],)).fetchone() is not None
            retained = receipts.read_owned(conn, raw, missing_ok=True)
            if retained is not None:
                header, blobs, _files = retained
                receipts.check_retry(header, raw, deck, evidence)
                closure, receipt_ready = header["closure"], True
                store, captured_storage = _storage(conn)
            elif _captured is not None:
                header, blobs = receipts.decode(_captured)
                if header["owner"] != receipts._owner(conn, raw):
                    raise ValueError("Captured retention retry belongs to another original owner")
                receipts.check_retry(header, raw, deck, evidence)
                closure, capture = header["closure"], _captured
                store, captured_storage = _storage(conn)
            elif prior_ready:
                verify_in(conn, raw)
                return DraftRetention(raw["candidate_id"], "cas", deck, deepcopy(evidence))
            elif prior:
                return DraftRetention(
                    raw["candidate_id"], "incomplete", deck, deepcopy(evidence),
                    "Original image declarations unavailable; explicit capture required")
            else:
                try:
                    store, captured_storage, payload, inventory, blobs = _encode(
                        conn, observation, deck, evidence)
                    closure = {"candidate_id": raw["candidate_id"], "source_sha256": fingerprint,
                               "payload": canonical_json(payload).decode(),
                               "inventory": canonical_json(inventory).decode()}
                    verify_summary(summarize(raw), closure, lambda row: blobs[row["sha256"]])
                    capture = receipts.capture(conn, raw, closure, evidence, blobs)
                except (ValueError, OSError, KeyError) as error:
                    closure, captured_storage, blobs = None, None, None
                    reason = str(error)
            if closure is not None:
                if not receipt_ready:
                    try:
                        receipts.write_owned(conn, capture)
                        receipt_ready = True
                    except OSError as error:
                        reason = str(error)
                try:
                    store = _owned_store(conn, store)
                    stage_bytes(store, blobs)
                    for sha, data in blobs.items():
                        store.verified_path(BlobManifest(sha, len(data)))
                    ready = True
                except (ValueError, OSError) as error:
                    reason = str(error)
            conn.execute("BEGIN IMMEDIATE")
            _scope(conn, path, observation)
            _existing(conn, raw, deck, evidence)
            if captured_storage is not None and _storage(conn)[1] != captured_storage:
                raise ValueError("Original artifact storage changed before draft retention")
            if receipt_ready:
                verified = receipts.read_owned(conn, raw)
                if verified[0]["closure"] != closure:
                    raise ValueError("Draft receipt changed before retention commit")
            conn.execute("INSERT OR IGNORE INTO research_file_drafts VALUES(?,?,?,?)", tuple(
                raw[key] for key in ("candidate_id", "entity_id", "deck", "observation")))
            if ready:
                _schema(conn, create=True)
                conn.execute("INSERT OR IGNORE INTO " + TABLE + " VALUES(?,?,?,?)", tuple(
                    closure[key] for key in (
                        "candidate_id", "source_sha256", "payload", "inventory")))
                if _closure_row(conn, raw["candidate_id"]) != closure:
                    raise ValueError("Original raw closure changed before commit")
            _scope(conn, path, observation)
    except sqlite3.Error as error:
        # A fully captured result must survive failure of the metadata ledger as
        # well. Durable CAS/receipt errors keep their prior exception contract.
        if ready or receipt_ready or capture is None:
            raise
        reason = str(error)
    state = "cas" if ready else "receipt" if receipt_ready else "incomplete"
    return DraftRetention(raw["candidate_id"], state, deck, deepcopy(evidence), reason, capture)


def retry_retention(outcome):
    """Retry only the exact in-process captured bytes, never another model call."""
    from paper_daily.raw_deck_receipts import decode
    from paper_daily.sync_deck_publication import DraftRetention

    if not isinstance(outcome, DraftRetention) or outcome._capture is None:
        raise ValueError("No original captured byte declaration is available")
    header, _blobs = decode(outcome._capture)
    return retain_outcome(json.loads(header["raw"]["observation"]), outcome.deck,
                          evidence=outcome.evidence, request_id=outcome.candidate_id,
                          _captured=outcome._capture)


def repair(database, raw, *, current=lambda: True):
    """Explicit worker action: restore verified original receipt bytes into CAS."""
    from paper_daily import raw_deck_receipts as receipts
    from paper_daily.sync_artifacts import stage_bytes

    path = Path(database).resolve(strict=True)
    observation = json.loads(raw["observation"])
    def check(conn):
        _scope(conn, path, observation)
        row = conn.execute("SELECT candidate_id,entity_id,deck,observation FROM "
                           "research_file_drafts WHERE candidate_id=?", (raw["candidate_id"],)
                           ).fetchone()
        if row is None or tuple(row) != tuple(raw[key] for key in
                ("candidate_id", "entity_id", "deck", "observation")) or not current():
            raise ValueError("Original raw draft or review lifetime changed")
    with closing(sqlite3.connect(path.as_uri() + "?mode=rw", uri=True)) as conn, conn:
        check(conn)
        header, blobs, files = receipts.read_owned(conn, raw)
        store, storage = _storage(conn)
        store = _owned_store(conn, store)
        stage_bytes(store, blobs)
        check(conn)
        conn.execute("BEGIN IMMEDIATE")
        check(conn)
        fresh = receipts.read_owned(conn, raw)
        if fresh[0] != header or fresh[2] != files or _storage(conn)[1] != storage:
            raise ValueError("Original receipt/storage changed during repair")
        _schema(conn, create=True)
        closure = header["closure"]
        previous = _closure_row(conn, raw["candidate_id"], missing_ok=True)
        if previous is not None and previous != closure:
            raise ValueError("Original draft closure differs from its receipt")
        conn.execute("INSERT OR IGNORE INTO " + TABLE + " VALUES(?,?,?,?)", tuple(
            closure[key] for key in ("candidate_id", "source_sha256", "payload", "inventory")))
        verify_in(conn, raw)
        check(conn)
    return raw["candidate_id"]


def read_detached(database, candidate_id):
    """Read verified archived content, never resurrect a writer or old job."""
    from paper_daily.file_change import version

    identifier(candidate_id)
    path = Path(database)
    native = _native(path)
    root = path.parent / "objects"
    _native(root)
    with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)) as conn:
        conn.execute("BEGIN")
        if not conn.execute("SELECT 1 FROM recovery_identity WHERE id=1").fetchone():
            raise ValueError("Select a detached recovery workspace")
        def record(table):
            row = conn.execute(
                "SELECT CASE WHEN length(CAST(data AS BLOB))<=? THEN data ELSE NULL END "
                "FROM recovery_records WHERE table_name=? AND json_valid(data) "
                "AND json_extract(data,'$.candidate_id')=? LIMIT 2",
                (4 * MAX_BODY, table, candidate_id),).fetchall()
            if len(row) != 1 or row[0][0] is None:
                raise ValueError("Archived raw draft is missing, duplicate or oversized")
            return json.loads(row[0][0])
        raw, closure = record("research_file_drafts"), record(TABLE)
        def read(item):
            digest(item["sha256"])
            target = root / item["sha256"]
            _native(target)
            before = version(target)
            if before[2] != item["size"]:
                raise ValueError("Recovered raw draft size changed")
            with target.open("rb") as stream:
                if version(target, stream=stream) != before:
                    raise ValueError("Recovered raw draft changed before reading")
                data = stream.read(item["size"] + 1)
                if version(target, stream=stream) != before:
                    raise ValueError("Recovered raw draft changed while reading")
            return data
        body = verify_summary(summarize(raw), closure, read)
        if _native(path) != native:
            raise ValueError("Recovery database was replaced while reading")
    return {"deck": body["deck"], "images": json.loads(closure["inventory"])["images"],
            "source_document_hash": json.loads(closure["payload"])["source_document_hash"],
            "publish": False, "sync": False, "requires_explicit_review": True}
