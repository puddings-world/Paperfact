"""Durable single-slide jobs: persistence precedes optional UI adoption.

Private receipts retain the original instruction, model prompt, complete candidate
and verified figure closure. They are local research, never wire/telemetry data.
Retry reuses the receipt and original publication identity, without another model.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import sqlite3
import tempfile
from contextlib import closing
from copy import deepcopy
from dataclasses import dataclass, field
from pathlib import Path
from uuid import UUID, uuid4

from paper_daily import llm, presentations, slide_revise, store
from paper_daily.sync_deck_publication import publication_scope, runtime

MAX_RECORD = 48 * 1024**2
MAX_IMAGES = 32 * 1024**2


def _identity(path):
    if not path.exists():
        return None
    stat = path.stat()
    return [stat.st_dev, stat.st_ino]


def _hash_file(path):
    if not path.exists():
        return None
    if path.stat().st_size > 8 * 1024**2:
        raise ValueError("Presentation snapshot exceeds 8 MiB")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _binding(path):
    if not path.is_file():
        return None
    with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as conn:
        if not conn.execute(
            "SELECT 1 FROM sqlite_master WHERE name='research_sync_binding'"
        ).fetchone():
            return None
        row = conn.execute(
            "SELECT workspace,origin FROM research_sync_binding WHERE id=1"
        ).fetchone()
        return list(row) if row else None


def _parent(path, paper_id, *, install=False):
    if not path.is_file():
        return None
    from paper_daily.research_lifecycle import ensure_lifecycle, parent_lifecycle

    with closing(sqlite3.connect(path.as_uri() + "?mode=rw", uri=True)) as conn:
        if not conn.execute("SELECT 1 FROM sqlite_master WHERE name='papers'").fetchone():
            return None
        if install:
            conn.execute("BEGIN IMMEDIATE")
            ensure_lifecycle(conn)
            conn.commit()
        return parent_lifecycle(conn, "paper", paper_id)


def _write(path, value):
    data = json.dumps(value, ensure_ascii=False, allow_nan=False).encode("utf-8")
    if len(data) > MAX_RECORD:
        raise ValueError("Slide revision receipt exceeds its bounded storage")
    # Never follow an existing junction/symlink into another research workspace.
    for ancestor in (path, *path.parents):
        if ancestor.is_symlink() or getattr(ancestor, "is_junction", lambda: False)():
            raise ValueError("Revision receipt path must not contain links")
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, prefix=".revision-", delete=False) as stream:
        temp = Path(stream.name)
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())
    try:
        temp.replace(path)
    finally:
        temp.unlink(missing_ok=True)


@dataclass
class Revision:
    request_id: str
    deck: presentations.Deck
    index: int
    instruction: str
    database: Path
    database_identity: list | None
    binding: list | None
    destination: Path
    original_hash: str | None
    receipt: Path
    parent_token: str | None
    client: object = field(repr=False)
    connections: object = field(repr=False)
    record: dict = field(default_factory=dict)
    updated: presentations.Deck | None = None

    def selected_workspace(self):
        return (
            Path(store.DB_PATH).resolve() == self.database
            and presentations._path(self.deck.paper_id, self.deck.mode).resolve()
            == self.destination
        )

    def workspace_current(self):
        try:
            return (
                _identity(self.database) == self.database_identity
                and _binding(self.database) == self.binding
                and _parent(self.database, self.deck.paper_id) == self.parent_token
            )
        except (OSError, sqlite3.Error, ValueError):
            return False


def begin(deck, index, instruction):
    """Capture only paths/metadata on the caller thread; image work runs off-thread."""
    from paper_daily.recovery_decks import assert_writable

    if getattr(deck, "_recovery_deck", None) is not None:
        raise ValueError("Recovered slides are read-only until explicitly copied for editing")
    assert_writable(store.DB_PATH, deck.paper_id, deck.mode)
    instruction = instruction.strip()
    if not instruction or len(instruction) > 2000 or not 0 <= index < len(deck.slides):
        raise ValueError("Invalid slide revision target or instruction")
    captured = deepcopy(deck)  # Includes the original managed binding and assets.
    captured._revision_roots = {
        "folder": presentations._folder(deck.paper_id).resolve(),
        "figures": Path(presentations.FIG_DIR).resolve(),
    }
    destination = presentations._path(deck.paper_id, deck.mode).resolve()
    captured._revision_destination = destination
    captured._revision_original_hash = _hash_file(destination)
    database = Path(store.DB_PATH).resolve()
    try:
        client = runtime()
        database_identity, binding = _identity(database), _binding(database)
    except sqlite3.Error as exc:
        raise ValueError("The original research workspace is unavailable") from exc
    observation = getattr(captured, "_file_observation", None)
    if observation is not None and (
        observation.get("database"),
        observation.get("database_identity"),
        [observation.get("workspace_id"), observation.get("device_id")],
        observation.get("local_id"),
        observation.get("mode"),
    ) != (str(database), database_identity, binding, captured.paper_id, captured.mode):
        raise ValueError("The open deck belongs to another workspace; reopen it before revising")
    identity = str(uuid4())
    parent = _parent(database, captured.paper_id, install=True)
    return Revision(
        identity,
        captured,
        index,
        instruction,
        database,
        database_identity,
        binding,
        destination,
        _hash_file(destination),
        captured._revision_roots["folder"] / ".revision-requests" / (identity + ".json"),
        parent,
        client,
        llm.capture_connections(),
    )


def _evidence(job):
    operation = getattr(job.deck, "_file_operation", None)
    if operation is not None:
        from paper_daily.sync_artifacts import paths
        from paper_daily.sync_blobs import BlobManifest
        from paper_daily.sync_files import read_json

        with job.client.journal.transaction() as conn:
            configured = paths(conn)
        if configured is None:
            raise ValueError("Captured deck artifact storage is unavailable")
        blobs = configured[0]
        row = operation["payload"]["body"]
        body = read_json(blobs.verified_path(BlobManifest(row["sha256"], row["size"])).read_bytes())
        if body["evidence_asset"]:
            row = next(
                a for a in operation["payload"]["assets"] if a["id"] == body["evidence_asset"]
            )
            return read_json(
                blobs.verified_path(BlobManifest(row["sha256"], row["size"])).read_bytes()
            )
    return slide_revise.evidence(job.deck)


def _prepare(job):
    if not job.workspace_current():
        raise ValueError("Original workspace changed before the revision started")
    if job.client is None and _hash_file(job.destination) != job.original_hash:
        raise ValueError("Saved deck changed before the revision started")
    evidence = _evidence(job)
    if len(json.dumps(evidence, ensure_ascii=False).encode("utf-8")) > 8 * 1024**2:
        raise ValueError("Revision evidence exceeds 8 MiB")
    evidence = dict(evidence, coverage=evidence.get("coverage", job.deck.coverage))
    # This receipt owns the exact snapshot used for this revision, including a
    # newly collected snapshot for a legacy deck. Its hash identifies these bytes,
    # not an older deck's evidence or the paper's PDF.
    payload = {key: value for key, value in evidence.items() if key != "source_hash"}
    encoded = json.dumps(
        payload, sort_keys=True, ensure_ascii=False, allow_nan=False
    ).encode("utf-8")
    if len(encoded) > 8 * 1024**2:
        raise ValueError("Revision evidence exceeds 8 MiB")
    evidence["source_hash"] = hashlib.sha256(encoded).hexdigest()
    from paper_daily.sync_deck_files import validate_png

    images = {}
    if len(job.deck.figures) > 128:
        raise ValueError("Too many figures for a single revision")
    for figure in job.deck.figures:
        blob = presentations.figure_bytes(job.deck, figure["id"])
        validate_png(blob)
        images[figure["id"]] = blob
        if sum(map(len, images.values())) > MAX_IMAGES:
            raise ValueError("Revision images exceed 32 MiB")
    job.deck._revision_figures = images
    job.deck._revision_evidence = deepcopy(evidence)
    job.record = {
        "version": 1,
        "request_id": job.request_id,
        "database": str(job.database),
        "database_identity": job.database_identity,
        "binding": job.binding,
        "original_file_hash": job.original_hash,
        "parent_token": job.parent_token,
        "paper_id": job.deck.paper_id,
        "mode": job.deck.mode,
        "index": job.index,
        "instruction": job.instruction,
        "original": job.deck.to_dict(),
        "observation": getattr(job.deck, "_file_observation", None),
        "file_operation": getattr(job.deck, "_file_operation", None),
        "evidence": evidence,
        "figures": {
            key: {
                "sha256": hashlib.sha256(blob).hexdigest(),
                "base64": base64.b64encode(blob).decode("ascii"),
            }
            for key, blob in images.items()
        },
        "prompt": None,
        "system": None,
        "result": None,
        "summary": None,
        "status": "prepared",
        "reason": None,
    }
    # Reserve the entire maximum result before spending any model call.
    if len(json.dumps(job.record, ensure_ascii=False).encode("utf-8")) > MAX_RECORD - 8 * 1024**2:
        raise ValueError("Insufficient receipt capacity for a completed revision")
    _write(job.receipt, job.record)


def publish(job):
    """Idempotently publish a completed candidate; never regenerate on failure."""
    if job.updated is None or not job.record.get("result"):
        raise ValueError("No completed slide revision to publish")
    if job.record["status"] == "accepted":
        return "accepted"
    try:
        if not job.workspace_current():
            raise ValueError("Original workspace changed; result retained for review")
        if job.client is None and _hash_file(job.destination) != job.original_hash:
            # A previous write may have committed before the receipt update failed.
            current = json.loads(job.destination.read_text(encoding="utf-8"))
            if current != job.updated.to_dict():
                raise ValueError("Saved deck changed; result retained for review")
        else:
            job.updated._revision_database = job.database
            job.updated._revision_guard = lambda: job.workspace_current()
            evidence = job.deck._revision_evidence
            if evidence is not None and not job.updated.source_hash:
                # A blank-source legacy deck keeps its unknown input identity. A local
                # file has no hash-named place for that snapshot, so the receipt keeps
                # it; a synced deck carries it, so recovery can still export it.
                evidence = None if job.client is None else dict(evidence, source_hash="")
            with publication_scope(job.client):
                presentations.save_deck(
                    job.updated,
                    observation=getattr(job.deck, "_file_observation", None),
                    request_id=job.request_id,
                    evidence=evidence,
                )
        job.record.update(status="accepted", reason=None, result=job.updated.to_dict())
    except (OSError, sqlite3.Error, ValueError) as exc:
        job.record.update(status="candidate", reason=str(exc)[:2000])
    _write(job.receipt, job.record)
    return job.record["status"]


def run(job):
    """Background worker boundary; the UI callback has no persistence responsibility."""
    from paper_daily.research_job_lock import claim

    lock_target = job.database if job.database.is_file() else job.destination
    with claim(lock_target, "slide-revision", job.deck.paper_id + ":" + job.deck.mode) as acquired:
        if not acquired:
            return None, "This deck already has a revision in progress"
        if job.updated is not None:
            status = publish(job)
        else:
            with publication_scope(job.client), llm.connection_scope(job.connections):
                cfg = llm.settings(task="slides")
                _prepare(job)

                def before_model(prompt, system):
                    job.record.update(prompt=prompt, system=system)
                    _write(job.receipt, job.record)

                job.deck._revision_before_model = before_model
                slide, reason = slide_revise.revise(job.deck, job.index, job.instruction, cfg=cfg)
                if slide is None:
                    job.record.update(status="failed", reason=reason[:2000])
                    _write(job.receipt, job.record)
                    return None, reason
                candidate = deepcopy(job.deck)
                del candidate._revision_before_model
                slide.elements = None
                candidate.slides[job.index] = slide
                candidate.edited = True
                if candidate.source_hash:
                    candidate.source_hash = job.deck._revision_evidence["source_hash"]
                presentations.deck_from_dict(candidate.to_dict())
                job.updated = candidate
                job.record.update(
                    result=candidate.to_dict(), summary=reason[:200], status="generated"
                )
                # This verified closure survives a failed DB/file write or vanished UI.
                _write(job.receipt, job.record)
                status = publish(job)
        return json.dumps(
            {"request_id": job.request_id, "status": status, "summary": job.record["summary"]},
            ensure_ascii=False,
        ), "ok"


RECORD_FIELDS = frozenset(
    {
        "version",
        "request_id",
        "database",
        "database_identity",
        "binding",
        "parent_token",
        "paper_id",
        "mode",
        "index",
        "instruction",
        "original",
        "observation",
        "file_operation",
        "original_file_hash",
        "evidence",
        "figures",
        "prompt",
        "system",
        "result",
        "summary",
        "status",
        "reason",
    }
)


def validate_request_record(record):
    """Validate retained private data without opening embedded paths or running AI."""
    if not isinstance(record, dict) or set(record) != RECORD_FIELDS or record["version"] != 1:
        raise ValueError("Invalid slide revision receipt")
    if len(json.dumps(record, ensure_ascii=False, allow_nan=False).encode()) > MAX_RECORD:
        raise ValueError("Oversized slide revision receipt")
    if str(UUID(record["request_id"])) != record["request_id"]:
        raise ValueError("Invalid slide revision identity")
    original = presentations.deck_from_dict(record["original"])
    if (original.paper_id, original.mode) != (record["paper_id"], record["mode"]):
        raise ValueError("Slide revision owner mismatch")
    if type(record["index"]) is not int or not 0 <= record["index"] < len(original.slides):
        raise ValueError("Invalid slide index")
    for name, bound in (("database", 4096), ("instruction", 2000)):
        if not isinstance(record[name], str) or not record[name] or len(record[name]) > bound:
            raise ValueError("Invalid slide revision text")
    for name, bound in (("prompt", 1024**2), ("system", 16000), ("reason", 2000), ("summary", 200)):
        if record[name] is not None and (
            not isinstance(record[name], str) or len(record[name]) > bound
        ):
            raise ValueError("Invalid slide revision explanation")
    identity = record["database_identity"]
    digest = record["original_file_hash"]
    if digest is not None and (
        not isinstance(digest, str)
        or len(digest) != 64
        or any(x not in "0123456789abcdef" for x in digest)
    ):
        raise ValueError("Invalid original file hash")
    if identity is not None and (
        not isinstance(identity, list)
        or len(identity) != 2
        or any(type(x) is not int or x < 0 for x in identity)
    ):
        raise ValueError("Invalid original database identity")
    binding = record["binding"]
    if binding is not None and (
        not isinstance(binding, list)
        or len(binding) != 2
        or any(not isinstance(x, str) or not x or len(x) > 128 for x in binding)
    ):
        raise ValueError("Invalid original workspace binding")
    token = record["parent_token"]
    if token is not None and (
        not isinstance(token, str)
        or len(token) != 32
        or any(x not in "0123456789abcdef" for x in token)
    ):
        raise ValueError("Invalid original paper lifecycle")
    if record["status"] not in {"prepared", "generated", "accepted", "candidate", "failed"}:
        raise ValueError("Invalid revision state")
    if not isinstance(record["evidence"], dict) or not isinstance(record["figures"], dict):
        raise ValueError("Invalid revision evidence")
    if len(record["figures"]) > 128:
        raise ValueError("Too many captured figures")
    total = 0
    from paper_daily.sync_deck_files import validate_png

    for key, row in record["figures"].items():
        if key not in {f["id"] for f in original.figures} or set(row) != {"sha256", "base64"}:
            raise ValueError("Invalid captured figure identity")
        data = base64.b64decode(row["base64"], validate=True)
        if hashlib.sha256(data).hexdigest() != row["sha256"]:
            raise ValueError("Captured figure hash mismatch")
        validate_png(data)
        total += len(data)
    if total > MAX_IMAGES:
        raise ValueError("Captured figures exceed their quota")
    result = record["result"]
    if result is not None:
        candidate = presentations.deck_from_dict(result)
        if (candidate.paper_id, candidate.mode, candidate.deck_id, len(candidate.slides)) != (
            original.paper_id,
            original.mode,
            original.deck_id,
            len(original.slides),
        ):
            raise ValueError("Revised deck identity changed")
        for index, (before, after) in enumerate(
            zip(original.slides, candidate.slides, strict=True)
        ):
            if index != record["index"] and before != after:
                raise ValueError("Revision changed another slide")
    elif record["status"] in {"accepted", "candidate", "generated"}:
        raise ValueError("Completed revision has no result")
    observation = record["observation"]
    if observation is not None:
        if not isinstance(observation, dict) or (
            observation.get("database"),
            observation.get("database_identity"),
            observation.get("local_id"),
            observation.get("mode"),
        ) != (record["database"], record["database_identity"], record["paper_id"], record["mode"]):
            raise ValueError("Revision observation owner mismatch")
        if binding != [observation.get("workspace_id"), observation.get("device_id")]:
            raise ValueError("Revision observation binding mismatch")
    operation = record["file_operation"]
    if operation is not None:
        from paper_daily.sync_schema_v2 import canonical_operation

        canonical_operation(operation)
        if observation is None or (
            operation["entity_type"] != "research_file"
            or operation["entity_id"] != observation["entity_id"]
            or operation["payload"].get("paper_id") != observation["paper_id"]
            or operation["payload"].get("slot") != record["mode"]
        ):
            raise ValueError("Revision artifact identity mismatch")


def load_request(path, *, database, deck_root, figures_root):
    """Explicit owned-workspace retry; embedded paths never choose the destination."""
    database, deck_root, path = Path(database).resolve(), Path(deck_root).resolve(), Path(path)
    if path.stat().st_size > MAX_RECORD:
        raise ValueError("Oversized slide revision receipt")
    for ancestor in (path, *path.parents):
        if ancestor.is_symlink() or getattr(ancestor, "is_junction", lambda: False)():
            raise ValueError("Revision receipt path must not contain links")
    record = json.loads(path.read_text(encoding="utf-8"))
    validate_request_record(record)
    if record["result"] is None:
        raise ValueError("Receipt has no completed result; retry cannot invoke a model")
    folder = deck_root / hashlib.sha256(record["paper_id"].encode()).hexdigest()[:24]
    expected = folder / ".revision-requests" / (record["request_id"] + ".json")
    if path.resolve() != expected or record["database"] != str(database):
        raise ValueError("Receipt is not owned by the explicitly selected workspace")
    deck = presentations.deck_from_dict(record["original"])
    deck._file_observation = record["observation"]
    if record["file_operation"] is not None:
        deck._file_operation = record["file_operation"]
    deck._revision_roots = {"folder": folder, "figures": Path(figures_root).resolve()}
    deck._revision_destination = folder / (deck.mode + ".json")
    deck._revision_figures = {
        key: base64.b64decode(value["base64"], validate=True)
        for key, value in record["figures"].items()
    }
    deck._revision_evidence = record["evidence"]
    client = None
    if (
        record["binding"]
        and _identity(database) == record["database_identity"]
        and _binding(database) == record["binding"]
    ):
        client = runtime(database=database)
    # Compare the original serialized file, never adopt the current file as a new base.
    original_hash = record.get("original_file_hash")
    deck._revision_original_hash = original_hash
    job = Revision(
        record["request_id"],
        deck,
        record["index"],
        record["instruction"],
        database,
        record["database_identity"],
        record["binding"],
        deck._revision_destination,
        original_hash,
        expected,
        record["parent_token"],
        client,
        None,
        record,
    )
    if record["result"] is not None:
        candidate = deepcopy(deck)
        rebuilt = presentations.deck_from_dict(record["result"])
        candidate.__dict__.update(rebuilt.__dict__)
        job.updated = candidate
    return job


def editable_deck(job):
    """Return a normal editor deck, without the worker's frozen lookup overrides."""
    if job.record.get("status") != "accepted":
        raise ValueError("Only a saved revision can be adopted by the editor")
    deck = deepcopy(job.updated)
    for name in tuple(vars(deck)):
        if name.startswith("_revision_"):
            delattr(deck, name)
    return deck
