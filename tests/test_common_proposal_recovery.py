"""Public archive -> final native Verify, no duplicated candidates or auto-Apply."""

import json
import sqlite3
from contextlib import closing
from pathlib import Path
from uuid import uuid4

import pytest
from test_common_proposal_recovery_journey import actual as actual
from test_common_proposal_recovery_journey import case as case
from test_common_proposal_recovery_journey import codec as codec
from test_common_proposal_recovery_journey import local as local
from test_common_proposal_recovery_journey import native, sender, state
from test_common_proposal_recovery_journey import no_external as no_external
from test_common_proposal_recovery_journey import original as original
from test_common_proposal_recovery_journey import package as package
from test_common_proposal_recovery_journey import scientific as scientific

from paper_daily import enrolled_deck_proposals as catalog
from paper_daily import enrollment_history as history
from paper_daily import proposal_recovery_review as recovered
from paper_daily.recovery_adoption import RecoveryAdoptionService
from paper_daily.research_file_review import _storage
from paper_daily.research_review import ResearchReview
from paper_daily.sync_capture import suppress_capture
from paper_daily.sync_deck_publication import runtime
from paper_daily.workspace_service import Ticket, WorkspaceService


@pytest.fixture(params=["local", "enrolled"])
def receiver(request):
    database, science, reread, primary, prior_title = sender(request, request.param)
    baseline = state(database)
    output = database.parent.parent / (database.parent.name + "-public-controls-" + request.param)
    output.mkdir()
    service = WorkspaceService(database)
    service.status()  # Explicit public workspace review establishes its native baseline.
    archive, detached = output / "full.zip", output / "detached"
    manifest = service.backup(archive, Ticket())["manifest"]
    service.inspect(archive, Ticket())
    service.restore(archive, detached, manifest["backup_id"], Ticket())
    adopter = RecoveryAdoptionService(detached / "papers.db")
    inspection = adopter.inspect()
    assert inspection.report["current_deck_count"] == 1
    report = adopter.prepare(
        inspection,
        output / "editable",
        backup_output=output / "editable.zip",
        request_id=str(uuid4()),
    )
    path = Path(report["database"])
    yield dict(
        database=path,
        source=database,
        source_before=baseline,
        science=science,
        reread=reread,
        primary=primary,
        prior_title=prior_title,
        kind=request.param,
    )
    assert state(database) == baseline and reread().content == science


def entries(review):
    return [row for row in review.page(limit=100)["items"] if row["origin"] == "enrolled_deck"]


def count(database):
    with closing(sqlite3.connect(database)) as conn:
        present = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE name=?", (catalog.TABLE,)
        ).fetchone()
        return conn.execute("SELECT count(*) FROM " + catalog.TABLE).fetchone()[0] if present else 0


def preview(review):
    rows = entries(review)
    assert len(rows) == 1 and recovered.virtual(rows[0]["id"])
    return review.preview("enrolled_deck", rows[0]["id"])


def all_rows(database):
    with closing(sqlite3.connect(database)) as conn:
        names = [
            row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        ]
        return {
            name: sorted(
                conn.execute('SELECT * FROM "' + name.replace('"', '""') + '"').fetchall(), key=repr
            )
            for name in names
        }


def test_public_verify_repeat_restart_has_one_actual_owner_and_keeps_saved_deck(receiver):
    database = receiver["database"]
    service = ResearchReview(database)
    before = state(database)
    before_full = all_rows(database)
    with closing(sqlite3.connect(database)) as conn:
        before_tables = {
            row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
    client = runtime(database=database)
    pending = client.journal.pending()
    try:
        original = preview(service)
        assert original.data["retained"] == receiver["science"]["deck"]
        assert original.data["retained_evidence"] == receiver["science"]["evidence"]
        assert original.data["apply"] is False and count(database) == 0
        first = service.prepare_file(original)
        assert not recovered.virtual(first.data["id"]) and count(database) == 1
        for _ in range(3):
            repeated = service.prepare_file(original)
            assert repeated.data["id"] == first.data["id"]
        assert first.data["current"]["title"] == receiver["prior_title"]
        assert client.journal.pending() == pending
        after = state(database)
        assert {name: rows for name, rows in after.items() if name != catalog.TABLE} == before
        with closing(sqlite3.connect(database)) as conn:
            after_tables = {
                row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
            }
        assert after_tables == before_tables | {catalog.TABLE, history.TABLE}
        assert set(after) - set(before) == {catalog.TABLE} and len(after[catalog.TABLE]) == 1
        listed = entries(service)
        assert len(listed) == 1 and listed[0]["id"] == first.data["id"]
        with closing(service._connect()) as conn:
            links = conn.execute(
                "SELECT count(*) FROM research_history_archive WHERE protocol=?",
                (recovered.LINK_PROTOCOL,),
            ).fetchone()[0]
            cache = _storage(conn)[0]
        assert links == 1
        full = catalog.read(client, cache, first.data["id"], expected_native=native(database))
        assert full.content == receiver["science"] and len(full.content["image_bytes"]) == 4
        with closing(service._connect()) as conn:
            assert catalog.record(conn, first.data["id"]) == full.record
        owner = json.loads(full.record["owner_json"])["target"]
        assert owner["database"] == str(database.resolve())
        assert owner["native"] == list(native(database))
        assert owner["binding"] == [client.journal.workspace_id, client.journal.device_id]
        with closing(service._connect()) as conn:
            wrapped = conn.execute(
                "SELECT record_id,protocol,body_json FROM research_history_archive "
                "WHERE protocol=?",
                (recovered.LINK_PROTOCOL,),
            ).fetchall()
        assert len(wrapped) == 1
        link, sources = history.validate(
            dict(zip(history.COLUMNS.split(), wrapped[0], strict=True))
        )
        assert not sources and link["proposal_id"] == first.data["id"]
        assert link["source_id"] == original.data["id"][len(recovered.PREFIX) :]
        from paper_daily.sync_files import canonical_json

        assert link["receiver_json"] == canonical_json(owner).decode()
        after_full = all_rows(database)
        assert set(after_full) == set(before_full) | {catalog.TABLE, history.TABLE}
        for table, previous_rows in before_full.items():
            if table != history.TABLE:
                assert after_full[table] == previous_rows
        assert after_full[history.TABLE] == sorted(
            [*before_full.get(history.TABLE, []), tuple(wrapped[0])], key=repr
        )
        assert len(after_full[catalog.TABLE]) == 1
    finally:
        service.close()
    reopened = ResearchReview(database)
    try:
        assert entries(reopened) == listed and count(database) == 1
        with pytest.raises(ValueError):
            reopened.prepare_file(original)  # Original session HMAC is not a replay capability.
        current = reopened.prepare_file(reopened.preview("enrolled_deck", listed[0]["id"]))
        assert current.data["id"] == first.data["id"]
        assert current.data["retained"] == receiver["science"]["deck"]
    finally:
        reopened.close()


def test_actual_link_sql_denial_rolls_back_catalog_then_exact_retry(receiver, monkeypatch):
    service = ResearchReview(receiver["database"])
    client = runtime(database=service.path)
    original = history.retain_in
    saw_uncommitted = []

    def denied(conn, rows):
        if any(row["protocol"] == recovered.LINK_PROTOCOL for row in rows):
            saw_uncommitted.append(
                conn.execute("SELECT count(*) FROM " + catalog.TABLE).fetchone()[0]
            )
            conn.set_authorizer(
                lambda action, table, *_: (
                    sqlite3.SQLITE_DENY
                    if action == sqlite3.SQLITE_INSERT and table == history.TABLE
                    else sqlite3.SQLITE_OK
                )
            )
            try:
                return original(conn, rows)
            finally:
                conn.set_authorizer(None)
        return original(conn, rows)

    try:
        view = preview(service)
        before, pending = state(service.path), client.journal.pending()
        monkeypatch.setattr(history, "retain_in", denied)
        with pytest.raises(sqlite3.DatabaseError):
            service.prepare_file(view)
        assert saw_uncommitted == [1] and count(service.path) == 0
        assert state(service.path) == before and client.journal.pending() == pending
        assert len(entries(service)) == 1 and recovered.virtual(entries(service)[0]["id"])
        monkeypatch.setattr(history, "retain_in", original)
        retried = service.prepare_file(view)
        assert count(service.path) == 1 and len(entries(service)) == 1
        assert retried.data["retained_evidence"] == receiver["science"]["evidence"]
        assert retried.data["current"]["title"] == receiver["prior_title"]
        assert client.journal.pending() == pending
    finally:
        service.close()


@pytest.mark.parametrize("change", ["parent", "source", "close"])
def test_final_receiver_change_rejects_old_verify_without_hiding_original_content(receiver, change):
    service = ResearchReview(receiver["database"])
    client = runtime(database=service.path)
    original_bytes = None
    try:
        view = preview(service)
        if change == "parent":
            with client.journal.transaction() as conn, suppress_capture(conn):
                conn.execute(
                    "UPDATE papers SET title='Changed after display' WHERE id=?",
                    (view.data["target"]["id"],),
                )
        elif change == "source":
            with closing(service._connect()) as conn:
                cache = _storage(conn)[0]
            original_path = cache.root / "objects" / receiver["science"]["source_document_hash"]
            original_bytes = original_path.read_bytes()
            original_path.write_bytes(original_bytes[:-1] + b"!")
        else:
            service.close()
        before, pending = state(service.path), client.journal.pending()
        with pytest.raises((ValueError, OSError)):
            service.prepare_file(view)
        assert count(service.path) == 0 and state(service.path) == before
        assert client.journal.pending() == pending
    finally:
        if original_bytes is not None:
            original_path.write_bytes(original_bytes)
        service.close()
    reopened = ResearchReview(receiver["database"])
    try:
        assert len(entries(reopened)) == 1 and recovered.virtual(entries(reopened)[0]["id"])
        current = preview(reopened)
        assert current.data["retained_evidence"] == receiver["science"]["evidence"]
    finally:
        reopened.close()


def test_close_after_real_offlock_prepare_cannot_commit_general_owner(receiver, monkeypatch):
    service = ResearchReview(receiver["database"])
    original = catalog.prepare
    completed = []

    def prepared(*args, **kwargs):
        result = original(*args, **kwargs)
        completed.append(result.proposal_id)
        service.close()
        return result

    view = preview(service)
    before = state(service.path)
    monkeypatch.setattr(catalog, "prepare", prepared)
    with pytest.raises(ValueError):
        service.prepare_file(view)
    assert len(completed) == 1 and count(service.path) == 0
    assert state(service.path) == before


def test_actual_apply_is_separate_one_op_and_complete_archive_content_survives(receiver):
    service = ResearchReview(receiver["database"])
    client = runtime(database=service.path)
    try:
        view = service.prepare_file(preview(service))
        pending = len(client.journal.pending())
        decided = service.decide(view, request_id="explicit-recovered-apply", confirm_target=True)
        assert decided == {"decision": "applied", "operation_id": "explicit-recovered-apply"}
        assert len(client.journal.pending()) == pending + 1
        assert (
            service.decide(view, request_id="explicit-recovered-apply", confirm_target=True)
            == decided
        )
        assert len(client.journal.pending()) == pending + 1
        with closing(service._connect()) as conn:
            cache = _storage(conn)[0]
        retained = catalog.read(
            client, cache, view.data["id"], expected_native=native(service.path)
        )
        assert retained.content == receiver["science"] and len(retained.content["image_bytes"]) == 4
        refreshed = service.prepare_file(service.preview("enrolled_deck", view.data["id"]))
        assert refreshed.data["current"]["title"] == receiver["science"]["deck"]["title"]
        assert refreshed.data["original"]["title"] == receiver["prior_title"]
        assert set(retained.content["original_bytes"]) == {
            receiver["science"]["source_document_hash"]
        }
    finally:
        service.close()


def test_first_enrollment_archives_local_catalog_then_final_verify_creates_fresh_owner(
    scientific, tmp_path
):
    import hashlib

    import pymupdf

    from paper_daily import local_deck_proposals as local_catalog
    from paper_daily import portable_deck_proposal as codec
    from paper_daily import store
    from paper_daily.fetch import _safe_name
    from paper_daily.workspace_enrollment import EnrollmentService

    source = tmp_path / "first-local-source"
    source.mkdir()
    database = source / "papers.sqlite"
    with closing(sqlite3.connect(database)) as conn:
        conn.executescript(store.SCHEMA)
        store._migrate(conn)
        store.upsert_papers(
            conn,
            [
                dict(
                    id="local-paper",
                    title="Actual first local owner",
                    venue="Fixture",
                    year=2026,
                    source="fixture",
                )
            ],
        )
        conn.commit()
    deck, evidence, images, originals, original_a, primary_b = scientific
    images["evidence:four"] = pymupdf.Pixmap(
        pymupdf.csRGB, 2, 2, b"\x15\x72\x91" * 4, False
    ).tobytes("png")
    evidence["figures"].append(
        dict(
            id="evidence:four",
            label="Fourth retained evidence",
            caption="Complete fourth caption",
            page=1,
            document_hash=original_a,
        )
    )
    manifest, blobs = codec.encode(
        deck, evidence, images, originals, source_document_hash=original_a
    )
    intent = local_catalog.prepare(
        database,
        "local-paper",
        manifest,
        lambda item: blobs[item["sha256"]],
        request_id="first-enroll",
        expected_native=native(database),
    )
    proposal = local_catalog.retain(intent)
    expected = local_catalog.read(database, proposal, expected_native=native(database)).content
    pdfs = source / "pdf"
    pdfs.mkdir()
    primary = pdfs / (_safe_name("local-paper") + ".pdf")
    primary.write_bytes(primary_b)
    before = database.read_bytes()
    baseline = state(database)
    service = EnrollmentService(database)
    planned = service.plan(pdfs={"local-paper": primary})
    assert planned["supported"], planned["blockers"]
    result = service.prepare(
        tmp_path / "first-editable",
        backup_output=tmp_path / "first.zip",
        request_id=str(uuid4()),
        pdfs={"local-paper": primary},
    )
    assert result["status"] == "prepared_for_review" and not result["adopted"]
    receiver = Path(result["database"])
    assert count(receiver) == 0
    review = ResearchReview(receiver)
    try:
        displayed = preview(review)
        assert displayed.data["retained_evidence"] == expected["evidence"]
        verified = review.prepare_file(displayed)
        client = runtime(database=receiver)
        with closing(review._connect()) as conn:
            cache = _storage(conn)[0]
        actual = catalog.read(client, cache, verified.data["id"], expected_native=native(receiver))
        assert actual.content == expected and len(actual.content["image_bytes"]) == 4
        assert verified.data["current"] is None and verified.data["apply"]
        assert set(actual.content["original_bytes"]) == {original_a}
        assert hashlib.sha256(primary_b).hexdigest() != original_a
    finally:
        review.close()
    assert database.read_bytes() == before and state(database) == baseline
    assert primary.read_bytes() == primary_b
