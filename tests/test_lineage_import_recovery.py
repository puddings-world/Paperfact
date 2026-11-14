"""Real imported Lineage archives preserve science/history/bytes without old grants."""

import hashlib
import json
import sqlite3
import zipfile
from contextlib import closing
from uuid import uuid4

import pytest
from lineage_package_fixture import lineage_archive as lineage_archive
from test_lineage_jobs import work
from test_lineage_package_publish import apply, observe_in
from test_lineage_package_publish import incoming as incoming
from test_sync_recovery import archive_rows, rewrite

from paper_daily import lineage_import_originals, lineage_sets, llm, source_snapshots, sync_recovery
from paper_daily import lineage_package_publish as publisher
from paper_daily import lineage_package_targets as targets
from paper_daily.manual_highlight_ops import capture_owner


@pytest.fixture
def imported(incoming, monkeypatch):
    work(apply, incoming)
    monkeypatch.setattr(
        llm, "complete_result", lambda *_a, **_k: pytest.fail("Archive-only operation")
    )
    return incoming


def test_actual_backup_restore_preserves_report_native_provenance_and_all_peer_pdfs(
    imported, tmp_path
):
    database = imported[0]
    output = tmp_path / "imported.zip"
    before = database.read_bytes()
    manifest = sync_recovery.create(database, output)
    assert database.read_bytes() == before
    assert sync_recovery.inspect(output) == manifest
    rows = archive_rows(output, publisher.TABLE)
    with closing(sqlite3.connect(database)) as conn:
        native = [
            dict(request_id=r[0], body_json=r[1])
            for r in conn.execute("SELECT * FROM " + publisher.TABLE)
        ]
    assert rows == native
    assert archive_rows(output, lineage_sets.TABLE) == lineage_sets.saved(
        database, "receiver-focal"
    )
    body = publisher.validate_record(rows[0])
    originals = body["records"][0]["sources"]
    with zipfile.ZipFile(output) as archive:
        for original in originals:
            assert (
                archive.read("objects/" + original["sha256"])
                == source_snapshots.source_path(database, original).read_bytes()
            )
    destination = tmp_path / "restored"
    sync_recovery.restore_detached(output, destination)
    restored = destination / "papers.db"
    assert lineage_sets.saved(restored, "receiver-focal") == lineage_sets.saved(
        database, "receiver-focal"
    )
    with closing(sqlite3.connect(restored)) as conn:
        names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert not names & {
            publisher.TABLE,
            "research_local_source_owners",
            "paperfact_sync_identity",
            "research_generation_requests",
        }
        archived = [
            json.loads(r[0])
            for r in conn.execute(
                "SELECT data FROM recovery_records WHERE table_name=?", (publisher.TABLE,)
            )
        ]
    assert archived == rows
    for original in originals:
        assert (
            destination / "objects" / original["sha256"]
        ).read_bytes() == source_snapshots.source_path(database, original).read_bytes()
    row = lineage_sets.saved(restored, "receiver-focal")[0]
    assert not lineage_import_originals.has_record(restored, row)
    owner = capture_owner(restored, "receiver-focal")
    selected = lineage_sets.decode(row["body_json"])["report"]["sources"][0]
    with pytest.raises(ValueError, match="current native receipt"):
        work(lineage_import_originals.prepare, owner, row, selected["id"])


@pytest.mark.parametrize(
    "broken", ["action", "association", "source-hash", "pdf", "history-budget"]
)
def test_missing_or_changed_source_closure_leaves_no_incomplete_archive(
    imported, tmp_path, broken, monkeypatch
):
    database = imported[0]
    with closing(sqlite3.connect(database)) as conn, conn:
        if broken == "action":
            conn.execute("DELETE FROM research_lineage_imports")
        elif broken == "association":
            conn.execute(
                "DELETE FROM research_local_source_owners WHERE request_id="
                "(SELECT request_id FROM research_local_source_owners LIMIT 1)"
            )
        elif broken == "source-hash":
            conn.execute("UPDATE research_local_source_owners SET sha256=?", ("0" * 64,))
        elif broken == "history-budget":
            monkeypatch.setattr(publisher, "MAX_HISTORY", 1)
    if broken == "pdf":
        from pathlib import Path

        Path(imported[5]._files[0][2]).unlink()
    with closing(sqlite3.connect(database)) as conn:
        before = list(conn.iterdump())
    output = tmp_path / "refuse.zip"
    with pytest.raises((ValueError, OSError)):
        sync_recovery.create(database, output)
    assert not output.exists()
    with closing(sqlite3.connect(database)) as conn:
        assert list(conn.iterdump()) == before


def test_explicit_replacement_keeps_both_actions_and_displaced_scientific_data(imported, tmp_path):
    database = imported[0]
    changed = dict(
        lineage_sets.saved(database, "receiver-focal")[0], written_at="2026-10-01T00:00:00+00:00"
    )
    staged = work(
        publisher.stage,
        database,
        imported[4],
        imported[3],
        request_id=str(uuid4()),
        expected_native=imported[1],
    )

    def replace_saved():
        with closing(sqlite3.connect(database)) as conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute("UPDATE paper_lineage_sets SET written_at=?", (changed["written_at"],))
            observed = observe_in(conn, imported)
            publisher.publish_in(conn, staged, observed, replace=True)
            conn.commit()

    work(replace_saved)
    output = tmp_path / "history.zip"
    sync_recovery.create(database, output)
    actions = archive_rows(output, publisher.TABLE)
    assert len(actions) == 2
    bodies = [publisher.validate_record(row) for row in actions]
    assert changed in [
        json.loads(item["before_json"]) for body in bodies for item in body["records"]
    ]
    assert len(archive_rows(output, "research_local_source_owners")) == 6
    sync_recovery.restore_detached(output, tmp_path / "history-restored")
    with closing(sqlite3.connect(tmp_path / "history-restored" / "papers.db")) as conn:
        archived = [
            json.loads(r[0])
            for r in conn.execute(
                "SELECT data FROM recovery_records WHERE table_name=?", (publisher.TABLE,)
            )
        ]
    assert archived == actions


def mutate_table(manifest, files, name, change):
    key = "tables/" + name + ".jsonl"
    rows = [json.loads(line) for line in files[key].splitlines()]
    change(rows)
    data = b"".join(
        (json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n").encode() for row in rows
    )
    files[key] = data
    entry = next(t for t in manifest["tables"] if t["name"] == name)
    entry.update(count=len(rows), size=len(data), sha256=hashlib.sha256(data).hexdigest())


def test_valid_container_hashes_do_not_excuse_missing_or_foreign_original_association(
    imported, tmp_path
):
    original = tmp_path / "valid.zip"
    sync_recovery.create(imported[0], original)

    def mutation(manifest, files):
        mutate_table(manifest, files, "research_local_source_owners", lambda rows: rows.pop())

    broken = rewrite(original, tmp_path / "broken.zip", mutation)
    with pytest.raises(ValueError, match="exact original association"):
        sync_recovery.inspect(broken)
    destination = tmp_path / "must-not-exist"
    with pytest.raises(ValueError):
        sync_recovery.restore_detached(broken, destination)
    assert not destination.exists()


def replaced_versions(imported, tmp_path):
    from uuid import UUID

    import test_lineage_target_jobs
    from test_lineage_packages import package
    from test_lineage_recovery import published
    from test_research_evidence import pdf
    from test_research_lineage import PRIOR, corpus

    from paper_daily import lineage_packages, research_lineage

    database = imported[0]
    old = lineage_sets.saved(database, "receiver-focal")[0]
    sender = tmp_path / "versioned-sender"
    sender.mkdir()
    initial = corpus.__wrapped__(sender)
    pdf(initial[1] / "prior.pdf", [[PRIOR, "New source version retaining the quoted evidence."]])
    captured = research_lineage.capture(
        initial[0], "focal", ["prior", "later"], legacy_root=initial[1]
    )
    with pytest.MonkeyPatch.context() as patch:
        identities = iter([UUID(old["corpus_key"]), uuid4()])
        patch.setattr(test_lineage_target_jobs, "uuid4", lambda: next(identities))
        published((initial[0], initial[1], captured), patch)
        exported = work(lineage_packages.collect, initial[0], ["focal"])
    output = tmp_path / "new-version.zip"
    manifest, tables = package(exported, output)
    with zipfile.ZipFile(output) as archive:
        validated = work(targets.validate, archive, manifest, tables)
    staged = work(
        publisher.stage,
        database,
        validated,
        imported[3],
        request_id=str(uuid4()),
        expected_native=imported[1],
    )

    def replace_report():
        with closing(sqlite3.connect(database)) as conn:
            conn.execute("BEGIN IMMEDIATE")
            observed = targets.observe_in(conn, validated, imported[3], expected_native=imported[1])
            publisher.publish_in(conn, staged, observed, replace=True)
            conn.commit()

    work(replace_report)
    new = lineage_sets.saved(database, "receiver-focal")[0]
    assert new["corpus_key"] == old["corpus_key"] and new["source_hash"] != old["source_hash"]
    return old, new


def test_source_version_replacement_restores_both_exact_pdf_sets_and_displaced_quotes(
    imported, tmp_path
):
    old, new = replaced_versions(imported, tmp_path)
    output = tmp_path / "versions.zip"
    sync_recovery.create(imported[0], output)
    actions = [publisher.validate_record(row) for row in archive_rows(output, publisher.TABLE)]
    assert len(actions) == 2
    assert old in [
        json.loads(item["before_json"]) for action in actions for item in action["records"]
    ]
    all_originals = [
        original for action in actions for item in action["records"] for original in item["sources"]
    ]
    assert len({r["sha256"] for r in all_originals}) >= 4
    with zipfile.ZipFile(output) as archive:
        for original in all_originals:
            assert (
                archive.read("objects/" + original["sha256"])
                == source_snapshots.source_path(imported[0], original).read_bytes()
            )
    destination = tmp_path / "versions-restored"
    sync_recovery.restore_detached(output, destination)
    assert lineage_sets.saved(destination / "papers.db", "receiver-focal") == [new]
    with closing(sqlite3.connect(destination / "papers.db")) as conn:
        retained = [
            json.loads(r[0])
            for r in conn.execute(
                "SELECT data FROM recovery_records WHERE table_name=?", (publisher.TABLE,)
            )
        ]
    assert retained == archive_rows(output, publisher.TABLE)
    for original in all_originals:
        assert (
            destination / "objects" / original["sha256"]
        ).read_bytes() == source_snapshots.source_path(imported[0], original).read_bytes()


@pytest.mark.parametrize("bad", ["quote", "page-count", "displaced-quote"])
def test_rehashed_archive_metadata_still_must_match_actual_original_words_and_pages(
    imported, tmp_path, bad
):
    from paper_daily import claim_content, lineage_content, lineage_packages

    if bad == "displaced-quote":
        replaced_versions(imported, tmp_path)
    original = tmp_path / "honest.zip"
    sync_recovery.create(imported[0], original)

    def alter(row):
        body = lineage_sets.decode(row["body_json"])
        report = body["report"]
        if bad == "page-count":
            report["sources"][0]["page_count"] = 2
        else:
            passage = report["statements"][0]["passages"][0]
            passage["quote"] = "Invented evidence which does not occur in this original PDF."
            passage["id"] = lineage_content.passage_id(passage)
        report["id"] = claim_content.hashed({k: v for k, v in report.items() if k != "id"})
        row["body_json"] = lineage_sets.canonical(body)
        lineage_sets.validate_row(row)
        return row

    def mutate(manifest, files):
        if bad != "displaced-quote":
            mutate_table(
                manifest,
                files,
                lineage_sets.TABLE,
                lambda rows: rows.__setitem__(0, alter(rows[0])),
            )

        def change_actions(rows):
            for row in rows:
                body = publisher.validate_record(row)
                for item in body["records"]:
                    key = "before_json" if bad == "displaced-quote" else "row_json"
                    data = json.loads(item[key])
                    if data is not None:
                        item[key] = lineage_packages._json(alter(data))
                body["fingerprint"] = publisher._fingerprint(body)
                row["body_json"] = lineage_packages._json(body)
                publisher.validate_record(row)

        mutate_table(manifest, files, publisher.TABLE, change_actions)

    broken = rewrite(original, tmp_path / "dishonest.zip", mutate)
    with pytest.raises(ValueError, match="Lineage (located quote|original page count)"):
        sync_recovery.inspect(broken)
    destination = tmp_path / "not-restored"
    with pytest.raises(ValueError):
        sync_recovery.restore_detached(broken, destination)
    assert not destination.exists()


def test_retired_import_history_preserves_originals_without_reviving_a_deleted_peer(
    imported, tmp_path
):
    database = imported[0]
    with closing(sqlite3.connect(database)) as conn, conn:
        conn.execute("DELETE FROM paper_lineage_sets")
        conn.execute("DELETE FROM papers WHERE id='receiver-prior'")
    output = tmp_path / "retired.zip"
    sync_recovery.create(database, output)
    actions = archive_rows(output, publisher.TABLE)
    assert len(actions) == 1
    assert archive_rows(output, lineage_sets.TABLE) == []
    assert not any(p["id"] == "receiver-prior" for p in archive_rows(output, "papers"))
    body = publisher.validate_record(actions[0])
    prior = next(
        r
        for r in body["records"][0]["sources"]
        if json.loads(r["owner_json"])["paper_id"] == "receiver-prior"
    )
    destination = tmp_path / "retired-restored"
    sync_recovery.restore_detached(output, destination)
    assert (destination / "objects" / prior["sha256"]).read_bytes() == source_snapshots.source_path(
        database, prior
    ).read_bytes()
    with closing(sqlite3.connect(destination / "papers.db")) as conn:
        assert conn.execute("SELECT id FROM papers WHERE id='receiver-prior'").fetchone() is None
        assert not conn.execute(
            "SELECT name FROM sqlite_master WHERE name=?", (publisher.TABLE,)
        ).fetchone()
        archived = [
            json.loads(r[0])
            for r in conn.execute(
                "SELECT data FROM recovery_records WHERE table_name=?", (publisher.TABLE,)
            )
        ]
    assert archived == actions


def test_unknown_future_research_schema_still_refuses_backup_without_omission(imported, tmp_path):
    with closing(sqlite3.connect(imported[0])) as conn, conn:
        conn.execute("CREATE TABLE research_future_lineage_evidence(body_json TEXT)")
        conn.execute("INSERT INTO research_future_lineage_evidence VALUES('{}')")
    with closing(sqlite3.connect(imported[0])) as conn:
        before = list(conn.iterdump())
    destination = tmp_path / "future.zip"
    with pytest.raises(sync_recovery.RecoveryError, match="Unsupported research schema"):
        sync_recovery.create(imported[0], destination)
    assert not destination.exists()
    with closing(sqlite3.connect(imported[0])) as conn:
        assert list(conn.iterdump()) == before
