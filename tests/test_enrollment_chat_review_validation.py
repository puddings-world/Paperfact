"""Bounded, no-I/O history parsing and failure-safe reviewed-QA enrollment."""

import copy
import hashlib
import json
import sqlite3
from contextlib import closing
from pathlib import Path
from uuid import uuid4

import pytest
from test_chat_resume import candidate
from test_enrollment_chat_review_history import prepare
from test_enrollment_chat_review_history import reviewed as reviewed
from test_enrollment_chat_review_history import source as source
from test_sync_capture import bound as bound
from test_sync_capture import seed

from paper_daily import enrollment_history
from paper_daily import research_chat_review as review
from paper_daily import research_generation as generation
from paper_daily.workspace_enrollment import EnrollmentService
from paper_daily.workspace_service import Cancelled, SnapshotChanged, Ticket

PROTOCOL = "research_chat_review_receipts"


def repack(row, snapshot):
    record = snapshot["record"]
    record["candidate_id"] = hashlib.sha256(
        (record["context_json"] + record["answer_json"]).encode()
    ).hexdigest()
    row["target_json"] = review.encode(snapshot)
    row["record_json"] = review.encode(snapshot["record"])
    row["fingerprint"] = review._hash(
        {"preview": snapshot, "body": json.loads(row["answer_json"])["body"]}
    )


def duplicate(raw, key):
    value = json.loads(raw)[key]
    # Add the exact same value under a duplicate key. Last-key-wins decoding
    # would hide this while preserving the runtime fingerprint.
    return "{" + json.dumps(key) + ":" + json.dumps(value) + "," + raw[1:]


def test_review_archive_parser_uses_no_database_or_observed_file_paths(reviewed, monkeypatch):
    row = reviewed["receipt"]
    expected = reviewed["turns"][0]["source_hash"]

    def deny(*_args, **_kwargs):
        pytest.fail("Archive validation followed an observed database or file path")

    with monkeypatch.context() as patch:
        patch.setattr(sqlite3, "connect", deny)
        patch.setattr(Path, "open", deny)
        wrapped = enrollment_history.wrap(PROTOCOL, row)
        record, sources = enrollment_history.validate(wrapped)
    assert record == row and expected in sources


@pytest.mark.parametrize(
    "change",
    [
        "duplicate_target",
        "duplicate_record",
        "duplicate_context",
        "bool_rowid",
        "bool_year",
        "title_object",
        "unknown_field",
        "wrong_result",
        "bad_fingerprint",
        "bad_history_owner",
    ],
)
def test_review_archive_rejects_malformed_nested_inputs_even_with_recomputed_fingerprint(
    reviewed,
    change,
):
    row = copy.deepcopy(reviewed["receipt"])
    snapshot = json.loads(row["target_json"])
    if change == "duplicate_context":
        snapshot["record"]["context_json"] = duplicate(
            snapshot["record"]["context_json"], "version"
        )
    elif change == "bool_rowid":
        snapshot["target"]["parent"]["row"]["_rowid"] = True
    elif change == "bool_year":
        snapshot["target"]["parent"]["row"]["year"] = True
    elif change == "title_object":
        snapshot["target"]["parent"]["row"]["title"] = {"unexpected": "object"}
    elif change == "bad_history_owner":
        snapshot["target"]["history"][0]["paper_id"] = "different-paper"
    repack(row, snapshot)
    if change == "duplicate_target":
        row["target_json"] = duplicate(row["target_json"], "version")
    elif change == "duplicate_record":
        row["record_json"] = duplicate(row["record_json"], "request_id")
    elif change == "unknown_field":
        row["unexpected"] = "future runtime authority"
    elif change == "wrong_result":
        result = json.loads(row["result_json"])
        result["answer_key"] = str(uuid4())
        row["result_json"] = review.encode(result)
    elif change == "bad_fingerprint":
        row["fingerprint"] = "0" * 64
    if change in {
        "duplicate_target",
        "duplicate_record",
        "duplicate_context",
        "bool_rowid",
        "bool_year",
        "title_object",
    }:
        # These pass the narrower runtime receipt shape. Enrollment needs the
        # stricter nested archive contract as well as a matching fingerprint.
        review.validate_receipt(row)
    with pytest.raises(ValueError):
        enrollment_history.wrap(PROTOCOL, row)


def test_bounded_review_json_and_changed_archive_body_are_refused(reviewed, monkeypatch):
    row = reviewed["receipt"]
    wrapped = enrollment_history.wrap(PROTOCOL, row)
    altered = dict(wrapped, body_json=wrapped["body_json"].replace("human-reviewed", "altered"))
    with pytest.raises(ValueError):
        enrollment_history.validate(altered)
    monkeypatch.setattr(enrollment_history, "MAX_ROW", len(row["target_json"].encode()) - 1)
    with pytest.raises(ValueError, match="bound"):
        enrollment_history.wrap(PROTOCOL, row)


@pytest.mark.parametrize("change", ["cancel", "receipt_changed", "publication_failure"])
def test_reviewed_enrollment_cancel_change_and_failure_leave_no_partial_outputs(
    reviewed,
    tmp_path,
    monkeypatch,
    change,
):
    value = reviewed
    before = value["database"].read_bytes()
    ticket = Ticket()
    changed = False

    def progress(message):
        nonlocal changed
        if not message.startswith("Coverage checked"):
            return
        if change == "cancel":
            ticket.cancel()
        elif change == "receipt_changed" and not changed:
            changed = True
            with closing(generation._connect(value["database"])) as conn, conn:
                conn.execute("UPDATE research_chat_review_receipts SET fingerprint=?", ("0" * 64,))

    if change == "publication_failure":
        from paper_daily import workspace_enrollment

        original_publish = workspace_enrollment.publish_directory

        def fail(*_args, **_kwargs):
            raise OSError("simulated publication failure")

        monkeypatch.setattr(workspace_enrollment, "publish_directory", fail)
    error = (
        Cancelled
        if change == "cancel"
        else (SnapshotChanged, ValueError)
        if change == "receipt_changed"
        else OSError
    )
    with pytest.raises(error):
        EnrollmentService(value["database"]).prepare(
            tmp_path / "candidate",
            backup_output=tmp_path / "backup.zip",
            request_id=str(uuid4()),
            pdfs={"paper": value["primary"]},
            ticket=ticket,
            progress=progress,
        )
    assert not (tmp_path / "candidate").exists() and not (tmp_path / "backup.zip").exists()
    if change != "receipt_changed":
        assert value["database"].read_bytes() == before
    if change == "publication_failure":
        monkeypatch.setattr(workspace_enrollment, "publish_directory", original_publish)
        # A failed publication remains explicitly retryable with full history.
        result = prepare(value, tmp_path)
        assert Path(result["database"]).exists()


@pytest.mark.parametrize(
    "change", ["valid", "foreign_parent", "foreign_turn", "desired_valid", "desired_workspace"]
)
def test_enrolled_review_history_observations_remain_bound_to_their_declared_targets(bound, change):
    from paper_daily import store
    from paper_daily.research_chat_review import ChatReview

    seed()
    record = candidate()
    service = ChatReview(store.DB_PATH)
    preview = service.preview(record)
    service.apply(preview, request_id=str(uuid4()))
    service.close()
    with closing(generation._connect(store.DB_PATH)) as conn:
        row = dict(conn.execute("SELECT * FROM research_chat_review_receipts").fetchone())
    snapshot = json.loads(row["target_json"])
    target = snapshot["target"]
    if change == "foreign_parent":
        target["parent"]["observation"]["entity_id"] = str(uuid4())
    elif change == "foreign_turn":
        target["user_observation"]["entity_id"] = str(uuid4())
    elif change.startswith("desired"):
        desired = dict(
            workspace_id=snapshot["binding"]["workspace_id"],
            paper_id=target["parent"]["portable"],
            operation_id=str(uuid4()),
            incarnation=str(uuid4()),
            parent_incarnation=target["parent"]["observation"]["incarnation"],
            sha256="f" * 64,
            size=100,
            media_type="application/pdf",
        )
        if change == "desired_workspace":
            desired["workspace_id"] = "another-workspace"
        target["desired"] = [review.encode(desired), 1]
    repack(row, snapshot)
    review.validate_receipt(row)
    if change in {"valid", "desired_valid"}:
        wrapped = enrollment_history.wrap(PROTOCOL, row)
        retained, hashes = enrollment_history.validate(wrapped)
        assert retained == row
        assert hashes == ({"f" * 64} if change == "desired_valid" else set())
    else:
        with pytest.raises(ValueError):
            enrollment_history.wrap(PROTOCOL, row)
