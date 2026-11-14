"""Actual native source-complete exports and standalone ZIP validation; no live imports."""

import copy
import hashlib
import json
import zipfile
from contextlib import closing
from dataclasses import replace
from pathlib import Path

import pytest
from test_lineage_jobs import work
from test_lineage_recovery import published
from test_research_lineage import corpus as corpus

from paper_daily import lineage_packages as packages
from paper_daily import lineage_sets, llm


def package(prepared, destination, *, focal_ids=("focal",), mutate=lambda _m, _t, _f: None):
    focal = set(focal_ids)
    tables = dict(
        papers=[p for p in prepared.papers if p["id"] in focal],
        cited_papers=[p for p in prepared.papers if p["id"] not in focal],
        paper_lineage_sets=prepared.rows,
    )
    files = {path.as_posix(): data for path, data in prepared.files}
    manifest = dict(
        format=2,
        capabilities=["lineage"],
        pdfs_included=True,
        lineage_sources=prepared.records,
        file_hashes={name: hashlib.sha256(data).hexdigest() for name, data in files.items()},
    )
    mutate(manifest, tables, files)
    with zipfile.ZipFile(destination, "w") as archive:
        archive.writestr("manifest.json", json.dumps(manifest))
        archive.writestr("tables.json", json.dumps(tables))
        for name, data in files.items():
            archive.writestr("files/" + name, data)
    return manifest, tables


def export(corpus, monkeypatch):
    published(corpus, monkeypatch)
    monkeypatch.setattr(llm, "complete_result", lambda *_a, **_k: pytest.fail("Saved-only export"))
    return work(packages.collect, corpus[0], ["focal"])


def test_exact_reports_context_papers_and_all_originals_without_native_grants_or_writes(
    corpus, monkeypatch, tmp_path
):
    prepared = export(corpus, monkeypatch)
    before = corpus[0].read_bytes()
    assert {row["id"] for row in prepared.papers} == {"focal", "prior", "later"}
    assert len(prepared.rows) == 1 and len(prepared.records) == len(prepared.files) == 3
    output = tmp_path / "lineage.zip"
    manifest, tables = package(prepared, output)
    with zipfile.ZipFile(output) as archive:
        assert packages.validate_package(archive, manifest, tables) == prepared.rows
        for source in prepared.records:
            assert (
                archive.read("files/" + source["path"])
                == (corpus[1] / (source["paper_id"] + ".pdf")).read_bytes()
            )
        raw = archive.read("manifest.json") + archive.read("tables.json")
    assert b"database_identity" not in raw and b"parent_lifecycle" not in raw
    assert b"device_id" not in raw and b"owner_json" not in raw
    work(packages.check_export, prepared)
    assert corpus[0].read_bytes() == before
    assert len(tables["papers"]) == 1 and len(tables["cited_papers"]) == 2


def test_returned_content_cannot_mutate_native_export_observation(corpus, monkeypatch, tmp_path):
    prepared = export(corpus, monkeypatch)
    changed = prepared.rows
    changed[0]["written_at"] = "2026-11-01T00:00:00+00:00"
    assert prepared.rows != changed
    with pytest.raises(ValueError, match="native observed export"):
        work(packages.check_export, replace(prepared, _sources="[]"))
    output = tmp_path / "unchanged.zip"
    manifest, tables = package(prepared, output)
    with zipfile.ZipFile(output) as archive:
        assert packages.validate_package(archive, manifest, tables) == prepared.rows


def test_changed_context_or_report_is_refused_at_final_publication(corpus, monkeypatch):
    prepared = export(corpus, monkeypatch)
    import sqlite3

    with closing(sqlite3.connect(corpus[0])) as conn, conn:
        conn.execute("UPDATE papers SET title='Renamed peer' WHERE id='prior'")
    with pytest.raises(ValueError, match="context changed"):
        work(packages.check_export, prepared)


def test_unsupported_or_cancelled_selection_has_no_export_or_source_grant(corpus, monkeypatch):
    export(corpus, monkeypatch)
    assert work(packages.collect, corpus[0], []) is None
    with pytest.raises(ValueError, match="Include exact originals"):
        work(packages.collect, corpus[0], ["focal"], with_pdfs=False)
    with pytest.raises(ValueError, match="cancelled"):
        work(packages.collect, corpus[0], ["focal"], cancelled=lambda: True)
    with pytest.raises(ValueError, match="actual selected/context paper"):
        work(packages.collect, corpus[0], ["missing-from-workspace"])
    with pytest.raises(ValueError, match="explicit paper selection"):
        work(packages.collect, corpus[0], "focal")


@pytest.mark.parametrize(
    "broken",
    [
        "peer",
        "missing",
        "extra",
        "source-owner",
        "source-order",
        "source-path",
        "source-id",
        "capability",
        "duplicate-capability",
        "format",
        "link-only",
    ],
)
def test_wrong_owner_incomplete_or_undeclared_zip_source_closure_refuses(
    corpus, monkeypatch, tmp_path, broken
):
    prepared = export(corpus, monkeypatch)

    def mutate(manifest, tables, files):
        sources = manifest["lineage_sources"]
        if broken == "peer":
            tables["cited_papers"].pop()
        elif broken == "missing":
            files.pop(sources[0]["path"])
        elif broken == "extra":
            files["lineage-sources/undeclared.pdf"] = next(iter(files.values()))
        elif broken == "source-owner":
            sources[0]["paper_id"] = sources[1]["paper_id"]
        elif broken == "source-order":
            sources.reverse()
        elif broken == "source-path":
            sources[0]["path"] = "../escape.pdf"
        elif broken == "source-id":
            sources[0]["source_id"] = "0" * 64
        elif broken == "capability":
            manifest["capabilities"] = []
        elif broken == "duplicate-capability":
            manifest["capabilities"] = ["lineage", "lineage"]
        elif broken == "format":
            manifest["format"] = 2.0
        else:
            manifest["pdfs_included"] = False

    output = tmp_path / "bad.zip"
    manifest, tables = package(prepared, output, mutate=mutate)
    with zipfile.ZipFile(output) as archive, pytest.raises(ValueError, match="Lineage"):
        packages.validate_package(archive, manifest, tables)


@pytest.mark.parametrize("changed", ["quote", "page-count"])
def test_rehashed_scientific_report_must_still_match_actual_pdf(
    corpus, monkeypatch, tmp_path, changed
):
    from paper_daily import claim_content, lineage_content

    prepared = export(corpus, monkeypatch)

    def mutate(_manifest, tables, _files):
        row = tables["paper_lineage_sets"][0]
        body = lineage_sets.decode(row["body_json"])
        report = body["report"]
        if changed == "quote":
            p = report["statements"][0]["passages"][0]
            p["quote"] = "This invented sentence does not occur in that original."
            p["id"] = lineage_content.passage_id(p)
        else:
            report["sources"][0]["page_count"] = 2
        report["id"] = claim_content.hashed({k: v for k, v in report.items() if k != "id"})
        row["body_json"] = lineage_sets.canonical(body)
        lineage_sets.validate_row(row)  # The ordinary structural/digest contract admits it.

    output = tmp_path / "rehashed.zip"
    manifest, tables = package(prepared, output, mutate=mutate)
    with (
        zipfile.ZipFile(output) as archive,
        pytest.raises(ValueError, match="Lineage (located quote|original page count)"),
    ):
        packages.validate_package(archive, manifest, tables)


def test_actual_archive_metadata_and_duplicate_keys_are_checked_before_use(
    corpus, monkeypatch, tmp_path
):
    prepared = export(corpus, monkeypatch)
    output = tmp_path / "actual.zip"
    manifest, tables = package(prepared, output)
    changed = copy.deepcopy(manifest)
    changed["unadmitted"] = "caller mutation"
    with zipfile.ZipFile(output) as archive, pytest.raises(ValueError, match="admitted metadata"):
        packages.validate_package(archive, changed, tables)
    with zipfile.ZipFile(output) as archive:
        files = {name: archive.read(name) for name in archive.namelist()}
    files["manifest.json"] = b'{"format":2,' + files["manifest.json"][1:]
    duplicate = tmp_path / "duplicate.json.zip"
    with zipfile.ZipFile(duplicate, "w") as archive:
        for name, data in files.items():
            archive.writestr(name, data)
    with (
        zipfile.ZipFile(duplicate) as archive,
        pytest.raises(ValueError, match="Duplicate Lineage"),
    ):
        packages.validate_package(archive, manifest, tables)


def test_different_current_primary_pdf_does_not_replace_saved_lineage_original(
    corpus, monkeypatch, tmp_path
):
    from test_research_evidence import pdf

    published(corpus, monkeypatch)
    original = (corpus[1] / "focal.pdf").read_bytes()
    pdf(corpus[1] / "focal.pdf", [["A separately selected newer primary original."]])
    current = (corpus[1] / "focal.pdf").read_bytes()
    prepared = work(packages.collect, corpus[0], ["focal"])
    source = next(s for s in prepared.records if s["paper_id"] == "focal")
    assert dict(prepared.files)[Path(source["path"])] == original
    assert (corpus[1] / "focal.pdf").read_bytes() == current
    output = tmp_path / "old-original.zip"
    manifest, tables = package(prepared, output)
    with zipfile.ZipFile(output) as archive:
        assert packages.validate_package(archive, manifest, tables) == prepared.rows


def test_collection_and_validation_enforce_byte_and_page_budgets(corpus, monkeypatch, tmp_path):
    prepared = export(corpus, monkeypatch)
    output = tmp_path / "bounded.zip"
    manifest, tables = package(prepared, output)
    monkeypatch.setattr(packages, "MAX_TOTAL_PAGES", 1)
    with zipfile.ZipFile(output) as archive, pytest.raises(ValueError, match="page budget"):
        packages.validate_package(archive, manifest, tables)
    monkeypatch.setattr(packages, "MAX_TOTAL", 1)
    with pytest.raises(ValueError, match="memory budget"):
        work(packages.collect, corpus[0], ["focal"])
    work(packages.check_export, None)


def test_validation_cancellation_returns_no_partial_content_or_write(corpus, monkeypatch, tmp_path):
    prepared = export(corpus, monkeypatch)
    output = tmp_path / "cancel.zip"
    manifest, tables = package(prepared, output)
    before = corpus[0].read_bytes()
    with zipfile.ZipFile(output) as archive, pytest.raises(ValueError, match="cancelled"):
        packages.validate_package(archive, manifest, tables, cancelled=lambda: True)
    extract = packages.research_evidence._extract
    cancelled = False

    def completed(*args):
        nonlocal cancelled
        result = extract(*args)
        cancelled = True
        return result

    monkeypatch.setattr(packages.research_evidence, "_extract", completed)
    with zipfile.ZipFile(output) as archive, pytest.raises(ValueError, match="cancelled"):
        packages.validate_package(archive, manifest, tables, cancelled=lambda: cancelled)
    assert corpus[0].read_bytes() == before


def test_unavailable_selected_peer_is_context_without_an_invented_pdf(
    corpus, monkeypatch, tmp_path
):
    import sqlite3

    from test_lineage_publication import publish
    from test_lineage_target_jobs import job_for, observed

    from paper_daily import lineage_publication, research_lineage, store
    from paper_daily.ai_types import Completion

    with closing(sqlite3.connect(corpus[0])) as conn, conn:
        store._migrate(conn)
    captured = research_lineage.capture(
        corpus[0], "focal", ["prior", "later", "missing"], legacy_root=corpus[1]
    )
    chosen = (corpus[0], corpus[1], captured)
    observation = observed(chosen)
    response = json.dumps(
        dict(format=research_lineage.PROPOSALS, focal=captured.focal, statements=[])
    )
    monkeypatch.setattr(llm, "complete_result", lambda *_a, **_k: Completion(response))
    job = job_for(chosen, observation)
    work(job.run)
    work(publish, corpus[0], work(lineage_publication.prepare, job._state.candidate))
    monkeypatch.setattr(llm, "complete_result", lambda *_a, **_k: pytest.fail("Read-only package"))
    prepared = work(packages.collect, corpus[0], ["focal"])
    assert {p["id"] for p in prepared.papers} == {"focal", "prior", "later", "missing"}
    assert len(prepared.records) == len(prepared.files) == 3
    assert all(source["paper_id"] != "missing" for source in prepared.records)
    output = tmp_path / "unavailable.zip"
    manifest, tables = package(prepared, output)
    with zipfile.ZipFile(output) as archive:
        assert packages.validate_package(archive, manifest, tables) == prepared.rows
    body = lineage_sets.decode(prepared.rows[0]["body_json"])
    assert body["report"]["sources"][-1]["availability"] == "unavailable"
