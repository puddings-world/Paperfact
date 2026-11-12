"""Fresh receiver targets and sources, never historical write authority."""

import hashlib
import json
from contextlib import closing
from pathlib import Path
from uuid import uuid4

import pytest
from test_enrollment_review_draft_journey import decision as decision
from test_enrollment_review_draft_journey import draft_variants as draft_variants
from test_enrollment_review_draft_journey import prepare
from test_enrollment_review_draft_journey import source as source
from test_sync_source_files import pdf

from paper_daily import research_generation as generation
from paper_daily.document_reader import DocumentReader
from paper_daily.research_review import ResearchReview
from paper_daily.sync_client import SyncClient
from paper_daily.sync_journal import Journal
from paper_daily.sync_research import research_writer


@pytest.fixture
def copied(draft_variants, tmp_path):
    value = draft_variants
    original = value["primary"].with_name("historical-a.pdf")
    value["primary"].rename(original)
    value["primary"].write_bytes(pdf("Receiver current original B"))
    before = value["database"].read_bytes()
    result = prepare(value, tmp_path)
    path = Path(result["database"])
    review = ResearchReview(path)
    items = [item for item in review.page()["items"] if item["origin"] == "archived_draft"]
    assert len(items) == 2
    archived = review.preview("archived_draft", items[0]["id"])
    target = review.resume_targets(archived)["items"][0]
    current = DocumentReader.from_workspace(path).resolve(target["id"])
    assert current.available and current.sha256 != value["source_hash"]
    return dict(
        value=value,
        result=result,
        path=path,
        review=review,
        archived=archived,
        target=target,
        current=current,
        old_database_bytes=before,
    )


def client_for(path):
    with closing(generation._connect(path)) as conn:
        binding = generation._binding(conn)
    return SyncClient(
        Journal(path, workspace_id=binding["workspace_id"], device_id=binding["device_id"]),
        research_writer,
    )


def rows(path, sql):
    with closing(generation._connect(path)) as conn:
        return [tuple(row) for row in conn.execute(sql)]


def test_receiver_draft_can_restart_verify_edit_apply_and_retry_without_replacing_b(copied):
    value = copied
    review = value["review"]
    archived = value["archived"]
    archive_before = review.export_text(archived)
    client = client_for(value["path"])
    pending_before = client.journal.pending()
    preview = review.resume_draft(archived, value["target"]["id"])
    assert preview.data["origin"] == "archived_resume"
    assert preview.data["source_hash"] == value["value"]["source_hash"]
    assert preview.data["editable"] and not preview.data["apply"]
    request = str(uuid4())
    saved = review.save_draft(preview, "Researcher edited receiver draft", request)
    assert client.journal.pending() == pending_before
    review.close()

    reopened = ResearchReview(value["path"])
    try:
        loaded = reopened.load_draft("archived_resume", archived.data["id"])
        assert loaded["draft_id"] == saved["draft_id"]
        assert loaded["body"] == "Researcher edited receiver draft"
        assert not loaded["preview"].data["apply"]
        ready = reopened.verify_resumed_draft(loaded["preview"])
        assert ready.data["apply"] and ready.data["resume_state"] == "ready"
        with pytest.raises(ValueError, match="Confirm"):
            reopened.decide(ready, body=loaded["body"], request_id=request)
        result = reopened.decide(
            ready, body=loaded["body"], request_id=request, confirm_target=True
        )
        assert result["decision"] == "applied"
        assert rows(value["path"], "SELECT body FROM close_readings") == [(loaded["body"],)]
        assert rows(value["path"], "SELECT count(*) FROM research_review_receipts") == [(1,)]
        pending = client.journal.pending()
        assert len(pending) == len(pending_before) + 2
        assert {op["entity_type"] for op in pending[len(pending_before) :]} == {
            "research_file",
            "research_content",
        }
        research = next(
            op for op in pending[len(pending_before) :] if op["entity_type"] == "research_content"
        )
        assert research["payload"]["source_document_hash"] == value["value"]["source_hash"]
        assert research["payload"]["data"]["body"] == loaded["body"]
        assert archived.data["id"] not in json.dumps(pending)
        assert (
            reopened.decide(ready, body=loaded["body"], request_id=request, confirm_target=True)
            == result
        )
        assert client.journal.pending() == pending
        original = reopened.preview("archived_draft", archived.data["id"])
        assert reopened.export_text(original) == archive_before
        current = DocumentReader.from_workspace(value["path"]).resolve(value["target"]["id"])
        assert current.sha256 == value["current"].sha256
        assert hashlib.sha256(current.path.read_bytes()).hexdigest() == current.sha256
        assert value["value"]["database"].read_bytes() == value["old_database_bytes"]
    finally:
        reopened.close()


@pytest.mark.parametrize("target", ["", "missing-paper", None])
def test_empty_or_removed_target_keeps_original_and_research_unchanged(copied, target):
    review = copied["review"]
    before = rows(copied["path"], "SELECT envelope FROM paperfact_sync_operations")
    text = review.export_text(copied["archived"])
    with pytest.raises(ValueError, match="target"):
        review.resume_draft(copied["archived"], target)
    assert review.export_text(copied["archived"]) == text
    assert rows(copied["path"], "SELECT envelope FROM paperfact_sync_operations") == before
    review.close()


def test_missing_original_refuses_then_retry_uses_retained_a_not_current_b(copied):
    value = copied
    review = value["review"]
    selected = review.resume_draft(value["archived"], value["target"]["id"])
    retained = value["path"].parent / "pdf" / ".history" / (value["value"]["source_hash"] + ".pdf")
    original = retained.read_bytes()
    retained.unlink()
    before = client_for(value["path"]).journal.pending()
    review.save_draft(selected, "Text survives missing original", "missing-original")
    with pytest.raises(ValueError, match="missing or changed"):
        review.verify_resumed_draft(selected)
    assert client_for(value["path"]).journal.pending() == before
    assert review.load_draft("archived_resume", selected.data["id"])["body"] == (
        "Text survives missing original"
    )
    retained.write_bytes(original)
    ready = review.verify_resumed_draft(selected)
    assert ready.data["apply"] and ready.data["source_hash"] == value["value"]["source_hash"]
    assert ready.data["source_hash"] != value["current"].sha256
    assert value["current"].path.read_bytes() != original
    review.close()


@pytest.mark.parametrize("change", ["text", "parent", "selected_pdf"])
def test_changed_displayed_base_never_rebases_or_applies_silently(copied, change):
    value = copied
    review = value["review"]
    selected = review.resume_draft(value["archived"], value["target"]["id"])
    ready = review.verify_resumed_draft(selected)
    request = str(uuid4())
    review.save_draft(ready, "Never replace newer work", request)
    if change == "text":
        with closing(generation._connect(value["path"])) as conn:
            current = generation.begin_generation(
                conn, table="close_readings", owner_id=value["target"]["id"], input_reader="target"
            )
        row = dict(current.target)
        row["body"] = "Newer researcher work"
        assert generation.publish_generation(current, row=row).status == "accepted"
    elif change == "parent":
        with closing(generation._connect(value["path"])) as conn, conn:
            conn.execute("UPDATE papers SET title='Renamed while review open'")
    else:
        value["current"].path.write_bytes(pdf("Different selected PDF C"))
    before = client_for(value["path"]).journal.pending()
    with pytest.raises(ValueError, match="changed"):
        review.decide(
            ready, body="Never replace newer work", request_id=request, confirm_target=True
        )
    with pytest.raises(ValueError, match="changed"):
        review.verify_resumed_draft(ready)
    assert client_for(value["path"]).journal.pending() == before
    assert rows(value["path"], "SELECT body FROM close_readings") == [
        ("Newer researcher work" if change == "text" else "Human-reviewed interpretation",)
    ]
    assert (
        review.load_draft("archived_resume", ready.data["id"])["body"] == "Never replace newer work"
    )
    review.close()


def test_receipt_failure_rolls_back_source_research_and_outbox_then_retry_succeeds(
    copied, monkeypatch
):
    value = copied
    review = value["review"]
    selected = review.resume_draft(value["archived"], value["target"]["id"])
    ready = review.verify_resumed_draft(selected)
    request = str(uuid4())
    review.save_draft(ready, "Atomic researcher text", request)
    before = client_for(value["path"]).journal.pending()
    versions = rows(value["path"], "SELECT operation FROM research_file_versions")
    original_receipt = review._receipt

    def fail(*_args):
        raise RuntimeError("Receipt storage unavailable")

    monkeypatch.setattr(review, "_receipt", fail)
    with pytest.raises(RuntimeError, match="Receipt storage"):
        review.decide(ready, body="Atomic researcher text", request_id=request, confirm_target=True)
    assert client_for(value["path"]).journal.pending() == before
    assert rows(value["path"], "SELECT operation FROM research_file_versions") == versions
    assert rows(value["path"], "SELECT body FROM close_readings") == [
        ("Human-reviewed interpretation",)
    ]
    assert (
        review.load_draft("archived_resume", ready.data["id"])["body"] == "Atomic researcher text"
    )
    monkeypatch.setattr(review, "_receipt", original_receipt)
    assert (
        review.decide(
            ready, body="Atomic researcher text", request_id=request, confirm_target=True
        )["decision"]
        == "applied"
    )
    assert len(client_for(value["path"]).journal.pending()) == len(before) + 2
    review.close()


def test_simultaneous_identical_applies_create_one_research_source_and_receipt(copied):
    from concurrent.futures import ThreadPoolExecutor

    value = copied
    review = value["review"]
    ready = review.verify_resumed_draft(
        review.resume_draft(value["archived"], value["target"]["id"])
    )
    before = client_for(value["path"]).journal.pending()
    request = str(uuid4())
    with ThreadPoolExecutor(max_workers=4) as workers:
        results = list(
            workers.map(
                lambda _index: review.decide(
                    ready,
                    body="One accepted researcher text",
                    request_id=request,
                    confirm_target=True,
                ),
                range(8),
            )
        )
    assert results == [results[0]] * 8
    assert len(client_for(value["path"]).journal.pending()) == len(before) + 2
    assert rows(value["path"], "SELECT count(*) FROM research_review_receipts") == [(1,)]
    assert rows(value["path"], "SELECT body FROM close_readings") == [
        ("One accepted researcher text",)
    ]
    with pytest.raises(ValueError, match="changed"):
        review.decide(ready, body="Different retry", request_id=request, confirm_target=True)
    review.close()


def test_two_windows_preserve_cas_loser_without_overwriting_saved_draft(copied):
    from paper_daily.research_review_drafts import DraftConflict

    value = copied
    review = value["review"]
    selected = review.resume_draft(value["archived"], value["target"]["id"])
    saved = review.save_draft(selected, "First receiver text", "first-save")
    other = ResearchReview(value["path"])
    try:
        loaded = other.load_draft("archived_resume", selected.data["id"])
        winner = other.save_draft(loaded["preview"], "Other window wins", "winner", **saved)
        with pytest.raises(DraftConflict):
            review.save_draft(selected, "Losing window still has its text", "loser", **saved)
        result = review.load_draft("archived_resume", selected.data["id"])
        assert result["body"] == "Other window wins" and result["revision"] == winner["revision"]
        assert "Losing window still has its text" in review.export_text(
            selected, body="Losing window still has its text"
        )
        assert rows(value["path"], "SELECT body FROM close_readings") == [
            ("Human-reviewed interpretation",)
        ]
    finally:
        review.close()
        other.close()


def test_close_while_source_verifies_never_publishes_late_result(copied, monkeypatch):
    import threading
    from concurrent.futures import ThreadPoolExecutor

    from paper_daily import sync_source_files

    value = copied
    review = value["review"]
    selected = review.resume_draft(value["archived"], value["target"]["id"])
    review.save_draft(selected, "Keep text while closing", "closing-draft")
    before = client_for(value["path"]).journal.pending()
    entered, release = threading.Event(), threading.Event()
    original = sync_source_files.prepare_source

    def held(*args, **kwargs):
        entered.set()
        assert release.wait(10)
        return original(*args, **kwargs)

    monkeypatch.setattr(sync_source_files, "prepare_source", held)
    with ThreadPoolExecutor(max_workers=1) as workers:
        future = workers.submit(review.verify_resumed_draft, selected)
        try:
            assert entered.wait(10)
            review.close()
        finally:
            release.set()
        with pytest.raises(ValueError, match="closed"):
            future.result(timeout=10)
    assert client_for(value["path"]).journal.pending() == before
    reopened = ResearchReview(value["path"])
    try:
        saved = reopened.load_draft("archived_resume", selected.data["id"])
        assert saved["body"] == "Keep text while closing" and not saved["preview"].data["apply"]
    finally:
        reopened.close()


def test_resumed_text_and_both_original_versions_survive_rebackup(copied, tmp_path):
    import zipfile

    from paper_daily import enrollment_history, sync_recovery
    from paper_daily.sync_artifacts import paths

    value = copied
    review = value["review"]
    ready = review.verify_resumed_draft(
        review.resume_draft(value["archived"], value["target"]["id"])
    )
    request = str(uuid4())
    review.save_draft(ready, "Text continued on receiver", request)
    review.decide(ready, body="Text continued on receiver", request_id=request, confirm_target=True)
    with closing(generation._connect(value["path"])) as conn:
        blob_store, _root = paths(conn)
        private = dict(conn.execute("SELECT * FROM research_review_drafts").fetchone())
    archive = tmp_path / "receiver-backup.zip"
    sync_recovery.create(
        value["path"], archive, blob_store=blob_store, pdf_roots=[value["path"].parent / "pdf"]
    )
    with zipfile.ZipFile(archive) as bundle:
        assert (
            bundle.read("objects/" + value["value"]["source_hash"])
            == value["value"]["original_bytes"]
        )
        assert hashlib.sha256(bundle.read("objects/" + value["current"].sha256)).hexdigest() == (
            value["current"].sha256
        )
    destination = tmp_path / "receiver-detached"
    sync_recovery.restore_detached(archive, destination)
    recovered = ResearchReview(destination / "papers.db")
    try:
        texts = [
            recovered.export_text(recovered.preview(item["origin"], item["id"]))
            for item in recovered.page()["items"]
            if item["origin"] == "archived_draft"
        ]
        assert len(texts) == 3 and any("Text continued on receiver" in text for text in texts)
        with closing(generation._connect(destination / "papers.db")) as conn:
            raw = conn.execute(
                "SELECT data FROM recovery_records WHERE table_name=?", ("research_review_drafts",)
            ).fetchone()
            assert (
                enrollment_history.validate(
                    enrollment_history.wrap("research_review_drafts", json.loads(raw[0]))
                )[0]
                == private
            )
        assert rows(destination / "papers.db", "SELECT body FROM close_readings") == [
            ("Text continued on receiver",)
        ]
    finally:
        recovered.close()
        review.close()


@pytest.mark.parametrize("change", ["changed_history", "unknown_pdf"])
def test_rebackup_never_ignores_modified_or_unrepresented_pdf(copied, tmp_path, change):
    from paper_daily import sync_recovery
    from paper_daily.sync_artifacts import paths

    value = copied
    review = value["review"]
    ready = review.verify_resumed_draft(
        review.resume_draft(value["archived"], value["target"]["id"])
    )
    review.decide(
        ready, body="Accepted manual research", request_id=str(uuid4()), confirm_target=True
    )
    location = value["path"].parent / "pdf"
    if change == "changed_history":
        changed = location / ".history" / (value["value"]["source_hash"] + ".pdf")
    else:
        changed = location / "unrepresented-research.pdf"
    changed_bytes = pdf("Unaccounted original")
    changed.write_bytes(changed_bytes)
    before = value["path"].read_bytes()
    with closing(generation._connect(value["path"])) as conn:
        store, _root = paths(conn)
    output = tmp_path / "must-not-be-partial.zip"
    with pytest.raises(sync_recovery.RecoveryError, match="complete migration"):
        sync_recovery.create(value["path"], output, blob_store=store, pdf_roots=[location])
    assert not output.exists()
    assert value["path"].read_bytes() == before
    assert changed.read_bytes() == changed_bytes
    review.close()


def test_resume_never_reads_the_old_workspace_or_its_observed_paths(copied, monkeypatch):
    import sqlite3

    value = copied
    review = value["review"]
    old_root = value["value"]["database"].parent.resolve()
    native_open, native_connect = Path.open, sqlite3.connect

    def opened(path, *args, **kwargs):
        if path.resolve().is_relative_to(old_root):
            pytest.fail("Resumption followed a historical source path")
        return native_open(path, *args, **kwargs)

    def connected(path, *args, **kwargs):
        if old_root.as_posix().lower() in str(path).replace(chr(92), "/").lower():
            pytest.fail("Resumption opened the old database")
        return native_connect(path, *args, **kwargs)

    with monkeypatch.context() as patches:
        patches.setattr(Path, "open", opened)
        patches.setattr(sqlite3, "connect", connected)
        ready = review.verify_resumed_draft(
            review.resume_draft(value["archived"], value["target"]["id"])
        )
        review.decide(
            ready, body="Receiver-owned provenance", request_id=str(uuid4()), confirm_target=True
        )
        assert rows(value["path"], "SELECT body FROM close_readings") == [
            ("Receiver-owned provenance",)
        ]
    assert value["value"]["database"].read_bytes() == value["old_database_bytes"]
    review.close()


def test_source_bytes_changed_after_verification_refuse_without_partial_publication(copied):
    from paper_daily.sync_artifacts import paths
    from paper_daily.sync_blobs import BlobManifest

    value = copied
    review = value["review"]
    ready = review.verify_resumed_draft(
        review.resume_draft(value["archived"], value["target"]["id"])
    )
    with closing(generation._connect(value["path"])) as conn:
        store, _version = paths(conn)
    source = store.verified_path(
        BlobManifest(value["value"]["source_hash"], len(value["value"]["original_bytes"]))
    )
    source.write_bytes(pdf("Corrupted staged original"))
    before = client_for(value["path"]).journal.pending()
    request = str(uuid4())
    review.save_draft(ready, "Preserve this edited draft", request)
    with pytest.raises(ValueError, match="bytes changed"):
        review.decide(
            ready, body="Preserve this edited draft", request_id=request, confirm_target=True
        )
    assert client_for(value["path"]).journal.pending() == before
    assert rows(value["path"], "SELECT body FROM close_readings") == [
        ("Human-reviewed interpretation",)
    ]
    assert review.load_draft("archived_resume", ready.data["id"])["body"] == (
        "Preserve this edited draft"
    )
    review.close()


def test_source_less_manual_draft_never_inherits_the_current_pdf_hash(copied):
    from paper_daily import enrollment_history, sync_capture

    value = copied
    review = value["review"]
    with closing(generation._connect(value["path"])) as conn:
        expected = generation.begin_generation(
            conn, table="close_readings", owner_id=value["target"]["id"], input_reader="target"
        )
    current = dict(expected.target)
    current["body"] = "Newer text to create a real candidate"
    with closing(generation._connect(value["path"])) as conn:
        latest = generation.begin_generation(
            conn, table="close_readings", owner_id=value["target"]["id"], input_reader="target"
        )
    assert generation.publish_generation(latest, row=current).status == "accepted"
    original = dict(expected.target)
    original["body"] = "Earlier ungrounded draft"
    result = generation.publish_generation(expected, row=original)
    assert result.status == "candidate"
    preview = review.target_preview(
        review.preview("generation", result.request_id), value["target"]["id"]
    )
    saved = review.save_draft(preview, "Manual text without a recorded PDF", str(uuid4()))
    with closing(generation._connect(value["path"])) as conn, conn:
        raw = dict(
            conn.execute(
                "SELECT * FROM research_review_drafts WHERE draft_id=?", (saved["draft_id"],)
            ).fetchone()
        )
        carrier = enrollment_history.wrap("research_review_drafts", raw)
        with sync_capture.suppress_capture(conn):
            conn.execute(
                "INSERT INTO research_history_archive VALUES(?,?,?)",
                (carrier["record_id"], carrier["protocol"], carrier["body_json"]),
            )
    archived = review.preview("archived_draft", carrier["record_id"])
    ready = review.verify_resumed_draft(review.resume_draft(archived, value["target"]["id"]))
    assert ready.data["source_hash"] is None
    assert generation.GenerationContext(ready.data["expected"]).data["document"]["sha256"] == (
        value["current"].sha256
    )
    before = client_for(value["path"]).journal.pending()
    review.decide(
        ready, body="Explicit manual interpretation", request_id=str(uuid4()), confirm_target=True
    )
    pending = client_for(value["path"]).journal.pending()
    assert len(pending) == len(before) + 1
    assert pending[-1]["payload"]["source_document_hash"] is None
    assert pending[-1]["payload"]["data"]["body"] == "Explicit manual interpretation"
    review.close()


@pytest.mark.parametrize("table", ["dives", "paper_context", "list_surveys", "list_reading_goals"])
def test_each_additional_text_format_resumes_to_its_explicit_current_target(copied, table):
    from paper_daily import enrollment_history, sync_capture

    value = copied
    review = value["review"]
    kind, column, _feature, _reader = generation.REGISTRY[table]
    if kind == "paper":
        owner = value["target"]["id"]
    else:
        owner = rows(value["path"], "SELECT id FROM lists")[0][0]
    stamp = "2026-11-01T00:00:00+00:00"
    schemas = {
        "dives": {"body": "Earlier text", "spec": "fixture-v1", "written_at": stamp},
        "paper_context": {
            "summary": "Earlier text",
            "reading_json": "[]",
            "written_at": stamp,
            "edited": 0,
        },
        "list_surveys": {
            "body": "Earlier text",
            "papers": 1,
            "spec": "fixture-v1",
            "written_at": stamp,
            "edited": 0,
        },
        "list_reading_goals": {"body": "Earlier text", "written_at": stamp},
    }
    original = {column: owner, **schemas[table]}
    field = "body" if "body" in original else "summary"
    with closing(generation._connect(value["path"])) as conn:
        earlier = generation.begin_generation(
            conn, table=table, owner_id=owner, input_reader="target"
        )
        latest = generation.begin_generation(
            conn, table=table, owner_id=owner, input_reader="target"
        )
    current = {**original, field: "Current researcher version"}
    assert generation.publish_generation(latest, row=current).status == "accepted"
    result = generation.publish_generation(earlier, row=original)
    assert result.status == "candidate"
    view = review.target_preview(review.preview("generation", result.request_id), owner)
    saved = review.save_draft(view, "Private manual text", str(uuid4()))
    with closing(generation._connect(value["path"])) as conn, conn:
        raw = dict(
            conn.execute(
                "SELECT * FROM research_review_drafts WHERE draft_id=?", (saved["draft_id"],)
            ).fetchone()
        )
        archive = enrollment_history.wrap("research_review_drafts", raw)
        with sync_capture.suppress_capture(conn):
            conn.execute(
                "INSERT INTO research_history_archive VALUES(?,?,?)",
                (archive["record_id"], archive["protocol"], archive["body_json"]),
            )
    archived = review.preview("archived_draft", archive["record_id"])
    targets = review.resume_targets(archived)["items"]
    assert any(item["id"] == owner for item in targets)
    selected = review.resume_draft(archived, owner)
    assert selected.data["current"][field] == "Current researcher version"
    assert selected.data["retained"][field] == "Private manual text"
    ready = review.verify_resumed_draft(selected)
    request = str(uuid4())
    new_draft = review.save_draft(ready, "Continued manual research", request)
    result = review.decide(
        ready, body="Continued manual research", request_id=request, confirm_target=True
    )
    assert result["decision"] == "applied"
    assert rows(value["path"], f'SELECT "{field}" FROM "{table}" WHERE "{column}"=\'{owner}\'') == [
        ("Continued manual research",)
    ]
    assert (
        review.load_draft("archived_resume", archived.data["id"])["draft_id"]
        == new_draft["draft_id"]
    )
    assert "Private manual text" in review.export_text(archived)
    assert (
        client_for(value["path"]).journal.pending()[-1]["payload"]["source_document_hash"] is None
    )
    review.close()
