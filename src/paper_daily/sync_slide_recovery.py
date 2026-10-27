"""Typed, detached recovery of private slide-revision receipts and their closure.

No helper in this module returns a publisher/job or follows a path from archived
content. Restored records retain provenance but have no publication capability.
"""

from __future__ import annotations

import base64
import hashlib
import json
import re
import sqlite3
from contextlib import closing
from copy import deepcopy
from pathlib import Path
from uuid import UUID

from paper_daily import slide_revision
from paper_daily.sync_blobs import BlobManifest, _no_link
from paper_daily.sync_deck_files import validate_png
from paper_daily.sync_files import validate_closure, validate_payload

TABLE = "research_slide_revision_recovery"
COLUMNS = "request_id manifest"
MAX_RECEIPTS = 2000
MAX_BYTES = 256 * 1024**2
HASH = re.compile(r"[0-9a-f]{64}")


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False).encode("utf-8")


def _pairs(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("Duplicate slide recovery field")
        value[key] = item
    return value


def _load(data):
    return json.loads(
        data,
        object_pairs_hook=_pairs,
        parse_constant=lambda _value: (_ for _ in ()).throw(ValueError("Nonfinite JSON")),
    )


def _path(path):
    path = Path(path).absolute()
    for part in (path, *path.parents):
        _no_link(part)
    return path


def _descriptor(data):
    return {"sha256": hashlib.sha256(data).hexdigest(), "size": len(data)}


def _check_descriptor(row, maximum):
    if not isinstance(row, dict) or set(row) != {"sha256", "size"}:
        raise ValueError("Invalid slide recovery blob descriptor")
    BlobManifest(row["sha256"], row["size"])
    if type(row["size"]) is not int or not 0 < row["size"] <= maximum:
        raise ValueError("Slide recovery blob exceeds its bound")


def _artifacts(record):
    observation = record["observation"] or {}
    result = {}
    for operation in (record["file_operation"], observation.get("artifact")):
        if operation is not None:
            from paper_daily.sync_schema_v2 import canonical_operation

            canonical_operation(operation)
            if operation["entity_type"] != "research_file" or operation["action"] != "put":
                raise ValueError("Invalid original slide artifact")
            if operation["workspace_id"] != observation.get("workspace_id"):
                raise ValueError("Original slide artifact belongs to another workspace")
            if operation["entity_id"] != observation.get("entity_id"):
                raise ValueError("Original slide artifact belongs to another deck")
            payload = operation["payload"]
            result[_json(payload)] = payload
    return [result[key] for key in sorted(result)]


def _source_hashes(record):
    hashes = set()
    for deck in (record["original"], record["result"]):
        if deck is not None:
            for row in [*deck["sources"], *deck["figures"]]:
                if row.get("document_hash"):
                    hashes.add(row["document_hash"])
    for row in record["evidence"].get("sources", []):
        if row.get("document_hash"):
            hashes.add(row["document_hash"])
    for payload in _artifacts(record):
        if payload["source_document_hash"]:
            hashes.add(payload["source_document_hash"])
        hashes.update(row["sha256"] for row in payload["input_versions"]["documents"])
    observation = record["observation"] or {}
    for key in ("desired_document", "applied_document"):
        target = observation.get(key)
        if target is not None:
            from paper_daily.sync_documents import _validate_target

            _validate_target(target)
            if target["workspace_id"] != observation.get("workspace_id"):
                raise ValueError("Original PDF belongs to another workspace")
            hashes.add(target["sha256"])
    if len(hashes) > 16 or any(not isinstance(h, str) or not HASH.fullmatch(h) for h in hashes):
        raise ValueError("Invalid or excessive original source PDF references")
    return hashes


def validate_manifest(row):
    if not isinstance(row, dict) or set(row) != {"request_id", "manifest"}:
        raise ValueError("Invalid slide recovery row")
    value = _load(row["manifest"])
    if (
        not isinstance(value, dict)
        or set(value)
        != {"version", "request_id", "workspace_id", "body", "figures", "sources", "artifacts"}
        or type(value["version"]) is not int
        or value["version"] != 1
    ):
        raise ValueError("Invalid slide recovery manifest")
    if (
        str(UUID(row["request_id"])) != row["request_id"]
        or row["request_id"] != value["request_id"]
    ):
        raise ValueError("Invalid slide recovery request identity")
    workspace = value["workspace_id"]
    if workspace is not None and (
        not isinstance(workspace, str) or not workspace or len(workspace) > 128
    ):
        raise ValueError("Invalid slide recovery workspace")
    _check_descriptor(value["body"], slide_revision.MAX_RECORD)
    if not isinstance(value["figures"], dict) or len(value["figures"]) > 128:
        raise ValueError("Invalid slide recovery figure closure")
    if not isinstance(value["sources"], list) or len(value["sources"]) > 16:
        raise ValueError("Invalid slide recovery source closure")
    if not isinstance(value["artifacts"], list) or len(value["artifacts"]) > 2:
        raise ValueError("Invalid original artifact closure")
    for figure_id, descriptor in value["figures"].items():
        if not isinstance(figure_id, str) or not figure_id or len(figure_id) > 300:
            raise ValueError("Invalid recovered figure identity")
        _check_descriptor(descriptor, 8_000_000)
    if sum(d["size"] for d in value["figures"].values()) > slide_revision.MAX_IMAGES:
        raise ValueError("Recovered figures exceed their quota")
    for descriptor in value["sources"]:
        _check_descriptor(descriptor, 150 * 1024**2)
    if len({d["sha256"] for d in value["sources"]}) != len(value["sources"]):
        raise ValueError("Duplicate source PDF")
    for payload in value["artifacts"]:
        validate_payload(payload)
    return value


def references(value):
    yield value["body"]
    yield from value["figures"].values()
    yield from value["sources"]
    for payload in value["artifacts"]:
        yield payload["body"]
        yield from payload["assets"]


def read_retained(row, read):
    """Verify and return private data only. The result is deliberately not a Revision."""
    value = validate_manifest(row)

    def verified(descriptor):
        data = read(descriptor)
        if not isinstance(data, bytes) or _descriptor(data) != {
            "sha256": descriptor["sha256"],
            "size": descriptor["size"],
        }:
            raise ValueError("Slide recovery blob failed size/hash verification")
        return data

    body = _load(verified(value["body"]))
    if not isinstance(body, dict) or body.get("figures") != value["figures"]:
        raise ValueError("Slide recovery figure manifest mismatch")
    record = deepcopy(body)
    record["figures"] = {}
    for identity, descriptor in value["figures"].items():
        data = verified(descriptor)
        validate_png(data)
        record["figures"][identity] = {
            "sha256": descriptor["sha256"],
            "base64": base64.b64encode(data).decode("ascii"),
        }
    slide_revision.validate_request_record(record)
    for figure in record["original"]["figures"]:
        asset = figure.get("asset")
        if isinstance(asset, str) and re.fullmatch(r"[0-9a-f]{64}\.png", asset):
            captured = value["figures"].get(figure["id"])
            if captured is None or captured["sha256"] != asset[:-4]:
                raise ValueError("Captured figure differs from its original immutable identity")
    if record["request_id"] != row["request_id"]:
        raise ValueError("Recovered request differs from its row")
    binding = record["binding"]
    if (binding[0] if binding else None) != value["workspace_id"]:
        raise ValueError("Recovered request belongs to another workspace")
    if _artifacts(record) != value["artifacts"]:
        raise ValueError("Recovered original artifact closure differs")
    if _source_hashes(record) != {d["sha256"] for d in value["sources"]}:
        raise ValueError("Recovered original source closure differs")
    from paper_daily.presentations import deck_from_dict
    from paper_daily.slide_layout import used_figures

    for raw in (record["original"], record["result"]):
        if raw is not None and not used_figures(deck_from_dict(raw)) <= set(record["figures"]):
            raise ValueError("Recovered slide has an unretained figure")
    for payload in value["artifacts"]:
        validate_closure(payload, verified)
    import pymupdf

    for descriptor in value["sources"]:
        with pymupdf.open(stream=verified(descriptor), filetype="pdf") as document:
            if document.is_encrypted or document.page_count < 1:
                raise ValueError("Original source PDF is unreadable")
    return record


def _represented_deck(raw, candidates):
    """Allow omitted layout defaults, but never discard an existing unknown field."""
    from paper_daily.presentations import deck_from_dict

    normalized = deck_from_dict(raw).to_dict()

    def preserved(before, after):
        if isinstance(before, dict):
            return isinstance(after, dict) and all(
                key in after and preserved(value, after[key]) for key, value in before.items()
            )
        if isinstance(before, list):
            return (
                isinstance(after, list)
                and len(before) == len(after)
                and all(preserved(left, right) for left, right in zip(before, after, strict=True))
            )
        return before == after

    return _json(normalized) in candidates and preserved(raw, normalized)


def collect(
    database,
    roots,
    temporary,
    retained_refs,
    blob_store=None,
    *,
    source_resolver=None,
    legacy_slots=None,
):
    """Return synthetic rows, staged objects and exact legacy receipt aliases."""
    database = _path(database)
    stat = database.stat()
    current_identity = [stat.st_dev, stat.st_ino]
    current_binding = slide_revision._binding(database)
    objects, allowed, rows, seen, bytes_read = {}, {}, [], {}, 0
    folder_data, row_ids, receipt_count = {}, set(), 0
    source_hashes = set()
    current_parents = {}
    staging = Path(temporary) / "slide-revision-objects"
    staging.mkdir()

    def stage(data):
        descriptor = _descriptor(data)
        path = staging / descriptor["sha256"]
        if not path.exists():
            path.write_bytes(data)
        objects[descriptor["sha256"]] = path
        return descriptor

    def read(descriptor):
        if descriptor["sha256"] in objects:
            return objects[descriptor["sha256"]].read_bytes()
        if source_resolver is not None and descriptor["sha256"] in source_hashes:
            adopted = source_resolver.find(descriptor["sha256"], descriptor["size"])
            if adopted is not None:
                return source_resolver.objects[descriptor["sha256"]].read_bytes()
        if blob_store is None:
            raise ValueError("Original slide sources/assets require their owned BlobStore")
        return blob_store.verified_path(
            BlobManifest(descriptor["sha256"], descriptor["size"])
        ).read_bytes()

    for root in sorted({_path(root) for root in roots}):
        decks = root / "presentations"
        if not decks.exists():
            continue
        _path(decks)
        for path in sorted(decks.glob("*/.revision-requests/*")):
            _path(path)
            if (
                not path.is_file()
                or path.suffix != ".json"
                or path.stat().st_size > slide_revision.MAX_RECORD
            ):
                raise ValueError("Unexpected or oversized slide revision receipt")
            raw = path.read_bytes()
            bytes_read += len(raw)
            receipt_count += 1
            if bytes_read > MAX_BYTES or receipt_count > MAX_RECEIPTS:
                raise ValueError("Slide revision recovery inventory exceeds its bound")
            record = _load(raw)
            slide_revision.validate_request_record(record)
            expected_folder = hashlib.sha256(record["paper_id"].encode()).hexdigest()[:24]
            if (
                path.name != record["request_id"] + ".json"
                or path.parent.parent.name != expected_folder
            ):
                raise ValueError("Slide receipt filename/owner mismatch")
            same_identity = record["database_identity"] == current_identity
            same_bound_owner = (
                record["binding"] is not None and record["binding"] == current_binding
            )
            if record["binding"] != current_binding or not (same_identity or same_bound_owner):
                raise ValueError("Slide receipt belongs to a replaced or different workspace")
            identity = record["request_id"]
            encoded = _json(record)
            if identity in seen and seen[identity] != encoded:
                raise ValueError("Conflicting slide revision receipts")
            seen[identity] = encoded
            allowed[path] = (hashlib.sha256(raw).hexdigest(), len(raw))
            images = {
                key: stage(base64.b64decode(item["base64"], validate=True))
                for key, item in record["figures"].items()
            }
            body = deepcopy(record)
            body["figures"] = images
            sources = []
            own_targets = record["observation"] or {}
            sizes = dict(retained_refs)
            for key in ("desired_document", "applied_document"):
                target = own_targets.get(key)
                if target:
                    sizes[target["sha256"]] = target["size"]
            required_sources = _source_hashes(record)
            source_hashes.update(required_sources)
            for digest in sorted(required_sources):
                if digest not in sizes:
                    if source_resolver is None:
                        raise ValueError("Original slide source PDF lacks a retained manifest")
                    sizes[digest] = source_resolver.require(digest)["size"]
                sources.append({"sha256": digest, "size": sizes[digest]})
            manifest = {
                "version": 1,
                "request_id": identity,
                "workspace_id": current_binding[0] if current_binding else None,
                "body": stage(_json(body)),
                "figures": images,
                "sources": sources,
                "artifacts": _artifacts(record),
            }
            row = {"request_id": identity, "manifest": _json(manifest).decode()}
            read_retained(row, read)
            if identity not in row_ids:
                rows.append(row)
                row_ids.add(identity)
            content = folder_data.setdefault(
                path.parent.parent,
                {
                    "decks": set(),
                    "evidence": set(),
                    "images": set(),
                    "slots": set(),
                    "legacy": [],
                },
            )
            content["decks"].update(
                _json(deck) for deck in (record["original"], record["result"]) if deck is not None
            )
            content["evidence"].add(_json(record["evidence"]))
            content["images"].update(item["sha256"] for item in images.values())
            content["slots"].add(record["mode"] + ".json")
            if record["binding"] is None:
                if record["paper_id"] not in current_parents:
                    current_parents[record["paper_id"]] = slide_revision._parent(
                        database, record["paper_id"]
                    )
                content["legacy"].append(record)

    # Inventory each paper folder once, regardless of its retained job count.
    # Only typed content already represented by verified receipts may bypass the
    # migration check; other legacy decks/history/research still fail.
    for folder, content in folder_data.items():
        for item in folder.rglob("*"):
            _path(item)
            if not item.is_file() or item in allowed:
                continue
            png = item.parent.name == "assets" and item.suffix == ".png"
            deck = item.name in content["slots"] or (
                item.parent.name == "history" and item.suffix == ".json"
            )
            evidence = item.parent.name == "evidence" and item.suffix == ".json"
            write_lock = item.name == ".deck-write.lock"
            job_lock = item.parent.name == ".research-jobs" and re.fullmatch(
                r"[0-9a-f]{64}\.lock", item.name
            )
            if not (png or deck or evidence or write_lock or job_lock):
                continue
            if item.stat().st_size > 8 * 1024**2:
                continue
            data = item.read_bytes()
            bytes_read += len(data)
            if bytes_read > MAX_BYTES:
                raise ValueError("Slide recovery inventory exceeds its byte bound")
            digest = hashlib.sha256(data).hexdigest()
            represented = False
            if png:
                represented = digest in content["images"]
            elif deck:
                represented = _represented_deck(_load(data), content["decks"])
            elif evidence:
                represented = _json(_load(data)) in content["evidence"]
            elif write_lock:
                represented = data == b""
            elif job_lock:
                represented = data == b"0"
            if represented:
                allowed[item] = (digest, len(data))
                if (
                    legacy_slots is not None
                    and item.parent == folder
                    and item.name in content["slots"]
                ):
                    current = _load(data)
                    matches = [
                        record
                        for record in content["legacy"]
                        if record["mode"] + ".json" == item.name
                        and record["parent_token"] is not None
                        and record["parent_token"] == current_parents.get(record["paper_id"])
                        and _represented_deck(
                            current,
                            {
                                _json(raw)
                                for raw in (record["original"], record["result"])
                                if raw is not None
                            },
                        )
                    ]
                    if matches:
                        record = sorted(matches, key=lambda record: record["request_id"])[0]
                        legacy_slots.append(
                            {
                                "paper_id": record["paper_id"],
                                "slot": record["mode"],
                                "request_id": record["request_id"],
                                "parent_token": record["parent_token"],
                                "deck": _json(stage(data)).decode(),
                            }
                        )
    return rows, objects, allowed


def _read_object(root, descriptor):
    path = _path(root / descriptor["sha256"])
    if path.stat().st_size != descriptor["size"]:
        raise ValueError("Detached object size differs from its manifest")
    return path.read_bytes()


def read_detached(database, request_id):
    """Read verified retained research without reviving original write/session state."""
    database = _path(database)
    with closing(sqlite3.connect(database.as_uri() + "?mode=ro", uri=True)) as conn:
        if not conn.execute(
            "SELECT 1 FROM sqlite_master WHERE name='recovery_identity'"
        ).fetchone():
            raise ValueError("Select a detached recovery workspace")
        found = []
        for raw in conn.execute("SELECT data FROM recovery_records WHERE table_name=?", (TABLE,)):
            row = _load(raw[0])
            if row["request_id"] == request_id:
                found.append(row)
    if len(found) != 1:
        raise ValueError("Retained slide revision is missing or ambiguous")
    record = read_retained(found[0], lambda row: _read_object(database.parent / "objects", row))
    return {
        "record": record,
        "capabilities": {
            "publish": False,
            "retry": False,
            "sync": False,
            "requires_explicit_review": True,
        },
    }


def recovered_evidence_target(folder, deck, asset):
    """Stage a verified local lookup without inventing a historical input digest."""
    descriptor = {key: asset[key] for key in ("sha256", "size")}
    _check_descriptor(descriptor, 8 * 1024**2)
    mapping = {
        "version": 1,
        "paper_id": deck["paper_id"],
        "slot": deck["mode"],
        "deck_id": deck["deck_id"],
        "original_source_hash": deck["source_hash"],
        "asset": descriptor,
    }
    validate_evidence_mapping(mapping)
    location = folder / ("recovery-evidence-" + deck["mode"] + ".json")
    if location.exists():
        raise ValueError("Duplicate recovered evidence lookup")
    location.write_bytes(_json(mapping))
    return folder / "recovered-evidence" / (descriptor["sha256"] + ".json")


def validate_evidence_mapping(value):
    from paper_daily.presentations import MODES

    if (
        not isinstance(value, dict)
        or set(value) != {"version", "paper_id", "slot", "deck_id", "original_source_hash", "asset"}
        or type(value["version"]) is not int
        or value["version"] != 1
    ):
        raise ValueError("Invalid recovered evidence mapping")
    if value["slot"] not in MODES:
        raise ValueError("Invalid recovered evidence slot")
    for key, limit in (("paper_id", 1024), ("deck_id", 100), ("original_source_hash", 100)):
        if not isinstance(value[key], str) or len(value[key]) > limit:
            raise ValueError("Invalid recovered evidence identity")
    if not value["paper_id"] or not value["deck_id"]:
        raise ValueError("Missing recovered evidence identity")
    _check_descriptor(value["asset"], 8 * 1024**2)


def _verify_evidence_owner(database, mapping):
    from paper_daily.sync_deck_files import validate_body
    from paper_daily.sync_schema_v2 import canonical_operation

    with closing(sqlite3.connect(database.as_uri() + "?mode=ro", uri=True)) as conn:
        rows = conn.execute(
            "SELECT table_name,data FROM recovery_records WHERE table_name IN "
            "('research_paper_identity','research_file_applied')"
        ).fetchall()
    portable = {
        row["sync_id"]
        for name, raw in rows
        if name == "research_paper_identity"
        and (row := _load(raw))["local_id"] == mapping["paper_id"]
    }
    operations = []
    for name, raw in rows:
        if name != "research_file_applied":
            continue
        operation = _load(_load(raw)["operation"])
        canonical_operation(operation)
        if operation["action"] == "put" and (
            operation["payload"]["paper_id"] in portable
            and operation["payload"]["slot"] == mapping["slot"]
        ):
            operations.append(operation)
    if len(operations) != 1:
        raise ValueError("Recovered evidence has no unique applied deck owner")
    payload = operations[0]["payload"]
    data = _read_object(database.parent / "objects", payload["body"])
    if _descriptor(data) != {key: payload["body"][key] for key in ("sha256", "size")}:
        raise ValueError("Recovered deck body hash differs")
    body = _load(data)
    validate_body(body, payload)
    owned = next((row for row in payload["assets"] if row["id"] == body["evidence_asset"]), None)
    if (
        body["deck"]["deck_id"] != mapping["deck_id"]
        or body["deck"]["source_hash"] != mapping["original_source_hash"]
        or owned is None
        or owned["role"] != "evidence"
        or {key: owned[key] for key in ("sha256", "size")} != mapping["asset"]
    ):
        raise ValueError("Recovered evidence mapping differs from its retained deck provenance")


def read_detached_evidence(database, paper_id, slot):
    """Open exact evidence with unknown legacy input identity, for explicit review."""
    from paper_daily.presentations import MODES

    database = _path(database)
    if slot not in MODES:
        raise ValueError("Invalid recovered evidence slot")
    with closing(sqlite3.connect(database.as_uri() + "?mode=ro", uri=True)) as conn:
        if not conn.execute(
            "SELECT 1 FROM sqlite_master WHERE name='recovery_identity'"
        ).fetchone():
            raise ValueError("Select a detached recovery workspace")
    folder = database.parent / "presentations" / hashlib.sha256(paper_id.encode()).hexdigest()[:24]
    location = _path(folder / ("recovery-evidence-" + slot + ".json"))
    if location.stat().st_size > 8192:
        raise ValueError("Oversized recovered evidence mapping")
    mapping = _load(location.read_bytes())
    validate_evidence_mapping(mapping)
    if (mapping["paper_id"], mapping["slot"]) != (paper_id, slot):
        raise ValueError("Recovered evidence owner mismatch")
    _verify_evidence_owner(database, mapping)
    descriptor = mapping["asset"]
    path = _path(folder / "recovered-evidence" / (descriptor["sha256"] + ".json"))
    if path.stat().st_size != descriptor["size"]:
        raise ValueError("Recovered evidence size differs")
    data = path.read_bytes()
    if _descriptor(data) != descriptor:
        raise ValueError("Recovered evidence hash differs")
    evidence = _load(data)
    if (
        not isinstance(evidence, dict)
        or set(evidence) != {"version", "sources", "coverage", "source_hash"}
        or evidence["source_hash"] != mapping["original_source_hash"]
    ):
        raise ValueError("Recovered evidence provenance differs")
    return {
        "bytes": data,
        "evidence": evidence,
        "mapping": mapping,
        "historical_input_digest_known": False,
        "capabilities": {"read": True, "export": True, "publish": False, "retry": False},
    }


def export_detached_evidence(database, paper_id, slot, destination):
    retained = read_detached_evidence(database, paper_id, slot)
    destination = _path(destination)
    with destination.open("xb") as stream:
        stream.write(retained["bytes"])
    return destination
