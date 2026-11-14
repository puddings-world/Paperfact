"""Real complete Lineage archives preserve reports and exact peer PDF ownership."""

import hashlib
import json
import shutil
import sqlite3
import zipfile
from contextlib import closing
from pathlib import Path
from uuid import uuid4

import pytest
from test_lineage_jobs import work
from test_lineage_publication import prepared, publish
from test_lineage_target_jobs import job_for, observed
from test_research_lineage import corpus as corpus
from test_sync_recovery import archive_rows, rewrite

from paper_daily import (
    lineage_candidates,
    lineage_sets,
    llm,
    recovery_provenance,
    research_lineage,
    source_snapshots,
    store,
    sync_recovery,
)
from paper_daily.ai_types import Completion
from paper_daily.recovery_adoption import RecoveryAdoptionService


def published(corpus, monkeypatch):
    with closing(sqlite3.connect(corpus[0])) as conn, conn:
        store._migrate(conn)
    job, staged = prepared(corpus, monkeypatch)
    work(publish, corpus[0], staged)
    return job


def test_real_backup_restore_retains_canonical_report_and_all_originals_without_live_receipts(
    corpus, monkeypatch, tmp_path
):
    job = published(corpus, monkeypatch)
    package = tmp_path / "complete.zip"
    manifest = sync_recovery.create(corpus[0], package)
    assert sync_recovery.inspect(package) == manifest
    assert archive_rows(package, lineage_sets.TABLE) == [
        json.loads(job._state.candidate.record["row_json"])
    ]
    receipt = archive_rows(package, "research_lineage_publications")[0]
    assert receipt["request_id"] == job.request_id
    originals = json.loads(receipt["sources_json"])
    with zipfile.ZipFile(package) as archive:
        for original in originals:
            assert (
                archive.read("objects/" + original["sha256"])
                == source_snapshots.source_path(corpus[0], original).read_bytes()
            )
    restored = tmp_path / "detached"
    sync_recovery.restore_detached(package, restored)
    assert lineage_sets.saved(restored / "papers.db", "focal") == lineage_sets.saved(
        corpus[0], "focal"
    )
    with closing(sqlite3.connect(restored / "papers.db")) as conn:
        assert not conn.execute(
            "SELECT 1 FROM sqlite_master WHERE name IN "
            "('research_lineage_publications','research_local_source_owners','paperfact_sync_identity')"
        ).fetchall()
        archived = [
            json.loads(r[0])
            for r in conn.execute(
                "SELECT data FROM recovery_records WHERE table_name='research_lineage_publications'"
            )
        ]
    assert archived == [receipt]
    assert len(work(lineage_candidates.saved, corpus[0], "focal")) == 1


@pytest.mark.parametrize(
    "broken", ["candidate", "publication", "association", "candidate-id", "original-file"]
)
def test_incomplete_publication_refuses_backup_without_partial_output(
    corpus, monkeypatch, tmp_path, broken
):
    job = published(corpus, monkeypatch)
    with closing(sqlite3.connect(corpus[0])) as conn, conn:
        if broken == "candidate":
            conn.execute("DELETE FROM research_generation_requests")
        elif broken == "publication":
            conn.execute("DELETE FROM research_lineage_publications")
        elif broken == "association":
            conn.execute(
                "DELETE FROM research_local_source_owners WHERE rowid=("
                "SELECT min(rowid) FROM research_local_source_owners)"
            )
        elif broken == "candidate-id":
            conn.execute("UPDATE research_lineage_publications SET candidate_id=?", ("0" * 64,))
    if broken == "original-file":
        original = json.loads(job._state.candidate.record["context_json"])["inputs"]["originals"][1]
        source_snapshots.source_path(corpus[0], original).unlink()
    output = tmp_path / "refuse.zip"
    with pytest.raises((ValueError, OSError)):
        sync_recovery.create(corpus[0], output)
    assert not output.exists()
    assert corpus[0].is_file()


def test_valid_container_hashes_do_not_hide_missing_paper_source_association(
    corpus, monkeypatch, tmp_path
):
    published(corpus, monkeypatch)
    package = tmp_path / "original.zip"
    sync_recovery.create(corpus[0], package)

    def remove_association(manifest, files):
        table = next(t for t in manifest["tables"] if t["name"] == "research_local_source_owners")
        name = "tables/" + table["name"] + ".jsonl"
        lines = files[name].splitlines(keepends=True)[1:]
        files[name] = b"".join(lines)
        table.update(
            count=len(lines), size=len(files[name]), sha256=hashlib.sha256(files[name]).hexdigest()
        )

    damaged = rewrite(package, tmp_path / "damaged.zip", remove_association)
    with pytest.raises(ValueError, match="exact original association"):
        sync_recovery.inspect(damaged)
    target = tmp_path / "must-not-restore"
    with pytest.raises(ValueError, match="exact original association"):
        sync_recovery.restore_detached(damaged, target)
    assert not target.exists()


def test_detached_inspection_prepares_editable_lineage_with_fresh_authority_and_keeps_source(
    corpus, monkeypatch, tmp_path
):
    with closing(sqlite3.connect(corpus[0])) as conn, conn:
        for identity, title in conn.execute("SELECT id,title FROM papers").fetchall():
            conn.execute(
                "UPDATE papers SET title_key=? WHERE id=?", (store.title_key(title), identity)
            )
    captured = research_lineage.capture(
        corpus[0], "focal", ["prior", "later"], legacy_root=corpus[1]
    )
    published((corpus[0], corpus[1], captured), monkeypatch)
    package, folder = tmp_path / "complete.zip", tmp_path / "detached"
    sync_recovery.create(corpus[0], package)
    sync_recovery.restore_detached(package, folder)
    database = folder / "papers.db"
    before = database.read_bytes()
    service = RecoveryAdoptionService(database)
    inspection = service.inspect()
    assert inspection.report["research_counts"][lineage_sets.TABLE] == 1
    assert inspection.report["supported"] and inspection.report["blockers"] == []
    result = work(
        service.prepare,
        inspection,
        tmp_path / "editable",
        backup_output=tmp_path / "editable.zip",
        request_id=str(uuid4()),
    )
    assert result["editable_copy"] and result["history_preserved"] and not result["uploaded"]
    assert lineage_sets.saved(Path(result["database"]), "focal") == lineage_sets.saved(
        database, "focal"
    )
    assert (
        sync_recovery.inspect(tmp_path / "editable.zip")["workspace_id"] == result["workspace_id"]
    )
    assert database.read_bytes() == before


def test_equal_pdf_hashes_preserve_separate_paper_associations(corpus, monkeypatch, tmp_path):
    with closing(sqlite3.connect(corpus[0])) as conn, conn:
        store._migrate(conn)
    shutil.copyfile(corpus[1] / "prior.pdf", corpus[1] / "later.pdf")
    capture = research_lineage.capture(
        corpus[0], "focal", ["prior", "later"], legacy_root=corpus[1]
    )
    chosen = (corpus[0], corpus[1], capture)
    observation = observed(chosen)
    response = json.dumps(
        dict(format=research_lineage.PROPOSALS, focal=capture.focal, statements=[])
    )
    monkeypatch.setattr(llm, "complete_result", lambda *_a, **_k: Completion(response))
    job = job_for(chosen, observation)
    work(job.run)
    from paper_daily.lineage_publication import prepare

    work(publish, corpus[0], work(prepare, job._state.candidate))
    package = tmp_path / "same-bytes.zip"
    manifest = sync_recovery.create(corpus[0], package)
    receipt = archive_rows(package, "research_lineage_publications")[0]
    originals = json.loads(receipt["sources_json"])
    assert len(originals) == 3 and len({r["sha256"] for r in originals}) == 2
    assert {json.loads(r["owner_json"])["paper_id"] for r in originals} == {
        "focal",
        "prior",
        "later",
    }
    assert len(manifest["blobs"]) == 2
    assert sync_recovery.inspect(package) == manifest


def test_complete_publication_can_be_retained_as_archive_only_recovery_provenance(
    corpus, monkeypatch, tmp_path
):
    published(corpus, monkeypatch)
    package = tmp_path / "complete.zip"
    manifest = sync_recovery.create(corpus[0], package)
    tables = {t["name"]: archive_rows(package, t["name"]) for t in manifest["tables"]}
    provenance = recovery_provenance.encode(manifest, tables)
    groups = recovery_provenance.validate_groups(provenance)
    assert len(groups) == 1
    assert len(groups[0].lineage.rows) == 1
    assert len(groups[0].lineage.publications) == 1


@pytest.mark.parametrize("consumer", ["package", "later-recovery"])
def test_lineage_associations_cannot_grant_an_unrelated_later_outcome_original(
    corpus, monkeypatch, consumer
):
    from types import SimpleNamespace

    from paper_daily.later_outcome_packages import _owned
    from paper_daily.later_outcome_recovery import Records
    from paper_daily.research_generation import _connect

    job = published(corpus, monkeypatch)
    row = dict(paper_id="focal", document_hash=corpus[2].sources[0]["document_hash"])
    if consumer == "package":
        with closing(_connect(corpus[0])) as conn:
            assert _owned(conn, corpus[0], row) is None
    else:
        records = Records()
        originals = json.loads(job._state.candidate.record["context_json"])["inputs"]["originals"]
        for original in originals:
            records.add("research_local_source_owners", original)
        owner = json.loads(originals[0]["owner_json"])
        context = SimpleNamespace(
            paper_ids={"focal", "prior", "later"},
            paper_map={},
            parent_lifecycles={("paper", "focal"): dict(active=1, token=owner["parent_lifecycle"])},
        )
        with pytest.raises(ValueError, match="exact paper/source ownership"):
            records.authority(context, row)
