"""Saved report reading is source-aware, local, immutable and independent of AI."""

import json
from contextlib import closing
from dataclasses import replace
from pathlib import Path

import pytest
from test_survey import conn as conn
from test_survey_jobs import ready as ready
from test_survey_package_compound import archive
from test_survey_package_local import local as local
from test_survey_packages import exported as exported
from test_survey_publication import dump
from test_survey_publication import prepared as prepared
from test_sync_capture import bound as bound

from paper_daily import bundle, survey_packages, survey_reader
from paper_daily import research_generation as generation


@pytest.fixture(params=["native", "local"])
def saved(request, exported, local, tmp_path):
    if request.param == "native":
        return exported[0][0].journal.path, "list", exported[0][5].report
    result = bundle.import_(archive(exported, tmp_path), pdfs=False)
    return local[0], result["list"], exported[0][5].report


def test_read_checks_saved_report_without_pdf_parsing_network_or_sql_changes(saved, monkeypatch):
    from paper_daily import llm, local_source_owners

    database, list_id, report = saved
    with closing(generation._connect(database)) as conn:
        before = list(conn.iterdump())

    def forbidden(*args, **kwargs):
        pytest.fail("Opening saved research must not parse originals or invoke AI")

    monkeypatch.setattr(survey_packages, "verify_original", forbidden)
    monkeypatch.setattr(local_source_owners, "_read_pdf", forbidden)
    monkeypatch.setattr(llm, "complete_result", forbidden)
    result = survey_reader.read(database, list_id)
    assert result.data["report"] == report and result.current()
    assert result.data["sources"][0]["title"]
    with closing(generation._connect(database)) as conn:
        assert list(conn.iterdump()) == before
    with monkeypatch.context() as patch:
        patch.setattr(survey_reader, "_readonly_connection", forbidden)
        assert result.current()
    assert not replace(result, _json="{}").current()


def test_exact_quote_preview_opens_captured_page_without_changing_research(saved):
    database, list_id, _report = saved
    value = survey_reader.read(database, list_id)
    result = survey_reader.inspect(value, 0, 0, 0)
    assert result["page"] == 1 and result["pages"] == 1 and result["located"]
    assert result["image"].startswith(b"\x89PNG") and result["quote"] == "A selected method"
    assert value.current()
    with pytest.raises(ValueError, match="page within"):
        survey_reader.inspect(value, 0, 0, 0, page=2)
    with pytest.raises(ValueError, match="saved quotation"):
        survey_reader.inspect(value, -1, 0, 0)
    with pytest.raises(ValueError, match="cancelled"):
        survey_reader.inspect(value, 0, 0, 0, cancelled=lambda: True)


def test_changed_metadata_or_replaced_database_refuses_late_reader_results(saved):
    database, list_id, _ = saved
    result = survey_reader.read(database, list_id)
    with closing(generation._connect(database)) as conn, conn:
        conn.execute("UPDATE lists SET name='A later list name' WHERE id=?", (list_id,))
    assert not result.current()
    with pytest.raises(ValueError, match="changed"):
        survey_reader.inspect(result, 0, 0, 0)
    result = survey_reader.read(database, list_id)
    original = database.with_suffix(".old")
    database.rename(original)
    try:
        database.write_bytes(original.read_bytes())
        assert not result.current()
    finally:
        database.unlink(missing_ok=True)
        original.rename(database)


def test_native_pending_update_keeps_old_applied_report_and_shows_notice(exported):
    from paper_daily import survey_content, sync_survey_files
    from paper_daily.sync_artifacts import applied_file, desired_file
    from paper_daily.sync_files import list_file_id

    client = exported[0][0]
    with client.journal.transaction() as conn:
        previous = applied_file(conn, list_file_id("list"))
    report = json.loads(json.dumps(exported[0][5].report))
    for section in report["sections"]:
        for statement in section["statements"]:
            del statement["id"]
    report["sections"][0]["statements"][0]["text"] = "A later analysis awaiting its bytes."
    updated = survey_content.assemble(
        inputs=report["inputs"],
        generation=report["generation"],
        sources=report["sources"],
        sections=report["sections"],
    )
    payload, _blobs = sync_survey_files.encode(
        updated,
        "list",
        previous["payload"]["source_bindings"],
        input_versions=previous["payload"]["input_versions"],
    )
    with client.journal.transaction() as conn:
        operation = client.new_graph_operation_in(
            conn, "research_file", list_file_id("list"), payload
        )
        client.journal.apply_in(conn, operation, client.writer)
        assert applied_file(conn, operation["entity_id"]) != desired_file(
            conn, operation["entity_id"]
        )
    before = dump(client)
    result = survey_reader.read(client.journal.path, "list")
    assert result.data["update_pending"] and result.data["report"] == exported[0][5].report
    assert dump(client) == before


def archived(ready):
    from paper_daily import survey_jobs

    job = survey_jobs.SurveyJob.capture(ready[0], "cat", legacy_root=ready[1])
    proposal = job.generate()
    receipt = survey_jobs.retain(job, proposal)
    return job, receipt


def test_retained_original_reader_uses_exact_private_bytes_without_applying_or_ai(ready):
    from paper_daily import survey_jobs, survey_local_generated, survey_publication

    job, receipt = archived(ready)
    # Today's primary PDF is not the original of this historical report.
    (ready[1] / "a.pdf").write_bytes(b"A different current original")
    with closing(generation._connect(ready[0])) as conn:
        before = list(conn.iterdump())
    value = survey_reader.read_retained(ready[0], "cat", receipt.request_id)
    assert value.current() and value.data["kind"] == "retained"
    assert value.data["report"] == survey_jobs.read_retained(ready[0], "cat", receipt.request_id)
    result = survey_reader.inspect(value, 0, 0, 0)
    assert result["located"] and result["page"] == result["pages"] == 1
    assert result["quote"] == "A selected method improves measurement."
    assert result["document_hash"] == job._receipts[0]["sha256"]
    assert result["image"].startswith(b"\x89PNG")
    assert not replace(value, _archive=None).current()
    for publisher in (survey_local_generated, survey_publication):
        with pytest.raises(ValueError, match="checked proposal"):
            publisher.prepare(value)
    with pytest.raises(ValueError, match="cancelled"):
        survey_reader.inspect(value, 0, 0, 0, cancelled=lambda: True)
    assert len(ready[2]) == 1 and survey_reader.read(ready[0], "cat").data["kind"] == "none"
    with closing(generation._connect(ready[0])) as conn:
        assert list(conn.iterdump()) == before


@pytest.mark.parametrize(
    "change", ["record", "receipt", "original", "missing", "workspace", "during"],
)
def test_retained_source_changes_refuse_preview_without_substituting_primary(
    ready, change, monkeypatch,
):
    from paper_daily import position_source_snapshots, source_snapshots

    job, receipt = archived(ready)
    value = survey_reader.read_retained(ready[0], "cat", receipt.request_id)
    row = job._receipts[0]
    source, _version = position_source_snapshots.verify(ready[0], row)
    if change == "record":
        path = Path(value._archive[0])
        path.write_bytes(path.read_bytes() + b" ")
    elif change == "receipt":
        source_snapshots.receipt_path(ready[0], row).write_bytes(b"{}")
    elif change == "original":
        source.write_bytes(b"corrupt retained PDF")
    elif change == "missing":
        source.unlink()
    elif change == "during":
        actual = survey_packages.verify_original

        def changed(*args, **options):
            actual(*args, **options)
            source_snapshots.receipt_path(ready[0], row).write_bytes(b"{}")

        monkeypatch.setattr(survey_packages, "verify_original", changed)
    else:
        with closing(generation._connect(ready[0])) as conn, conn:
            conn.execute("UPDATE lists SET name='Later state' WHERE id='cat'")
    with pytest.raises((ValueError, OSError)):
        survey_reader.inspect(value, 0, 0, 0)
    assert len(ready[2]) == 1
    assert (ready[1] / "a.pdf").read_bytes().startswith(b"%PDF")
    assert survey_reader.read(ready[0], "cat").data["kind"] == "none"
