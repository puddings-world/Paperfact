"""Saved explanation links must match complete captured inputs, not quote indexes alone."""

import copy
import json

import pytest
from test_reading_link_jobs import capture, save
from test_reading_link_jobs import links_ready as links_ready
from test_reading_link_jobs import ready as ready
from test_reading_link_jobs import workspace as workspace
from test_research_generation import rows

from paper_daily import audit_inputs, llm


@pytest.mark.parametrize("change", ["quote", "reason", "order", "explanation", "legacy"])
def test_old_links_preserve_explanation_but_never_borrow_changed_quote(
    links_ready, monkeypatch, change
):
    database, _client, document, _selected, _routes, requests, highlight = links_ready
    highlight = copy.deepcopy(highlight)
    initial = json.loads(highlight["body_json"])
    initial["items"].append(
        dict(initial["items"][0], text="Another independently selected passage.")
    )
    highlight["body_json"] = json.dumps(initial)
    save(database, "paper_highlight_analysis", "highlight_analysis", highlight)
    assert capture(links_ready).run().status == "accepted"
    original_links = rows(database, "SELECT * FROM paper_reading_links")
    before = audit_inputs.AuditCapture.capture(database, "paper", document=document).run()
    item = next(i for i in before["items"] if i["feature"] == "reading_links")
    assert item["provenance"]["link_state"] == "matched" and len(item["passages"]) == 1
    if change in {"quote", "reason", "order"}:
        changed = copy.deepcopy(initial)
        if change == "order":
            changed["items"].reverse()
        else:
            changed["items"][0]["text" if change == "quote" else "reason"] = (
                "Updated research wording."
            )
        highlight["body_json"] = json.dumps(changed)
        save(database, "paper_highlight_analysis", "highlight_analysis", highlight)
    elif change == "explanation":
        edited = rows(database, "SELECT * FROM dives WHERE paper_id='paper'")[0]
        edited["body"] += "\nNew interpretation."
        save(database, "dives", "dive", edited)
    else:
        edited = dict(original_links[0], source_hash="b" * 64)
        save(database, "paper_reading_links", "reading_links", edited)
    monkeypatch.setattr(llm, "complete_result", lambda *a, **k: pytest.fail("Audit called AI"))
    stored = rows(database, "SELECT * FROM paper_reading_links")
    report = audit_inputs.AuditCapture.capture(database, "paper", document=document).run()
    changed_item = next(i for i in report["items"] if i["feature"] == "reading_links")
    assert changed_item["text"] == item["text"]
    assert changed_item["passages"] == []
    assert changed_item["provenance"]["link_state"] == "analysis_changed"
    assert any(c["state"] == "linked_analysis_changed" for c in report["checks"])
    assert rows(database, "SELECT * FROM paper_reading_links") == stored
    assert stored[0]["body_json"] == original_links[0]["body_json"] and len(requests) == 1
