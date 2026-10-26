"""Pure observed-set CAS for private v2 workspace/list ordering.

Graph values are detached lifecycle metadata keyed by (kind, id). Authority calls
use accepted state; builders may use their own optimistic state. These functions
do not read receipts, mutate graph values, or replace graph lifecycle validation.
"""

from __future__ import annotations

import hashlib
import json
import re
from uuid import UUID

from paper_daily.sync_journal import ID

ORDER_KINDS = frozenset({"list_order", "workspace_list_order"})
MAX_ITEMS = 2000


def scope(operation):
    """Derive the closed digest scope from a validated operation or scope stub."""
    kind = operation["entity_type"]
    if kind == "list_order":
        parents = operation["parents"]
        if len(parents) != 1 or parents[0]["kind"] != "list":
            raise ValueError("List ordering requires its exact list scope")
        parent = parents[0]
        if operation["entity_id"] != parent["id"]:
            raise ValueError("Order identity must equal its list scope")
        incarnation = parent["incarnation"]
    elif kind == "workspace_list_order":
        if operation["entity_id"] != "workspace-lists" or operation["parents"]:
            raise ValueError("Invalid workspace ordering scope")
        incarnation = None
    else:
        raise ValueError("Unsupported ordering kind")
    return {"kind": kind, "id": operation["entity_id"], "incarnation": incarnation}


def _items(items, *, membership=False):
    if not isinstance(items, list) or len(items) > MAX_ITEMS:
        raise ValueError("Order items must be a list of at most 2000 entries")
    seen = set()
    for item in items:
        if not isinstance(item, dict) or set(item) != {"id", "incarnation"}:
            raise ValueError("Order items require id and incarnation only")
        for value in item.values():
            if not isinstance(value, str) or not ID.fullmatch(value):
                raise ValueError("Invalid order item identifier")
        if item["id"] in seen:
            raise ValueError("Order items cannot contain duplicate identities")
        seen.add(item["id"])
        if membership:
            try:
                if str(UUID(item["id"])) != item["id"]:
                    raise ValueError("Noncanonical UUID")
            except ValueError as exc:
                raise ValueError("List order items must be canonical membership UUIDs") from exc


def validate_payload(operation):
    """Validate intrinsic payload shape independently of the current graph set."""
    found_scope = scope(operation)
    payload = operation["payload"]
    expected = {"items", "observed_set"}
    if found_scope["kind"] == "list_order":
        expected.add("list_id")
    if set(payload) != expected:
        raise ValueError("Unexpected or missing ordering fields")
    if "list_id" in expected and payload["list_id"] != found_scope["id"]:
        raise ValueError("Ordering payload must match its list scope")
    _items(payload["items"], membership=found_scope["kind"] == "list_order")
    digest = payload["observed_set"]
    if not isinstance(digest, str) or re.fullmatch(r"[0-9a-f]{64}", digest) is None:
        raise ValueError("Observed set must be a lowercase SHA256 digest")


def canonical_set_bytes(operation, items):
    """Stable cross-language hash input; item order intentionally has no meaning."""
    found_scope = scope(operation)
    _items(items, membership=found_scope["kind"] == "list_order")
    document = {
        "domain": "paperfact.sync.ordering",
        "version": 1,
        "workspace_id": operation["workspace_id"],
        "scope": found_scope,
        "items": sorted((dict(item) for item in items), key=lambda item: item["id"]),
    }
    return json.dumps(document, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )


def observed_set(operation, items):
    return hashlib.sha256(canonical_set_bytes(operation, items)).hexdigest()


def active_items(operation, graph):
    """Return the exact effective-active set in this workspace-scoped graph."""
    found_scope = scope(operation)
    items = []
    wanted = "list" if found_scope["kind"] == "workspace_list_order" else "membership"
    for (kind, identity), entity in graph.items():
        if kind != wanted or not entity["active"]:
            continue
        if wanted == "membership":
            refs = {parent["kind"]: parent for parent in entity["parents"]}
            parent = refs.get("list")
            if parent is None or (parent["id"], parent["incarnation"]) != (
                found_scope["id"],
                found_scope["incarnation"],
            ):
                continue
            if any(
                (found := graph.get((ref["kind"], ref["id"]))) is None
                or not found["active"]
                or found["incarnation"] != ref["incarnation"]
                for ref in entity["parents"]
            ):
                continue
        items.append({"id": identity, "incarnation": entity["incarnation"]})
    return sorted(items, key=lambda item: item["id"])


def validate_order(operation, graph):
    """False preserves a set conflict; matching set requires a full permutation.

    Normal graph preconditions remain mandatory, including for an empty deleted
    list. Deletion resets an order without asserting the current item set.
    """
    if operation["entity_type"] not in ORDER_KINDS or operation["action"] == "delete":
        return True
    validate_payload(operation)
    actual = active_items(operation, graph)
    if observed_set(operation, actual) != operation["payload"]["observed_set"]:
        return False
    supplied = sorted(operation["payload"]["items"], key=lambda item: item["id"])
    if supplied != actual:
        raise ValueError("Order must be a complete permutation of the observed active set")
    return True
