"""Resumed text owns its own read-only source capability, never a deck/claim grant."""

from contextlib import closing

import pytest
from test_archived_draft_resumption import client_for, rows
from test_archived_draft_resumption import copied as copied
from test_archived_draft_resumption import decision as decision
from test_archived_draft_resumption import draft_variants as draft_variants
from test_archived_draft_resumption import source as source

from paper_daily import research_generation as generation
from paper_daily.desktop import original_version


def test_resumed_source_a_opens_readonly_without_publishing_or_replacing_b(copied):
    value = copied
    review = value["review"]
    ready = review.verify_resumed_draft(
        review.resume_draft(value["archived"], value["target"]["id"])
    )
    review.save_draft(ready, "Human text stays intact while inspecting A", "inspect-draft")
    before = client_for(value["path"]).journal.pending()
    body = rows(value["path"], "SELECT body FROM close_readings")
    current = value["current"].path.read_bytes()
    snapshot = original_version.prepare_resumed_draft(review, ready, value["value"]["source_hash"])
    assert snapshot.data == value["value"]["original_bytes"]
    assert snapshot.document_hash == value["value"]["source_hash"] and snapshot.pages == 1
    assert original_version.metadata_current(snapshot)
    assert snapshot.draft_proof is not None
    for name in ("retained_proof", "active_proof", "material_proof", "local_proof"):
        assert getattr(snapshot, name, None) is None
    assert client_for(value["path"]).journal.pending() == before
    assert rows(value["path"], "SELECT body FROM close_readings") == body
    assert value["current"].path.read_bytes() == current
    assert review.load_draft("archived_resume", ready.data["id"])["body"] == (
        "Human text stays intact while inspecting A"
    )
    with closing(generation._connect(value["path"])) as conn:
        assert not conn.execute(
            "SELECT 1 FROM sqlite_master WHERE name='research_review_receipts'"
        ).fetchone()
    review.close()


def prepared(copied):
    review = copied["review"]
    ready = review.verify_resumed_draft(
        review.resume_draft(copied["archived"], copied["target"]["id"])
    )
    snapshot = original_version.prepare_resumed_draft(review, ready, copied["value"]["source_hash"])
    return review, ready, snapshot


def test_gui_admission_has_no_sql_pdf_hash_or_provider_calls(copied, monkeypatch):
    import sqlite3

    from paper_daily import llm, resumed_draft_originals

    review, _ready, snapshot = prepared(copied)

    def forbidden(*_args, **_kwargs):
        raise AssertionError("GUI admission attempted slow work or provider access")

    with monkeypatch.context() as patches:
        patches.setattr(sqlite3, "connect", forbidden)
        patches.setattr(resumed_draft_originals.hashlib, "sha256", forbidden)
        patches.setattr(resumed_draft_originals.pymupdf, "open", forbidden)
        patches.setattr(llm, "capture_connections", forbidden)
        for _index in range(20):
            assert original_version.draft_status(snapshot) == "ready"
            assert original_version.metadata_current(snapshot)
    review.close()
    assert original_version.draft_status(snapshot) == "revoked"


def test_private_draft_save_rechecks_same_base_and_retains_exact_a(copied):
    from paper_daily import resumed_draft_originals

    review, ready, snapshot = prepared(copied)
    before = client_for(copied["path"]).journal.pending()
    review.save_draft(ready, "New private edit while A remains open", "private-edit")
    assert original_version.draft_status(snapshot) == "recheck"
    replacement = resumed_draft_originals.revalidate(snapshot.draft_proof)
    assert replacement.data == snapshot.data
    assert replacement.preview == snapshot.draft_proof.preview
    assert resumed_draft_originals.gui_status(replacement) == "ready"
    assert client_for(copied["path"]).journal.pending() == before
    assert review.load_draft("archived_resume", ready.data["id"])["body"] == (
        "New private edit while A remains open"
    )
    review.close()


@pytest.mark.parametrize("change", ["target", "source_a", "selected_b", "database"])
def test_original_changes_refuse_revalidation_without_recapturing_authority(copied, change):
    import os
    import sqlite3

    from test_sync_source_files import pdf

    from paper_daily import resumed_draft_originals

    review, ready, snapshot = prepared(copied)
    if change == "target":
        with closing(generation._connect(copied["path"])) as conn:
            expected = generation.begin_generation(
                conn, table="close_readings", owner_id=copied["target"]["id"], input_reader="target"
            )
        row = dict(expected.target)
        row["body"] = "New accepted research"
        assert generation.publish_generation(expected, row=row).status == "accepted"
        assert original_version.draft_status(snapshot) == "recheck"
    elif change == "database":
        replacement = copied["path"].with_name("replacement.sqlite")
        with (
            closing(sqlite3.connect(copied["path"])) as old,
            closing(sqlite3.connect(replacement)) as new,
        ):
            old.backup(new)
        os.replace(replacement, copied["path"])
        assert original_version.draft_status(snapshot) == "revoked"
    else:
        path = snapshot.source if change == "source_a" else copied["current"].path
        path.write_bytes(pdf("Changed original bytes"))
        assert original_version.draft_status(snapshot) == "revoked"
    with pytest.raises(ValueError, match="changed|replaced"):
        resumed_draft_originals.revalidate(snapshot.draft_proof)
    if change != "database":
        assert review.export_text(ready, body="Keep this human text")
    review.close()


@pytest.mark.parametrize("choice", ["historical", "unverified", "wrong_pdf"])
def test_only_the_verified_draft_and_its_recorded_a_can_open(copied, choice):
    review = copied["review"]
    selected = review.resume_draft(copied["archived"], copied["target"]["id"])
    before = client_for(copied["path"]).journal.pending()
    if choice == "historical":
        preview = copied["archived"]
        sha = copied["value"]["source_hash"]
    elif choice == "unverified":
        preview = selected
        sha = copied["value"]["source_hash"]
    else:
        preview = review.verify_resumed_draft(selected)
        sha = copied["current"].sha256
    with pytest.raises(ValueError, match="original|recorded|session"):
        original_version.prepare_resumed_draft(review, preview, sha)
    assert client_for(copied["path"]).journal.pending() == before
    review.close()


def test_cancel_before_admission_never_reads_source_or_database(copied, monkeypatch):
    import sqlite3

    review = copied["review"]

    def forbidden(*_args, **_kwargs):
        raise AssertionError("Cancelled source preparation performed I/O")

    monkeypatch.setattr(sqlite3, "connect", forbidden)
    assert (
        original_version.prepare_resumed_draft(
            review, copied["archived"], copied["value"]["source_hash"], cancelled=lambda: True
        )
        is None
    )
    review.close()


def test_failed_final_document_check_does_not_retain_an_orphan_source_capability(
    copied, monkeypatch
):
    from paper_daily import archived_draft_resume

    review = copied["review"]
    selected = review.resume_draft(copied["archived"], copied["target"]["id"])
    before = client_for(copied["path"]).journal.pending()
    original = archived_draft_resume._check_document

    def changed(_document):
        raise ValueError("Selected PDF changed at the final check")

    monkeypatch.setattr(archived_draft_resume, "_check_document", changed)
    with pytest.raises(ValueError, match="final check"):
        review.verify_resumed_draft(selected)
    assert review._resume_sources == {} and review._resume_documents == {}
    assert client_for(copied["path"]).journal.pending() == before
    monkeypatch.setattr(archived_draft_resume, "_check_document", original)
    ready = review.verify_resumed_draft(selected)
    snapshot = original_version.prepare_resumed_draft(review, ready, copied["value"]["source_hash"])
    assert snapshot.data == copied["value"]["original_bytes"]
    assert client_for(copied["path"]).journal.pending() == before
    review.close()
