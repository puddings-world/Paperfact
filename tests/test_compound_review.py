"""Typed candidate groups apply atomically from the exact displayed review base."""

import json
import sqlite3
from contextlib import closing
from uuid import uuid4

import pytest
from test_research_generation import rows
from test_research_generation import workspace as workspace

from paper_daily import research_compound as compound
from paper_daily import research_generation as generation
from paper_daily import store
from paper_daily.research_review import ResearchReview


def candidate(workspace, phase="citations"):
    path, client, document = workspace
    with closing(generation._connect(path)) as conn:
        context = compound.begin(conn, phase=phase, owner_id="paper")
    if phase in {"citations", "resources"}:
        context, _, _ = compound.read_text(
            context, pdf_root=document.path.parent, text_root=document.path.parent
        )
    keys = ["one", "two"]
    completion = None
    if phase == "resources":
        keys = ["https://github.com/example/" + key for key in keys]
        values = [compound.row(context, key, kind="code", source="pdf") for key in keys]
        completion = "text"
    else:
        values = [
            compound.row(
                context, key, title=key, **({"basis": "context"} if phase == "citations" else {})
            )
            for key in keys
        ]
    with store.connect() as conn:
        conn.execute("UPDATE papers SET title='New title' WHERE id='paper'")
    result = compound.publish(context, puts=values, completion=completion)
    assert result.status == "candidate"
    from paper_daily.research_review import _setup

    with closing(generation._connect(path)) as conn, conn:
        _setup(conn)
    review = ResearchReview(path)
    return review, result.request_id, context, values


@pytest.mark.parametrize("phase", ["citations", "fetch", "judge", "resources"])
def test_complete_group_exact_retry_preserves_candidate_and_source(workspace, phase):
    path, client, document = workspace
    review, identity, context, values = candidate(workspace, phase)
    original = rows(path, "SELECT * FROM research_compound_requests")
    preview = review.preview("compound", identity)
    assert preview.data["apply"]
    assert not preview.data["editable"]
    assert preview.data["retained"]["puts"] == values
    before = len(client.journal.pending()) if client else 0
    request = str(uuid4())
    result = review.decide(preview, request_id=request)
    assert result["decision"] == "applied"
    assert review.decide(preview, request_id=request) == result
    assert rows(path, f"SELECT * FROM {context.table}") == values
    assert rows(path, "SELECT * FROM research_compound_requests") == original
    assert len(rows(path, "SELECT * FROM research_review_receipts")) == 1
    if client:
        operations = client.journal.pending()[before:]
        assert len(operations) == 2
        assert all(op["entity_type"] == "research_content" for op in operations)
        expected = document.sha256 if phase in {"citations", "resources"} else None
        assert all(op["payload"]["source_document_hash"] == expected for op in operations)


@pytest.mark.parametrize("change", ["row", "parent", "pdf"])
def test_late_change_preserves_entire_group(workspace, change):
    path, client, document = workspace
    review, identity, context, _ = candidate(workspace)
    preview = review.preview("compound", identity)
    if change == "row":
        with closing(generation._connect(path)) as conn:
            newer = compound.begin(conn, phase="citations", owner_id="paper")
        compound.publish(newer, puts=[compound.row(newer, "late", title="Late", basis="context")])
    elif change == "parent":
        with store.connect() as conn:
            conn.execute("UPDATE papers SET title='Later' WHERE id='paper'")
    else:
        from test_research_generation import pdf

        document.path.unlink()
        pdf(document.path, "Changed PDF arrangement")
    before = rows(path, "SELECT * FROM cites")
    pending = client.journal.pending() if client else []
    with pytest.raises(ValueError, match="changed"):
        review.decide(preview)
    assert rows(path, "SELECT * FROM cites") == before
    assert client is None or client.journal.pending() == pending
    assert rows(path, "SELECT * FROM research_review_receipts") == []


def test_explicit_target_confirmation_retains_historical_hash(workspace):
    path, client, document = workspace
    review, identity, _context, _ = candidate(workspace)
    with store.connect() as conn:
        store.upsert_papers(
            conn,
            [
                {
                    "id": "other",
                    "title": "Other",
                    "source": "fixture",
                    "venue": "Fixture",
                    "year": 2026,
                }
            ],
        )
    preview = review.target_preview(review.preview("compound", identity), "other")
    assert preview.data["requires_confirmation"]
    assert "not verified" in preview.data["reason"]
    before = len(client.journal.pending()) if client else 0
    with pytest.raises(ValueError, match="Confirm"):
        review.decide(preview)
    assert rows(path, "SELECT * FROM cites") == []
    review.decide(preview, confirm_target=True)
    assert {r["paper_id"] for r in rows(path, "SELECT * FROM cites")} == {"other"}
    if client:
        assert all(
            op["payload"]["source_document_hash"] == document.sha256
            for op in client.journal.pending()[before:]
        )


def test_receipt_failure_rolls_back_rows_outbox_and_flag(workspace, monkeypatch):
    path, client, _document = workspace
    review, identity, _context, _ = candidate(workspace, "resources")
    preview = review.preview("compound", identity)
    before = client.journal.pending() if client else []
    receipt = review._receipt

    def fail(*args):
        receipt(*args)
        raise sqlite3.OperationalError("fixture receipt failure")

    monkeypatch.setattr(review, "_receipt", fail)
    with pytest.raises(sqlite3.OperationalError):
        review.decide(preview)
    assert rows(path, "SELECT * FROM resources") == []
    assert rows(path, "SELECT * FROM kv WHERE key='resources:paper'") == []
    assert client is None or client.journal.pending() == before
    monkeypatch.setattr(review, "_receipt", receipt)
    review.decide(preview)
    assert len(rows(path, "SELECT * FROM resources")) == 2


def test_keep_export_and_no_json_replay(workspace):
    path, _client, _document = workspace
    review, identity, _context, _ = candidate(workspace)
    preview = review.preview("compound", identity)
    with pytest.raises(ValueError, match="typed records"):
        review.decide(preview, body='{"puts":[]}')
    exported = json.loads(review.export_text(preview))
    assert exported["content"]["puts"][0]["title"] == "one"
    assert "db_path" not in review.export_text(preview)
    assert review.decide(preview, keep=True)["decision"] == "kept"
    assert rows(path, "SELECT * FROM cites") == []
    assert any(i["origin"] == "compound" for i in review.page()["items"])


def test_recreated_parent_requires_explicit_target_and_preserves_candidate(workspace):
    path, _client, _document = workspace
    review, identity, _context, _ = candidate(workspace)
    old = review.preview("compound", identity)
    with store.connect() as conn:
        conn.execute("DELETE FROM papers WHERE id='paper'")
        store.upsert_papers(
            conn,
            [
                {
                    "id": "paper",
                    "title": "Paper",
                    "year": 2026,
                    "venue": "Fixture",
                    "source": "fixture",
                }
            ],
        )
    with pytest.raises(ValueError, match="changed"):
        review.decide(old)
    fresh = review.preview("compound", identity)
    assert not fresh.data["apply"]
    chosen = review.target_preview(fresh, "paper")
    review.decide(chosen, confirm_target=True)
    assert len(rows(path, "SELECT * FROM cites")) == 2
    assert rows(path, "SELECT status FROM research_compound_requests") == [{"status": "candidate"}]


def test_late_desired_or_applied_document_change_rejects_group(workspace):
    path, client, _document = workspace
    review, identity, _context, _ = candidate(workspace)
    if client is None:
        # This fixture still has no graph/document metadata. A local PDF change
        # is covered separately; introducing managed metadata must invalidate it.
        from paper_daily.sync_research import prepare

        prepare(path, workspace_id="new-workspace", device_id="new-device")
    portable = rows(path, "SELECT sync_id FROM research_paper_identity")[0]["sync_id"]
    preview = review.preview("compound", identity)
    with closing(sqlite3.connect(path)) as conn, conn:
        conn.execute(
            "INSERT INTO research_document_desired VALUES(?,?,?)",
            (portable, '{"fixture":"changed desired version"}', 1),
        )
    before = rows(path, "SELECT * FROM cites")
    with pytest.raises(ValueError, match="changed"):
        review.decide(preview)
    assert rows(path, "SELECT * FROM cites") == before


def test_deletion_and_puts_are_one_group(workspace):
    path, _client, _document = workspace
    with closing(generation._connect(path)) as conn:
        context = compound.begin(conn, phase="citations", owner_id="paper")
    assert (
        compound.publish(
            context, puts=[compound.row(context, "old", title="Old", basis="context")]
        ).status
        == "accepted"
    )
    with closing(generation._connect(path)) as conn:
        context = compound.begin(conn, phase="citations", owner_id="paper")
    with store.connect() as conn:
        conn.execute("UPDATE papers SET title='Changed' WHERE id='paper'")
    result = compound.publish(
        context, puts=[compound.row(context, "new", title="New", basis="context")], deletes=["old"]
    )
    review = ResearchReview(path)
    preview = review.preview("compound", result.request_id)
    assert preview.data["retained"]["deletes"] == ["old"]
    review.decide(preview)
    assert [r["ref_key"] for r in rows(path, "SELECT * FROM cites")] == ["new"]


def test_manual_and_curated_current_rows_are_not_overwritten(workspace):
    path, _client, _document = workspace
    review, identity, _context, _ = candidate(workspace)
    with closing(generation._connect(path)) as conn:
        context = compound.begin(conn, phase="citations", owner_id="paper")
    compound.publish(
        context, puts=[compound.row(context, "one", title="Manual", basis="context", edited=1)]
    )
    preview = review.preview("compound", identity)
    with pytest.raises(ValueError, match="manual"):
        review.decide(preview)
    assert [r["title"] for r in rows(path, "SELECT * FROM cites")] == ["Manual"]


def test_owned_sidecar_is_explicitly_reattachable(workspace):
    path, _client, _document = workspace
    review, identity, context, _ = candidate(workspace)
    record = rows(path, "SELECT * FROM research_compound_requests")[0]
    side = compound._recovery_path(context)
    side.parent.mkdir(parents=True)
    side.write_text(json.dumps(record), encoding="utf-8")
    selected = next(i for i in review.page()["items"] if i["origin"] == "compound_sidecar")
    preview = review.preview(selected["origin"], selected["id"])
    review.decide(preview)
    assert side.read_text(encoding="utf-8") == json.dumps(record)
    assert len(rows(path, "SELECT * FROM cites")) == 2


def test_detached_compound_record_requires_confirmed_new_target(workspace):
    path, _client, _document = workspace
    review, identity, _context, _ = candidate(workspace)
    record = rows(path, "SELECT * FROM research_compound_requests")[0]
    # Archive provenance is valid but describes an earlier database identity.
    context = json.loads(record["context_json"])
    context["database_identity"] = [123, 456]
    original = compound.Context(generation._context_json(context))
    archived = compound._record(
        original, json.loads(record["mutations_json"]), "candidate", "detached"
    )
    with closing(sqlite3.connect(path)) as conn, conn:
        conn.execute("CREATE TABLE recovery_records(table_name TEXT,data TEXT)")
        conn.execute(
            "INSERT INTO recovery_records VALUES(?,?)",
            ("research_compound_requests", json.dumps(archived)),
        )
    fresh = ResearchReview(path)
    preview = fresh.preview("compound_recovery", "1")
    assert not preview.data["apply"]
    chosen = fresh.target_preview(preview, "paper")
    fresh.decide(chosen, confirm_target=True)
    assert len(rows(path, "SELECT * FROM cites")) == 2
    assert json.loads(rows(path, "SELECT data FROM recovery_records")[0]["data"]) == archived


def test_database_replaced_never_receives_old_review(workspace, tmp_path):
    path, _client, _document = workspace
    review, identity, _context, _ = candidate(workspace)
    preview = review.preview("compound", identity)
    old = tmp_path / "original.sqlite"
    path.rename(old)
    with closing(sqlite3.connect(path)) as conn:
        conn.execute("CREATE TABLE sentinel(value TEXT)")
    with pytest.raises(ValueError, match="replaced"):
        review.decide(preview)
    assert rows(path, "SELECT * FROM sentinel") == []
    assert rows(old, "SELECT * FROM cites") == []


def test_same_displayed_group_has_one_winner_under_concurrent_apply(workspace):
    from concurrent.futures import ThreadPoolExecutor

    path, _client, _document = workspace
    review, identity, _context, _ = candidate(workspace)
    other = ResearchReview(path)
    previews = [
        (review, review.preview("compound", identity)),
        (other, other.preview("compound", identity)),
    ]

    def apply(pair):
        try:
            return pair[0].decide(pair[1])["decision"]
        except ValueError:
            return "stale"

    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(apply, previews))
    assert sorted(results) == ["applied", "stale"]
    assert len(rows(path, "SELECT * FROM cites")) == 2
    assert len(rows(path, "SELECT * FROM research_review_receipts")) == 1


def test_deleted_graph_key_needs_explicit_restore_and_syncs_once(workspace, tmp_path):
    path, client, _document = workspace
    review, identity, _context, _ = candidate(workspace)
    with closing(generation._connect(path)) as conn:
        create = compound.begin(conn, phase="citations", owner_id="paper")
    assert (
        compound.publish(
            create, puts=[compound.row(create, "one", title="Interim", basis="context")]
        ).status
        == "accepted"
    )
    with closing(generation._connect(path)) as conn:
        delete = compound.begin(conn, phase="citations", owner_id="paper")
    assert compound.publish(delete, puts=[], deletes=["one"]).status == "accepted"
    preview = review.preview("compound", identity)
    if client:
        assert not preview.data["apply"]
        with pytest.raises(ValueError, match="restoration"):
            review.decide(preview)
    chosen = review.target_preview(preview, "paper")
    request = str(uuid4())
    review.decide(chosen, confirm_target=True, request_id=request)
    review.decide(chosen, confirm_target=True, request_id=request)
    assert {r["title"] for r in rows(path, "SELECT * FROM cites")} == {"one", "two"}
    if client:
        from paper_daily.sync_service import ReferenceService

        service = ReferenceService(tmp_path / "authority.sqlite")
        token = service.enroll("workspace", "device")
        client.sync_once(service, token)
        assert client.status()["conflicts"] == 0
        assert not client.journal.pending()
    assert len(rows(path, "SELECT * FROM research_review_receipts")) == 1


def test_pdf_changed_during_apply_rolls_back_group_and_receipt(workspace, monkeypatch):
    from test_research_generation import pdf

    path, client, document = workspace
    review, identity, _context, _ = candidate(workspace)
    preview = review.preview("compound", identity)
    before = client.journal.pending() if client else []
    original = review._receipt

    def changed(*args):
        original(*args)
        document.path.unlink()
        pdf(document.path, "Changed during apply")

    monkeypatch.setattr(review, "_receipt", changed)
    with pytest.raises(ValueError, match="PDF changed"):
        review.decide(preview)
    assert rows(path, "SELECT * FROM cites") == []
    assert rows(path, "SELECT * FROM research_review_receipts") == []
    assert client is None or client.journal.pending() == before


def test_completion_flag_change_after_preview_preserves_group(workspace):
    path, _client, _document = workspace
    review, identity, _context, _ = candidate(workspace, "resources")
    preview = review.preview("compound", identity)
    with store.connect() as conn:
        store.set_kv(conn, "resources:paper", "notext")
    with pytest.raises(ValueError, match="changed"):
        review.decide(preview)
    assert rows(path, "SELECT * FROM resources") == []
    assert rows(
        path, "SELECT json_extract(value,'$') AS value FROM kv WHERE key='resources:paper'"
    ) == [{"value": "notext"}]


def test_complete_backup_retains_compound_source_and_review_receipt(workspace, tmp_path):
    from paper_daily import sync_recovery

    path, _client, _document = workspace
    review, identity, _context, _ = candidate(workspace)
    review.decide(review.preview("compound", identity), request_id="backup-reviewed-group")
    source = rows(path, "SELECT * FROM research_compound_requests")[0]
    from test_sync_recovery import blob

    from paper_daily.sync_blobs import BlobStore
    from paper_daily.sync_documents import _encode
    from paper_daily.sync_journal import Journal
    from paper_daily.sync_research import prepare

    if _client is None:
        prepare(path, workspace_id="workspace", device_id="device")
        Journal(path, workspace_id="workspace", device_id="device")
    portable = rows(path, "SELECT sync_id FROM research_paper_identity")[0]["sync_id"]
    objects = BlobStore(tmp_path / "owned")
    manifest = blob(objects, _document.path.read_bytes())
    target = dict(
        workspace_id="workspace",
        paper_id=portable,
        operation_id="source-doc",
        incarnation="source-doc",
        parent_incarnation="paper-origin",
        sha256=manifest.sha256,
        size=manifest.size,
        media_type="application/pdf",
    )
    with closing(sqlite3.connect(path)) as conn, conn:
        conn.execute(
            "INSERT INTO research_document_desired VALUES(?,?,1)", (portable, _encode(target))
        )
        conn.execute(
            "INSERT INTO research_document_applied VALUES(?,?)", (portable, _encode(target))
        )
    package = tmp_path / "backup.pfb"
    sync_recovery.create(path, package, blob_store=objects)
    sync_recovery.restore_detached(package, tmp_path / "restored")
    detached = tmp_path / "restored" / "papers.db"
    assert (
        tmp_path / "restored" / "objects" / manifest.sha256
    ).read_bytes() == _document.path.read_bytes()
    records = rows(detached, "SELECT table_name,data FROM recovery_records")
    assert any(
        r["table_name"] == "research_compound_requests" and json.loads(r["data"]) == source
        for r in records
    )
    assert any(
        r["table_name"] == "research_review_receipts"
        and json.loads(r["data"])["request_id"] == "backup-reviewed-group"
        for r in records
    )
    fresh = ResearchReview(detached)
    item = next(i for i in fresh.page()["items"] if i["origin"] == "compound_recovery")
    preview = fresh.preview(item["origin"], item["id"])
    assert not preview.data["apply"]
    assert preview.data["retained"]["puts"][0]["title"] == "one"


@pytest.mark.parametrize("part", ["desired", "applied"])
def test_document_version_metadata_change_is_detected_independently(workspace, part):
    path, client, _document = workspace
    review, identity, _context, _ = candidate(workspace)
    if client is None:
        from paper_daily.sync_research import prepare

        prepare(path, workspace_id="workspace", device_id="device")
    portable = rows(path, "SELECT sync_id FROM research_paper_identity")[0]["sync_id"]
    preview = review.preview("compound", identity)
    with closing(sqlite3.connect(path)) as conn, conn:
        if part == "desired":
            conn.execute("INSERT INTO research_document_desired VALUES(?,?,?)", (portable, "{}", 0))
        else:
            conn.execute("INSERT INTO research_document_applied VALUES(?,?)", (portable, "{}"))
    with pytest.raises(ValueError, match="version changed"):
        review.decide(preview)
    assert rows(path, "SELECT * FROM cites") == []


def test_manual_reference_candidate_keeps_its_observed_source_hash(workspace):
    path, client, document = workspace
    review, identity, _context, _ = candidate(workspace)
    review.decide(review.preview("compound", identity))
    with closing(generation._connect(path)) as conn:
        edit = compound.begin(conn, phase="edit_reference", owner_id="paper", key="one")
    changed = compound.row(edit, "one", title="Reviewed manual reference", edited=1)
    with store.connect() as conn:
        conn.execute("UPDATE papers SET title='Another title' WHERE id='paper'")
    # Manual phases only consume owner identity, so a competing target change
    # supplies the stale condition while retaining the original source receipt.
    with closing(generation._connect(path)) as conn:
        newer = compound.begin(conn, phase="edit_reference", owner_id="paper", key="one")
    compound.publish(newer, puts=[compound.row(newer, "one", title="Concurrent", edited=1)])
    result = compound.publish(edit, puts=[changed])
    assert result.status == "candidate"
    preview = review.preview("compound", result.request_id)
    if client:
        assert preview.data["source_hash"] == document.sha256
        # Source bytes were not reread by the manual producer; explicit target
        # confirmation retains that historical source instead of retagging it.
        preview = review.target_preview(preview, "paper")
    before = len(client.journal.pending()) if client else 0
    review.decide(preview, confirm_target=bool(client))
    assert rows(path, "SELECT title FROM cites WHERE ref_key='one'") == [
        {"title": "Reviewed manual reference"}
    ]
    if client:
        assert (
            client.journal.pending()[before:][0]["payload"]["source_document_hash"]
            == document.sha256
        )


def test_detached_manual_review_resolves_original_hash_from_archived_receipt(workspace, tmp_path):
    path, client, document = workspace
    review, identity, _context, _ = candidate(workspace)
    review.decide(review.preview("compound", identity))
    with closing(generation._connect(path)) as conn:
        edit = compound.begin(conn, phase="edit_reference", owner_id="paper", key="one")
    with closing(generation._connect(path)) as conn:
        newer = compound.begin(conn, phase="edit_reference", owner_id="paper", key="one")
    compound.publish(newer, puts=[compound.row(newer, "one", title="New current", edited=1)])
    result = compound.publish(
        edit, puts=[compound.row(edit, "one", title="Retained manual", edited=1)]
    )
    record = next(
        r
        for r in rows(path, "SELECT * FROM research_compound_requests")
        if r["request_id"] == result.request_id
    )
    detached = tmp_path / "detached.sqlite"
    with closing(sqlite3.connect(detached)) as conn, conn:
        conn.executescript(store.SCHEMA)
        store.upsert_papers(
            conn,
            [
                {
                    "id": "paper",
                    "title": "Detached paper",
                    "year": 2026,
                    "venue": "Fixture",
                    "source": "fixture",
                }
            ],
        )
        conn.execute("CREATE TABLE recovery_records(table_name TEXT,data TEXT)")
        conn.execute(
            "INSERT INTO recovery_records VALUES(?,?)",
            ("research_compound_requests", json.dumps(record)),
        )
        if client:
            for operation in rows(path, "SELECT * FROM paperfact_sync_operations"):
                conn.execute(
                    "INSERT INTO recovery_records VALUES(?,?)",
                    ("paperfact_sync_operations", json.dumps(operation)),
                )
    fresh = ResearchReview(detached)
    preview = fresh.preview("compound_recovery", "1")
    expected_hash = document.sha256 if client else None
    assert preview.data["source_hash"] == expected_hash
    assert not preview.data["apply"]
    selected = fresh.target_preview(preview, "paper")
    assert selected.data["source_hash"] == expected_hash
    fresh.decide(selected, confirm_target=True)
    receipt = rows(detached, "SELECT provenance FROM research_review_receipts")[0]
    assert json.loads(receipt["provenance"])["source_document_hash"] == expected_hash
    assert rows(detached, "SELECT title FROM cites") == [{"title": "Retained manual"}]
    assert (
        json.loads(rows(detached, "SELECT data FROM recovery_records WHERE rowid=1")[0]["data"])
        == record
    )


def test_mixed_live_and_deleted_group_restores_only_deleted_incarnation(workspace):
    path, client, _document = workspace
    review, identity, _context, _ = candidate(workspace)
    with closing(generation._connect(path)) as conn:
        seeded = compound.begin(conn, phase="citations", owner_id="paper")
    compound.publish(
        seeded,
        puts=[
            compound.row(seeded, key, title="Existing " + key, basis="context")
            for key in ("one", "two")
        ],
    )
    live_incarnation = None
    if client:
        live_incarnation = next(
            op["incarnation"]
            for op in client.journal.pending()
            if op.get("payload", {}).get("key") == "two"
        )
    with closing(generation._connect(path)) as conn:
        deletion = compound.begin(conn, phase="citations", owner_id="paper")
    compound.publish(deletion, puts=[], deletes=["one"])
    selected = review.target_preview(review.preview("compound", identity), "paper")
    review.decide(selected, confirm_target=True)
    assert {r["title"] for r in rows(path, "SELECT * FROM cites")} == {"one", "two"}
    if client:
        operations = [
            op for op in client.journal.pending() if op.get("payload", {}).get("key") == "two"
        ]
        assert operations[-1]["incarnation"] == live_incarnation
        one = [op for op in client.journal.pending() if op.get("payload", {}).get("key") == "one"]
        assert one[-1]["incarnation"] != one[0]["incarnation"]
