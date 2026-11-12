"""The real highlight producer's saved content can be revised without another AI call."""

import json

from test_highlight_generation import capture, marks, rows
from test_highlight_generation import ready as ready
from test_highlight_generation import workspace as workspace

from paper_daily import highlight_draft_revision as revision
from paper_daily import llm
from paper_daily import research_evidence as evidence


def test_actual_generated_highlight_row_revises_without_changing_saved_layers_or_running_ai(
    ready, monkeypatch
):
    assert capture(ready).run().status == "accepted"
    database, client, document = ready[:3]
    row = rows(database, "SELECT * FROM paper_highlight_analysis")[0]
    saved_marks = marks(database)
    snapshot = evidence.capture(document)
    before = (
        rows(database, "SELECT * FROM paper_highlight_analysis"),
        marks(database),
        client.journal.pending() if client else None,
        len(ready[5]),
    )
    draft = revision.editable(row)
    draft["items"][0]["reason"] = (
        "Human appraisal: this controls the comparison but not generalization."
    )
    draft["items"][0]["kind"] = "limitation"

    def forbidden(*args, **kwargs):
        raise AssertionError("Manual highlight revision invoked AI")

    monkeypatch.setattr(llm, "complete_result", forbidden)
    result = revision.revise_for_receiver(snapshot, row, json.dumps(draft))
    assert result["all_quotes_located"] and result["analysis"] is not None
    assert result["analysis"]["items"][0]["reason"] == draft["items"][0]["reason"]
    assert result["analysis"]["items"][0]["kind"] == "limitation"
    assert result["analysis"]["coverage"] == json.loads(row["body_json"])["coverage"]
    assert result["source"]["document_hash"] == document.sha256
    assert result["source"]["paper_id"] == (document.paper_id or document.local_id)
    assert result["marks"][0]["source_key"] == saved_marks[0]["source_key"]
    assert result["marks"][0]["anchor"] == json.loads(saved_marks[0]["anchor"])
    assert before == (
        rows(database, "SELECT * FROM paper_highlight_analysis"),
        marks(database),
        client.journal.pending() if client else None,
        len(ready[5]),
    )
