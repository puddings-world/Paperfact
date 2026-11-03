"""One explicit workflow connects canonical highlights and explanation evidence."""

import json
from contextlib import closing

import pytest
from test_highlight_generation import ready as _ready
from test_highlight_generation import workspace as _workspace

from paper_daily import llm, reading_annotation_jobs, store, sync_capture
from paper_daily import research_generation as generation
from paper_daily.ai_types import Completion

workspace = _workspace
ready = _ready


@pytest.fixture
def explained(ready, monkeypatch):
    database = ready[0]
    for table in ("dives", "close_readings"):
        with closing(generation._connect(database)) as conn:
            context = generation.begin_generation(
                conn,
                table=table,
                owner_id="paper",
                input_reader="target",
            )
        assert (
            generation.publish_generation(
                context,
                row={
                    "paper_id": "paper",
                    "body": "## Methods\nThe controlled comparison explains the result.",
                    "written_at": store.now(),
                    "spec": "fixture",
                },
            ).status
            == "accepted"
        )
    highlight_model = llm.complete_result
    links = []

    def complete(prompt, **kwargs):
        if prompt.startswith("{"):
            links.append(json.loads(prompt))
            return Completion(
                json.dumps(
                    {
                        "links": [
                            {
                                "quote": 0,
                                "section": "dive:0",
                                "explanation": "This supports the comparison.",
                            }
                        ]
                    }
                )
            )
        return highlight_model(prompt, **kwargs)

    monkeypatch.setattr(llm, "complete_result", complete)
    return ready, links


def run(ready, **kwargs):
    return reading_annotation_jobs.prepare(
        ready[0], "paper", legacy_root=ready[2].path.parent, **kwargs
    )


def test_first_analysis_links_evidence_and_second_run_is_offline_without_accounts(
    explained, monkeypatch
):
    ready, links = explained
    result, reason = run(ready)
    assert reason == "ok" and result["marks"]["mapped"] == 1
    assert result["explanation"]["links"][0]["quote"] == 0
    assert not result["explanation_pending"]
    assert len(ready[5]) == 1 and len(links) == 1
    ready[2].path.unlink()
    monkeypatch.setattr(
        llm, "capture_connections", lambda: pytest.fail("Cached research needs no account")
    )
    monkeypatch.setattr(
        llm, "complete_result", lambda *a, **k: pytest.fail("Cached research called AI")
    )
    cached, reason = run(ready)
    assert reason == "cached" and cached == result


def test_link_failure_reports_partial_success_without_discarding_highlights(explained, monkeypatch):
    ready, _ = explained
    complete = llm.complete_result
    monkeypatch.setattr(
        llm,
        "complete_result",
        lambda prompt, **kwargs: (
            Completion(None, "Link service unavailable")
            if prompt.startswith("{")
            else complete(prompt, **kwargs)
        ),
    )
    result, reason = run(ready)
    assert result["marks"]["mapped"] == 1
    assert result["explanation_pending"] and result["explanation"] is None
    assert "unavailable" in result["explanation_reason"]
    assert "incomplete" in reason
    with closing(generation._connect(ready[0])) as conn:
        assert conn.execute("SELECT count(*) FROM paper_highlight_analysis").fetchone()[0] == 1
        assert conn.execute("SELECT count(*) FROM pdf_ai_highlights").fetchone()[0] == 1
        assert conn.execute("SELECT count(*) FROM paper_reading_links").fetchone()[0] == 0


def test_one_workflow_keeps_original_account_across_both_phases(explained, monkeypatch):
    ready, _ = explained
    complete = llm.complete_result

    def switch_account(prompt, **kwargs):
        response = complete(prompt, **kwargs)
        ready[3].update(account="changed", model="changed-model")
        return response

    monkeypatch.setattr(llm, "complete_result", switch_account)
    assert run(ready)[0]["explanation"]
    assert ready[4] == [{"account": "original", "model": "original-model"}] * 2


def test_deleted_canonical_analysis_stays_deleted_without_explicit_force(explained, monkeypatch):
    ready, _ = explained
    assert run(ready)[0]["explanation"]
    with closing(generation._connect(ready[0])) as conn:
        observed = sync_capture.observe_target(conn, "paper", "paper", "highlight_analysis")
        with sync_capture.expecting(conn, [observed]):
            conn.execute("DELETE FROM paper_highlight_analysis WHERE paper_id='paper'")
            conn.commit()
    monkeypatch.setattr(llm, "capture_connections", lambda: pytest.fail("Deletion prompted for AI"))
    result, reason = run(ready)
    assert result["analysis"] == {"items": [], "known": True}
    assert result["marks"] is None and "deleted" in reason


def test_duplicate_workflow_activation_does_not_repeat_paid_phase(explained, monkeypatch):
    ready, links = explained
    complete = llm.complete_result

    def duplicate(prompt, **kwargs):
        result, reason = run(ready)
        assert result is None and "already running" in reason
        return complete(prompt, **kwargs)

    monkeypatch.setattr(llm, "complete_result", duplicate)
    assert run(ready)[0]["explanation"]
    assert len(ready[5]) == len(links) == 1


def test_highlights_can_finish_before_explanation_exists(ready):
    result, reason = run(ready)
    assert reason == "ok" and result["marks"]["mapped"] == 1
    assert result["explanation"] is None and not result["explanation_pending"]
    assert "Complete the explanation" in result["explanation_reason"]
    assert len(ready[5]) == 1


def test_new_selection_between_phases_is_not_linked_as_the_old_result(explained, monkeypatch):
    from paper_daily.highlight_jobs import HighlightJob
    from paper_daily.reading_link_jobs import ReadingLinksJob

    ready, links = explained
    original = ReadingLinksJob.capture

    def intervene(*args, **kwargs):
        ready[6][:] = [1]
        assert (
            HighlightJob.capture(ready[0], "paper", legacy_root=ready[2].path.parent).run().status
            == "accepted"
        )
        return original(*args, **kwargs)

    monkeypatch.setattr(ReadingLinksJob, "capture", staticmethod(intervene))
    result, reason = run(ready)
    assert result["explanation_pending"] and "incomplete" in reason
    assert "changed" in result["explanation_reason"]
    assert links == []
    with closing(generation._connect(ready[0])) as conn:
        body = json.loads(
            conn.execute("SELECT body_json FROM paper_highlight_analysis").fetchone()[0]
        )
    assert body["items"][0]["text"] != result["analysis"]["items"][0]["text"]


def test_the_materials_panel_shows_the_saved_analysis_for_the_pdf_in_use(ready, monkeypatch):
    from paper_daily import materials
    from paper_daily.document_reader import from_workspace

    assert run(ready)[1] == "ok"
    document = from_workspace(ready[0], legacy_root=ready[2].path.parent).resolve("paper")
    saved = materials._saved_analysis("paper", document)
    assert saved is not None and saved["items"]
    assert all(item["document_hash"] == document.sha256 for item in saved["items"])
    # Made from another version of the PDF: not shown as if it were this one's.
    monkeypatch.setattr(materials, "document_current", lambda _document: False)
    assert materials._saved_analysis("paper", document) is None
