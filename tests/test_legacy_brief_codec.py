"""Closed Markdown/event ownership contract, independent from deck/PDF bounds."""

import copy

import pytest

from paper_daily import legacy_briefs
from paper_daily.sync_files import canonical_json, descriptor, file_id, validate_closure

PAPER = "11111111-1111-4111-8111-111111111111"
EVENT = "22222222-2222-4222-8222-222222222222"
OTHER = "33333333-3333-4333-8333-333333333333"
MARKDOWN = b"# Exact legacy brief\n\n<script>never executed</script>\n"


def codec():
    return legacy_briefs.encode(
        PAPER, EVENT, "fixture-event-incarnation", MARKDOWN, legacy_day="2026-10-30"
    )


def test_exact_bytes_event_incarnation_date_and_feature_identity_are_closed():
    payload, blobs = codec()
    body = validate_closure(payload, lambda item: blobs[item["sha256"]])
    assert body == dict(
        version=1,
        paper_id=PAPER,
        event_id=EVENT,
        event_incarnation="fixture-event-incarnation",
        legacy_day="2026-10-30",
    )
    assert blobs[payload["assets"][0]["sha256"]] == MARKDOWN
    assert legacy_briefs.validate_markdown(MARKDOWN).startswith("# Exact legacy brief")
    assert legacy_briefs.filename(body) == "2026-10-30-brief.md"
    assert file_id(PAPER, "legacy_brief", EVENT) != file_id(PAPER, "deck", "guide")
    assert payload["source_document_hash"] is None
    assert payload["input_versions"]["complete"] is False
    with pytest.raises(ValueError):
        file_id(PAPER, "deck", EVENT)


@pytest.mark.parametrize(
    "change",
    [
        "version_bool",
        "extra_asset",
        "role",
        "slot",
        "pdf_source",
        "old_job",
        "body_paper",
        "body_event",
        "incarnation",
        "day",
        "extra_body",
        "binary",
    ],
)
def test_unknown_or_mismatched_brief_ownership_is_not_accepted(change):
    payload, blobs = codec()
    payload, blobs = copy.deepcopy(payload), dict(blobs)
    body = validate_closure(payload, lambda item: blobs[item["sha256"]])
    if change == "version_bool":
        payload["format_version"] = True
    elif change == "extra_asset":
        payload["assets"].append(dict(payload["assets"][0], id="extra"))
    elif change == "role":
        payload["assets"][0]["role"] = "execute"
    elif change == "slot":
        payload["slot"] = OTHER
    elif change == "pdf_source":
        payload["source_document_hash"] = "a" * 64
    elif change == "old_job":
        payload["input_versions"]["entities"] = [{"grant": "old-job-authority"}]
    elif change == "binary":
        data = b"\x00binary"
        payload["assets"][0].update(descriptor(data, "text/markdown"))
        blobs[payload["assets"][0]["sha256"]] = data
    else:
        if change == "body_paper":
            body["paper_id"] = OTHER
        elif change == "body_event":
            body["event_id"] = OTHER
        elif change == "incarnation":
            body["event_incarnation"] = False
        elif change == "day":
            body["legacy_day"] = "../../private"
        else:
            body["execute"] = "never"
        data = canonical_json(body)
        payload["body"] = descriptor(data, "application/json")
        blobs[payload["body"]["sha256"]] = data
    with pytest.raises(ValueError):
        validate_closure(payload, lambda item: blobs[item["sha256"]])
