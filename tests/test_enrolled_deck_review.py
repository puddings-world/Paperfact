"""Actual shared operations and receipts; no public UI/registry wiring is implied."""

import copy
import os
import sqlite3
from contextlib import closing

import pytest
from test_enrolled_deck_proposals import actual as actual
from test_enrolled_deck_proposals import case as case
from test_enrolled_deck_proposals import codec as codec
from test_enrolled_deck_proposals import native, prepare, save
from test_enrolled_deck_proposals import no_external as no_external
from test_enrolled_deck_proposals import original as original
from test_enrolled_deck_proposals import package as package
from test_enrolled_deck_proposals import scientific as scientific

from paper_daily import enrolled_deck_proposals as catalog
from paper_daily import enrolled_deck_review as helper
from paper_daily import presentations
from paper_daily.research_review import ResearchReview, digest, encode, validate_receipt
from paper_daily.sync_artifacts import applied_file, desired_file, verify_closure
from paper_daily.sync_capture import suppress_capture
from paper_daily.sync_files import file_id
from paper_daily.sync_source_files import input_versions


def begin(actual):
    identity = save(actual, prepare(actual))
    service = ResearchReview(actual["client"].journal.path)
    with closing(service._connect()) as conn:
        record = catalog.record(conn, identity)
    data = dict(
        origin="enrolled_deck",
        id=identity,
        record_hash=digest(record),
        **helper.prepare(service, record),
    )
    return service, data


def apply(service, data, request="enrolled-review", **kwargs):
    return helper.apply(
        service, data, digest(data), request, kwargs.get("body"), kwargs.get("confirm_target", True)
    )


def current(actual):
    with actual["client"].journal.transaction() as conn:
        return (
            desired_file(conn, file_id(actual["portable"], "deck", "guide")),
            applied_file(conn, file_id(actual["portable"], "deck", "guide")),
        )


def receipts(service):
    with closing(service._connect()) as conn:
        if not conn.execute(
            "SELECT 1 FROM sqlite_master WHERE name='research_review_receipts'"
        ).fetchone():
            return []
        return [dict(row) for row in conn.execute("SELECT * FROM research_review_receipts")]


def test_normal_explicit_apply_one_operation_receipt_and_replay_preserve_full_union(actual):
    prior_operation = current(actual)[0]
    prior_body = verify_closure(actual["store"], prior_operation)[1]["deck"]
    service, data = begin(actual)
    client = actual["client"]
    before = client.journal.pending()
    try:
        assert data["current"] == prior_body and data["original"] == prior_body
        assert data["retained"] == actual["expected"]["deck"]
        assert data["retained_evidence"] == actual["expected"]["evidence"]
        assert len(data["image_manifest"]) == 4 and len(data["original_manifest"]) == 1
        assert len(encode(data).encode()) < 8 * 1024**2
        with pytest.raises(ValueError, match="Confirm"):
            apply(service, data, confirm_target=False)
        with pytest.raises(ValueError, match="typed"):
            apply(service, data, body="not typed JSON")
        assert client.journal.pending() == before
        result = apply(service, data)
        assert result == {"decision": "applied", "operation_id": "enrolled-review"}
        assert len(client.journal.pending()) == len(before) + 1
        desired, active = current(actual)
        assert desired == active and active["operation_id"] == result["operation_id"]
        assert active["payload"]["input_versions"] == input_versions()
        assert active["payload"]["source_document_hash"] == actual["package"].original_a
        _proof, body, _blobs = verify_closure(actual["store"], active)
        assert body["deck"]["title"] == data["retained"]["title"]
        canonical = presentations.deck_from_dict(copy.deepcopy(data["retained"])).to_dict()
        assert body["deck"]["slides"] == canonical["slides"]
        supplied = data["retained"]["slides"][0]["elements"][2]
        installed = body["deck"]["slides"][0]["elements"][2]
        assert {key: installed[key] for key in supplied} == supplied
        assert {key: value for key, value in installed.items() if key not in supplied} == {
            "align": "left",
            "bold": False,
            "color": "#172238",
            "size": 26,
        }

        assert len(body["deck"]["figures"]) == 2  # Ordinary active wire keeps used figures.
        before_retry = client.journal.pending()
        for _ in range(10):
            assert apply(service, data) == result
        assert client.journal.pending() == before_retry
        saved = receipts(service)
        assert len(saved) == 1 and validate_receipt(saved[0])
        retained = catalog.read(
            client, actual["store"], data["id"], expected_native=native(client.journal.path)
        )
        assert retained.content == actual["expected"] and len(retained.content["image_bytes"]) == 4
    finally:
        service.close()


def test_receipt_failure_after_actual_activation_rolls_back_then_exact_retry(actual, monkeypatch):
    service, data = begin(actual)
    client = actual["client"]
    before = client.journal.pending()
    old = current(actual)
    original = service._receipt
    seen = []

    def fail(conn, *args):
        active = applied_file(conn, file_id(actual["portable"], "deck", "guide"))
        assert active and active["operation_id"] == "receipt-retry"
        seen.append(active)
        raise sqlite3.OperationalError("Synthetic receipt storage denial")

    monkeypatch.setattr(service, "_receipt", fail)
    try:
        with pytest.raises(sqlite3.OperationalError, match="receipt"):
            apply(service, data, "receipt-retry")
        assert len(seen) == 1 and current(actual) == old
        assert client.journal.pending() == before and receipts(service) == []
        monkeypatch.setattr(service, "_receipt", original)
        result = apply(service, data, "receipt-retry")
        assert result["operation_id"] == "receipt-retry"
        assert len(client.journal.pending()) == len(before) + 1
        assert len(receipts(service)) == 1
    finally:
        service.close()


@pytest.mark.parametrize(
    "change",
    ["paper", "inputs", "recreate", "close", "store-binding", "source", "database", "index"],
)
def test_changed_displayed_context_refuses_and_preserves_both_scientific_versions(actual, change):
    service, data = begin(actual)
    client = actual["client"]
    if change == "close":
        service.close()
    elif change in {"database", "index"}:
        path = (
            client.journal.path if change == "database" else actual["store"].root / "index.sqlite"
        )
        replacement = path.with_suffix(".review-replacement")
        with (
            closing(sqlite3.connect(path)) as source,
            closing(sqlite3.connect(replacement)) as target,
        ):
            source.backup(target)
        assert native(path) != native(replacement)
        os.replace(replacement, path)
    elif change == "store-binding":
        with closing(sqlite3.connect(actual["store"].root / "index.sqlite")) as conn, conn:
            conn.execute("UPDATE transfer_binding SET device='foreign'")
    elif change == "source":
        sha = actual["package"].original_a
        path = actual["store"].root / "objects" / sha
        data_a = path.read_bytes()
        path.write_bytes(data_a[:-1] + bytes([data_a[-1] ^ 1]))
    else:
        with client.journal.transaction() as conn, suppress_capture(conn):
            if change == "paper":
                conn.execute(
                    "UPDATE papers SET title='A later title' WHERE id=?", (actual["local"],)
                )
            elif change == "inputs":
                conn.execute(
                    "INSERT INTO notes(paper_id,body,created_at) VALUES(?,?,?)",
                    (actual["local"], "New input", "2026-11-01T00:00:00Z"),
                )
            else:
                # Controlled external repair, not supported graph deletion.
                row = conn.execute("SELECT * FROM papers WHERE id=?", (actual["local"],)).fetchone()
                conn.execute("DELETE FROM papers WHERE id=?", (actual["local"],))
                conn.execute("INSERT INTO papers VALUES(" + ",".join("?" for _ in row) + ")", row)
    before, active = client.journal.pending(), current(actual)
    try:
        with pytest.raises((ValueError, FileNotFoundError)):
            apply(service, data, "stale-context")
        assert client.journal.pending() == before and current(actual) == active
    finally:
        service.close()


def test_newer_active_base_rejects_old_preview_but_successful_replay_is_historical_read(actual):
    service, first = begin(actual)
    with closing(service._connect()) as conn:
        record = catalog.record(conn, first["id"])
    second = dict(
        origin="enrolled_deck",
        id=first["id"],
        record_hash=digest(record),
        **helper.prepare(service, record),
    )
    try:
        result = apply(service, first, "first-version")
        pending = actual["client"].journal.pending()
        with pytest.raises(ValueError, match="changed"):
            apply(service, second, "stale-second")
        assert apply(service, first, "first-version") == result
        assert actual["client"].journal.pending() == pending
        fresh = dict(
            origin="enrolled_deck",
            id=first["id"],
            record_hash=digest(record),
            **helper.prepare(service, record),
        )
        assert fresh["current"]["title"] == first["retained"]["title"]
        assert fresh["original"] == first["original"]
    finally:
        service.close()


@pytest.mark.parametrize("fault", ["close", "paper"])
def test_change_during_materialize_refuses_before_shared_publication(actual, monkeypatch, fault):
    service, data = begin(actual)
    before, active = actual["client"].journal.pending(), current(actual)
    original = helper.materialize

    def change(*args):
        directory = original(*args)
        if fault == "close":
            service.close()
        else:
            with actual["client"].journal.transaction() as conn, suppress_capture(conn):
                conn.execute(
                    "UPDATE papers SET title='Changed while materializing' WHERE id=?",
                    (actual["local"],),
                )
        return directory

    monkeypatch.setattr(helper, "materialize", change)
    try:
        with pytest.raises(ValueError):
            apply(service, data, "late-refusal")
        assert actual["client"].journal.pending() == before and current(actual) == active
    finally:
        service.close()


def test_initially_absent_artifact_version_root_can_be_created_only_by_reviewed_materialization(
    actual,
):
    client = actual["client"]
    # Original source bytes are already owned in CAS; current PDF B stays untouched.
    new_root = actual["package"].case["root"] / "new-version-root"
    with client.journal.transaction() as conn, suppress_capture(conn):
        conn.execute("UPDATE research_file_paths SET version_root=? WHERE id=1", (str(new_root),))
    assert not new_root.exists()
    service, data = begin(actual)
    try:
        assert data["expected"]["storage"]["version_root"] is None
        result = apply(service, data, "fresh-root")
        assert new_root.is_dir() and result["operation_id"] == "fresh-root"
        assert current(actual)[1]["operation_id"] == "fresh-root"
    finally:
        service.close()


def test_original_deck_at_adoption_is_distinct_from_later_displayed_current(actual):
    service, first = begin(actual)
    try:
        apply(service, first, "active-before-second-retention")
        identity = save(actual, prepare(actual, request_id="after-active"))
        with closing(service._connect()) as conn:
            record = catalog.record(conn, identity)
        view = helper.prepare(service, record)
        assert view["original"] == view["current"] and view["original"] is not None
        assert view["retained"] == actual["expected"]["deck"]
        assert len(view["image_manifest"]) == 4
    finally:
        service.close()
