"""Retained research opens its exact original independently of the current PDF."""

import hashlib
import os
import sqlite3
from contextlib import closing
from types import SimpleNamespace

import pytest
from test_enrolled_proposal_packages import union_package as union_package
from test_local_blob_binding import no_external as no_external
from test_local_deck_proposals import local as local
from test_portable_deck_proposal import scientific as scientific

from paper_daily.research_review import Preview, ResearchReview


@pytest.fixture(params=["local", "enrolled"])
def context(union_package, request):
    case = union_package
    if request.param == "local":
        service = ResearchReview(case.sender_db, presentation_root=case.saved.parents[1])
        preview = service.preview("local_deck", case.sender_id)
    else:
        report = case.importer.apply(case.importer.prepare(case.archive))
        service = ResearchReview(case.receiver.journal.path)
        preview = service.preview("enrolled_deck", report["proposal_ids"][0])
    yield SimpleNamespace(service=service, preview=preview, case=case, kind=request.param)
    service.close()


def rows(database):
    with closing(sqlite3.connect(database)) as conn:
        return tuple(conn.iterdump())


def source_bytes(database):
    root = database.parent
    return {
        str(path.relative_to(root)): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file() and (path.suffix == ".pdf" or path.parent.name == "objects")
    }


def test_read_retained_original_uses_exact_A_without_primary_activation_or_research_writes(context):
    from paper_daily import retained_originals

    c = context
    before = rows(c.service.path)
    originals_before = source_bytes(c.service.path)
    proof = retained_originals.prepare(c.service, c.preview, c.case.original_sha)
    assert proof is not None
    assert proof.document_hash == c.case.original_sha
    assert hashlib.sha256(proof.data).hexdigest() == c.case.original_sha
    assert proof.data == c.case.expected["original_bytes"][c.case.original_sha]
    assert retained_originals.metadata_current(proof)
    assert rows(c.service.path) == before
    assert source_bytes(c.service.path) == originals_before
    assert c.case.saved.read_bytes() == c.case.saved_before


def test_unknown_source_or_modified_preview_cannot_read_another_original(context):
    from paper_daily import retained_originals

    before = rows(context.service.path)
    with pytest.raises(ValueError):
        retained_originals.prepare(context.service, context.preview, "a" * 64)
    forged = Preview(context.preview.serialized + " ", context.preview.seal)
    with pytest.raises(ValueError):
        retained_originals.prepare(context.service, forged, context.case.original_sha)
    with closing(ResearchReview(context.service.path)) as other, pytest.raises(ValueError):
        retained_originals.prepare(other, context.preview, context.case.original_sha)
    assert rows(context.service.path) == before


@pytest.mark.parametrize("changed", ["paper", "source_bytes", "proposal", "index"])
def test_prepared_original_invalidates_after_actual_owner_or_source_change(context, changed):
    from paper_daily import retained_originals

    c = context
    proof = retained_originals.prepare(c.service, c.preview, c.case.original_sha)
    if changed == "source_bytes":
        proof.source.write_bytes(proof.data)
    elif changed == "index":
        with closing(sqlite3.connect(proof.storage_root / "index.sqlite")) as conn, conn:
            conn.execute("UPDATE blobs SET complete=0 WHERE digest=?", (proof.document_hash,))
    else:
        from paper_daily import research_generation as generation
        from paper_daily.sync_capture import suppress_capture

        with closing(generation._connect(c.service.path)) as conn, conn, suppress_capture(conn):
            if changed == "paper":
                conn.execute("DELETE FROM papers WHERE id=?", (proof.paper_id,))
            else:
                table = (
                    "research_local_deck_proposals"
                    if c.kind == "local"
                    else "research_enrolled_deck_proposals"
                )
                conn.execute(
                    "DELETE FROM " + table + " WHERE proposal_id=?", (c.preview.data["id"],)
                )
    assert not retained_originals.metadata_current(proof)


def test_cancelled_or_closed_source_open_has_no_result_or_side_effect(context):
    from paper_daily import retained_originals

    c = context
    before = rows(c.service.path)
    assert (
        retained_originals.prepare(
            c.service, c.preview, c.case.original_sha, cancelled=lambda: True
        )
        is None
    )
    proof = retained_originals.prepare(c.service, c.preview, c.case.original_sha)
    c.service.close()
    assert not retained_originals.metadata_current(proof)
    with pytest.raises(ValueError):
        retained_originals.prepare(c.service, c.preview, c.case.original_sha)
    assert rows(c.service.path) == before


def test_metadata_checks_do_not_rehash_read_or_parse_pdf_content(context, monkeypatch):
    from pathlib import Path

    from paper_daily import retained_originals
    from paper_daily.desktop import original_version

    proof = retained_originals.prepare(context.service, context.preview, context.case.original_sha)

    def forbidden(*a, **kw):
        pytest.fail("Metadata check attempted heavy PDF/content I/O")

    monkeypatch.setattr(Path, "read_bytes", forbidden)
    monkeypatch.setattr(original_version.pymupdf, "open", forbidden)
    assert retained_originals.metadata_current(proof)


def test_native_database_replacement_is_rejected_before_opening_the_replacement(
    context, monkeypatch
):
    from paper_daily import retained_originals

    c = context
    proof = retained_originals.prepare(c.service, c.preview, c.case.original_sha)
    replacement = c.service.path.with_name("replacement-original-reader.sqlite")
    with (
        closing(sqlite3.connect(c.service.path)) as source,
        closing(sqlite3.connect(replacement)) as target,
    ):
        source.backup(target)
    original_native = c.service.path.stat().st_ino
    os.replace(replacement, c.service.path)
    assert c.service.path.stat().st_ino != original_native
    opened = []
    connect = retained_originals.sqlite3.connect

    def tracked(*a, **kw):
        opened.append(a[0])
        return connect(*a, **kw)

    monkeypatch.setattr(retained_originals.sqlite3, "connect", tracked)
    assert not retained_originals.metadata_current(proof)
    with pytest.raises(ValueError, match="replaced"):
        retained_originals.prepare(c.service, c.preview, c.case.original_sha)
    assert opened == []


def test_retired_enrolled_original_is_not_reauthorized_by_retained_bytes(union_package):
    from paper_daily import research_generation as generation
    from paper_daily import retained_originals
    from paper_daily.sync_capture import suppress_capture
    from paper_daily.sync_files import file_id

    case = union_package
    report = case.importer.apply(case.importer.prepare(case.archive))
    with closing(ResearchReview(case.receiver.journal.path)) as service:
        preview = service.preview("enrolled_deck", report["proposal_ids"][0])
        proof = retained_originals.prepare(service, preview, case.original_sha)
        portable = proof.proposal.record["portable_id"]
        with closing(generation._connect(service.path)) as conn, conn, suppress_capture(conn):
            conn.execute(
                "UPDATE research_file_desired SET active=0 WHERE entity_id=?",
                (file_id(portable, "original_source", case.original_sha),),
            )
        assert proof.source.read_bytes() == proof.data
        assert not retained_originals.metadata_current(proof)
        with pytest.raises(ValueError):
            retained_originals.prepare(service, preview, case.original_sha)
