"""Typed citation coverage stays coupled to observed bytes and accepted rows."""

import json
import os
from contextlib import closing

import pytest
from test_research_compound import begin, seed
from test_research_compound import driver as driver
from test_research_generation import rows
from test_research_generation import workspace as workspace

from paper_daily import analyze, cites, followups, llm, store
from paper_daily import research_compound as compound
from paper_daily import research_generation as generation
from paper_daily.sources import crossref


def read_coverage(path):
    with closing(generation._connect(path)) as conn:
        return cites.coverage(conn, "paper", verify_source=True)


def answers(keys):
    return [
        {
            "key": str(key),
            "title": "Reference",
            "purpose": "Evidence",
            "gist": "Method",
            "verdict": followups.VERDICTS[0],
            "why": "Core",
        }
        for key in keys
    ]


def test_actual_partial_receipt_preserves_prior_rows_then_full_retry_completes(driver, monkeypatch):
    path, client, _document, _calls, _install, invoke = driver
    seed(path, "citations", "old")
    monkeypatch.setattr(
        crossref,
        "reference_list",
        lambda _: {str(i): {"title": f"Reference {i}"} for i in range(1, 6)},
    )
    outputs = [answers([1]), answers(range(1, 6))]
    calls = []

    def complete(*args, **kwargs):
        calls.append(args[0])
        return json.dumps(outputs.pop(0)), "ok"

    monkeypatch.setattr(llm, "complete", complete)
    assert invoke("citations") == 1
    assert {row["ref_key"] for row in rows(path, "SELECT * FROM cites")} == {"1", "old"}
    assert read_coverage(path) == {
        "state": "partial",
        "sent": 5,
        "answered": 1,
        "reason": "Citation analysis covers 1/5 references",
    }
    with closing(generation._connect(path)) as conn:
        assert not analyze.status(conn, "paper")["cites"]
        assert store.get_kv(conn, "cites.coverage.paper") is None
    receipt = rows(path, "SELECT * FROM research_compound_requests")[-1]
    compound.validate_request_record(receipt)
    mutation = json.loads(receipt["mutations_json"])
    assert mutation["completion"] == {
        "kind": "citation_coverage",
        "sent": ["1", "2", "3", "4", "5"],
        "answered": ["1"],
    }
    assert mutation["deletes"] == []
    pending = client.journal.pending() if client else None
    ctx = compound.Context(receipt["context_json"])
    assert compound.retry_publication(ctx).status == "accepted"
    if client:
        assert client.journal.pending() == pending
    assert invoke("citations") == 5 and len(calls) == 2
    assert read_coverage(path)["state"] == "complete"
    assert {row["ref_key"] for row in rows(path, "SELECT * FROM cites")} == set("12345")


def test_rows_without_typed_receipt_never_claim_verified_coverage(workspace):
    path, _client, _doc = workspace
    seed(path, "citations", "1")
    assert read_coverage(path)["state"] == "unknown"
    with closing(generation._connect(path)) as conn:
        assert not cites.complete(conn, "paper")


def test_replaced_bytes_even_with_same_size_and_mtime_invalidate_coverage(driver):
    path, _client, document, _calls, install, invoke = driver
    install("citations")
    assert invoke("citations") == 2 and read_coverage(path)["state"] == "complete"
    before = document.path.stat()
    raw = document.path.read_bytes()
    document.path.write_bytes(raw[:-1] + (b" " if raw[-1:] != b" " else b"\n"))
    os.utime(document.path, ns=(before.st_atime_ns, before.st_mtime_ns))
    assert document.path.stat().st_size == before.st_size
    assert read_coverage(path)["state"] == "unknown"


def test_cold_reader_requires_existing_normal_verification_before_claiming_complete(driver):
    from paper_daily import document_reader

    path, _client, document, _calls, install, invoke = driver
    install("citations")
    assert invoke("citations") == 2 and read_coverage(path)["state"] == "complete"
    document_reader._FACTORIES.clear()
    with closing(generation._connect(path)) as conn:
        assert cites.coverage(conn, "paper")["state"] == "unverified"
    assert read_coverage(path)["state"] == "complete"
    reader = document_reader.from_workspace(path, legacy_root=document.path.parent)
    assert reader.resolve("paper").available
    assert read_coverage(path)["state"] == "complete"


@pytest.mark.parametrize(
    "bad",
    [
        {"kind": "citation_coverage", "sent": ["1"], "answered": ["2"]},
        {"kind": "citation_coverage", "sent": ["1", "1"], "answered": ["1"]},
        {"kind": "citation_coverage", "sent": [], "answered": []},
        {"kind": "other", "sent": ["1"], "answered": ["1"]},
    ],
)
def test_invalid_coverage_metadata_rejected_before_any_save(workspace, bad):
    path, client, _document = workspace
    ctx = begin(path, "citations")
    row = compound.row(ctx, "1", title="Reference", gist="Method")
    before = client.journal.pending() if client else None
    with pytest.raises(ValueError):
        compound.publish(ctx, puts=[row], completion=bad)
    assert rows(path, "SELECT * FROM cites") == []
    if client:
        assert client.journal.pending() == before


def test_empty_or_malformed_answer_preserves_saved_research_without_success_receipt(
    driver, monkeypatch
):
    path, _client, _document, _calls, _install, invoke = driver
    seed(path, "citations", "old")
    before = rows(path, "SELECT * FROM cites")
    count = len(rows(path, "SELECT * FROM research_compound_requests"))
    for answer in ("", "not JSON", "[]"):
        monkeypatch.setattr(
            llm, "complete", lambda *a, answer=answer, **kw: (answer, "fixture failure")
        )
        assert invoke("citations") == 0
        assert rows(path, "SELECT * FROM cites") == before
        assert len(rows(path, "SELECT * FROM research_compound_requests")) == count


def test_fetch_timestamp_does_not_complete_the_missing_story(workspace):
    path, _client, _doc = workspace
    with store.connect() as conn:
        store.set_kv(conn, "followups.checked.paper", "2026-10-30T00:00:00+00:00")
        assert not followups.done(conn, "paper")
        expected = followups.overview_edit_snapshot(conn, "paper")
    followups.edit_overview("paper", "", [], expected=expected)
    with store.connect() as conn:
        assert not followups.done(conn, "paper")
        expected = followups.overview_edit_snapshot(conn, "paper")
    followups.edit_overview("paper", "Accepted research context", [], expected=expected)
    with store.connect() as conn:
        assert followups.done(conn, "paper")


def test_title_only_and_unrequested_reference_keys_do_not_count_as_answered(driver, monkeypatch):
    path, _client, _document, _calls, _install, invoke = driver
    monkeypatch.setattr(
        llm,
        "complete",
        lambda *a, **kw: (
            json.dumps([{"key": "1", "title": "Only a title"}] + answers(["invented"])),
            "ok",
        ),
    )
    assert invoke("citations") == 0
    assert rows(path, "SELECT * FROM cites") == []
    assert read_coverage(path)["state"] == "unknown"


def test_gui_metadata_check_never_hashes_or_claims_complete(driver, monkeypatch):
    path, _client, _document, _calls, install, invoke = driver
    install("citations")
    assert invoke("citations") == 2
    monkeypatch.setattr(compound, "_input_current", lambda *_: pytest.fail("GUI source hashing"))
    with closing(generation._connect(path)) as conn:
        assert cites.coverage(conn, "paper")["state"] == "unverified"
        assert not cites.complete(conn, "paper")


@pytest.mark.parametrize("replace_source", [False, True])
def test_overview_waits_for_both_chains_and_preserves_original_source(
    workspace,
    monkeypatch,
    replace_source,
):
    import threading

    from paper_daily import closeread, dive, research_question_jobs, resources, venues

    path, _client, document = workspace
    monkeypatch.setattr(analyze, "PDF_DIR", document.path.parent)
    monkeypatch.setattr(analyze, "has_pdf", lambda _: True)
    monkeypatch.setattr(
        analyze,
        "status",
        lambda *a, **kw: dict(
            pdf=True,
            dive=False,
            highlights=True,
            cites=False,
            later=False,
        ),
    )
    monkeypatch.setattr(venues, "refresh", lambda *a, **kw: None)
    monkeypatch.setattr(resources, "needs_check", lambda *a: False)
    monkeypatch.setattr(research_question_jobs, "ensure", lambda *a, **kw: ([], "fixture"))
    citation_ready, explanation_ready = threading.Event(), threading.Event()
    stories = []

    def write_dive(**kwargs):
        assert citation_ready.wait(5)
        return 1

    def close_reading(*a, **kw):
        if replace_source:
            before = document.path.stat()
            raw = document.path.read_bytes()
            document.path.write_bytes(raw[:-1] + b" ")
            os.utime(document.path, ns=(before.st_atime_ns, before.st_mtime_ns))
        explanation_ready.set()
        return "Accepted close reading", "ok"

    def references(*a, **kw):
        citation_ready.set()
        return 0

    def later(*a, **kwargs):
        assert kwargs["overview_too"] is False
        with store.connect(path=path) as conn:
            store.set_kv(conn, "followups.checked.paper", "2026-10-30T00:00:00+00:00")
        return 0

    def overview(*a, **kwargs):
        assert explanation_ready.is_set() and citation_ready.is_set()
        stories.append(kwargs["database"])
        return True, "ok"

    monkeypatch.setattr(dive, "dive_ahead", write_dive)
    monkeypatch.setattr(closeread, "write", close_reading)
    monkeypatch.setattr(cites, "analyse", references)
    monkeypatch.setattr(followups, "analyse", later)
    monkeypatch.setattr(followups, "overview", overview)
    analyze.analyse("paper", database=path, log=lambda _: None)
    assert stories == ([] if replace_source else [path])
    if replace_source:
        with store.connect(path=path) as conn:
            assert "PDF changed" in analyze.failed(conn, "paper", "later")


@pytest.mark.parametrize("verdict", ["必讀", "值得", "參考", "略過"])
def test_actual_chinese_verdicts_are_meaningful_and_corrupted_literals_are_not(verdict):
    row = dict(verdict=verdict, purpose="Role", gist="Method", why="Rationale")
    assert compound.citation_answered(row)
    assert not compound.citation_answered({**row, "verdict": "??"})
