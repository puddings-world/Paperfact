"""Apply a retained deck through its reviewed base, without regenerating AI output."""

import json
import sqlite3
from contextlib import closing

import pytest
from test_sync_files import LOCAL, save_current
from test_sync_files import codec as codec_fixture
from test_sync_files import pair as pair_fixture

from paper_daily import presentations, store
from paper_daily.research_review import ResearchReview
from paper_daily.sync_deck_publication import StaleDeckError

codec = codec_fixture
pair = pair_fixture


@pytest.fixture
def retained(pair, codec):
    save_current(pair, codec[0])
    first = presentations.load_deck(LOCAL, "guide")
    stale = presentations.load_deck(LOCAL, "guide")
    first.title = "Current manual version"
    presentations.save_deck(first)
    stale.title = "Retained reviewed version"
    stale.slides[0].speaker_notes = "Retained explanation"
    with pytest.raises(StaleDeckError) as raised:
        presentations.save_deck(stale)
    return pair[1], raised.value.candidate_id


def test_explicit_retained_deck_review_applies_editable_sources_once(retained):
    client, identity = retained
    review = ResearchReview(client.journal.path)
    initial = review.preview("file", identity)
    assert not initial.data["apply"]
    before = client.journal.pending()
    displayed = review.prepare_file(initial)
    assert displayed.data["apply"] and not displayed.data["editable"]
    assert displayed.data["requires_confirmation"]
    assert displayed.data["current"]["title"] == "Current manual version"
    assert displayed.data["retained"]["title"] == "Retained reviewed version"
    assert client.journal.pending() == before
    with pytest.raises(ValueError, match="Confirm"):
        review.decide(displayed, request_id="review-file-one")
    result = review.decide(displayed, request_id="review-file-one", confirm_target=True)
    assert result == {"decision": "applied", "operation_id": "review-file-one"}
    assert len(client.journal.pending()) == len(before) + 1
    reopened = presentations.load_deck(LOCAL, "guide")
    assert reopened.title == "Retained reviewed version"
    assert reopened.slides[0].speaker_notes == "Retained explanation"
    assert reopened.slides[0].elements[2]["text"] == "Editable"
    assert presentations.figure_bytes(reopened, "figure:1")
    assert presentations.figure_bytes(reopened, "figure:2")
    presentations.save_deck(reopened)
    newer = client.journal.pending()
    assert review.decide(displayed, request_id="review-file-one", confirm_target=True) == result
    assert client.journal.pending() == newer
    with closing(sqlite3.connect(client.journal.path)) as conn:
        assert conn.execute(
            "SELECT count(*) FROM research_file_candidates WHERE candidate_id=?", (identity,)
        ).fetchone() == (1,)
        assert conn.execute(
            "SELECT count(*) FROM research_review_receipts WHERE request_id=?", ("review-file-one",)
        ).fetchone() == (1,)
    text = json.loads(review.export_text(displayed))
    assert text["content"]["title"] == "Retained reviewed version"
    assert "database_identity" not in json.dumps(text)


def prepared(retained):
    client, identity = retained
    review = ResearchReview(client.journal.path)
    return client, identity, review, review.prepare_file(review.preview("file", identity))


@pytest.mark.parametrize("change", ["save", "inputs", "paper", "parent_aba"])
def test_displayed_base_changes_preserve_both_decks(retained, change):
    client, identity, review, preview = prepared(retained)
    if change == "save":
        current = presentations.load_deck(LOCAL, "guide")
        current.title = "Even newer manual version"
        presentations.save_deck(current)
    else:
        with client.journal.transaction() as conn:
            if change == "inputs":
                conn.execute("INSERT INTO notes(paper_id,body,created_at) VALUES(?,?,?)",
                             (LOCAL, "New analysis input", "2026-11-01T00:00:00Z"))
            elif change == "paper":
                conn.execute("UPDATE papers SET title='Changed title' WHERE id=?", (LOCAL,))
            else:
                row = conn.execute("SELECT * FROM papers WHERE id=?", (LOCAL,)).fetchone()
                columns = [c[1] for c in conn.execute("PRAGMA table_info(papers)")]
                conn.execute("DELETE FROM papers WHERE id=?", (LOCAL,))
                conn.execute("INSERT INTO papers VALUES("+",".join("?" for _ in columns)+")", row)
    pending = client.journal.pending()
    with pytest.raises(ValueError, match="changed|lifecycle|active"):
        review.decide(preview, request_id="reject-late", confirm_target=True)
    assert client.journal.pending() == pending
    with closing(sqlite3.connect(client.journal.path)) as conn:
        assert conn.execute("SELECT payload FROM research_file_candidates WHERE candidate_id=?",
                            (identity,)).fetchone()
        assert conn.execute("SELECT count(*) FROM research_file_versions WHERE operation_id=?",
                            ("reject-late",)).fetchone() == (0,)


@pytest.mark.parametrize("change", ["missing", "corrupt", "replace_same_bytes"])
def test_candidate_assets_are_rechecked_before_apply(retained, change):
    client, _, review, preview = prepared(retained)
    from pathlib import Path
    filename = next(iter(preview.data["expected"]["files"]))
    path = Path(filename)
    old = path.read_bytes()
    if change == "missing":
        path.unlink()
    elif change == "corrupt":
        path.write_bytes(b"x" * len(old))
    else:
        path.rename(path.with_suffix(".old"))
        path.write_bytes(old)
    pending = client.journal.pending()
    with pytest.raises((ValueError, OSError)):
        review.decide(preview, request_id="bad-assets", confirm_target=True)
    assert client.journal.pending() == pending


def test_receipt_failure_rolls_back_operation_and_activation_then_retry(retained, monkeypatch):
    client, _, review, preview = prepared(retained)
    pending = client.journal.pending()
    receipt = review._receipt
    def fail(*args):
        raise sqlite3.OperationalError("injected receipt failure")
    monkeypatch.setattr(review, "_receipt", fail)
    with pytest.raises(sqlite3.OperationalError, match="receipt failure"):
        review.decide(preview, request_id="atomic-file", confirm_target=True)
    assert client.journal.pending() == pending
    assert presentations.load_deck(LOCAL, "guide").title == "Current manual version"
    monkeypatch.setattr(review, "_receipt", receipt)
    review.decide(preview, request_id="atomic-file", confirm_target=True)
    assert presentations.load_deck(LOCAL, "guide").title == "Retained reviewed version"
    assert len(client.journal.pending()) == len(pending) + 1


def test_materialization_failure_changes_no_research_and_retry_succeeds(retained, monkeypatch):
    from paper_daily import sync_artifacts
    client, _, review, preview = prepared(retained)
    pending = client.journal.pending()
    materialize = sync_artifacts.materialize
    def fail(*args):
        raise OSError("injected disk failure")
    monkeypatch.setattr(sync_artifacts, "materialize", fail)
    with pytest.raises(OSError, match="disk failure"):
        review.decide(preview, request_id="retry-file", confirm_target=True)
    assert client.journal.pending() == pending
    assert presentations.load_deck(LOCAL, "guide").title == "Current manual version"
    monkeypatch.setattr(sync_artifacts, "materialize", materialize)
    review.decide(preview, request_id="retry-file", confirm_target=True)
    assert presentations.load_deck(LOCAL, "guide").title == "Retained reviewed version"


@pytest.mark.parametrize("change", ["close", "database_replace", "foreign_preview"])
def test_original_session_and_database_identity_guard_apply(retained, change):
    client, _, review, preview = prepared(retained)
    pending = client.journal.pending()
    if change == "close":
        review.close()
    elif change == "database_replace":
        path = client.journal.path
        path.rename(path.with_suffix(".old"))
        path.write_bytes(path.with_suffix(".old").read_bytes())
    else:
        review = ResearchReview(client.journal.path)
    with pytest.raises(ValueError, match="closed|replaced|another"):
        review.decide(preview, request_id="wrong-owner", confirm_target=True)
    assert client.journal.pending() == pending


def test_global_workspace_switch_cannot_redirect_file_application(retained, pair, monkeypatch):
    client, _, review, preview = prepared(retained)
    other = pair[2]
    before = other.journal.pending()
    monkeypatch.setattr(store, "DB_PATH", other.journal.path)
    review.decide(preview, request_id="original-file", confirm_target=True)
    assert other.journal.pending() == before
    monkeypatch.setattr(store, "DB_PATH", client.journal.path)
    assert presentations.load_deck(LOCAL, "guide").title == "Retained reviewed version"


def test_keep_without_preparation_does_not_publish_and_rejects_raw_deck_edit(retained):
    client, identity = retained
    review = ResearchReview(client.journal.path)
    preview = review.preview("file", identity)
    pending = client.journal.pending()
    result = review.decide(preview, keep=True, request_id="keep-file")
    assert result["decision"] == "kept" and client.journal.pending() == pending
    preview = review.prepare_file(preview)
    with pytest.raises(ValueError, match="typed deck"):
        review.decide(preview, body="arbitrary JSON", request_id="bad-text", confirm_target=True)
    assert client.journal.pending() == pending


def test_duplicate_requests_publish_once_after_restart_and_keep_newer_edits(retained):
    from concurrent.futures import ThreadPoolExecutor
    client, identity, review, preview = prepared(retained)
    pending = client.journal.pending()
    def apply():
        return review.decide(preview, request_id="duplicate-file", confirm_target=True)
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: apply(), range(8)))
    assert all(r == results[0] for r in results)
    assert len(client.journal.pending()) == len(pending) + 1
    reopened = ResearchReview(client.journal.path)
    assert reopened.page()["items"][0]["id"] == identity
    assert presentations.load_deck(LOCAL, "guide").title == "Retained reviewed version"


@pytest.mark.parametrize("change", ["newer_write", "close"])
def test_change_during_file_materialization_never_commits_stale_result(
    retained, monkeypatch, change
):
    from paper_daily import sync_artifacts
    client, _, review, preview = prepared(retained)
    materialize = sync_artifacts.materialize
    marker = []
    def changing(*args):
        monkeypatch.setattr(sync_artifacts, "materialize", materialize)
        result = materialize(*args)
        if change == "close":
            review.close()
        else:
            current = presentations.load_deck(LOCAL, "guide")
            current.title = "Saved while materializing"
            presentations.save_deck(current)
        marker.extend(client.journal.pending())
        return result
    monkeypatch.setattr(sync_artifacts, "materialize", changing)
    with pytest.raises(ValueError, match="changed|closed"):
        review.decide(preview, request_id="during-file", confirm_target=True)
    assert client.journal.pending() == marker
    expected = "Current manual version" if change == "close" else "Saved while materializing"
    assert presentations.load_deck(LOCAL, "guide").title == expected


def test_retained_deck_keeps_original_pdf_a_when_primary_is_b(pair, codec):
    import hashlib

    import pymupdf
    from test_sync_files import PAPER

    from paper_daily.sync_artifacts import stage_bytes
    from paper_daily.sync_blobs import BlobManifest
    from paper_daily.sync_deck_publication import observe_deck, publish_deck
    from paper_daily.sync_documents import (
        applied_document,
        bind_verified_document,
        desired_document,
        verify_document,
    )
    client, blob_store = pair[1], pair[3].store
    def attach(text):
        with pymupdf.open() as pdf:
            pdf.new_page().insert_text((40, 40), text)
            raw = pdf.tobytes()
        sha = hashlib.sha256(raw).hexdigest()
        stage_bytes(blob_store, {sha: raw})
        operation = client.new_graph_operation("paper_document", PAPER, {
            "paper_id": PAPER, "sha256": sha, "size": len(raw), "media_type": "application/pdf"})
        client.save(operation)
        with client.journal.transaction() as conn:
            target = desired_document(conn, PAPER)
        verified = verify_document(blob_store, target)
        with client.journal.transaction() as conn:
            assert bind_verified_document(conn, target, verified)
        return target, raw
    target_a, bytes_a = attach("Original A used by the slides")
    value = codec[0]
    value.paper_id = LOCAL
    value.source_hash = "evidence-a"
    sources = [dict(row, document_hash=target_a["sha256"]) for row in value.sources]
    publish_deck(value, observation=observe_deck(LOCAL, "guide"), evidence={
        "sources": sources, "coverage": [], "source_hash": "evidence-a"})
    stale = presentations.load_deck(LOCAL, "guide")
    target_b, bytes_b = attach("Current primary B")
    current = presentations.load_deck(LOCAL, "guide")
    current.title = "Current uses historical A too"
    presentations.save_deck(current)
    stale.title = "Retained scientific result from A"
    with pytest.raises(StaleDeckError) as raised:
        presentations.save_deck(stale)
    review = ResearchReview(client.journal.path)
    preview = review.prepare_file(review.preview("file", raised.value.candidate_id))
    assert preview.data["source_hash"] == target_a["sha256"]
    review.decide(preview, request_id="historical-a", confirm_target=True)
    operation = client.journal.pending()[-1]
    assert operation["payload"]["source_document_hash"] == target_a["sha256"]
    assert (operation["payload"]["input_versions"]["documents"][0]["operation_id"]
            == target_a["operation_id"])
    with client.journal.transaction() as conn:
        assert applied_document(conn, PAPER) == target_b
    assert (blob_store.verified_path(BlobManifest(target_a["sha256"], len(bytes_a))).read_bytes()
            == bytes_a)
    assert (blob_store.verified_path(BlobManifest(target_b["sha256"], len(bytes_b))).read_bytes()
            == bytes_b)
    assert presentations.load_deck(LOCAL, "guide").title == "Retained scientific result from A"


def test_enrolled_capture_apply_has_one_shared_operation_and_one_receipt(retained, monkeypatch):
    from paper_daily.sync_capture import install
    client, identity = retained
    monkeypatch.setattr(store, "ensure_dirs", lambda: None)
    with store.connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        install(conn, workspace_id="workspace", device_id="a")
    review = ResearchReview(client.journal.path)
    preview = review.prepare_file(review.preview("file", identity))
    pending = client.journal.pending()
    review.decide(preview, request_id="captured-file", confirm_target=True)
    assert len(client.journal.pending()) == len(pending) + 1
    assert client.journal.pending()[-1]["operation_id"] == "captured-file"
    with closing(sqlite3.connect(client.journal.path)) as conn:
        assert conn.execute("SELECT count(*) FROM research_review_receipts").fetchone() == (1,)
        assert conn.execute("SELECT count(*) FROM research_file_versions WHERE operation_id=?",
                            ("captured-file",)).fetchone() == (1,)
    assert presentations.load_deck(LOCAL, "guide").title == "Retained reviewed version"


@pytest.mark.parametrize("change", ["registration", "index_replaced"])
def test_registered_storage_changes_reject_without_new_operation(retained, change, tmp_path):
    from pathlib import Path
    client, _, review, preview = prepared(retained)
    pending = client.journal.pending()
    with client.journal.transaction() as conn:
        registration = conn.execute(
            "SELECT blob_root FROM research_file_paths WHERE id=1").fetchone()
    if change == "registration":
        replacement = tmp_path / "other-versions"
        replacement.mkdir()
        with client.journal.transaction() as conn:
            conn.execute("UPDATE research_file_paths SET version_root=? WHERE id=1",
                         (str(replacement),))
    else:
        index = Path(registration[0]) / "index.sqlite"
        old = index.with_suffix(".previous")
        index.rename(old)
        index.write_bytes(old.read_bytes())
    with pytest.raises(ValueError, match="storage changed"):
        review.decide(preview, request_id="moved-store", confirm_target=True)
    assert client.journal.pending() == pending


def test_deleted_deck_requires_explicit_restoration_and_keeps_retained_history(retained):
    from test_sync_files import PAPER

    from paper_daily.sync_artifacts import desired_file
    from paper_daily.sync_files import file_id
    client, identity = retained
    entity = file_id(PAPER, "deck", "guide")
    deletion = client.new_graph_operation("research_file", entity, {}, action="delete")
    client.save(deletion)
    review = ResearchReview(client.journal.path)
    preview = review.prepare_file(review.preview("file", identity))
    assert preview.data["current"] is None
    assert preview.data["target"]["restoring"] is True
    pending = client.journal.pending()
    with pytest.raises(ValueError, match="Confirm"):
        review.decide(preview, request_id="restore-file")
    assert client.journal.pending() == pending
    result = review.decide(preview, request_id="restore-file", confirm_target=True)
    assert result["operation_id"] == "restore-file"
    restored = client.journal.pending()[-1]
    assert restored["incarnation"] != deletion["incarnation"]
    assert restored["action"] == "put"
    assert len(client.journal.pending()) == len(pending) + 1
    with client.journal.transaction() as conn:
        assert desired_file(conn, entity) == restored
        assert conn.execute("SELECT count(*) FROM research_file_candidates WHERE candidate_id=?",
                            (identity,)).fetchone()[0] == 1
    assert presentations.load_deck(LOCAL, "guide").title == "Retained reviewed version"
    assert review.decide(preview, request_id="restore-file", confirm_target=True) == result
    assert len(client.journal.pending()) == len(pending) + 1
