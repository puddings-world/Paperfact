"""Review applies the version actually displayed, atomically and without models."""

import sqlite3
from contextlib import closing

import pytest

from paper_daily import research_generation as generation
from paper_daily import store, sync_capture
from paper_daily.research_review import ResearchReview
from paper_daily.sync_client import SyncClient
from paper_daily.sync_journal import Journal
from paper_daily.sync_research import prepare, research_writer
from paper_daily.sync_service import ReferenceService

STAMP = "2026-10-26T00:00:00+00:00"


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    path = tmp_path / "research.db"
    with sqlite3.connect(path) as conn:
        conn.executescript(store.SCHEMA)
    conn.close()
    prepare(path, workspace_id="workspace", device_id="device")
    client = SyncClient(
        Journal(path, workspace_id="workspace", device_id="device"), research_writer
    )
    monkeypatch.setattr(store, "DB_PATH", path)
    monkeypatch.setattr(store, "ensure_dirs", lambda: None)
    with store.connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        sync_capture.install(conn, workspace_id="workspace", device_id="device")
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
    return path, client


def context(path):
    with closing(generation._connect(path)) as conn:
        return generation.begin_generation(
            conn, table="close_readings", owner_id="paper", input_reader="target"
        )


def output(body):
    return {"paper_id": "paper", "body": body, "spec": "fixture-v1", "written_at": STAMP}


def query(path, sql):
    with closing(sqlite3.connect(path)) as conn:
        return conn.execute(sql).fetchall()


def candidate(path, *, source_hash=None):
    initial = context(path)
    if source_hash:
        data = initial.data
        data["document"] = {
            "sha256": source_hash,
            "path": str(path.parent / "old.pdf"),
            "target": None,
            "managed": False,
        }
        initial = generation.GenerationContext(generation._context_json(data))
    generation.publish_generation(context(path), row=output("Current saved analysis"))
    result = generation.publish_generation(initial, row=output("Retained generated analysis"))
    assert result.status == "candidate"
    return result.request_id


def test_generated_apply_uses_displayed_base_and_keeps_candidate(workspace):
    path, client = workspace
    identity = candidate(path, source_hash="a" * 64)
    review = ResearchReview(path)
    preview = review.preview("generation", identity)
    assert preview.data["apply"]
    assert preview.data["original"] is None
    assert preview.data["current"]["body"] == "Current saved analysis"
    count = len(client.journal.pending())
    result = review.decide(preview, body="Reviewed draft", request_id="review-one")
    assert result["decision"] == "applied"
    assert query(path, "SELECT body FROM close_readings") == [("Reviewed draft",)]
    assert len(client.journal.pending()) == count + 1
    operation = client.journal.pending()[-1]
    assert operation["payload"]["source_document_hash"] == "a" * 64
    assert operation["payload"]["data"]["body"] == "Reviewed draft"
    assert review.decide(preview, body="Reviewed draft", request_id="review-one") == result
    assert len(client.journal.pending()) == count + 1
    assert query(path, "SELECT status FROM research_generation_requests ORDER BY rowid")[-1] == (
        "candidate",
    )
    assert query(path, "SELECT count(*) FROM research_review_receipts") == [(1,)]


def test_late_write_preserves_current_and_edited_candidate(workspace):
    path, client = workspace
    identity = candidate(path)
    review = ResearchReview(path)
    preview = review.preview("generation", identity)
    generation.publish_generation(context(path), row=output("Newer edit while preview open"))
    pending = client.journal.pending()
    with pytest.raises(ValueError, match="changed"):
        review.decide(preview, body="Retain this draft", request_id="late")
    assert query(path, "SELECT body FROM close_readings") == [("Newer edit while preview open",)]
    assert client.journal.pending() == pending
    assert "Retain this draft" in review.export_text(preview, body="Retain this draft")
    with pytest.raises(sqlite3.OperationalError):
        query(path, "SELECT * FROM research_review_receipts")
    fresh = review.preview("generation", identity)
    review.decide(fresh, body="Explicitly reviewed against newer edit", request_id="fresh")
    assert query(path, "SELECT body FROM close_readings") == [
        ("Explicitly reviewed against newer edit",)
    ]


def test_keep_current_and_retry_never_emit_outbox(workspace):
    path, client = workspace
    review = ResearchReview(path)
    preview = review.preview("generation", candidate(path))
    before = client.journal.pending()
    review.decide(preview, keep=True, request_id="keep")
    review.decide(preview, keep=True, request_id="keep")
    assert client.journal.pending() == before
    assert query(path, "SELECT body FROM close_readings") == [("Current saved analysis",)]
    assert review.page()["items"][-1]["decision"] == "kept"
    with pytest.raises(ValueError, match="changed"):
        review.decide(preview, request_id="keep")


def test_receipt_failure_rolls_back_research_and_outbox(workspace, monkeypatch):
    path, client = workspace
    review = ResearchReview(path)
    preview = review.preview("generation", candidate(path))
    before = client.journal.pending()

    def fail(*args):
        raise sqlite3.OperationalError("fixture receipt failure")

    monkeypatch.setattr(review, "_receipt", fail)
    with pytest.raises(sqlite3.OperationalError, match="receipt failure"):
        review.decide(preview, request_id="atomic")
    assert client.journal.pending() == before
    assert query(path, "SELECT body FROM close_readings") == [("Current saved analysis",)]


def test_global_path_switch_does_not_redirect_and_closed_session_cannot_write(
    workspace, tmp_path, monkeypatch
):
    path, client = workspace
    review = ResearchReview(path)
    preview = review.preview("generation", candidate(path))
    other = tmp_path / "other.db"
    other.write_bytes(b"unrelated file")
    monkeypatch.setattr(store, "DB_PATH", other)
    review.decide(preview, request_id="original-only")
    assert other.read_bytes() == b"unrelated file"
    before = client.journal.pending()
    review.close()
    with pytest.raises(ValueError, match="closed"):
        review.decide(preview, request_id="closed")
    assert client.journal.pending() == before


def test_replaced_database_and_cross_session_preview_rejected(workspace, tmp_path):
    path, _ = workspace
    review = ResearchReview(path)
    preview = review.preview("generation", candidate(path))
    other_review = ResearchReview(path)
    with pytest.raises(ValueError, match="another review"):
        other_review.decide(preview, keep=True)
    archived = tmp_path / "old.db"
    path.rename(archived)
    path.write_bytes(archived.read_bytes())
    with pytest.raises(ValueError, match="replaced"):
        review.decide(preview, request_id="replacement")
    assert query(path, "SELECT body FROM close_readings") == [("Current saved analysis",)]


def test_page_bounds_and_exports_exclude_receipt_paths(workspace, tmp_path):
    path, _ = workspace
    identity = candidate(path)
    review = ResearchReview(path)
    for i in range(4):
        initial = context(path)
        generation.publish_generation(context(path), row=output(f"new {i}"))
        generation.publish_generation(initial, row=output(f"candidate {i}"))
    seen = []
    cursor = None
    while True:
        page = review.page(after=cursor, limit=2)
        assert len(page["items"]) <= 2
        seen.extend(item["id"] for item in page["items"])
        cursor = page["next"]
        if cursor is None:
            break
    assert len(seen) == len(set(seen)) == 5
    with pytest.raises(ValueError):
        review.page(limit=101)
    preview = review.preview("generation", identity)
    text = review.export_text(preview)
    assert "Retained generated analysis" in text
    assert str(path) not in text
    assert "database_identity" not in text and "inputs" not in text
    destination = tmp_path / "review.txt"
    review.export(preview, destination)
    with pytest.raises(FileExistsError):
        review.export(preview, destination, body="overwrite")
    assert destination.read_text("utf-8") == text


def test_invalid_output_does_not_mutate(workspace):
    path, client = workspace
    review = ResearchReview(path)
    preview = review.preview("generation", candidate(path))
    before = client.journal.pending()
    with pytest.raises(ValueError):
        review.decide(preview, body="x" * (201 * 1024))
    assert client.journal.pending() == before


def test_unenrolled_generation_can_export_but_not_infer_parent_lifecycle(tmp_path, monkeypatch):
    path = tmp_path / "legacy.db"
    with sqlite3.connect(path) as conn:
        conn.executescript(store.SCHEMA)
        conn.execute(
            "INSERT INTO papers(id,title,title_key,venue,year,source) "
            "VALUES('paper','Paper','paper','Fixture',2026,'fixture')"
        )
    review = ResearchReview(path)
    preview = review.preview("generation", candidate(path))
    assert not preview.data["apply"]
    with pytest.raises(ValueError, match="lifecycle"):
        review.decide(preview)
    assert "Retained generated analysis" in review.export_text(preview)


@pytest.fixture
def remote(tmp_path):
    from test_sync_research_roundtrip import database, save_note

    a, b = database(tmp_path / "a.db", "a"), database(tmp_path / "b.db", "b")
    service = ReferenceService(tmp_path / "authority.db")
    ta, tb = service.enroll("workspace", "a"), service.enroll("workspace", "b")
    save_note(a, "Original")
    a.sync_once(service, ta)
    b.sync_once(service, tb)
    save_note(a, "Canonical")
    save_note(b, "Retained remote")
    a.sync_once(service, ta)
    b.sync_once(service, tb)
    a.sync_once(service, ta)
    with closing(generation._connect(b.journal.path)) as conn:
        conn.execute("BEGIN IMMEDIATE")
        sync_capture.install(conn, workspace_id="workspace", device_id="b")
        conn.commit()
    return a, b, service, ta, tb


def test_remote_resolution_is_atomic_displayed_and_uses_resolution_of(remote):
    a, b, service, ta, tb = remote
    review = ResearchReview(b.journal.path)
    conflict = review.page()["items"][0]
    preview = review.preview("remote", conflict["id"])
    assert preview.data["apply"]
    assert preview.data["original"]["body"] == "Original"
    assert preview.data["current"]["body"] == "Canonical"
    result = review.decide(preview, body="Reviewed resolution", request_id="review-remote")
    pending = b.journal.pending()
    assert len(pending) == 1
    assert (
        pending[0]["resolution_of"]
        == preview.data["expected"]["event"]["operation"]["operation_id"]
    )
    assert review.decide(preview, body="Reviewed resolution", request_id="review-remote") == result
    b.sync_once(service, tb)
    a.sync_once(service, ta)
    assert query(a.journal.path, "SELECT body FROM notes WHERE body='Reviewed resolution'") == [
        ("Reviewed resolution",)
    ]
    assert b.status()["conflicts"] == 0


def test_remote_newer_head_after_preview_blocks_resolution(remote):
    from test_sync_research_roundtrip import save_note

    a, b, service, ta, tb = remote
    review = ResearchReview(b.journal.path)
    preview = review.preview("remote", review.page()["items"][0]["id"])
    save_note(a, "New canonical after preview")
    a.sync_once(service, ta)
    b.sync_once(service, tb)
    with pytest.raises(ValueError, match="Displayed conflict changed"):
        review.decide(preview, body="My draft", request_id="stale-remote")
    assert not b.journal.pending()
    assert query(
        b.journal.path, "SELECT body FROM notes WHERE body='New canonical after preview'"
    ) == [("New canonical after preview",)]


def test_remote_receipt_failure_rolls_back_resolution_and_intent(remote, monkeypatch):
    _a, b, _service, _ta, _tb = remote
    review = ResearchReview(b.journal.path)
    preview = review.preview("remote", review.page()["items"][0]["id"])
    before = query(b.journal.path, "SELECT * FROM notes")
    monkeypatch.setattr(
        review, "_receipt", lambda *args: (_ for _ in ()).throw(ValueError("receipt fault"))
    )
    with pytest.raises(ValueError, match="receipt fault"):
        review.decide(preview, request_id="atomic-remote")
    assert query(b.journal.path, "SELECT * FROM notes") == before
    assert not b.journal.pending()
    assert query(b.journal.path, "SELECT * FROM research_resolution_intents") == []


@pytest.mark.parametrize("table", ["dives", "paper_context"])
def test_committed_generation_registry_entries_apply_without_losing_rich_fields(workspace, table):
    path, client = workspace

    def observation():
        with closing(generation._connect(path)) as conn:
            return generation.begin_generation(
                conn, table=table, owner_id="paper", input_reader="target"
            )

    original = observation()
    if table == "dives":
        current = {"paper_id": "paper", "body": "Current", "spec": "fixture", "written_at": STAMP}
        retained = {**current, "body": "Retained"}
    else:
        current = {
            "paper_id": "paper",
            "summary": "Current",
            "reading_json": "[]",
            "written_at": STAMP,
            "edited": 0,
        }
        retained = {**current, "summary": "Retained"}
    generation.publish_generation(observation(), row=current)
    result = generation.publish_generation(original, row=retained)
    review = ResearchReview(path)
    preview = review.preview("generation", result.request_id)
    assert preview.data["apply"]
    review.decide(preview, body="Reviewed", request_id="review-" + table)
    field = "body" if table == "dives" else "summary"
    assert query(path, f"SELECT {field} FROM {table}") == [("Reviewed",)]
    operation = client.journal.pending()[-1]
    assert operation["payload"]["data"][field] == "Reviewed"
    if table == "paper_context":
        assert operation["payload"]["data"]["reading_json"] == []
        assert operation["payload"]["data"]["edited"] == 1


@pytest.fixture
def remote_graph(tmp_path):
    from test_sync_operations import client, paper

    from paper_daily.sync_content import content_id
    from paper_daily.sync_operations import ResearchOperations

    a, b = client(tmp_path / "a.db", "a"), client(tmp_path / "b.db", "b")
    service = ReferenceService(tmp_path / "authority.db")
    ta, tb = service.enroll("workspace", "a"), service.enroll("workspace", "b")
    result = ResearchOperations(a).create_list("Route", [{"paper": paper()}], request_id="route")
    list_id = result["list_id"]
    scope = {"kind": "list", "id": list_id}
    identity = content_id(scope, "list_survey", "main")

    def save(current, body):
        payload = {
            "scope": scope,
            "feature": "list_survey",
            "key": "main",
            "source_document_hash": None,
            "data": {
                "body": body,
                "papers": 1,
                "spec": "fixture",
                "written_at": STAMP,
                "edited": 0,
            },
        }
        current.save(current.new_graph_operation("research_content", identity, payload))

    save(a, "Original survey")
    a.sync_once(service, ta)
    b.sync_once(service, tb)
    save(a, "Canonical survey")
    save(b, "Retained survey")
    a.sync_once(service, ta)
    b.sync_once(service, tb)
    a.sync_once(service, ta)
    with closing(generation._connect(b.journal.path)) as conn:
        conn.execute("BEGIN IMMEDIATE")
        sync_capture.install(conn, workspace_id="workspace", device_id="b")
        conn.commit()
    return a, b, service, ta, tb, list_id


def test_remote_v2_content_review_converges_with_rich_fields(remote_graph):
    a, b, service, ta, tb, _list = remote_graph
    review = ResearchReview(b.journal.path)
    preview = review.preview("remote", review.page()["items"][0]["id"])
    assert preview.data["apply"]
    review.decide(preview, body="Reviewed survey", request_id="review-rich")
    operation = b.journal.pending()[-1]
    assert operation["version"] == 2
    assert operation["payload"]["data"]["edited"] == 1
    assert operation["payload"]["data"]["papers"] == 1
    b.sync_once(service, tb)
    a.sync_once(service, ta)
    assert query(a.journal.path, "SELECT body FROM list_surveys") == [("Reviewed survey",)]
    assert b.status()["conflicts"] == 0


def test_remote_parent_delete_and_restore_cannot_reattach_old_candidate(remote_graph):
    a, b, service, ta, tb, list_id = remote_graph
    review = ResearchReview(b.journal.path)
    item = review.page()["items"][0]
    preview = review.preview("remote", item["id"])
    a.save(a.new_graph_operation("list", list_id, {}, action="delete"))
    a.sync_once(service, ta)
    b.sync_once(service, tb)
    with pytest.raises(ValueError, match="Displayed conflict changed"):
        review.decide(preview, request_id="deleted-parent")
    assert not review.preview("remote", item["id"]).data["apply"]
    a.save(
        a.new_graph_operation("list", list_id, {"name": "Restored route", "note": ""}, restore=True)
    )
    a.sync_once(service, ta)
    b.sync_once(service, tb)
    assert not review.preview("remote", item["id"]).data["apply"]
    assert not b.journal.pending()
    assert query(b.journal.path, "SELECT body FROM list_surveys") == []
