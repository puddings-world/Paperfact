"""Captured remote claim intent; private observations are never transferable authority."""

from paper_daily.sync_files import closed

FIELDS = {"event", "resolved_by", "head", "state", "parents", "outstanding"}


def capture(client, conn, sequence, entity_id):
    state = client.conflict_observation_in(conn, sequence)
    operation = state["event"]["operation"]
    if (operation["entity_type"], operation["entity_id"]) != ("research_content", entity_id):
        raise ValueError(
            "Select this conflict's original receiver; preserve edits when retargeting"
        )
    if state["resolved_by"] is not None or state["outstanding"]:
        raise ValueError("Conflict changed or has pending edits; review its current state")
    return state


def validate(snapshot, owner):
    """Closed history validation only. Fresh owner/source checks remain mandatory."""
    from paper_daily.claim_draft_resume import _payload, _reference
    from paper_daily.enrollment_review_drafts import _remote
    from paper_daily.sync_client import validate_event

    expected = snapshot["expected"]
    value = expected["conflict"]
    closed(value, FIELDS)
    validate_event(value["event"], owner["binding"]["workspace_id"])
    origin, identity = _reference(snapshot["id"])
    operation = value["event"]["operation"]
    if (
        origin != "remote"
        or str(value["event"]["sequence"]) != identity
        or operation["entity_type"] != "research_content"
        or operation["entity_id"] != expected["observation"]["entity_id"]
        or operation["action"] != "put"
        or value["resolved_by"] is not None
        or value["outstanding"] is not False
        or _payload(operation["payload"]) != snapshot["retained"]
    ):
        raise ValueError("Claim draft differs from its captured unresolved conflict")
    head = value["head"]
    if head is not None:
        closed(head, {"revision", "operation"})
    if head is None or head["operation"] is None:
        current = None
    else:
        from paper_daily.enrollment_history import _value
        from paper_daily.sync_journal import canonical_operation

        canonical = _value(head["operation"])
        canonical_operation(canonical)
        current = canonical["payload"]
    if (_payload(current) if current is not None else None) != snapshot["original"]:
        raise ValueError("Claim draft differs from its captured canonical comparison")
    return _remote(
        dict(
            expected=value,
            scope=dict(kind="research_content", id=operation["entity_id"]),
            current=current,
            retained=operation["payload"],
            original=None,
            target=None,
            parent_token=None,
            parent_row=None,
        ),
        owner,
    )


def check(client, conn, snapshot):
    from paper_daily.claim_draft_resume import _reference

    origin, identity = _reference(snapshot["id"])
    if origin != "remote":
        return
    expected = snapshot["expected"]
    if expected["version"] != 2:
        raise ValueError("Reselect this legacy remote claim draft to capture its conflict intent")
    if client.conflict_observation_in(conn, int(identity)) != expected["conflict"]:
        raise ValueError("Displayed claim conflict changed; retain edits and review again")
