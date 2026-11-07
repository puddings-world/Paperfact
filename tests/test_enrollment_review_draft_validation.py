"""Private saved drafts are bounded history, not SQL, file or application grants."""

import json
import sqlite3
from contextlib import closing
from pathlib import Path

import pytest
from test_enrollment_review_draft_journey import decision as decision
from test_enrollment_review_draft_journey import draft_variants as draft_variants
from test_enrollment_review_draft_journey import source as source
from test_research_review import remote as remote
from test_research_review import remote_graph as remote_graph

from paper_daily import enrollment_history
from paper_daily import research_generation as generation
from paper_daily import research_review_drafts as drafts
from paper_daily.research_review import ResearchReview

PROTOCOL = "research_review_drafts"


@pytest.mark.parametrize(
    "change",
    [
        "duplicate_owner",
        "duplicate_preview",
        "duplicate_expected",
        "nonfinite",
        "extra",
        "bool_revision",
        "bool_order",
        "foreign_parent",
        "unknown_parent",
        "sql_bool",
        "wrong_current",
        "unknown_original",
        "source_type",
        "oversized_body",
        "fingerprint",
    ],
)
def test_malformed_saved_draft_is_refused_even_with_recomputed_fingerprint(draft_variants, change):
    row = dict(draft_variants["drafts"][0])
    snapshot = json.loads(row["preview_json"])
    if change == "duplicate_owner":
        row["owner_json"] = row["owner_json"][:-1] + ',"binding":null}'
    elif change == "duplicate_preview":
        row["preview_json"] = row["preview_json"][:-1] + ',"editable":true}'
    elif change == "duplicate_expected":
        snapshot["expected"] = snapshot["expected"][:-1] + ',"owner_id":"paper"}'
    elif change == "nonfinite":
        row["owner_json"] = row["owner_json"].replace('"identity":[', '"identity":[NaN,')
    elif change == "extra":
        row["authority"] = "never execute"
    elif change == "bool_revision":
        row["revision"] = True
    elif change == "bool_order":
        row["save_order"] = True
    elif change == "foreign_parent":
        snapshot["parent_row"]["id"] = "another-paper"
    elif change == "unknown_parent":
        snapshot["parent_row"]["unvalidated"] = "never execute"
    elif change == "sql_bool":
        snapshot["parent_row"]["year"] = True
    elif change == "wrong_current":
        snapshot["current"]["paper_id"] = "another-paper"
    elif change == "unknown_original":
        snapshot["original"] = {"unknown": "not a SQL row"}
    elif change == "source_type":
        snapshot["source_hash"] = False
    elif change == "oversized_body":
        row["body"] = "x" * (drafts.MAX_BODY + 1)
    if change not in {"duplicate_owner", "duplicate_preview", "nonfinite"}:
        row["preview_json"] = json.dumps(snapshot)
    row["fingerprint"] = drafts._fingerprint(row) if change != "fingerprint" else "0" * 64
    before = draft_variants["database"].read_bytes()
    with pytest.raises(ValueError):
        enrollment_history.wrap(PROTOCOL, row)
    assert draft_variants["database"].read_bytes() == before


def test_draft_validation_preserves_original_strings_without_opening_the_observed_owner(
    draft_variants, monkeypatch
):
    row = dict(draft_variants["drafts"][0])
    row["owner_json"] = json.dumps(json.loads(row["owner_json"]), indent=2)
    row["fingerprint"] = drafts._fingerprint(row)
    connect = sqlite3.connect

    def trusted_schema_only(database, *args, **kwargs):
        if database != ":memory:":
            pytest.fail("Historical draft validation followed a database path")
        return connect(database, *args, **kwargs)

    def deny(*_args, **_kwargs):
        pytest.fail("Historical draft validation opened a file")

    monkeypatch.setattr(sqlite3, "connect", trusted_schema_only)
    monkeypatch.setattr(Path, "open", deny)
    wrapped = enrollment_history.wrap(PROTOCOL, row)
    assert enrollment_history.validate(wrapped) == (row, {draft_variants["source_hash"]})


def test_real_remote_conflict_draft_is_private_lossless_metadata(remote):
    _a, b, _service, _ta, _tb = remote
    review = ResearchReview(b.journal.path)
    try:
        item = next(row for row in review.page()["items"] if row["origin"] == "remote")
        preview = review.preview("remote", item["id"])
        review.save_draft(preview, "My remote conflict draft", "same-request")
    finally:
        review.close()
    with closing(generation._connect(b.journal.path)) as conn:
        row = dict(conn.execute("SELECT * FROM research_review_drafts").fetchone())
    wrapped = enrollment_history.wrap(PROTOCOL, row)
    assert enrollment_history.validate(wrapped) == (row, set())
    snapshot = json.loads(row["preview_json"])
    snapshot["expected"]["outstanding"] = 1
    row["preview_json"] = json.dumps(snapshot)
    row["fingerprint"] = drafts._fingerprint(row)
    with pytest.raises(ValueError, match="pending observation"):
        enrollment_history.wrap(PROTOCOL, row)


@pytest.mark.parametrize(
    "change",
    [
        "valid",
        "active_type",
        "unknown_state",
        "changed_parent",
        "parent_revision_type",
        "foreign_head",
        "duplicate_head",
        "wrong_current",
    ],
)
def test_real_v2_conflict_graph_is_closed_and_never_reinterpreted_as_authority(
    remote_graph, change
):
    _a, b, _service, _ta, _tb, _list = remote_graph
    review = ResearchReview(b.journal.path)
    try:
        item = next(row for row in review.page()["items"] if row["origin"] == "remote")
        view = review.preview("remote", item["id"])
        review.save_draft(view, "Saved survey review", "graph-draft")
    finally:
        review.close()
    with closing(generation._connect(b.journal.path)) as conn:
        row = dict(conn.execute("SELECT * FROM research_review_drafts").fetchone())
    if change == "valid":
        assert enrollment_history.validate(enrollment_history.wrap(PROTOCOL, row)) == (row, set())
        return
    snapshot = json.loads(row["preview_json"])
    expected = snapshot["expected"]
    if change == "active_type":
        expected["state"]["active"] = 1
    elif change == "unknown_state":
        expected["state"]["authority"] = "not a graph field"
    elif change == "changed_parent":
        expected["parents"][0]["ref"]["incarnation"] = "another-incarnation"
    elif change == "parent_revision_type":
        expected["parents"][0]["current"]["structure_revision"] = True
    elif change in {"foreign_head", "duplicate_head"}:
        if change == "foreign_head":
            operation = json.loads(expected["head"]["operation"])
            operation["workspace_id"] = "another-workspace"
            expected["head"]["operation"] = json.dumps(operation)
        else:
            original = expected["head"]["operation"]
            expected["head"]["operation"] = original[:-1] + ',"workspace_id":"workspace"}'
    elif change == "wrong_current":
        snapshot["current"]["data"]["body"] = "Not what was displayed"
    row["preview_json"] = json.dumps(snapshot)
    row["fingerprint"] = drafts._fingerprint(row)
    with pytest.raises(ValueError):
        enrollment_history.wrap(PROTOCOL, row)
