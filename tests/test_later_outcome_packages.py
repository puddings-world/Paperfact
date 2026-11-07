"""Exact source package helper behaviors; shared package activation tested separately."""

import hashlib
import io
import json
import os
import sqlite3
import zipfile
from contextlib import closing

import pytest
from test_research_generation import pdf
from test_research_generation import workspace as workspace

from paper_daily import (
    config,
    followups,
    local_source_owners,
    store,
)
from paper_daily import (
    later_outcome_packages as packages,
)
from paper_daily import (
    later_outcomes as outcomes,
)
from paper_daily import research_generation as generation
from paper_daily.research_lifecycle import ensure_lifecycle


def exported(workspace, monkeypatch, available):
    from paper_daily import llm

    def forbidden(*args, **kwargs):
        pytest.fail("Source/package/read workflow attempted a model call")

    monkeypatch.setattr(llm, "complete", forbidden)
    monkeypatch.setattr(llm, "complete_result", forbidden)
    database, client, document = workspace
    monkeypatch.setattr(config, "PDF_DIR", document.path.parent)
    if not available:
        document.path.unlink()
    monkeypatch.setattr(followups, "work_id", lambda _: "W1")
    monkeypatch.setattr(followups, "_citing_openalex", lambda _: [])
    monkeypatch.setattr(followups, "_citing_s2", lambda _: [])
    assert followups.fetch("paper", database=database) == 0
    with closing(generation._connect(database)) as conn:
        row = packages.read(conn, "paper")
        paper = dict(conn.execute("SELECT * FROM papers WHERE id='paper'").fetchone())
    tables = {"papers": [paper], outcomes.TABLE: [row]}
    files = {}
    before = database.read_bytes()
    proof = packages.export_sources(database, tables, files, with_pdfs=True)
    packages.check_export(proof)
    assert database.read_bytes() == before
    manifest = {
        "pdfs_included": True,
        "file_hashes": {
            p.as_posix(): hashlib.sha256(source.read_bytes()).hexdigest()
            for p, source in files.items()
        },
    }
    if proof.records:
        manifest["later_sources"] = list(proof.records)
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr("manifest.json", json.dumps(manifest))
        archive.writestr("tables.json", json.dumps(tables))
        for target, source in files.items():
            archive.writestr("files/" + target.as_posix(), source.read_bytes())
    return database, document, tables, manifest, output, proof


def receiver(tmp_path, paper):
    root = tmp_path / "receiver"
    root.mkdir()
    database = root / "research.sqlite"
    with closing(sqlite3.connect(database)) as conn, conn:
        conn.executescript(store.SCHEMA)
        store._migrate(conn)
        cols = list(paper)
        conn.execute(
            "INSERT INTO papers("
            + ",".join(cols)
            + ") VALUES("
            + ",".join("?" for _ in cols)
            + ")",
            list(paper.values()),
        )
        ensure_lifecycle(conn)
    return database


@pytest.mark.parametrize("available", [False, True])
def test_real_export_and_fresh_receiver_source_receipt(workspace, monkeypatch, tmp_path, available):
    sender, document, tables, manifest, output, proof = exported(workspace, monkeypatch, available)
    database = receiver(tmp_path, tables["papers"][0])
    stages = []
    with zipfile.ZipFile(output) as archive, packages.ImportLease() as lease:
        packages.validate_package(archive, manifest, tables)
        prepared = lease.prepare(database, archive, manifest, tables)
        stages = [item.path.parent for item in prepared if item.path]
        with closing(generation._connect(database)) as conn, conn:
            conn.execute("BEGIN IMMEDIATE")
            packages.ensure_import_in(conn, prepared)
            report = packages.write_import_in(
                conn, prepared, replace=False, package_sha256="e" * 64
            )
            assert report == dict(later_outcomes=1, later_outcomes_kept=0)
        with closing(generation._connect(database)) as conn:
            assert packages.read(conn, "paper") == tables[outcomes.TABLE][0]
            receipts = local_source_owners.records(conn)
            assert len(receipts) == int(available)
            if available:
                owner = json.loads(receipts[0]["owner_json"])
                assert owner["database_identity"] == generation._identity(database)
                assert owner["database_identity"] != generation._identity(sender)
                assert owner["paper_id"] == owner["source_owner_id"] == "paper"
                assert receipts[0]["sha256"] == document.sha256
    assert all(not stage.exists() for stage in stages)
    renamed = database.with_suffix(".closed")
    os.replace(database, renamed)
    os.replace(renamed, database)


def test_export_retains_exact_original_a_after_current_b_and_refuses_link_only(
    workspace, monkeypatch
):
    database, document, tables, manifest, output, proof = exported(workspace, monkeypatch, True)
    pdf(document.path, "New current B must not replace original A in shared outcome")
    files = {}
    new = packages.export_sources(database, tables, files, with_pdfs=True)
    assert new.records[0]["sha256"] == document.sha256
    assert hashlib.sha256(next(iter(files.values())).read_bytes()).hexdigest() == document.sha256
    assert hashlib.sha256(document.path.read_bytes()).hexdigest() != document.sha256
    with pytest.raises(ValueError, match="Include exact"):
        packages.export_sources(database, tables, {}, with_pdfs=False)


@pytest.mark.parametrize("change", ["parent", "target", "staged-source", "native"])
def test_changed_receiver_or_staged_source_never_publishes(
    workspace, monkeypatch, tmp_path, change
):
    sender, document, tables, manifest, output, proof = exported(workspace, monkeypatch, True)
    database = receiver(tmp_path, tables["papers"][0])
    with zipfile.ZipFile(output) as archive, packages.ImportLease() as lease:
        prepared = lease.prepare(database, archive, manifest, tables)
        if change == "staged-source":
            prepared[0].path.write_bytes(b"changed")
        elif change == "native":
            replacement = database.with_suffix(".replacement")
            replacement.write_bytes(database.read_bytes())
            os.replace(replacement, database)
        else:
            with closing(generation._connect(database)) as conn, conn:
                if change == "parent":
                    paper = tables["papers"][0]
                    conn.execute("DELETE FROM papers WHERE id='paper'")
                    cols = list(paper)
                    conn.execute(
                        "INSERT INTO papers("
                        + ",".join(cols)
                        + ") VALUES("
                        + ",".join("?" for _ in cols)
                        + ")",
                        list(paper.values()),
                    )
                else:
                    row = dict(tables[outcomes.TABLE][0])
                    row["written_at"] = "2026-11-02T00:00:00Z"
                    conn.execute(
                        "INSERT INTO paper_later_outcomes VALUES(?,?,?,?)",
                        tuple(
                            row[k] for k in ("paper_id", "body_json", "document_hash", "written_at")
                        ),
                    )
        with closing(generation._connect(database)) as conn:
            conn.execute("BEGIN IMMEDIATE")
            with pytest.raises(ValueError):
                packages.ensure_import_in(conn, prepared)
            conn.rollback()
        with closing(generation._connect(database)) as conn:
            assert local_source_owners.records(conn) == []
    assert all(not item.path.parent.exists() for item in prepared if item.path)
