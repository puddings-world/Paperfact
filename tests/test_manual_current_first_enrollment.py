"""Actual first-enrollment acceptance, not a synthetic producer/revision receipt."""

import copy
import hashlib
import json
import sqlite3
from contextlib import closing
from pathlib import Path
from uuid import uuid4

import pymupdf
from test_local_blob_binding import no_external as no_external
from test_portable_deck_proposal import scientific as scientific

from paper_daily import enrolled_deck_proposals as general
from paper_daily import local_deck_proposals as local
from paper_daily import portable_deck_proposal as content
from paper_daily import presentations, store
from paper_daily.document_reader import from_workspace
from paper_daily.fetch import _safe_name
from paper_daily.research_file_review import _storage
from paper_daily.research_review import ResearchReview
from paper_daily.sync_artifacts import desired_file, verify_closure
from paper_daily.sync_deck_publication import load_managed_deck, publication_scope, runtime
from paper_daily.sync_files import file_id
from paper_daily.sync_source_files import input_versions
from paper_daily.workspace_enrollment import EnrollmentBlocked, EnrollmentService


def sha(data):
    return hashlib.sha256(data).hexdigest()


def native(path):
    stat = path.stat()
    return stat.st_dev, stat.st_ino


def rows(database):
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


def tree(root):
    return {
        path.relative_to(root).as_posix(): sha(path.read_bytes())
        for path in root.rglob("*")
        if path.is_file()
    }


def test_public_first_enrollment_keeps_manual_current_editable_and_common_proposal_inactive(
    tmp_path, monkeypatch, scientific
):
    source = tmp_path / "source"
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
                    title="Local manual paper",
                    venue="Fixture",
                    year=2026,
                    source="fixture",
                )
            ],
        )
        conn.execute(
            "INSERT INTO notes(paper_id,body,created_at) VALUES(?,?,?)",
            ("local-paper", "Keep this saved note", "2026-11-01T00:00:00+00:00"),
        )
        conn.commit()
    monkeypatch.setattr(store, "DB_PATH", database)
    monkeypatch.setattr(presentations, "DECK_DIR", source / "presentations")
    deck, evidence, images, originals, original_a, primary_b = scientific
    current = copy.deepcopy(deck)
    current.paper_id = "local-paper"
    current.title = "Plain manually saved current deck"
    current.deck_id = str(uuid4())
    current._revision_figures = copy.deepcopy(images)  # Real editor-supplied in-memory PNGs.
    saved = presentations.save_deck(current)
    saved_bytes = saved.read_bytes()
    saved_json = json.loads(saved_bytes)
    assert saved == source / "presentations" / sha(b"local-paper")[:24] / "guide.json"
    assert len(saved_json["figures"]) == 3
    assert saved_json["figures"][-1]["caption"] == "Full unused caption"
    assert saved_json["figures"][-1]["file"] == "C:/private/cache.png"
    assert "asset" not in saved_json["figures"][-1]
    used = {row["id"]: row for row in saved_json["figures"] if row.get("asset")}
    assert len(used) == 2
    for identity, figure in used.items():
        assert (saved.parent / "assets" / figure["asset"]).read_bytes() == images[identity]
    assert not list(source.rglob(".revision-requests"))

    images["evidence:four"] = pymupdf.Pixmap(
        pymupdf.csRGB, 2, 2, b"\x21\x43\x65" * 4, False
    ).tobytes("png")
    evidence["figures"].append(
        dict(
            id="evidence:four",
            label="Fourth retained evidence",
            caption="Exact evidence-only fourth image",
            page=1,
            document_hash=original_a,
        )
    )
    manifest, blobs = content.encode(
        deck, evidence, images, originals, source_document_hash=original_a
    )
    prepared = local.prepare(
        database,
        "local-paper",
        manifest,
        lambda item: blobs[item["sha256"]],
        request_id="manual-first-proposal",
        expected_native=native(database),
    )
    proposal_id = local.retain(prepared)
    expected = local.read(database, proposal_id, expected_native=native(database)).content
    primary_dir = source / "pdf"
    primary_dir.mkdir()
    primary = primary_dir / (_safe_name("local-paper") + ".pdf")
    primary.write_bytes(primary_b)
    assert sha(primary_b) != original_a and len(expected["image_bytes"]) == 4
    assert set(expected["original_bytes"]) == {original_a}
    source_before, bytes_before, files_before = rows(database), database.read_bytes(), tree(source)
    output, backup = tmp_path / "editable", tmp_path / "enrollment.zip"
    service = EnrollmentService(database)
    plan = service.plan(pdfs={"local-paper": primary})
    result, error = None, None
    try:
        # Exercise the actual public guarded Prepare even if read-only Plan refuses.
        result = service.prepare(
            output, backup_output=backup, request_id=str(uuid4()), pdfs={"local-paper": primary}
        )
    except EnrollmentBlocked as refused:
        error = {"type": type(refused).__name__, "report": refused.plan}
    observed = dict(
        plan=plan,
        prepare_error=error,
        result=result,
        source_rows_unchanged=rows(database) == source_before,
        source_database_bytes_unchanged=database.read_bytes() == bytes_before,
        source_files_unchanged=tree(source) == files_before,
        saved_json_sha256=sha(saved_bytes),
        saved_used_asset_count=len(used),
        common_image_count=len(expected["image_bytes"]),
        original_a=original_a,
        primary_b=sha(primary_b),
        output_exists=output.exists(),
        backup_exists=backup.exists(),
    )
    (tmp_path / "observed.json").write_text(json.dumps(observed, indent=2), encoding="utf-8")
    assert rows(database) == source_before and database.read_bytes() == bytes_before
    assert tree(source) == files_before and saved.read_bytes() == saved_bytes
    assert local.read(database, proposal_id, expected_native=native(database)).content == expected
    assert plan["supported"], plan["blockers"]
    assert error is None and result["status"] == "prepared_for_review"

    receiver = Path(result["database"])
    client = runtime(database=receiver)
    with client.journal.transaction() as conn:
        portable = conn.execute(
            "SELECT sync_id FROM research_paper_identity WHERE local_id=?", ("local-paper",)
        ).fetchone()[0]
        operation = desired_file(conn, file_id(portable, "deck", "guide"))
        cache = _storage(conn)[0]
        tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master")}
        for name in ("research_generation_requests", "research_compound_requests"):
            if name in tables:
                assert conn.execute('SELECT count(*) FROM "' + name + '"').fetchone()[0] == 0
    # Original manual science is archived independently from used-figure active wire.
    from paper_daily import enrollment_history
    from paper_daily import proposal_recovery_current as observed_current
    from paper_daily.sync_blobs import BlobManifest

    with client.journal.transaction() as conn:
        archived = [
            enrollment_history.validate(row)[0]
            for row in enrollment_history.archived(conn)
            if row["protocol"] == observed_current.TABLE
        ]
    assert len(archived) == 1
    original_manual = observed_current.read(
        archived[0],
        lambda item: cache.verified_path(BlobManifest(item["sha256"], item["size"])).read_bytes(),
    )
    assert original_manual["raw"] == saved_json
    assert original_manual["evidence"] is None and original_manual["input_provenance"] == "unknown"
    assert original_manual["publish"] is False and len(original_manual["images"]) == 2
    assert original_manual["raw"]["figures"][-1]["caption"] == "Full unused caption"
    assert operation is not None and operation["payload"]["input_versions"] == input_versions()
    assert operation["payload"]["source_document_hash"] is None
    body = verify_closure(cache, operation)[1]
    assert body["deck"]["title"] == saved_json["title"]
    with publication_scope(client):
        managed, restored = load_managed_deck("local-paper", "guide")
        assert managed and restored is not None and restored.title == saved_json["title"]
        for identity in used:
            assert presentations.figure_bytes(restored, identity) == images[identity]
        restored.title = "Explicit manual edit after first enrollment"
        presentations.save_deck(restored, request_id="manual-first-edit")
        assert load_managed_deck("local-paper", "guide")[1].title == restored.title
    reader = from_workspace(receiver)
    try:
        document = reader.resolve("local-paper")
        assert document.available and document.sha256 == sha(primary_b)
    finally:
        reader.close()
    review = ResearchReview(receiver)
    try:
        entries = [
            row for row in review.page(limit=100)["items"] if row["origin"] == "enrolled_deck"
        ]
        assert len(entries) == 1
        verified = review.prepare_file(review.preview("enrolled_deck", entries[0]["id"]))
        retained = general.read(
            client, cache, verified.data["id"], expected_native=native(receiver)
        )
        assert retained.content == expected and len(retained.content["image_bytes"]) == 4
        assert verified.data["current"]["title"] == "Explicit manual edit after first enrollment"
        assert verified.data["current"]["title"] != expected["deck"]["title"]
    finally:
        review.close()
    assert rows(database) == source_before and tree(source) == files_before
