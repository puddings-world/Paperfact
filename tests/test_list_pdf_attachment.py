"""List intake preserves original ownership; replacement is a separate action."""

import json

import pytest
from test_legacy_primary_migration import make as make
from test_legacy_primary_migration import pdf
from test_native_pdf_downloads import setup, state
from test_native_primary_publication import enrolled
from test_research_plan import db as db

from paper_daily import cli, fetch, repdf, store
from paper_daily import native_primary_publication as native
from paper_daily.document_reader import from_workspace
from paper_daily.sync_blobs import BlobManifest


def result(added=1):
    return dict(
        added=added,
        paper_ids=["paper"] if added else [],
        already=[] if added else ["paper"],
    )


def roots(fixture, monkeypatch):
    monkeypatch.setattr(repdf, "PDF_DIR", fixture.path.parent)
    monkeypatch.setattr(fetch, "PDF_DIR", fixture.path.parent)


def offered(fixture):
    path = fixture.root / "offered.pdf"
    pdf(path, "A new PDF supplied with list intake")
    return path


@pytest.mark.parametrize("added", [0, 1])
def test_existing_native_original_and_positioned_notes_are_kept(make, monkeypatch, capsys, added):
    fixture = enrolled(make)
    roots(fixture, monkeypatch)
    fixture.path.unlink()  # Reproduce managed storage without a legacy alias.
    anchor = dict(p0=0, o0=0, p1=0, o1=3)
    with store.connect() as conn:
        conn.execute(
            "INSERT INTO notes(paper_id,body,created_at,kind,page,anchor) VALUES(?,?,?,?,?,?)",
            ("paper", "> retained passage", "2026-11-16T00:00:00Z", "note", 1, json.dumps(anchor)),
        )
    before = state(fixture)
    current = from_workspace(fixture.database).resolve("paper")
    original = current.path.read_bytes()
    assert cli._attach_pdf(result(added), str(offered(fixture)))
    assert "kept it" in capsys.readouterr().out
    assert state(fixture) == before and current.path.read_bytes() == original
    assert not fixture.path.exists()
    with store.connect() as conn:
        note = conn.execute("SELECT body,page,anchor FROM notes").fetchone()
        assert (note["body"], note["page"], json.loads(note["anchor"])) == (
            "> retained passage",
            1,
            anchor,
        )


def test_first_native_attachment_uses_shared_publication_and_repeat_keeps_it(make, monkeypatch):
    fixture = setup(make, monkeypatch)
    roots(fixture, monkeypatch)
    chosen = offered(fixture)
    assert cli._attach_pdf(result(), str(chosen))
    after = state(fixture)
    document = from_workspace(fixture.database).resolve("paper")
    assert document.managed and document.path.read_bytes() == chosen.read_bytes()
    assert after["applied"] == after["desired"] and not fixture.path.exists()
    for _ in range(4):
        assert cli._attach_pdf(result(0), str(chosen))
    assert state(fixture) == after


@pytest.mark.parametrize("mode", ["missing", "retired"])
def test_unavailable_managed_history_is_not_replaced_by_list_intake(
    make,
    monkeypatch,
    capsys,
    mode,
):
    fixture = enrolled(make)
    roots(fixture, monkeypatch)
    fixture.path.unlink()
    document = from_workspace(fixture.database).resolve("paper")
    manifest = BlobManifest(document.sha256, state(fixture)["applied"]["size"])
    if mode == "missing":
        fixture.blobs._path(manifest).unlink()
    else:
        operation = fixture.client.new_graph_operation(
            "paper_document",
            fixture.portable,
            {},
            action="delete",
        )
        fixture.client.journal.apply(operation, fixture.client.writer)
    before = state(fixture)
    assert not cli._attach_pdf(result(), str(offered(fixture)))
    assert "synchronization" in capsys.readouterr().out
    assert state(fixture) == before and not fixture.path.exists()


def test_later_native_original_between_cli_check_and_publication_wins(make, monkeypatch):
    fixture = setup(make, monkeypatch)
    roots(fixture, monkeypatch)
    chosen = offered(fixture)
    competing = fixture.root / "competing.pdf"
    pdf(competing, "The concurrently selected original")
    replace = repdf.replace

    def competing_publication(*args, **kwargs):
        assert kwargs["first_only"] is True
        native.run(native.prepare(native.observe(fixture.database, "paper"), competing))
        return replace(*args, **kwargs)

    monkeypatch.setattr(repdf, "replace", competing_publication)
    assert not cli._attach_pdf(result(), str(chosen))
    document = from_workspace(fixture.database).resolve("paper")
    assert document.path.read_bytes() == competing.read_bytes()
    assert not fixture.path.exists()


@pytest.mark.parametrize("ids", [[], ["paper", "other"]])
def test_empty_or_ambiguous_resolution_never_attaches_to_arbitrary_paper(make, monkeypatch, ids):
    fixture = setup(make, monkeypatch)
    roots(fixture, monkeypatch)
    before = state(fixture)
    assert not cli._attach_pdf(
        dict(added=len(ids), paper_ids=ids, already=[]), str(offered(fixture))
    )
    assert state(fixture) == before and not fixture.path.exists()


def test_same_resolved_identity_in_added_and_already_is_not_ambiguous(make, monkeypatch):
    fixture = setup(make, monkeypatch)
    roots(fixture, monkeypatch)
    assert cli._attach_pdf(
        dict(added=1, paper_ids=["paper"], already=["paper"]), str(offered(fixture))
    )
    assert state(fixture)["applied"] is not None


def legacy(db, tmp_path, monkeypatch):
    store.upsert_papers(
        db,
        [
            dict(
                id="paper",
                title="Existing paper",
                venue="Fixture",
                year=2026,
                source="fixture",
            )
        ],
    )
    db.commit()
    root = tmp_path / "pdf"
    root.mkdir()
    monkeypatch.setattr(repdf, "PDF_DIR", root)
    monkeypatch.setattr(fetch, "PDF_DIR", root)
    return root / "paper.pdf"


def test_adding_another_membership_keeps_existing_legacy_original(db, tmp_path, monkeypatch):
    alias = legacy(db, tmp_path, monkeypatch)
    alias.write_bytes(b"existing original")
    assert cli._attach_pdf(result(), str(tmp_path / "not-read.pdf"))
    assert alias.read_bytes() == b"existing original"
    assert not (alias.parent / "replaced").exists()


def test_legacy_first_file_cannot_clobber_original_that_appears_at_install(
    db, tmp_path, monkeypatch
):
    alias = legacy(db, tmp_path, monkeypatch)
    chosen = tmp_path / "offered.pdf"
    pdf(chosen, "Offered first PDF")
    link = repdf.os.link

    def supplied(source, dest):
        alias.write_bytes(b"independently supplied original")
        return link(source, dest)

    monkeypatch.setattr(repdf.os, "link", supplied)
    assert not cli._attach_pdf(result(), str(chosen))
    assert alias.read_bytes() == b"independently supplied original"
    assert not list(alias.parent.glob("*.part"))
    assert not (alias.parent / "replaced").exists()


def test_failed_native_attachment_preserves_existing_research(make, monkeypatch):
    fixture = setup(make, monkeypatch)
    roots(fixture, monkeypatch)
    before = state(fixture)
    invalid = fixture.root / "invalid.pdf"
    invalid.write_bytes(b"%PDF-incomplete")
    assert not cli._attach_pdf(result(), str(invalid))
    assert state(fixture) == before and not fixture.path.exists()


def test_first_legacy_attachment_installs_complete_file_without_replaced_copy(
    db, tmp_path, monkeypatch
):
    alias = legacy(db, tmp_path, monkeypatch)
    chosen = tmp_path / "offered.pdf"
    pdf(chosen, "Complete first legacy original")
    text = tmp_path / "text"
    text.mkdir()
    monkeypatch.setattr(repdf, "TEXT_DIR", text)
    monkeypatch.setattr(fetch, "TEXT_DIR", text)
    monkeypatch.setattr(fetch, "ensure_dirs", lambda: None)
    monkeypatch.setattr(repdf.figures, "extract", lambda *a, **k: [])
    monkeypatch.setattr(repdf, "FIG_DIR", tmp_path / "figures")
    assert cli._attach_pdf(result(), str(chosen))
    assert alias.read_bytes() == chosen.read_bytes()
    assert "Complete first legacy original" in (text / "paper.txt").read_text(encoding="utf-8")
    assert not list(alias.parent.glob("*.part")) and not (alias.parent / "replaced").exists()
