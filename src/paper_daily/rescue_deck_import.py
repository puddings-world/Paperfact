"""Explicit receiver-bound rescue proposals. No sender writer state is imported.

SQL, PDF verification and file decoding belong on a worker. Native-current guards
are metadata-only; they do not replace the caller's final view/lifetime guard.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import closing
from copy import deepcopy
from dataclasses import dataclass, field
from pathlib import Path
from threading import Lock
from uuid import NAMESPACE_URL, uuid5

from paper_daily import file_change, presentations, raw_deck_closure, raw_deck_receipts
from paper_daily import sync_deck_publication as publication
from paper_daily.pending_deck_result import read_export
from paper_daily.research_lifecycle import parent_lifecycle
from paper_daily.sync_blobs import _no_link
from paper_daily.sync_files import MAX_BODY, canonical_json, descriptor, identifier, read_json
from paper_daily.workspace_service import _binding, _tables

MAX_SOURCES = 16
MAX_SOURCE_BYTES = 512 * 1024**2
_SEAL = object()


def _path(value):
    value = Path(value).absolute()
    for part in (value, *value.parents):
        _no_link(part)
    return value.resolve(strict=True)


def _native(path):
    info = _path(path).stat()
    if not info.st_ino:
        raise ValueError("Rescue import requires known native identity")
    return info.st_dev, info.st_ino


def _plain(value):
    return json.loads(canonical_json(value))


def _check(current):
    if not current():
        raise ValueError("Rescue import was cancelled or its caller scope changed")


def _read(path):
    conn = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, cached_statements=0)
    conn.row_factory = sqlite3.Row
    return conn


def _scope(database, paper_id, slot, expected_native):
    path = _path(database)
    if _native(path) != tuple(expected_native):
        raise ValueError("Original rescue workspace was replaced")
    client = publication.runtime(database=path)
    if client is None:
        raise ValueError("Choose an existing enrolled receiver workspace")
    with closing(_read(path)) as conn:
        conn.execute("BEGIN")
        binding = _binding(conn, _tables(conn))
        expected = (client.journal.workspace_id, client.journal.device_id)
        if not {row[0] for row in binding} >= {
            "paperfact_sync_identity",
            "research_sync_binding",
        } or any(row[1] != expected for row in binding):
            raise ValueError("Receiver workspace/device bindings disagree")
        observation = publication._observation(conn, client, paper_id, slot)
        token = parent_lifecycle(conn, "paper", paper_id)
        parent = conn.execute("SELECT * FROM papers WHERE id=?", (paper_id,)).fetchone()
        if token is None or parent is None:
            raise ValueError("Choose a current paper with an existing local lifecycle")
        store, registration = raw_deck_closure._storage(conn)
        raw_deck_closure._owned_store(conn, store)  # Read-only actual transfer binding admission.
        result = _plain(
            {
                "database": str(path),
                "native": expected_native,
                "binding": binding,
                "paper_id": paper_id,
                "slot": slot,
                "parent_token": token,
                "parent_row": dict(parent),
                "observation": observation,
                "storage": registration,
            }
        )
    if _native(path) != tuple(expected_native):
        raise ValueError("Original rescue workspace changed during capture")
    if len(canonical_json(result)) > MAX_BODY:
        raise ValueError("Receiver rescue observation exceeds 8 MiB")
    return result


def _target_current(target):
    _sealed(target, TargetCapture)
    before = json.loads(target._snapshot)
    now = _scope(target.database, before["paper_id"], before["slot"], target.native)
    for key in (
        "database",
        "native",
        "binding",
        "paper_id",
        "slot",
        "parent_token",
        "parent_row",
        "storage",
    ):
        if before[key] != now[key]:
            raise ValueError("Original rescue receiver/parent/storage changed")
    if not publication._same_observation(now["observation"], before["observation"]):
        raise ValueError("Original rescue target or source inputs changed")
    return before


def _sealed(value, kind):
    if not isinstance(value, kind) or value._seal is not _SEAL:
        raise ValueError("Use an actually captured rescue request")


@dataclass(frozen=True)
class TargetCapture:
    database: Path
    native: tuple
    request_id: str
    _snapshot: str = field(repr=False)
    _summary: str = field(repr=False)
    _seal: object = field(repr=False, compare=False)

    @property
    def summary(self):
        return json.loads(self._summary)

    def native_current(self):
        try:
            return _native(self.database) == self.native
        except (OSError, ValueError):
            return False

    def current(self):
        try:
            _target_current(self)
            return True
        except (OSError, ValueError, sqlite3.Error):
            return False


def capture(database, paper_id, slot, *, expected_native, request_id, current=lambda: True):
    """Read-only worker capture; UI supplies its already captured original native owner."""
    _check(current)
    identifier(request_id)
    identifier("rescue:" + request_id)
    identifier(paper_id)
    if slot not in {"notes", "guide"}:
        raise ValueError("Unsupported receiver deck slot")
    if (
        not isinstance(expected_native, (tuple, list))
        or len(expected_native) != 2
        or any(type(n) is not int or n < 0 for n in expected_native)
        or not expected_native[1]
    ):
        raise ValueError("Capture the original native receiver before asynchronous work")
    path = _path(database)
    value = _scope(path, paper_id, slot, expected_native)
    summary = {
        "paper_id": paper_id,
        "paper_title": value["parent_row"]["title"],
        "slot": slot,
        "workspace_id": value["observation"]["workspace_id"],
        "device_id": value["observation"]["device_id"],
    }
    result = TargetCapture(
        path,
        tuple(expected_native),
        request_id,
        canonical_json(value).decode(),
        canonical_json(summary).decode(),
        _SEAL,
    )
    _target_current(result)
    _check(current)
    return result


def _file_bytes(path, expected=None):
    path = _path(path)
    if not path.is_file():
        raise ValueError("Choose a regular rescue export file")
    before = file_change.version(path)
    if before[2] > raw_deck_receipts.MAX_RECEIPT:
        raise ValueError("Rescue export exceeds 160 MiB")
    if expected is not None and before != expected:
        raise ValueError("Displayed rescue file was changed or replaced")
    with path.open("rb") as stream:
        if file_change.version(path, stream=stream) != before:
            raise ValueError("Rescue file changed before reading")
        data = stream.read(raw_deck_receipts.MAX_RECEIPT + 1)
        if file_change.version(path, stream=stream) != before:
            raise ValueError("Rescue file changed during reading")
    if len(data) > raw_deck_receipts.MAX_RECEIPT or file_change.version(path) != before:
        raise ValueError("Rescue file changed after reading")
    return path, data, before


@dataclass(frozen=True)
class RescuePreview:
    source_path: Path
    file_sha256: str
    file_version: tuple
    _bytes: bytes = field(repr=False)
    _research: str = field(repr=False)
    _images: tuple = field(repr=False)
    _source_document_hash: str | None = field(repr=False)
    _summary: str = field(repr=False)
    _seal: object = field(repr=False, compare=False)

    @property
    def summary(self):
        return json.loads(self._summary)

    @property
    def preview_data(self):
        result = json.loads(self._research)
        result.update(
            image_bytes=dict(self._images), publish=False, sync=False, requires_explicit_review=True
        )
        return result

    def native_current(self):
        try:
            return file_change.version(_path(self.source_path)) == self.file_version
        except (OSError, ValueError):
            return False


def inspect_file(path, *, current=lambda: True):
    """No SQL/retention: preview a validated immutable file even without a receiver/PDF."""
    _check(current)
    path, data, proof = _file_bytes(path)
    value = read_export(data)
    envelope = raw_deck_receipts._load(data)
    payload = read_json(envelope["closure"]["payload"].encode())
    original_hash = payload["source_document_hash"]
    if file_change.version(path) != proof:
        raise ValueError("Rescue file changed during validation")
    _check(current)
    scientific = {"deck": value["deck"], "evidence": value["evidence"]}
    summary = {
        "file_name": path.name,
        "deck_title": value["deck"]["title"],
        "paper_title": value["deck"]["paper_title"],
        "slot": value["deck"]["mode"],
        "slides": len(value["deck"]["slides"]),
        "images": len(value["image_bytes"]),
        "source_document_hash": original_hash,
        "source_status": "declared/unverified",
        "file_sha256": hashlib.sha256(data).hexdigest(),
    }
    return RescuePreview(
        path,
        summary["file_sha256"],
        proof,
        data,
        canonical_json(scientific).decode(),
        tuple(sorted(value["image_bytes"].items())),
        original_hash,
        canonical_json(summary).decode(),
        _SEAL,
    )


def _verify_preview(preview):
    _sealed(preview, RescuePreview)
    _path_, data, _proof = _file_bytes(preview.source_path, preview.file_version)
    if hashlib.sha256(data).hexdigest() != preview.file_sha256 or data != preview._bytes:
        raise ValueError("Displayed rescue content changed")


def _hashes(preview):
    value = json.loads(preview._research)
    evidence = value["evidence"] or {}
    rows = [
        *value["deck"]["sources"],
        *value["deck"]["figures"],
        *evidence.get("sources", []),
        *evidence.get("figures", []),
    ]
    hashes = {row["document_hash"] for row in rows if row.get("document_hash")}
    if preview._source_document_hash is not None:
        hashes.add(preview._source_document_hash)
    if len(hashes) > MAX_SOURCES:
        raise ValueError("Rescue import supports at most 16 exact original sources")
    return sorted(hashes)


def _cache_rows(conn, target, data, digest):
    """Read only this actual owner's bounded receipt namespace and selected SQL rows."""
    from itertools import islice

    from paper_daily import local_source_owners, source_snapshots
    from paper_daily.sync_documents import MAX_PDF_BYTES

    observation = data["observation"]
    binding = {key: observation[key] for key in ("workspace_id", "device_id")}
    root = (
        target.database.parent
        / ".paperfact-source-snapshots"
        / source_snapshots._namespace(dict(database_identity=list(target.native), binding=binding))
    )
    rows = [(row, None, None) for row in local_source_owners.records(conn, document_hash=digest)]
    if root.exists():
        root = _path(root)
        entries = list(islice(root.iterdir(), source_snapshots.MAX_RECEIPTS * 2 + 1))
        if len(entries) > source_snapshots.MAX_RECEIPTS * 2:
            raise ValueError("Original receipt namespace exceeds its entry budget")
        scanned_bytes = 0
        for entry in sorted(entries):
            _path(entry)
            receipt = entry / "receipt.json" if entry.is_dir() else entry
            if entry.is_dir():
                from paper_daily import position_source_snapshots

                if position_source_snapshots.is_stage(entry):
                    continue
            if not receipt.is_file():
                raise ValueError("Published original ownership receipt is missing")
            receipt = _path(receipt)
            before = file_change.version(receipt)
            if not receipt.is_file() or not 0 < before[2] <= source_snapshots.MAX_RECEIPT:
                raise ValueError("Original receipt exceeds its metadata budget")
            scanned_bytes += before[2]
            if scanned_bytes > local_source_owners.MAX_METADATA:
                raise ValueError("Original receipt namespace exceeds its byte budget")
            encoded = receipt.read_bytes()
            if file_change.version(receipt) != before or len(encoded) != before[2]:
                raise ValueError("Original receipt changed during verification")
            row = source_snapshots.validate(
                source_snapshots._decode(encoded), max_pdf_bytes=MAX_PDF_BYTES
            )
            if source_snapshots.receipt_path(target.database, row) != receipt:
                raise ValueError("Original receipt differs from its owned location")
            if row["sha256"] == digest:
                rows.append((row, str(receipt), before))
    selected = []
    for row, receipt, version in rows:
        owner = json.loads(row["owner_json"])
        if (
            owner["database_identity"] == list(target.native)
            and owner["binding"] == binding
            and owner["paper_id"] == data["paper_id"]
            and owner["source_owner_id"] in {data["paper_id"], observation["paper_id"]}
            and owner["parent_lifecycle"] == data["parent_token"]
        ):
            selected.append(dict(row=row, receipt=receipt, receipt_version=version))
    if not selected:
        raise ValueError("Declared original is unavailable or not owned by this exact local target")
    return sorted(selected, key=lambda item: canonical_json(item))[0]


def _verify_cache(target, metadata):
    from paper_daily import local_source_owners, source_snapshots
    from paper_daily.sync_documents import MAX_PDF_BYTES
    from paper_daily.sync_legacy_sources import validate_pdf

    row = metadata["row"]
    path = _path(source_snapshots.source_path(target.database, row, max_pdf_bytes=MAX_PDF_BYTES))
    if metadata["receipt"] is not None:
        receipt = _path(metadata["receipt"])
        if file_change.version(receipt) != tuple(metadata["receipt_version"]):
            raise ValueError("Original ownership receipt changed before source verification")
    # This low-level maintained byte reader grants no claim/publication authority.
    verified = local_source_owners._read_pdf(path, row["sha256"], row["size"])
    if verified is None:
        raise ValueError("Original source verification was cancelled")
    content, version = verified
    validate_pdf(content)
    if file_change.version(path) != version:
        raise ValueError("Original source changed during PDF verification")
    if metadata["receipt"] is not None and file_change.version(receipt) != tuple(
        metadata["receipt_version"]
    ):
        raise ValueError("Original ownership receipt changed during source verification")
    return path


def _sources(target, hashes):
    from paper_daily import sync_source_files
    from paper_daily.sync_artifacts import desired_file, paper_current
    from paper_daily.sync_documents import _paper_current, verify_document
    from paper_daily.sync_files import file_id, validate_payload

    data = _target_current(target)
    observation = data["observation"]
    with closing(_read(target.database)) as conn:
        conn.execute("BEGIN")
        store, _registration = raw_deck_closure._storage(conn)
        store = raw_deck_closure._owned_store(conn, store)
        selected, total = [], 0
        for sha in hashes:
            primary = observation["applied_document"]
            if (
                primary is not None
                and primary == observation["desired_document"]
                and primary["sha256"] == sha
                and _paper_current(conn, primary)
            ):
                selected.append(("primary", sha, primary, primary["size"]))
                total += primary["size"]
                continue
            operation = desired_file(conn, file_id(observation["paper_id"], "original_source", sha))
            if operation is None or not paper_current(conn, operation):
                cached = _cache_rows(conn, target, data, sha)
                size = cached["row"]["size"]
                selected.append(("cache", sha, cached, size))
                total += size
                continue
            validate_payload(operation["payload"])
            sync_source_files.validate_manifest(operation["payload"])
            size = operation["payload"]["assets"][0]["size"]
            selected.append(("retained", sha, operation, size))
            total += size
        if total > MAX_SOURCE_BYTES:
            raise ValueError("Rescue source verification exceeds 512 MiB")
        proofs = []
        for kind, sha, metadata, size in selected:
            if kind == "primary":
                verified = verify_document(store, metadata)
                if not verified.matches(metadata):
                    raise ValueError("Owned primary changed during rescue verification")
                path = verified._path
            elif kind == "cache":
                path = _verify_cache(target, metadata)
            else:
                path = sync_source_files.inspectable(conn, observation["paper_id"], sha)
                if path is None or desired_file(conn, metadata["entity_id"]) != metadata:
                    raise ValueError("Owned retained original changed during verification")
            path = _path(path)
            proofs.append(
                {
                    "kind": kind,
                    "sha256": sha,
                    "size": size,
                    "metadata": metadata,
                    "path": str(path),
                    "version": file_change.version(path),
                }
            )
    _target_current(target)
    return _plain(proofs)


@dataclass
class _State:
    lock: Lock = field(default_factory=Lock)
    result: object = None


@dataclass(frozen=True)
class ImportResult:
    retention: publication.DraftRetention
    context_current: bool
    publish: bool = False
    sync: bool = False
    requires_explicit_review: bool = True

    @property
    def candidate_id(self):
        return self.retention.candidate_id

    @property
    def state(self):
        return self.retention.state

    @property
    def durable(self):
        return self.retention.durable


@dataclass(frozen=True)
class RescueImport:
    target: TargetCapture
    preview: RescuePreview
    candidate_id: str
    fingerprint: str
    _deck: str = field(repr=False)
    _evidence: str = field(repr=False)
    _observation: str = field(repr=False)
    _sources: str = field(repr=False)
    _capture: bytes = field(repr=False)
    _summary: str = field(repr=False)
    _state: _State = field(repr=False, compare=False)
    _seal: object = field(repr=False, compare=False)

    @property
    def summary(self):
        return json.loads(self._summary)

    @property
    def preview_data(self):
        return self.preview.preview_data

    def native_current(self):
        return self.target.native_current() and self.preview.native_current()

    def current(self):
        try:
            _job_current(self)
            return True
        except (OSError, ValueError, sqlite3.Error):
            return False

    def run(self, *, current=lambda: True):
        return run(self, current=current)


def _job_current(job):
    _sealed(job, RescueImport)
    _target_current(job.target)
    _verify_preview(job.preview)
    if _sources(job.target, _hashes(job.preview)) != json.loads(job._sources):
        raise ValueError("Original rescue source ownership/version changed")


def prepare(target, source, *, current=lambda: True):
    from paper_daily import sync_source_files
    from paper_daily.sync_deck_files import encode_deck
    from paper_daily.sync_files import validate_input_versions

    _check(current)
    data = _target_current(target)
    preview = source if isinstance(source, RescuePreview) else inspect_file(source, current=current)
    _verify_preview(preview)
    scientific = json.loads(preview._research)
    if scientific["deck"]["mode"] != data["slot"]:
        raise ValueError("Choose the rescue file's declared deck slot explicitly")
    sources = _sources(target, _hashes(preview))
    _check(current)
    candidate = "rescue:" + target.request_id
    # This is a fresh receiver action/artifact ID, never a paper/source identity.
    action = {
        "request_id": target.request_id,
        "database": str(target.database),
        "native": target.native,
        "binding": data["binding"],
        "parent_token": data["parent_token"],
        "parent_row": data["parent_row"],
        "paper_id": data["paper_id"],
        "slot": data["slot"],
        "file": str(preview.source_path),
        "file_version": preview.file_version,
        "file_sha256": preview.file_sha256,
    }
    fingerprint = hashlib.sha256(canonical_json(action)).hexdigest()
    deck_value = deepcopy(scientific["deck"])
    deck_value["paper_id"] = data["paper_id"]
    deck_value["deck_id"] = str(uuid5(NAMESPACE_URL, "paperfact.rescue-import.v1:" + fingerprint))
    deck = presentations.deck_from_dict(deck_value)
    deck.version = deck_value["version"]
    deck._revision_figures = dict(preview._images)
    evidence = scientific["evidence"]
    observation = data["observation"]
    with closing(_read(target.database)) as conn:
        if conn.execute("SELECT 1 FROM sqlite_master WHERE name='research_file_drafts'").fetchone():
            row = conn.execute(
                "SELECT candidate_id,entity_id,deck,observation FROM "
                "research_file_drafts WHERE candidate_id=?",
                (candidate,),
            ).fetchone()
            if row is not None:
                raw = dict(row)
                if (
                    json.loads(raw["deck"]) != deck.to_dict()
                    or raw["entity_id"] != observation["entity_id"]
                    or not publication._same_observation(
                        observation, json.loads(raw["observation"])
                    )
                ):
                    raise ValueError("Rescue request ID was reused for changed input or target")
                observation = json.loads(raw["observation"])
        unknown = sync_source_files.input_versions()
        validate_input_versions(unknown)
        payload, blobs = encode_deck(
            deck,
            observation["paper_id"],
            input_versions=unknown,
            source_document_hash=preview._source_document_hash,
            evidence=evidence,
        )
        inventory = []
        for key, image in preview._images:
            item = {"id": key, **descriptor(image, "image/png")}
            inventory.append(item)
            blobs[item["sha256"]] = image
        raw = {
            "candidate_id": candidate,
            "entity_id": observation["entity_id"],
            "deck": canonical_json(deck.to_dict()).decode(),
            "observation": canonical_json(observation).decode(),
        }
        closure = {
            "candidate_id": candidate,
            "source_sha256": raw_deck_closure.source_hash(raw),
            "payload": canonical_json(payload).decode(),
            "inventory": canonical_json({"version": 1, "images": inventory}).decode(),
        }
        captured = raw_deck_receipts.capture(conn, raw, closure, evidence, blobs)
    _target_current(target)
    _verify_preview(preview)
    _check(current)
    summary = {
        **preview.summary,
        **target.summary,
        "source_paper_title": preview.summary["paper_title"],
        "target_id": target.summary["paper_id"],
        "target_title": target.summary["paper_title"],
        "candidate_id": candidate,
        "fingerprint": fingerprint,
        "source_status": "owned" if sources else "unknown",
    }
    return RescueImport(
        target,
        preview,
        candidate,
        fingerprint,
        canonical_json(deck.to_dict()).decode(),
        canonical_json(evidence).decode(),
        canonical_json(observation).decode(),
        canonical_json(sources).decode(),
        captured,
        canonical_json(summary).decode(),
        _State(),
        _SEAL,
    )


def run(job, *, current=lambda: True):
    """Retain a proposal only. A concurrent core-stage change may leave history, not activation."""
    _sealed(job, RescueImport)
    if not job._state.lock.acquire(blocking=False):
        raise ValueError("This rescue import already has an action in progress")
    try:
        _check(current)
        prior = job._state.result
        evidence = json.loads(job._evidence)
        if prior is not None:
            deck = prior.retention.deck
            if (
                deck.to_dict() != json.loads(job._deck)
                or prior.retention.evidence != evidence
                or getattr(deck, "_revision_figures", None) != dict(job.preview._images)
            ):
                raise ValueError("Actual rescue result changed; use a new explicit request")
            if prior.durable:
                _job_current(job)
                _check(current)
                result = ImportResult(prior.retention, True)
                job._state.result = result
                return result
        else:
            deck = presentations.deck_from_dict(json.loads(job._deck))
            deck.version = json.loads(job._deck)["version"]
            deck._revision_figures = dict(job.preview._images)
        _check(current)
        _job_current(job)
        _check(current)
        try:
            retention = raw_deck_closure.retain_outcome(
                json.loads(job._observation),
                deck,
                evidence=evidence,
                request_id=job.candidate_id,
                _captured=job._capture,
            )
        except (OSError, ValueError, sqlite3.Error) as error:
            # Preserve the actual imported material if retention refuses after
            # admission; this never turns refusal into an applied/saved result.
            retention = publication.DraftRetention(
                job.candidate_id, "incomplete", deck, evidence, str(error), job._capture
            )
        try:
            _check(current)
            _job_current(job)
            context_current = True
        except (OSError, ValueError, sqlite3.Error):
            context_current = False
        result = ImportResult(retention, context_current)
        job._state.result = result
        return result
    finally:
        job._state.lock.release()
