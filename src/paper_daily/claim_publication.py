"""Explicit claim restoration, scoped to one observed deletion and original source."""

from dataclasses import replace

from paper_daily import sync_capture, sync_content


class ClaimsDeleted(ValueError):
    pass


def deleted(context):
    data = context.data
    observed = data["observation"]
    return bool(
        (context.target is None and (context.inputs or {}).get("claims_known", False))
        or (observed and observed["incarnation"] is not None and not observed["active"])
    )


def seal(context, requested):
    from paper_daily import research_generation as generation

    if type(requested) is not bool:
        raise ValueError("Claim restoration intent must be explicit")
    if not deleted(context):
        if requested:
            raise ValueError(
                "Claims changed since deletion; review current content before restoring"
            )
        return context
    if not requested:
        raise ClaimsDeleted("Saved claims were deleted; explicit restoration is required")
    data = context.data
    if context.target is not None:
        raise ValueError("Claim deletion needs source-aware review before restoration")
    observed = data["observation"]
    if data["binding"] is not None and (
        not observed or observed["incarnation"] is None or observed["active"]
    ):
        raise ValueError("Claim restoration requires its exact observed synchronization tombstone")
    data["claim_restore"] = True
    return replace(context, _json=generation._context_json(data))


def validate(context):
    data = context.data
    if "claim_restore" in data:
        if data["claim_restore"] is not True or not deleted(context) or context.target is not None:
            raise ValueError("Invalid observed claim restoration")
        observed = data["observation"]
        if data["binding"] is not None and (
            not observed or observed["incarnation"] is None or observed["active"]
        ):
            raise ValueError("Claim restoration lacks its exact observed tombstone")
    elif deleted(context):
        raise ValueError("Claim publication cannot implicitly restore deleted content")


def apply_restore(conn, context, row):
    """Caller owns one transaction for new graph incarnation, SQL and receipt."""
    if not conn.in_transaction or not context.data.get("claim_restore"):
        raise ValueError("Claim restoration requires explicit observed transaction ownership")
    validate(context)
    client = conn._capture_client
    graph = client._optimistic_graph(conn)
    payload = sync_content.content_payload(conn, "paper_claim_sets", row)
    identity = sync_content.content_id(payload["scope"], "claims", "main")
    observed = context.data["observation"]
    prior = graph[0].get(("research_content", identity))
    if not prior or prior["active"] or prior["incarnation"] != observed["incarnation"]:
        raise ValueError("Observed deleted claim incarnation changed")
    with sync_capture.suppress_capture(conn):
        operation = client.new_graph_operation_in(
            conn, "research_content", identity, payload, restore=True
        )
        result = client.journal.apply_in(conn, operation, client.writer)
        if not result["applied"]:
            raise ValueError("Claim restoration was not applied atomically")
        client._overlay_optimistic(graph, operation)
    conn._capture_graph_cache = None
