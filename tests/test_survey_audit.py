"""List-report audits reuse exact owned originals, without rendering or AI."""

from contextlib import closing

import pytest
from test_survey import conn as conn
from test_survey_jobs import ready as ready
from test_survey_package_local import local as local
from test_survey_packages import exported as exported
from test_survey_publication import prepared as prepared
from test_survey_reader import saved as saved
from test_sync_capture import bound as bound

from paper_daily import local_operations, research_generation, store, survey_audit, survey_reader


def snapshot(database):
    with closing(research_generation._connect(database)) as connection:
        return list(connection.iterdump())


def test_saved_report_sources_checked_once_and_shared_operation_is_read_only(saved, monkeypatch):
    database, list_id, _report = saved
    before = snapshot(database)
    selected = survey_reader.read(database, list_id)
    actual, calls = survey_reader._checked_original, []

    def checked(*args):
        calls.append(args[1]["id"])
        return actual(*args)

    monkeypatch.setattr(survey_reader, "_checked_original", checked)
    monkeypatch.setattr(store, "DB_PATH", database)
    result = local_operations.dispatch("analysis.audit", {"list_id": list_id})
    assert result["ok"], result
    report = result["result"]
    assert report["format"] == survey_audit.FORMAT and report["semantics"] == "not_checked"
    assert report["originals_verified"] == report["originals_total"] > 0
    assert report["verified_located_passages"] > 0
    assert len(calls) == len(set(calls)) == report["originals_total"]
    assert selected.current() and snapshot(database) == before


@pytest.mark.parametrize("failure", ["unavailable", "cancel", "changed"])
def test_missing_originals_are_findings_but_cancellation_or_change_is_not_success(
    saved, monkeypatch, failure
):
    database, list_id, _report = saved
    selected = survey_reader.read(database, list_id)
    before = snapshot(database)
    if failure == "unavailable":
        def unavailable(*_args):
            raise ValueError("Synthetic missing original")

        monkeypatch.setattr(survey_reader, "_checked_original", unavailable)
        result = survey_audit.audit(selected)
        assert result["originals_verified"] == result["verified_located_passages"] == 0
        assert any(row["state"] == "unavailable" for row in result["sources"])
    elif failure == "cancel":
        with pytest.raises(ValueError, match="cancelled"):
            survey_audit.audit(selected, cancelled=lambda: True)
    else:
        monkeypatch.setattr(survey_reader.SavedReport, "current", lambda self: False)
        with pytest.raises(ValueError):
            survey_audit.audit(selected)
    assert snapshot(database) == before


def test_shared_audit_rejects_mixed_paper_and_list_without_reading(monkeypatch):
    monkeypatch.setattr(survey_reader, "read", lambda *_a: pytest.fail("Mixed target was read"))
    result = local_operations.dispatch("analysis.audit", {"paper_id": "paper", "list_id": "list"})
    assert not result["ok"] and result["error"]["code"] == "invalid_input"


@pytest.mark.parametrize("limit", ["original-changed", "bytes", "sources"])
def test_original_change_and_resource_bounds_never_return_success(saved, monkeypatch, limit):
    database, list_id, _report = saved
    selected = survey_reader.read(database, list_id)
    before = snapshot(database)
    if limit == "original-changed":
        original = survey_reader._checked_original

        def checked(*args):
            raw, _fresh = original(*args)
            return raw, lambda: False

        monkeypatch.setattr(survey_reader, "_checked_original", checked)
    else:
        monkeypatch.setattr(survey_audit, "MAX_BYTES" if limit == "bytes" else "MAX_ORIGINALS", 0)
    with pytest.raises(ValueError):
        survey_audit.audit(selected)
    assert snapshot(database) == before


def test_prepared_result_is_bound_to_its_saved_read_and_cannot_be_rewritten(saved):
    from dataclasses import replace

    database, list_id, _report = saved
    selected = survey_reader.read(database, list_id)
    prepared = survey_audit.prepare(selected)
    report = prepared.for_delivery(selected)
    report["sources"].clear()
    assert prepared.for_delivery(selected)["sources"]
    with pytest.raises(survey_reader.ReadChanged):
        replace(prepared, _json='{"originals_verified":999}').for_delivery(selected)
    with pytest.raises(survey_reader.ReadChanged):
        prepared.for_delivery(survey_reader.read(database, list_id))
