"""Pure lifecycle/parent rules shared by the reference authority and event receiver."""

from __future__ import annotations

from copy import deepcopy


def _parent_map(parents):
    return {(parent["kind"], parent["id"]): parent["incarnation"] for parent in parents}


def _parents_active(get_entity, parents):
    for parent in parents:
        found = get_entity(parent["kind"], parent["id"])
        if found is None or not found["active"] or found["incarnation"] != parent["incarnation"]:
            return False
    return True


def _touches_structure(operation, kind, identity, incarnation):
    if operation["version"] != 2:
        return False
    if (operation["entity_type"], operation["entity_id"]) == (kind, identity):
        return operation["incarnation"] == incarnation and (
            operation["action"] == "delete" or operation["incarnation"] == operation["operation_id"]
        )
    return _parent_map(operation["parents"]).get((kind, identity)) == incarnation


def _retirement(get_receipt, operation, current):
    if (
        operation["action"] != "delete"
        or not operation.get("resolution_of")
        or not operation["parents"]
    ):
        return False
    target = get_receipt(operation["resolution_of"])
    if target is None:
        raise ValueError("Resolution refers to an unknown conflict")
    source = target["operation"]
    if (
        target["outcome"] != "conflict"
        or source["version"] != 2
        or (source["workspace_id"], source["entity_type"], source["entity_id"])
        != (operation["workspace_id"], operation["entity_type"], operation["entity_id"])
    ):
        raise ValueError("Resolution must reference a conflict for this graph entity")
    reference = current if current is not None else source
    return operation["incarnation"] == reference["incarnation"] and _parent_map(
        operation["parents"]
    ) == _parent_map(reference["parents"])


def check_preconditions(get_entity, get_receipt, operation) -> bool:
    """Return False for preserved graph conflict; raise for missing/invalid dependencies.

    Callers first validate the closed operation schema and separately check the
    entity's base revision/depends_on. Accessors are scoped to one workspace.
    """
    kind, identity = operation["entity_type"], operation["entity_id"]
    current = get_entity(kind, identity)
    if operation["version"] == 1:
        if current is not None or (
            kind == "note"
            and operation["action"] == "put"
            and get_entity("paper", operation["payload"]["paper_id"]) is not None
        ):
            raise ValueError(
                "Version 1 cannot mutate an enrolled graph entity or bypass its parents"
            )
        return True

    if (
        kind == "membership"
        and operation["action"] == "put"
        and current is not None
        and current["incarnation"] == operation["incarnation"]
    ):
        origin = get_receipt(current["incarnation"])
        if origin is None:
            raise ValueError("Missing membership creation receipt")
        source = origin["operation"]
        if (
            source["version"] != 2
            or source["action"] != "put"
            or (source["entity_type"], source["entity_id"], source["incarnation"])
            != (kind, identity, current["incarnation"])
        ):
            raise ValueError("Invalid membership creation receipt")
        if source["payload"]["added_at"] != operation["payload"]["added_at"]:
            raise ValueError("Membership added_at is immutable within its incarnation")
    retirement = _retirement(get_receipt, operation, current)
    parents_match = True
    for parent in operation["parents"]:
        found = get_entity(parent["kind"], parent["id"])
        if found is None:
            raise ValueError("Missing graph parent; synchronize the parent first")
        if (
            not found["active"] or found["incarnation"] != parent["incarnation"]
        ) and not retirement:
            parents_match = False
    if not parents_match:
        return False
    incarnation = operation["incarnation"]
    if current is None:
        if incarnation != operation["operation_id"] and not retirement:
            return False
    else:
        if set(_parent_map(current["parents"])) != set(_parent_map(operation["parents"])):
            raise ValueError("A research entity cannot move to different parents")
        effective_active = current["active"] and _parents_active(get_entity, current["parents"])
        if operation["action"] == "put" and not effective_active:
            if incarnation == current["incarnation"] or incarnation != operation["operation_id"]:
                return False
        elif incarnation != current["incarnation"] or _parent_map(
            current["parents"]
        ) != _parent_map(operation["parents"]):
            return False
    if operation["action"] != "delete":
        return True
    structural = current["structure_revision"] if current else 0
    dependency = operation.get("structure_depends_on")
    if dependency is None:
        return operation["structure_revision"] == structural
    receipt = get_receipt(dependency)
    if receipt is None:
        raise ValueError("Missing structural predecessor")
    source = receipt["operation"]
    if (source["workspace_id"], source["device_id"]) != (
        operation["workspace_id"],
        operation["device_id"],
    ) or not _touches_structure(source, kind, identity, incarnation):
        raise ValueError("Unrelated structural predecessor")
    return receipt["outcome"] == "accepted" and receipt["sequence"] == structural


def apply_accepted(get_entity, set_entity, operation, sequence):
    """Advance graph metadata only for an already validated accepted event.

    get_entity(kind,id) returns a detached metadata dict or None;
    set_entity(kind,id,metadata) persists it inside the caller's transaction.
    No operation or retained metadata object is mutated in place.
    """
    if operation["version"] == 1:
        return
    if type(sequence) is not int or sequence <= 0:
        raise ValueError("Invalid graph event sequence")
    kind, identity = operation["entity_type"], operation["entity_id"]
    current = get_entity(kind, identity)
    lifecycle = (
        current is None
        or current["incarnation"] != operation["incarnation"]
        or operation["action"] == "delete"
    )
    state = {
        "incarnation": operation["incarnation"],
        "structure_revision": sequence if lifecycle else current["structure_revision"],
        "active": operation["action"] == "put",
        "parents": deepcopy(operation["parents"]),
    }
    parents = []
    for ref in operation["parents"]:
        parent = get_entity(ref["kind"], ref["id"])
        if parent is None:
            raise ValueError("Accepted event has a missing graph parent")
        if not parent["active"] or parent["incarnation"] != ref["incarnation"]:
            if operation["action"] == "delete" and operation.get("resolution_of"):
                continue
            raise ValueError("Accepted event has an unavailable graph parent")
        parent = deepcopy(parent)
        parent["structure_revision"] = sequence
        parents.append((ref["kind"], ref["id"], parent))
    set_entity(kind, identity, state)
    for parent_kind, parent_id, parent in parents:
        set_entity(parent_kind, parent_id, parent)
