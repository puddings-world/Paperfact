"""Durable local derived checks are private, bounded and never restore job authority."""

import copy
import json
from concurrent.futures import ThreadPoolExecutor

import pytest
from test_audit_appraisal import captured as captured_fixture
from test_audit_appraisal import response
from test_audit_appraisal import source as source_fixture

from paper_daily import audit_appraisal, llm
from paper_daily.appraisal_archive import AppraisalArchive

source = source_fixture
captured = captured_fixture


@pytest.fixture
def completed(captured, monkeypatch):
    monkeypatch.setattr(llm, "complete_result", response)
    job = audit_appraisal.AppraisalJob.prepare(captured[0], ["mark:1"])
    return captured[0], job.run()


def test_construct_and_read_do_not_create_cache_or_call_ai(completed, tmp_path, monkeypatch):
    capture, report = completed
    root = tmp_path / "private-cache"
    monkeypatch.setattr(
        llm, "complete_result", lambda *a, **k: pytest.fail("No AI on history reads")
    )
    archive = AppraisalArchive(root, capture)
    assert archive.current(capture) == [] and not root.exists()
    destination = archive.save(report)
    assert destination.is_file() and archive.current(capture)[0]["report"] == report
    assert AppraisalArchive(root, capture).current(capture)[0]["report"] == report
    assert archive.save(report) == destination
    assert len(list(destination.parent.glob("*.json"))) == 1
    assert "openai" in destination.read_text() and "fixture-account" not in destination.read_text()


def test_concurrent_same_report_retry_stores_one_record(completed, tmp_path):
    capture, report = completed
    archive = AppraisalArchive(tmp_path / "cache", capture)
    with ThreadPoolExecutor(max_workers=2) as executor:
        paths = list(executor.map(lambda _n: archive.save(report), range(2)))
    assert paths[0] == paths[1] and len(archive.current(capture)) == 1


def test_changed_retry_does_not_replace_old_review(completed, tmp_path):
    from paper_daily import claim_content

    capture, report = completed
    archive = AppraisalArchive(tmp_path / "cache", capture)
    destination = archive.save(report)
    before = destination.read_bytes()
    changed = copy.deepcopy(report)
    changed["findings"][0]["reason"] = "A different proposed judgment"
    changed["id"] = claim_content.hashed({k: v for k, v in changed.items() if k != "id"})
    with pytest.raises(ValueError, match="appraisal_retry_changed"):
        archive.save(changed)
    assert destination.read_bytes() == before


@pytest.mark.parametrize(
    "scope",
    ["digest", "unknown-field", "semantic-certification", "invalid-anchor", "foreign-source"],
)
def test_tampered_cache_is_not_loaded_or_promoted(completed, tmp_path, scope):
    capture, report = completed
    archive = AppraisalArchive(tmp_path / "cache", capture)
    destination = archive.save(report)
    record = json.loads(destination.read_bytes())
    if scope == "digest":
        record["report"]["id"] = "f" * 64
    elif scope == "unknown-field":
        record["report"]["credential"] = "must-not-be-accepted"
    elif scope == "semantic-certification":
        record["report"]["semantic_validation"] = "verified"
    elif scope == "invalid-anchor":
        record["report"]["findings"][0]["evidence"][0]["anchor"]["p0"] = -1
    else:
        record["report"]["source"]["document_hash"] = "f" * 64
    destination.write_text(json.dumps(record), encoding="utf-8")
    with pytest.raises(ValueError):
        archive.current(capture)


def test_overbudget_or_unknown_paths_fail_without_replacing_old_content(completed, tmp_path):
    capture, report = completed
    archive = AppraisalArchive(tmp_path / "cache", capture)
    path = archive.save(report)
    before = path.read_bytes()
    (path.parent / "unexpected.txt").write_text("Not a recognized derived report")
    with pytest.raises(ValueError):
        archive.current(capture)
    assert path.read_bytes() == before


def test_interrupted_stage_is_not_a_completed_report(completed, tmp_path):
    capture, report = completed
    archive = AppraisalArchive(tmp_path / "cache", capture)
    path = archive.save(report)
    (path.parent / ".stage-interrupted.tmp").write_bytes(b"{")
    assert archive.current(capture)[0]["report"] == report


def test_changed_selected_content_stays_in_history_but_is_not_current(completed, tmp_path):
    from dataclasses import replace

    capture, report = completed
    archive = AppraisalArchive(tmp_path / "cache", capture)
    path = archive.save(report)
    items = json.loads(capture._items_json)
    items[0]["text"] = "Changed selected assertion"
    other = replace(capture, _items_json=json.dumps(items))
    assert archive.current(other) == [] and path.exists()


def test_another_workspace_cannot_reuse_the_archive_scope(completed, tmp_path):
    from dataclasses import replace

    capture, report = completed
    archive = AppraisalArchive(tmp_path / "cache", capture)
    archive.save(report)
    state = json.loads(capture._state_json)
    state["binding"] = {"workspace_id": "another", "device_id": "another"}
    other = replace(capture, _state_json=json.dumps(state))
    with pytest.raises(ValueError, match="appraisal_workspace_changed"):
        archive.current(other)


def test_failed_publication_retains_job_result_and_retry_repairs_only_its_record(
    completed, tmp_path, monkeypatch
):
    import os

    capture, report = completed
    archive = AppraisalArchive(tmp_path / "cache", capture)
    link = os.link
    monkeypatch.setattr(
        os, "link", lambda *a, **k: (_ for _ in ()).throw(OSError("fixture disk failure"))
    )
    with pytest.raises(OSError):
        archive.save(report)
    assert archive.current(capture) == []
    monkeypatch.setattr(os, "link", link)
    assert archive.save(report).exists()
    assert archive.current(capture)[0]["report"] == report


def test_rehashed_anchor_tampering_still_requires_actual_original_quote(completed, tmp_path):
    from paper_daily import claim_content

    capture, report = completed
    archive = AppraisalArchive(tmp_path / "cache", capture)
    destination = archive.save(report)
    record = json.loads(destination.read_bytes())
    passage = record["report"]["findings"][0]["evidence"][0]
    passage["anchor"] = dict(p0=0, o0=0, p1=0, o1=0)
    passage["page"] = 1
    record["report"]["id"] = claim_content.hashed(
        {k: v for k, v in record["report"].items() if k != "id"}
    )
    destination.write_text(json.dumps(record), encoding="utf-8")
    with pytest.raises(ValueError):
        archive.current(capture)
