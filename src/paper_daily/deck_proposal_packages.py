"""Content-only deck proposals in list packages; never import a sender writer."""

from __future__ import annotations

import copy
import hashlib
import json
import sqlite3
from contextlib import closing, contextmanager, nullcontext
from dataclasses import dataclass, field
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

from paper_daily import file_change, presentations, raw_deck_closure, raw_deck_receipts
from paper_daily import rescue_deck_import as rescue
from paper_daily import sync_deck_publication as publication
from paper_daily.sync_files import MAX_BODY, canonical_json, descriptor, digest, file_id

TABLE = "deck_proposals"
CAPABILITY = "deck_proposals"
MAX_PROPOSALS = 1000
MAX_OBJECT_BYTES = 512 * 1024**2
_SEAL = object()


def _hash(data):
    return hashlib.sha256(data).hexdigest()


def relative(paper_id, sha):
    digest(sha)
    if not isinstance(paper_id, str) or not paper_id:
        raise ValueError("Proposal package needs an explicit paper owner")
    return Path("deck-proposals") / _hash(paper_id.encode())[:24] / sha


def descriptors(manifest):
    from paper_daily import portable_deck_proposal as codec

    codec.fingerprint(manifest)
    return (manifest["research"], *manifest["images"], *manifest["originals"])


def _rows(conn, ids):
    """Only this list's selected native paper/slot records; foreign rows grant nothing."""
    if not ids:
        return []
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    identities = []
    if "research_paper_identity" in tables:
        for pid in ids:
            row = conn.execute(
                "SELECT sync_id FROM research_paper_identity WHERE local_id=?", (pid,)
            ).fetchone()
            if row:
                identities.extend(file_id(row[0], "deck", slot) for slot in ("guide", "notes"))
    marks = ",".join("?" for _ in ids)
    entity_marks = ",".join("?" for _ in identities) or "NULL"
    output = []
    for origin, table, body in (
        ("file_draft", "research_file_drafts", "deck"),
        ("file", "research_file_candidates", "payload"),
    ):
        if table not in tables:
            continue
        values = conn.execute(
            "SELECT candidate_id,entity_id,"
            + body
            + ",observation FROM "
            + table
            + " WHERE entity_id IN ("
            + entity_marks
            + ") OR "
            + "CASE WHEN json_valid(observation) THEN json_extract(observation,'$.local_id') "
            + "ELSE NULL END IN ("
            + marks
            + ") ORDER BY candidate_id LIMIT ?",
            (*identities, *ids, MAX_PROPOSALS + 1),
        ).fetchall()
        for row in values:
            if len(output) >= MAX_PROPOSALS:
                raise ValueError("Too many retained presentation proposals for one package")
            if len(canonical_json(list(row))) > MAX_BODY:
                raise ValueError("Retained presentation metadata exceeds its package budget")
            record = dict(zip(("candidate_id", "entity_id", body, "observation"), row, strict=True))
            if origin == "file" and json.loads(record["payload"]).get("feature") != "deck":
                continue
            output.append((origin, record))
    return output


@dataclass(frozen=True)
class ProposalExport:
    database: Path
    native: tuple
    paper_ids: tuple
    snapshot: str
    targets: tuple
    source_files: tuple
    rows: tuple
    files: tuple
    local_reads: tuple = ()
    enrolled_reads: tuple = ()


def collect(database, paper_ids, *, with_pdfs=True):
    """Worker-only read of actual retained content and exact owned originals."""
    from paper_daily import portable_deck_proposal as codec
    from paper_daily.research_file_review import _body
    from paper_daily.sync_artifacts import paths

    database = rescue._path(database)
    native = rescue._native(database)
    ids = tuple(dict.fromkeys(paper_ids))
    with closing(sqlite3.connect(database.as_uri() + "?mode=ro", uri=True)) as conn:
        conn.row_factory = sqlite3.Row
        records = _rows(conn, ids)
    local_reads, local_rows, local_files = _collect_local(database, ids)
    enrolled_reads, enrolled_rows, enrolled_files = _collect_enrolled(database, ids)
    if not records and not local_reads and not enrolled_reads:
        return None
    if not with_pdfs and any(
        value.content["original_bytes"] for value in [*local_reads, *enrolled_reads]
    ):
        raise ValueError("Include exact original PDFs to share retained presentation proposals")
    targets, files, rows, source_files = (
        {}, {**local_files, **enrolled_files}, [*local_rows, *enrolled_rows], {}
    )
    for origin, record in records:
        observation = json.loads(record["observation"])
        pid, slot = observation.get("local_id"), observation.get("mode")
        if pid not in ids or slot not in {"guide", "notes"}:
            raise ValueError("Retained proposal differs from its selected package paper")
        key = (pid, slot)
        if key not in targets:
            targets[key] = rescue.capture(
                database,
                pid,
                slot,
                expected_native=native,
                request_id="export:" + _hash(canonical_json([pid, slot])),
            )
        target = targets[key]
        if record["entity_id"] != json.loads(target._snapshot)["observation"]["entity_id"]:
            raise ValueError("Retained proposal differs from its original paper/slot")
        with closing(sqlite3.connect(database.as_uri() + "?mode=ro", uri=True)) as conn:
            if origin == "file_draft":
                owned = raw_deck_receipts.read_owned(conn, record, missing_ok=True)
                if owned is None:
                    raise ValueError(
                        "Retained draft needs verified full-byte preparation before sharing"
                    )
                header, objects, _owned = owned
                source_files.update(_owned)
                deck = json.loads(header["raw"]["deck"])
                evidence = header["evidence"]
                payload = json.loads(header["closure"]["payload"])
                inventory = json.loads(header["closure"]["inventory"])["images"]
                images = {r["id"]: objects[r["sha256"]] for r in inventory}
            else:
                payload = json.loads(record["payload"])
                storage = paths(conn)
                if storage is None:
                    raise ValueError("Retained proposal has no verified artifact storage")
                guarded = {}
                deck = _body(storage[0], payload, guarded)
                source_files.update(guarded)
                evidence = None
                objects = {}
                from paper_daily.sync_blobs import BlobManifest

                for item in payload["assets"]:
                    path = storage[0].verified_path(BlobManifest(item["sha256"], item["size"]))
                    objects[item["sha256"]] = path.read_bytes()
                    source_files[str(path)] = file_change.version(path)
                    if item["role"] == "evidence":
                        evidence = json.loads(objects[item["sha256"]])
                        evidence.pop("version")
                images = {
                    r["id"]: objects[r["sha256"]]
                    for r in payload["assets"]
                    if r["role"] == "figure"
                }
        declared = {
            row["document_hash"]
            for row in (
                *deck["sources"],
                *deck["figures"],
                *(evidence or {}).get("sources", []),
                *(evidence or {}).get("figures", []),
            )
            if row.get("document_hash")
        }
        original_hash = payload["source_document_hash"]
        if original_hash is not None:
            declared.add(original_hash)
        if declared and not with_pdfs:
            raise ValueError("Include exact original PDFs to share retained presentation proposals")
        originals = {}
        for proof in rescue._sources(target, sorted(declared)):
            path = Path(proof["path"])
            data = path.read_bytes()
            if (
                canonical_json(file_change.version(path)) != canonical_json(proof["version"])
                or _hash(data) != proof["sha256"]
            ):
                raise ValueError("Owned proposal original changed during export")
            originals[proof["sha256"]] = data
            source_files[str(path)] = tuple(proof["version"])
        manifest, blobs = codec.encode(
            deck,
            evidence,
            images,
            originals,
            source_document_hash=original_hash,
        )
        proposal_id = _hash(canonical_json([origin, record["candidate_id"]]))
        rows.append({"paper_id": pid, "proposal_id": proposal_id, "manifest": manifest})
        for sha, data in blobs.items():
            path = relative(pid, sha)
            if path in files and files[path] != data:
                raise ValueError("Conflicting proposal package object")
            files[path] = data
        if sum(len(value) for value in files.values()) > MAX_OBJECT_BYTES:
            raise ValueError("Retained proposal package exceeds its total object budget")
    result = ProposalExport(
        database,
        native,
        ids,
        canonical_json(records).decode(),
        tuple(targets.values()),
        tuple(source_files.items()),
        tuple(rows),
        tuple(files.items()),
        tuple(local_reads),
        tuple(enrolled_reads),
    )
    check_export(result)
    return result


def _collect_local(database, paper_ids):
    from paper_daily import local_deck_proposals as catalog
    from paper_daily import portable_deck_proposal as codec

    output, rows, files = [], [], {}
    with closing(sqlite3.connect(database.as_uri() + "?mode=ro", uri=True)) as conn:
        if not conn.execute(
            "SELECT 1 FROM sqlite_master WHERE name=?", (catalog.TABLE,)
        ).fetchone():
            return output, rows, files
        ids = tuple(paper_ids)
        if not ids:
            return output, rows, files
        marks = ",".join("?" for _ in ids)
        found = conn.execute(
            "SELECT proposal_id,paper_id FROM "
            + catalog.TABLE
            + " WHERE paper_id IN ("
            + marks
            + ") ORDER BY proposal_id LIMIT ?",
            (*ids, MAX_PROPOSALS + 1),
        ).fetchall()
    if len(found) > MAX_PROPOSALS:
        raise ValueError("Too many local presentation proposals for one package")
    for identity, paper in found:
        captured = catalog.read(database, identity, expected_native=rescue._native(database))
        content = captured.content
        manifest, objects = codec.encode(
            content["deck"],
            content["evidence"],
            content["image_bytes"],
            content["original_bytes"],
            source_document_hash=content["source_document_hash"],
        )
        rows.append(
            {"paper_id": paper, "proposal_id": _hash(identity.encode()), "manifest": manifest}
        )
        for sha, data in objects.items():
            files[relative(paper, sha)] = data
        if sum(len(data) for data in files.values()) > MAX_OBJECT_BYTES:
            raise ValueError("Local presentation proposals exceed the package object budget")
        output.append(captured)
    return output, rows, files


def _collect_enrolled(database, paper_ids):
    from paper_daily import enrolled_deck_proposals as catalog
    from paper_daily.research_file_review import _storage

    output, rows, files = [], [], {}
    with closing(sqlite3.connect(database.as_uri() + "?mode=ro", uri=True)) as conn:
        if not catalog._schema(conn) or not paper_ids:
            return output, rows, files
        marks = ",".join("?" for _ in paper_ids)
        found = conn.execute(
            "SELECT proposal_id,local_id FROM " + catalog.TABLE
            + " WHERE local_id IN (" + marks + ") ORDER BY proposal_id LIMIT ?",
            (*paper_ids, MAX_PROPOSALS + 1),
        ).fetchall()
        storage = _storage(conn) if found else None
    if not found:
        return output, rows, files
    if len(found) > MAX_PROPOSALS or storage is None:
        raise ValueError("Enrolled proposal count or original artifact storage is unavailable")
    client = publication.runtime(database=database)
    if client is None:
        raise ValueError("Enrolled proposals require their actual workspace binding")
    native = rescue._native(database)
    for identity, paper in found:
        captured = catalog.read(client, storage[0], identity, expected_native=native)
        manifest = json.loads(captured.record["manifest_json"])
        content = captured.content
        from paper_daily import portable_deck_proposal as codec

        verified, objects = codec.encode(
            content["deck"], content["evidence"], content["image_bytes"],
            content["original_bytes"], source_document_hash=content["source_document_hash"],
        )
        if verified != manifest:
            raise ValueError("Enrolled retained science differs from its exact manifest")
        rows.append(
            {"paper_id": paper, "proposal_id": _hash(identity.encode()), "manifest": manifest}
        )
        for sha, data in objects.items():
            files[relative(paper, sha)] = data
        if sum(len(data) for data in files.values()) > MAX_OBJECT_BYTES:
            raise ValueError("Enrolled proposal package exceeds its object budget")
        output.append(captured)
    return output, rows, files


def check_export(export):
    if export is None:
        return
    if rescue._native(export.database) != export.native:
        raise ValueError("Original proposal database was replaced")
    with closing(sqlite3.connect(export.database.as_uri() + "?mode=ro", uri=True)) as conn:
        if canonical_json(_rows(conn, export.paper_ids)).decode() != export.snapshot:
            raise ValueError("Retained proposals changed during package export")
    if export.local_reads:
        from paper_daily import local_deck_proposals as catalog

        for captured in export.local_reads:
            actual = catalog.read(
                export.database, captured.record["proposal_id"], expected_native=export.native
            )
            if actual.record != captured.record or canonical_json(
                [(str(path), stamp) for path, stamp in actual.witnesses]
            ) != canonical_json([(str(path), stamp) for path, stamp in captured.witnesses]):
                raise ValueError("Local retained proposal changed during sharing")
    if export.enrolled_reads:
        from paper_daily import enrolled_deck_proposals as catalog
        from paper_daily.research_file_review import _storage

        client = publication.runtime(database=export.database)
        with closing(sqlite3.connect(export.database.as_uri() + "?mode=ro", uri=True)) as conn:
            storage = _storage(conn)
        if client is None or storage is None:
            raise ValueError("Enrolled proposal binding or storage changed during export")
        for captured in export.enrolled_reads:
            actual = catalog.read(
                client, storage[0], captured.record["proposal_id"], expected_native=export.native
            )
            if actual.record != captured.record or canonical_json(
                [(str(path), stamp) for path, stamp in actual.witnesses]
            ) != canonical_json([(str(path), stamp) for path, stamp in captured.witnesses]):
                raise ValueError("Enrolled retained proposal changed during sharing")
    if any(not target.current() for target in export.targets):
        raise ValueError("Original proposal paper or inputs changed during export")
    for path, before in export.source_files:
        if canonical_json(file_change.version(Path(path))) != canonical_json(before):
            raise ValueError("Original proposal bytes changed during package export")


def validate_package(archive, manifest, tables):
    from paper_daily import portable_deck_proposal as codec

    rows = tables.get(TABLE, [])
    if rows:
        infos = archive.infolist()
        if (
            len(infos) > 4096
            or sum(item.file_size for item in infos) > MAX_OBJECT_BYTES
            or any(
                item.file_size > MAX_BODY
                for item in infos
                if item.filename in {"manifest.json", "tables.json"}
            )
        ):
            raise ValueError("Complete proposal package exceeds its file/byte budget")
    if not isinstance(rows, list) or len(rows) > MAX_PROPOSALS:
        raise ValueError("Invalid proposal package row collection")
    papers = {r["id"] for r in tables["papers"]}
    seen, objects, total = set(), {}, 0
    for row in rows:
        if not isinstance(row, dict) or set(row) != {"paper_id", "proposal_id", "manifest"}:
            raise ValueError("Invalid proposal package fields")
        pid, proposal_id = row["paper_id"], row["proposal_id"]
        digest(proposal_id)
        if pid not in papers or (pid, proposal_id) in seen:
            raise ValueError("Duplicate or foreign proposal package owner")
        seen.add((pid, proposal_id))
        for item in descriptors(row["manifest"]):
            rel = relative(pid, item["sha256"]).as_posix()
            if rel in objects:
                if objects[rel] != item["size"]:
                    raise ValueError("Proposal object sizes disagree")
                continue
            info = archive.getinfo("files/" + rel)
            if (
                info.file_size != item["size"]
                or manifest.get("file_hashes", {}).get(rel) != item["sha256"]
            ):
                raise ValueError("Proposal package object differs from its declared content")
            total += info.file_size
            if total > MAX_OBJECT_BYTES:
                raise ValueError("Proposal package object budget exceeded")
            objects[rel] = item["size"]
        codec.decode(
            row["manifest"],
            lambda item, pid=pid: archive.read("files/" + relative(pid, item["sha256"]).as_posix()),
        )
    actual = {
        n.removeprefix("files/")
        for n in archive.namelist()
        if n.startswith("files/deck-proposals/") and not n.endswith("/")
    }
    if actual != set(objects):
        raise ValueError("Proposal package has missing or undeclared objects")


@dataclass(frozen=True)
class PreparedProposal:
    local_id: str
    portable_id: str
    candidate_id: str
    scientific: str
    payload: str
    inventory: str
    blob_items: tuple = field(repr=False)
    original_hashes: tuple
    seal: object = field(repr=False, compare=False)


def prepare_imports(
    rows, files, mapping, request, store, *, client=None, expected_native=None,
    current=lambda: True,
):
    from paper_daily import portable_deck_proposal as codec
    from paper_daily.sync_artifacts import stage_bytes
    from paper_daily.sync_deck_files import encode_deck
    from paper_daily.sync_source_files import input_versions

    output = []
    for row in rows:
        pid = row["paper_id"]
        portable = mapping[pid]["portable_id"]
        local = mapping[pid]["local_id"]
        decoded = codec.decode(
            row["manifest"], lambda item, pid=pid: files[relative(pid, item["sha256"]).as_posix()]
        )
        deck = presentations.deck_from_dict(copy.deepcopy(decoded["deck"]))
        if set(decoded["image_bytes"]) != {r["id"] for r in deck.figures}:
            if client is None:
                raise ValueError("Evidence-only images need the general retained-proposal adapter")
            from paper_daily import enrolled_deck_proposals as catalog

            prepared = catalog.prepare(
                client, store, local, portable, row["manifest"],
                lambda item, pid=pid: files[relative(pid, item["sha256"]).as_posix()],
                request_id="package-general:" + _hash(
                    canonical_json([request, row["proposal_id"], local])
                ),
                expected_native=expected_native, current=current, allow_absent=True,
            )
            output.append(prepared)
            continue
        deck.paper_id = local
        deck.deck_id = str(
            uuid5(
                NAMESPACE_URL,
                "paperfact.package.proposal:"
                + canonical_json([request, row["proposal_id"], local]).decode(),
            )
        )
        deck._revision_figures = decoded["image_bytes"]
        payload, blobs = encode_deck(
            deck,
            portable,
            input_versions=input_versions(),
            evidence=decoded["evidence"],
            source_document_hash=decoded["source_document_hash"],
        )
        inventory = []
        for key, image in sorted(decoded["image_bytes"].items()):
            item = {"id": key, **descriptor(image, "image/png")}
            inventory.append(item)
            blobs[item["sha256"]] = image
        stage_bytes(store, blobs)
        candidate = "package:" + str(
            uuid5(NAMESPACE_URL, canonical_json([request, row["proposal_id"], local]).decode())
        )
        output.append(
            PreparedProposal(
                local,
                portable,
                candidate,
                canonical_json({"deck": deck.to_dict(), "evidence": decoded["evidence"]}).decode(),
                canonical_json(payload).decode(),
                canonical_json({"version": 1, "images": inventory}).decode(),
                tuple(sorted(blobs.items())),
                tuple(decoded["original_bytes"]),
                _SEAL,
            )
        )
    return tuple(output)


class _PackageProposalGrant:
    def __init__(self, conn, client, proposals, grant):
        self.conn, self.client, self.proposals, self.grant = conn, client, proposals, grant
        self.ids = None

    def adopt(self):
        from paper_daily import enrolled_deck_proposals as catalog

        if self.conn is None:
            raise ValueError("Package proposal grant is no longer active")
        if self.ids is None:
            general = tuple(p for p in self.proposals if isinstance(p, catalog.Prepared))
            ids = self.grant.adopt() if general else []
            imported = dict(zip((p.proposal_id for p in general), ids, strict=True))
            self.ids = [
                imported[p.proposal_id] if isinstance(p, catalog.Prepared)
                else adopt_in(self.conn, self.client, p) for p in self.proposals
            ]
        return list(self.ids)


@contextmanager
def import_targets_in(conn, client, proposals, *, current=lambda: True, allow_updates=False):
    from paper_daily import enrolled_deck_proposals as catalog

    general = tuple(p for p in proposals if isinstance(p, catalog.Prepared))
    context = (
        catalog.import_targets_in(conn, general, current=current, allow_updates=allow_updates)
        if general else nullcontext(None)
    )
    with context as grant:
        admitted = _PackageProposalGrant(conn, client, proposals, grant)
        try:
            yield admitted
            if admitted.ids is None:
                raise ValueError("Package proposals were not adopted before commit")
        finally:
            admitted.conn = admitted.client = admitted.grant = None
            admitted.proposals = ()


def adopt_in(conn, client, proposal):
    """Use the package importer's transaction after its paper/source operations."""
    from paper_daily.sync_source_files import inspectable

    if (
        not isinstance(proposal, PreparedProposal)
        or proposal.seal is not _SEAL
        or not conn.in_transaction
    ):
        raise ValueError("Proposal adoption requires its prepared package transaction")
    scientific = json.loads(proposal.scientific)
    deck = presentations.deck_from_dict(scientific["deck"])
    if deck.paper_id != proposal.local_id:
        raise ValueError("Prepared proposal target changed")
    observation = publication._observation(conn, client, proposal.local_id, deck.mode)
    if observation["paper_id"] != proposal.portable_id:
        raise ValueError("Prepared proposal portable target changed")
    for sha in proposal.original_hashes:
        if inspectable(conn, proposal.portable_id, sha) is None:
            raise ValueError("Imported proposal original is not owned by its exact receiver")
    # A rolled-back import may leave an unowned immutable receipt. A new receiver
    # epoch/base must never overwrite that receipt or borrow its old authority.
    candidate_id = proposal.candidate_id + ":" + _hash(canonical_json(observation))[:32]
    raw = {
        "candidate_id": candidate_id,
        "entity_id": observation["entity_id"],
        "deck": canonical_json(deck.to_dict()).decode(),
        "observation": canonical_json(observation).decode(),
    }
    closure = {
        "candidate_id": candidate_id,
        "source_sha256": raw_deck_closure.source_hash(raw),
        "payload": proposal.payload,
        "inventory": proposal.inventory,
    }
    blobs = dict(proposal.blob_items)
    raw_deck_closure.verify_summary(
        raw_deck_closure.summarize(raw), closure, lambda item: blobs[item["sha256"]]
    )
    captured = raw_deck_receipts.capture(conn, raw, closure, scientific["evidence"], blobs)
    store, _registration = raw_deck_closure._storage(conn)
    owned = raw_deck_closure._owned_store(conn, store)
    from paper_daily.sync_blobs import BlobManifest

    for sha, data in blobs.items():
        owned.verified_path(BlobManifest(sha, len(data)))
    raw_deck_receipts.write_owned(conn, captured)
    prior = conn.execute(
        "SELECT candidate_id,entity_id,deck,observation FROM research_file_drafts "
        "WHERE candidate_id=?",
        (candidate_id,),
    ).fetchone()
    if prior is not None and tuple(prior) != tuple(raw.values()):
        raise ValueError("Imported proposal request identity was reused")
    conn.execute("INSERT OR IGNORE INTO research_file_drafts VALUES(?,?,?,?)", tuple(raw.values()))
    raw_deck_closure._schema(conn, create=True)
    conn.execute(
        "INSERT OR IGNORE INTO " + raw_deck_closure.TABLE + " VALUES(?,?,?,?)",
        tuple(closure.values()),
    )
    if raw_deck_closure._closure_row(conn, candidate_id) != closure:
        raise ValueError("Imported proposal closure changed")
    return candidate_id


@dataclass(frozen=True)
class LocalImports:
    prepared: tuple
    reused: tuple


def prepare_local_imports(database, archive, tables, package_sha256):
    from paper_daily import local_deck_proposals as catalog

    database = rescue._path(database)
    native = rescue._native(database)
    pending, reused = [], []
    for row in tables.get(TABLE, []):
        request = "package:" + _hash(
            canonical_json([package_sha256, row["proposal_id"], row["paper_id"]])
        )
        # A repeated complete package is a read of the genuinely retained owner;
        # it cannot refresh an earlier parent or adopt a changed manifest.
        with closing(sqlite3.connect(database.as_uri() + "?mode=ro", uri=True)) as conn:
            exists = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE name=?", (catalog.TABLE,)
            ).fetchone()
            prior = (
                conn.execute(
                    "SELECT proposal_id FROM " + catalog.TABLE + " WHERE request_id=?", (request,)
                ).fetchone()
                if exists
                else None
            )
        if prior:
            value = catalog.read(database, prior[0], expected_native=native)
            if (
                not value.current_parent
                or value.record["paper_id"] != row["paper_id"]
                or json.loads(value.record["manifest_json"]) != row["manifest"]
            ):
                raise ValueError("Imported proposal changed or belongs to an earlier local parent")
            reused.append(value)
            continue
        pending.append(
            catalog.prepare(
                database,
                row["paper_id"],
                row["manifest"],
                lambda item, row=row: archive.read(
                    "files/" + relative(row["paper_id"], item["sha256"]).as_posix()
                ),
                request_id=request,
                expected_native=native,
                allow_absent=True,
            )
        )
    return LocalImports(tuple(pending), tuple(reused))


class _LocalImportGrant:
    def __init__(self, conn, grant, reused):
        self.conn, self.grant, self.reused = conn, grant, reused
        self.ids = None

    def adopt(self):
        from paper_daily import local_deck_proposals as catalog

        if self.ids is not None:
            return list(self.ids)
        for value in self.reused:
            catalog.assert_current_in(self.conn, value)
        self.ids = (self.grant.adopt() if self.grant is not None else []) + [
            value.record["proposal_id"] for value in self.reused
        ]
        return list(self.ids)


def local_imports_in(conn, prepared, *, allow_updates=False):
    from contextlib import contextmanager, nullcontext

    from paper_daily import local_deck_proposals as catalog

    @contextmanager
    def owned():
        if not conn.in_transaction:
            raise ValueError("Local proposal import needs the caller transaction")
        for value in prepared.reused:
            catalog.assert_current_in(conn, value)
        context = (
            catalog.import_targets_in(conn, prepared.prepared, allow_updates=allow_updates)
            if prepared.prepared
            else nullcontext(None)
        )
        with context as grant:
            admitted = _LocalImportGrant(conn, grant, prepared.reused)
            try:
                yield admitted
                if admitted.ids is None:
                    raise ValueError("Local proposal import grant was not adopted")
                for value in prepared.reused:
                    catalog.assert_current_in(conn, value)
            finally:
                admitted.conn = admitted.grant = None

    return owned()
