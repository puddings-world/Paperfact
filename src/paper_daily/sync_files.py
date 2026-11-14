"""Closed immutable research-file manifests. No network, configuration or paths."""

from __future__ import annotations

import hashlib
import json
import re
from copy import deepcopy
from uuid import NAMESPACE_URL, UUID, uuid5

MAX_BODY = 8 * 1024**2
MAX_ASSETS = 64 * 1024**2
KINDS = {
    "paper",
    "list",
    "membership",
    "note",
    "reading_state",
    "paper_document",
    "research_content",
    "research_file",
    "list_order",
    "workspace_list_order",
}


def identifier(value):
    from paper_daily.sync_journal import _identifier

    _identifier(value)


def uuid(value):
    if not isinstance(value, str) or str(UUID(value)) != value:
        raise ValueError("Expected a canonical portable UUID")


def digest(value, *, nullable=False):
    if value is None and nullable:
        return
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value):
        raise ValueError("Expected a lowercase SHA256 digest")


def closed(value, fields):
    if not isinstance(value, dict) or set(value) != set(fields):
        raise ValueError("Unexpected or missing research-file fields")


def text(value, maximum, *, empty=False):
    if (
        not isinstance(value, str)
        or len(value.encode("utf-8")) > maximum
        or (not empty and not value.strip())
    ):
        raise ValueError("Invalid bounded artifact text")


def canonical_json(value):
    def walk(item, depth=0):
        if depth > 32:
            raise ValueError("Research JSON nesting exceeds 32 levels")
        if isinstance(item, dict):
            if any(not isinstance(k, str) for k in item):
                raise ValueError("JSON object keys must be strings")
            for child in item.values():
                walk(child, depth + 1)
        elif isinstance(item, list):
            for child in item:
                walk(child, depth + 1)

    walk(value)
    return json.dumps(
        value, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def read_json(data):
    if not isinstance(data, bytes) or len(data) > MAX_BODY:
        raise ValueError("Artifact JSON exceeds its byte bound")

    def pairs(rows):
        result = {}
        for key, value in rows:
            if key in result:
                raise ValueError("Duplicate JSON key")
            result[key] = value
        return result

    def invalid(_value):
        raise ValueError("Non-finite JSON value")

    try:
        value = json.loads(data.decode("utf-8"), object_pairs_hook=pairs, parse_constant=invalid)
        encoded = canonical_json(value)
    except (RecursionError, UnicodeError) as exc:
        raise ValueError("Invalid bounded artifact JSON") from exc
    if encoded != data:
        raise ValueError("Artifact JSON must use its canonical encoding")
    return value


def file_id(paper_id, feature, slot):
    uuid(paper_id)
    if feature == "original_source":
        digest(slot)
    elif feature == "legacy_brief":
        uuid(slot)
    elif feature != "deck" or slot not in ("notes", "guide"):
        raise ValueError("Unsupported research-file feature/slot")
    identity = json.dumps([paper_id, feature, slot], separators=(",", ":"))
    return str(uuid5(NAMESPACE_URL, "paperfact:research-file:" + identity))


def validate_input_versions(value):
    if not isinstance(value, dict):
        raise ValueError("Input versions must be an object")
    fields = {"schema_version", "complete", "entities", "documents", "inputs_sha256"}
    version = value.get("schema_version")
    if type(version) is not int or version not in (1, 2):
        raise ValueError("Unsupported input-version format; update the app/service")
    closed(value, fields | ({"workspace_id"} if version == 2 else set()))
    if type(value["complete"]) is not bool:
        raise ValueError("Input coverage must be explicit")
    if version == 2:
        identifier(value["workspace_id"])
    digest(value["inputs_sha256"], nullable=True)
    seen = set()
    for key, maximum in (("entities", 256), ("documents", 128)):
        if not isinstance(value[key], list) or len(value[key]) > maximum:
            raise ValueError("Too many input-version references")
        for row in value[key]:
            if key == "entities":
                closed(row, {"kind", "id", "incarnation", "revision", "depends_on"})
                if not isinstance(row["kind"], str) or row["kind"] not in KINDS:
                    raise ValueError("Unknown input entity kind")
                identifier(row["id"])
                if row["kind"] not in {"list", "note", "list_order", "workspace_list_order"}:
                    uuid(row["id"])
                if row["kind"] == "workspace_list_order" and row["id"] != "workspace-lists":
                    raise ValueError("Invalid workspace order identity")
                identity = (key, row["kind"], row["id"])
                if type(row["revision"]) is not int or row["revision"] < 0:
                    raise ValueError("Invalid observed revision")
                if row["depends_on"] is not None:
                    identifier(row["depends_on"])
            else:
                closed(
                    row, {"paper_id", "operation_id", "incarnation", "parent_incarnation", "sha256"}
                )
                uuid(row["paper_id"])
                identifier(row["operation_id"])
                identifier(row["parent_incarnation"])
                digest(row["sha256"])
                identity = (key, row["paper_id"])
            identifier(row["incarnation"])
            if identity in seen:
                raise ValueError("Duplicate input-version reference")
            seen.add(identity)
    if len(canonical_json(value)) > 64 * 1024:
        raise ValueError("Input-version block exceeds 64 KiB")


def scope_input_versions(value, workspace_id):
    """Stamp a caller-observed input scope; never rebase an already recorded one."""
    validate_input_versions(value)
    identifier(workspace_id)
    result = deepcopy(value)
    if result["schema_version"] == 1:
        result.update(schema_version=2, workspace_id=workspace_id)
    validate_input_versions(result)
    return result


def validate_payload(payload, *, entity_id=None, parents=None):
    closed(
        payload,
        {
            "paper_id",
            "feature",
            "slot",
            "format_version",
            "source_document_hash",
            "input_versions",
            "body",
            "assets",
        },
    )
    expected = file_id(payload["paper_id"], payload["feature"], payload["slot"])
    if entity_id is not None and expected != entity_id:
        raise ValueError("Artifact identity does not match feature/slot")
    if parents is not None and (
        len(parents) != 1
        or parents[0]["kind"] != "paper"
        or parents[0]["id"] != payload["paper_id"]
    ):
        raise ValueError("Artifact needs its exact paper parent")
    if type(payload["format_version"]) is not int or payload["format_version"] != 1:
        raise ValueError("Unsupported research-file format")
    digest(payload["source_document_hash"], nullable=True)
    validate_input_versions(payload["input_versions"])
    closed(payload["body"], {"sha256", "size", "media_type"})
    if payload["feature"] == "legacy_brief":
        from paper_daily.legacy_briefs import validate_manifest

        validate_manifest(payload)
        return
    if payload["feature"] == "original_source":
        from paper_daily.sync_source_files import validate_manifest

        validate_manifest(payload)
        return
    rows = payload["assets"]
    if not isinstance(rows, list) or len(rows) > 256:
        raise ValueError("Artifact supports at most 256 assets")
    ids, total = set(), 0
    hashes = {}
    for index, row in enumerate([payload["body"], *rows]):
        if index:
            closed(row, {"id", "role", "sha256", "size", "media_type"})
            text(row["id"], 250)
            if row["id"] in ids:
                raise ValueError("Duplicate logical asset ID")
            ids.add(row["id"])
            if row["role"] not in ("figure", "evidence", "source_text"):
                raise ValueError("Unsupported artifact asset role")
            media, limit = {
                "figure": ("image/png", 8_000_000),
                "evidence": ("application/json", MAX_BODY),
                "source_text": ("text/plain", MAX_BODY),
            }[row["role"]]
            total += row["size"] if type(row["size"]) is int else 0
        else:
            media, limit = "application/json", MAX_BODY
        digest(row["sha256"])
        if (
            type(row["size"]) is not int
            or not 0 < row["size"] <= limit
            or row["media_type"] != media
        ):
            raise ValueError("Invalid artifact size/media type")
        signature = (row["size"], row["media_type"])
        if row["sha256"] in hashes and hashes[row["sha256"]] != signature:
            raise ValueError("A blob hash has contradictory metadata")
        hashes[row["sha256"]] = signature
    if total > MAX_ASSETS:
        raise ValueError("Artifact assets exceed 64 MiB")


def referenced_blobs(operation):
    """Validated, deduplicated body/assets, suitable for backup and transfer."""
    from paper_daily.sync_journal import canonical_operation

    canonical_operation(operation)
    if operation["entity_type"] != "research_file":
        raise ValueError("Expected a research-file operation")
    if operation["action"] == "delete":
        return []
    payload = operation["payload"]
    found = {}
    for row in [payload["body"], *payload["assets"]]:
        found[row["sha256"]] = {key: row[key] for key in ("sha256", "size", "media_type")}
    return list(found.values())


def descriptor(data, media_type):
    return {"sha256": hashlib.sha256(data).hexdigest(), "size": len(data), "media_type": media_type}


def validate_closure(payload, read_blob):
    """read_blob receives {sha256,size,media_type}; never follows body paths/URLs."""
    validate_payload(payload)
    blobs = {}
    for row in [payload["body"], *payload["assets"]]:
        key = row["sha256"]
        if key not in blobs:
            data = read_blob({field: row[field] for field in ("sha256", "size", "media_type")})
            if (
                not isinstance(data, bytes)
                or len(data) != row["size"]
                or hashlib.sha256(data).hexdigest() != key
            ):
                raise ValueError("Artifact closure bytes do not match their manifest")
            blobs[key] = data
    if payload["feature"] == "legacy_brief":
        from paper_daily.legacy_briefs import validate_closure as validate_brief

        return validate_brief(payload, blobs)
    if payload["feature"] == "original_source":
        from paper_daily.sync_source_files import validate_source_closure

        return validate_source_closure(payload, blobs)
    from paper_daily.sync_deck_files import validate_deck_closure

    return validate_deck_closure(payload, blobs)
