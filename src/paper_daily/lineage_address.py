"""Closed v2 lineage content addressing, including empty typed deletions."""

from paper_daily import lineage_sets
from paper_daily.claim_content import closed


def validate(operation):
    """Return whether the operation uses this one registered address domain."""
    address = operation.get("content_address")
    payload = operation.get("payload")
    is_lineage = (
        isinstance(payload, dict)
        and payload.get("feature") == "lineage"
        and operation.get("action") == "put"
    )
    if address is None:
        if is_lineage or "content_address" in operation:
            raise ValueError("Lineage operations require their closed content address")
        return False
    closed(address, {"feature", "key"})
    if (
        operation.get("entity_type") != "research_content"
        or address["feature"] != "lineage"
        or operation.get("action") not in {"put", "delete"}
    ):
        raise ValueError("Unsupported registered content address")
    lineage_sets.uuid(address["key"])
    parents = operation.get("parents")
    if not isinstance(parents, list) or not 1 <= len(parents) <= 4:
        raise ValueError("Lineage address requires its bounded paper corpus")
    seen = set()
    for parent in parents:
        closed(parent, {"kind", "id", "incarnation"})
        if parent["kind"] != "paper":
            raise ValueError("Lineage corpus parent must be a paper")
        lineage_sets.uuid(parent["id"])
        if parent["id"] in seen:
            raise ValueError("Lineage corpus parent identity is duplicated")
        seen.add(parent["id"])
    from paper_daily.sync_content import content_id

    scope = {"kind": "paper", "id": parents[0]["id"]}
    if operation.get("entity_id") != content_id(scope, "lineage", address["key"]):
        raise ValueError("Lineage address differs from its focal scope and corpus identity")
    if operation["action"] == "put":
        if not is_lineage or payload.get("scope") != scope or payload.get("key") != address["key"]:
            raise ValueError("Lineage content address differs from its payload")
        data = payload.get("data")
        if not isinstance(data, dict) or not isinstance(data.get("body_json"), dict):
            raise ValueError("Lineage payload requires a closed binding body")
        body = lineage_sets.validate(data["body_json"], portable=True)
        if body["corpus_id"] != address["key"] or [row["paper_id"] for row in body["bindings"]] != [
            p["id"] for p in parents
        ]:
            raise ValueError("Lineage address does not bind its exact ordered paper corpus")
    elif payload != {}:
        raise ValueError("Lineage deletion requires an empty payload")
    return True


def metadata(kind, identity, state):
    """Validate only this optional registered graph address; never infer unknown deletes."""
    fields = {"incarnation", "parents", "active", "structure_revision"}
    if (
        not isinstance(state, dict)
        or not fields <= set(state)
        or set(state) - fields - {"content_address"}
        or not isinstance(state["parents"], list)
        or type(state["active"]) is not bool
        or type(state["structure_revision"]) is not int
        or state["structure_revision"] < 0
    ):
        raise ValueError("Invalid retained research graph metadata")
    from paper_daily.sync_journal import ID

    if not isinstance(state["incarnation"], str) or not ID.fullmatch(state["incarnation"]):
        raise ValueError("Invalid retained graph incarnation")
    for parent in state["parents"]:
        closed(parent, {"kind", "id", "incarnation"})
        if parent["kind"] not in {"paper", "list", "membership"}:
            raise ValueError("Invalid retained graph parent kind")
        for field in ("id", "incarnation"):
            if not isinstance(parent[field], str) or not ID.fullmatch(parent[field]):
                raise ValueError("Invalid retained graph parent identity")
    if "content_address" not in state:
        return
    validate(
        {
            "entity_type": kind,
            "entity_id": identity,
            "action": "delete",
            "payload": {},
            "parents": state["parents"],
            "content_address": state["content_address"],
        }
    )


def check_known(kind, identity, state, operation):
    metadata(kind, identity, state)
    if state.get("content_address") is not None:
        validate(operation)
        old = {(p["kind"], p["id"]) for p in state["parents"]}
        new = {(p["kind"], p["id"]) for p in operation["parents"]}
        if old != new:
            raise ValueError("Known lineage content cannot move to different paper parents")
    if state.get("content_address") != operation.get("content_address"):
        raise ValueError("Known research content address cannot be stripped or changed")


def retained(kind, identity, state, operation=None):
    metadata(kind, identity, state)
    if operation is not None and ("content_address" in state or "content_address" in operation):
        check_known(kind, identity, state, operation)
        # Head receipt and graph metadata advance within one receive transaction;
        # only the immutable typed address/parent identity is shared at every step.
    return state
