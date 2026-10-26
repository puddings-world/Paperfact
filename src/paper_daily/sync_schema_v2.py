"""Closed private v2 payloads for the first dependency-aware research graph."""

from __future__ import annotations

import json
from datetime import datetime
from urllib.parse import urlsplit
from uuid import NAMESPACE_URL, UUID, uuid5

from paper_daily.sync_documents import validate_manifest
from paper_daily.sync_journal import FIELDS, ID, MAX_BYTES
from paper_daily.sync_ordering import ORDER_KINDS, validate_payload

REQUIRED = FIELDS | {"incarnation", "parents", "structure_revision"}
OPTIONAL = {"resolution_of", "structure_depends_on"}
PAPER_FIELDS = {
    "title",
    "authors",
    "year",
    "venue",
    "abstract",
    "doi",
    "arxiv_id",
    "s2_id",
    "page_url",
    "pdf_url",
    "source",
}


def _identifier(value):
    if not isinstance(value, str) or not ID.fullmatch(value):
        raise ValueError("Invalid graph identifier")


def _uuid(value):
    _identifier(value)
    try:
        if str(UUID(value)) != value:
            raise ValueError("Paper identity must be a canonical UUID")
    except (ValueError, AttributeError) as exc:
        raise ValueError("Paper identity must be a canonical UUID") from exc


def _text(value, limit, *, nullable=False, nonempty=False):
    if value is None and nullable:
        return
    if not isinstance(value, str) or len(value) > limit or (nonempty and not value.strip()):
        raise ValueError("Invalid bounded research text")


def membership_id(list_id: str, paper_id: str) -> str:
    """Portable pair identity; paper aliases never silently change this key."""
    _identifier(list_id)
    _uuid(paper_id)
    pair = json.dumps([list_id, paper_id], separators=(",", ":"))
    return str(uuid5(NAMESPACE_URL, "paperfact:membership:" + pair))


def _paper(payload):
    if set(payload) != PAPER_FIELDS:
        raise ValueError("Unexpected or missing paper fields")
    _text(payload["title"], 2000, nonempty=True)
    authors = payload["authors"]
    if not isinstance(authors, list) or len(authors) > 200:
        raise ValueError("Invalid paper authors")
    for author in authors:
        _text(author, 300, nonempty=True)
    year = payload["year"]
    if year is not None and (type(year) is not int or not 0 <= year <= 2200):
        raise ValueError("Invalid paper year")
    for key, limit in {
        "venue": 120,
        "abstract": 128 * 1024,
        "doi": 512,
        "arxiv_id": 100,
        "s2_id": 200,
        "page_url": 4096,
        "pdf_url": 4096,
        "source": 120,
    }.items():
        _text(payload[key], limit, nullable=True)
    for key in ("page_url", "pdf_url"):
        if payload[key]:
            value = urlsplit(payload[key])
            if (
                value.scheme not in ("http", "https")
                or not value.hostname
                or value.username
                or value.password
                or any(c.isspace() for c in payload[key])
            ):
                raise ValueError("Paper URLs must be HTTP(S) without embedded credentials")


def canonical_operation(value: dict) -> str:
    if not isinstance(value, dict) or not REQUIRED <= set(value) <= REQUIRED | OPTIONAL:
        raise ValueError("Unexpected or missing version-2 operation fields")
    if type(value["version"]) is not int or value["version"] != 2:
        raise ValueError("Unsupported graph protocol version")
    for key in ("operation_id", "workspace_id", "device_id", "entity_id", "incarnation"):
        _identifier(value[key])
    for key in OPTIONAL:
        if key in value:
            _identifier(value[key])
            if value[key] == value["operation_id"]:
                raise ValueError("An operation cannot reference itself")
    if value["depends_on"] is not None:
        _identifier(value["depends_on"])
        if value["depends_on"] == value["operation_id"]:
            raise ValueError("An operation cannot depend on itself")
    for key in ("base_revision", "structure_revision"):
        if type(value[key]) is not int or value[key] < 0:
            raise ValueError("Invalid graph revision")
    kind, action, payload = value["entity_type"], value["action"], value["payload"]
    if kind not in (
        "list",
        "note",
        "paper",
        "membership",
        "reading_state",
        "list_order",
        "workspace_list_order",
        "paper_document",
        "research_content",
    ) or action not in (
        "put",
        "delete",
    ):
        raise ValueError("Unsupported graph operation")
    if not isinstance(payload, dict):
        raise ValueError("Payload must be an object")
    parents = value["parents"]
    if not isinstance(parents, list) or len(parents) > (3 if kind == "reading_state" else 2):
        raise ValueError("Invalid parent references")
    refs = {}
    for parent in parents:
        if not isinstance(parent, dict) or set(parent) != {"kind", "id", "incarnation"}:
            raise ValueError("Invalid parent reference")
        if parent["kind"] not in ("list", "paper", "membership") or parent["kind"] in refs:
            raise ValueError("Duplicate or unsupported parent kind")
        _identifier(parent["id"])
        _identifier(parent["incarnation"])
        if parent["kind"] in ("paper", "membership"):
            _uuid(parent["id"])
        refs[parent["kind"]] = parent
    expected = {
        "list": set(),
        "paper": set(),
        "note": {"paper"},
        "membership": {"list", "paper"},
        "reading_state": {"membership", "list", "paper"},
        "list_order": {"list"},
        "workspace_list_order": set(),
        "paper_document": {"paper"},
        "research_content": set(refs) if set(refs) in ({"paper"}, {"list"}) else {"invalid"},
    }[kind]
    if set(refs) != expected:
        raise ValueError("Research entity has incorrect parents")
    if kind == "research_content":
        _uuid(value["entity_id"])
    if kind == "paper":
        _uuid(value["entity_id"])
        if action == "delete":
            raise ValueError("Paper deletion requires a later retention contract")
    if kind in ("membership", "reading_state") and value["entity_id"] != membership_id(
        refs["list"]["id"], refs["paper"]["id"]
    ):
        raise ValueError("Membership identity does not match its parent pair")
    if kind == "reading_state" and refs["membership"]["id"] != value["entity_id"]:
        raise ValueError("Reading-state identity must match its membership parent")
    if kind == "list_order" and value["entity_id"] != refs["list"]["id"]:
        raise ValueError("Order identity must equal its list scope")
    if kind == "workspace_list_order" and value["entity_id"] != "workspace-lists":
        raise ValueError("Workspace order requires the fixed workspace-lists identity")
    if kind == "paper_document" and value["entity_id"] != refs["paper"]["id"]:
        raise ValueError("Document identity must match its paper parent")
    if action == "delete":
        if payload:
            raise ValueError("Delete must have an empty payload")
    elif kind == "research_content":
        from paper_daily.sync_content import validate_payload as validate_content

        validate_content(payload, entity_id=value["entity_id"], parents=parents)
    elif kind in ORDER_KINDS:
        validate_payload(value)
    elif kind == "paper":
        _paper(payload)
    elif kind == "paper_document":
        validate_manifest(payload, paper_id=refs["paper"]["id"])
    elif kind == "list":
        if set(payload) != {"name", "note"}:
            raise ValueError("List payload requires name and note only")
        _text(payload["name"], 200, nonempty=True)
        _text(payload["note"], 128 * 1024)
    elif kind == "note":
        if payload.get("paper_id") != refs["paper"]["id"]:
            raise ValueError("Text note payload must match its paper parent")
        if set(payload) == {"paper_id", "body"}:
            _text(payload["body"], 200 * 1024)
        else:
            from paper_daily.sync_content import validate_rich_note

            validate_rich_note(payload)
    elif kind == "reading_state":
        if set(payload) != {"list_id", "paper_id", "state", "delivered_at", "read_at"}:
            raise ValueError("Unexpected or missing reading-state fields")
        if payload["list_id"] != refs["list"]["id"] or payload["paper_id"] != refs["paper"]["id"]:
            raise ValueError("Reading-state payload does not match its parents")
        if payload["state"] not in ("pending", "delivered", "read", "skipped", "deferred"):
            raise ValueError("Invalid reading state")
        for key in ("delivered_at", "read_at"):
            _text(payload[key], 64, nullable=True)
            if payload[key] is not None:
                try:
                    stamp = datetime.fromisoformat(payload[key])
                    if stamp.tzinfo is None:
                        raise ValueError("Missing timestamp timezone")
                except ValueError as exc:
                    raise ValueError("Reading timestamps must be ISO with timezone") from exc
    else:
        if set(payload) != {"list_id", "paper_id", "citation", "added_at"}:
            raise ValueError("Unexpected or missing membership fields")
        if payload["list_id"] != refs["list"]["id"] or payload["paper_id"] != refs["paper"]["id"]:
            raise ValueError("Membership payload does not match its parents")
        _text(payload["citation"], 4000, nullable=True)
        _text(payload["added_at"], 64, nonempty=True)
        try:
            stamp = datetime.fromisoformat(payload["added_at"])
            if stamp.tzinfo is None:
                raise ValueError("Membership added_at requires a timezone")
        except ValueError as exc:
            raise ValueError("Membership added_at must be an ISO timestamp with timezone") from exc
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    if len(encoded.encode("utf-8")) > MAX_BYTES:
        raise ValueError("Sync operation exceeds 256 KiB")
    return encoded
