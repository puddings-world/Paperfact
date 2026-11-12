"""Saved A1 SQL output coverage never borrows today's original or invokes a model."""

import json
import sqlite3
from contextlib import closing

import pytest
from test_question_generation import ready as ready_fixture
from test_reading_link_jobs import QUOTE
from test_reading_link_jobs import links_ready as links_fixture
from test_research_evidence import UNIQUE, pdf
from test_research_evidence import source as source_fixture
from test_research_generation import workspace as workspace_fixture

from paper_daily import annotation_content, audit_appraisal, audit_inputs, llm, research_audit
from paper_daily.ai_types import Completion
from paper_daily.reading_link_jobs import ReadingLinksJob
from paper_daily.research_question_jobs import QuestionJob

source = source_fixture
workspace = workspace_fixture
ready = ready_fixture
links_ready = links_fixture
STAMP = "2026-10-30T00:00:00+00:00"
INPUT = "a" * 64


def put(source, feature, body, *, digest="current", source_hash=INPUT):
    row = dict(
        paper_id="paper",
        body_json=json.dumps(body),
        source_hash=source_hash,
        document_hash=source.sha256 if digest == "current" else digest,
        written_at=STAMP,
    )
    with closing(sqlite3.connect(source._owner.db_path)) as conn, conn:
        conn.execute("BEGIN")
        annotation_content.initialize(conn)
        conn.execute(
            "INSERT OR REPLACE INTO " + annotation_content.FEATURES[feature] + " VALUES(?,?,?,?,?)",
            tuple(row.values()),
        )
    return row


def questions():
    return {
        "items": [
            {
                "question": "Do 900 participants support causality?",
                "why": "Prose about 800 participants is not an original quotation.",
                "evidence": UNIQUE,
                "page": 2,
            }
        ]
    }


def highlights():
    return dict(
        items=[
            dict(
                text=UNIQUE, page=2, kind="evidence", reason="A declared quotation", source="page:2"
            )
        ],
        coverage=dict(pages=2, empty_pages=[], chunks=1, has_page_numbers=True),
    )


def links():
    return dict(
        analysis_hash=INPUT,
        links=[
            dict(
                quote=0,
                section="dive:0",
                explanation="This comparison proves general benefit in 50 participants.",
            )
        ],
    )


def context(source, **changes):
    row = dict(
        paper_id="paper",
        summary="A synthesis mentions 50 participants.",
        reading_json=json.dumps(
            [dict(title="Unresolved related title", direction="prior", why="Read 3 comparisons.")]
        ),
        written_at=STAMP,
        edited=0,
    )
    row.update(changes)
    with closing(sqlite3.connect(source._owner.db_path)) as conn, conn:
        conn.execute("INSERT OR REPLACE INTO paper_context VALUES(?,?,?,?,?)", tuple(row.values()))
    return row


def capture(source):
    return audit_inputs.AuditCapture.capture(source._owner.db_path, "paper", document=source)


def test_actual_typed_producers_are_audited_without_writes_or_more_completions(
    links_ready, monkeypatch
):
    database, _client, document, _selected, _routes, _requests, _highlight = links_ready
    calls = []

    def complete(prompt, **_kwargs):
        request = json.loads(prompt)
        calls.append(request)
        result = (
            {"links": [{"quote": 0, "section": "dive:0", "explanation": "Linked rationale"}]}
            if "quotes" in request
            else {
                "questions": [
                    {
                        "question": "Which comparison?",
                        "why": "Inspect its conditions.",
                        "evidence": QUOTE,
                    }
                ]
            }
        )
        return Completion(json.dumps(result))

    monkeypatch.setattr(llm, "complete_result", complete)
    question = QuestionJob.capture(database, "paper", legacy_root=document.path.parent)
    assert question.run().status == "accepted"
    linked = ReadingLinksJob.capture(database, "paper", legacy_root=document.path.parent)
    assert linked.run().status == "accepted"
    assert len(calls) == 2
    monkeypatch.setattr(llm, "complete_result", lambda *a, **k: pytest.fail("Audit invoked AI"))
    before = database.read_bytes()
    snapshot = audit_inputs.AuditCapture.capture(database, "paper", document=document)
    report = snapshot.run()
    selected = [row for row in report["items"] if row["feature"] in research_audit.A1_SQL_FEATURES]
    assert {row["feature"] for row in selected} == {"research_questions", "reading_links"}
    assert all(row["document_hash"] == document.sha256 for row in selected)
    assert all(row["provenance"]["input_hash"] != document.sha256 for row in selected)
    assert all(row["passages"][0]["quote"] == QUOTE for row in selected)
    assert (
        sum(
            row["state"] == "located"
            for row in report["checks"]
            if row["feature"] in research_audit.A1_SQL_FEATURES
        )
        == 2
    )
    assert report["semantics"] == "not_checked" and "semantic_support" in report["not_checked"]
    assert snapshot.current() and database.read_bytes() == before


def test_question_prose_is_not_a_quote_and_context_never_claims_pdf_identity(source, monkeypatch):
    put(source, "research_questions", questions())
    context(source)
    monkeypatch.setattr(llm, "capture_connections", lambda: pytest.fail("Read captured a route"))
    before = source._owner.db_path.read_bytes()
    report = capture(source).run()
    question = next(row for row in report["items"] if row["feature"] == "research_questions")
    assert (
        question["text"]
        == questions()["items"][0]["question"] + "\n\n" + questions()["items"][0]["why"]
    )
    assert [row["quote"] for row in question["passages"]] == [UNIQUE]
    context_rows = [row for row in report["items"] if row["feature"] == "paper_context"]
    assert len(context_rows) == 2
    assert all(row["document_hash"] is None and not row["passages"] for row in context_rows)
    assert all(row["provenance"]["input_hash"] is None for row in context_rows)
    assert all(
        row["state"] == "source_unknown"
        for row in report["checks"]
        if row["feature"] == "paper_context"
    )
    assert not any(
        row["rule"] == "reference_identity"
        for row in report["checks"]
        if row["feature"] == "paper_context"
    )
    assert source._owner.db_path.read_bytes() == before


@pytest.mark.parametrize("feature", ["research_questions", "reading_links"])
def test_source_less_typed_rows_do_not_promote_input_digest_to_document_hash(source, feature):
    put(source, "highlight_analysis", highlights(), digest=None)
    put(
        source,
        feature,
        questions() if feature == "research_questions" else links(),
        digest=None,
        source_hash=source.sha256,
    )
    report = capture(source).run()
    item = next(row for row in report["items"] if row["feature"] == feature)
    assert item["document_hash"] is None and item["provenance"]["input_hash"] == source.sha256
    expected_states = {"source_unknown"}
    if feature == "reading_links":
        # Owner-approved: legacy links without complete input provenance need review.
        expected_states.add("linked_analysis_changed")
        assert item["passages"] == []
        assert item["provenance"]["link_state"] == "analysis_changed"
    assert {
        row["state"] for row in report["checks"] if row["feature"] == feature
    } == expected_states


@pytest.mark.parametrize(
    "change,state",
    [
        ("missing", "linked_analysis_missing"),
        ("input", "linked_analysis_changed"),
        ("document", "linked_source_mismatch"),
        ("index", "linked_quote_unavailable"),
    ],
)
def test_link_quote_indexes_never_borrow_from_changed_or_missing_highlights(source, change, state):
    if change != "missing":
        put(
            source,
            "highlight_analysis",
            highlights(),
            digest="b" * 64 if change == "document" else "current",
            source_hash="b" * 64 if change == "input" else INPUT,
        )
    body = links()
    if change == "index":
        body["links"][0]["quote"] = 31
    put(source, "reading_links", body)
    report = capture(source).run()
    item = next(row for row in report["items"] if row["feature"] == "reading_links")
    assert item["passages"] == [] and item["document_hash"] == source.sha256
    assert any(row["state"] == state for row in report["checks"])
    assert not any(
        row["rule"] == "quote_location"
        for row in report["checks"]
        if row["feature"] == "reading_links"
    )
    assert report["semantics"] == "not_checked"


def test_old_typed_A_keeps_A_even_when_same_quote_occurs_in_current_B(source):
    put(source, "highlight_analysis", highlights())
    put(source, "reading_links", links())
    put(source, "research_questions", questions())
    original = source.sha256
    source.path.unlink()
    pdf(source.path, [[UNIQUE, "A different document version."]])
    source._owner.invalidate()
    current = source._owner.resolve("paper")
    assert current.sha256 != original
    report = capture(current).run()
    added = [row for row in report["items"] if row["feature"] in research_audit.A1_SQL_FEATURES]
    assert all(row["document_hash"] == original for row in added)
    quotes = [row for row in report["checks"] if row["rule"] == "quote_location"]
    assert quotes and all(
        row["state"] == "source_mismatch" and row["location"] is None for row in quotes
    )


@pytest.mark.parametrize("feature", ["research_questions", "reading_links", "paper_context"])
def test_new_saved_output_and_provenance_change_invalidates_capture(source, feature):
    if feature == "paper_context":
        context(source)
    else:
        put(source, feature, questions() if feature == "research_questions" else links())
    saved = capture(source)
    before = saved.run()
    table = "paper_context" if feature == "paper_context" else annotation_content.FEATURES[feature]
    with closing(sqlite3.connect(source._owner.db_path)) as conn, conn:
        field, value = ("edited", 1) if feature == "paper_context" else ("source_hash", "c" * 64)
        conn.execute(f"UPDATE {table} SET {field}=?", (value,))
    assert not saved.current()
    with pytest.raises(research_audit.AuditError, match="saved_content_changed"):
        saved.run()
    assert capture(source).run()["id"] != before["id"]


def test_metadata_only_new_output_during_capture_is_not_missed(source, monkeypatch):
    from paper_daily import research_evidence

    put(source, "research_questions", questions())
    original = research_evidence.capture

    def change(document):
        snapshot = original(document)
        with closing(sqlite3.connect(source._owner.db_path)) as conn, conn:
            conn.execute("UPDATE paper_research_questions SET source_hash=?", ("b" * 64,))
        return snapshot

    monkeypatch.setattr(research_evidence, "capture", change)
    with pytest.raises(research_audit.AuditError, match="saved_content_changed"):
        capture(source)


@pytest.mark.parametrize(
    "feature,body",
    [
        ("research_questions", {"items": []}),
        ("research_questions", {"items": [{"question": "Missing evidence"}]}),
        ("reading_links", {"links": [0], "analysis_hash": INPUT}),
        (
            "reading_links",
            {
                "links": [{"quote": True, "section": "dive:0", "explanation": "Invalid index"}],
                "analysis_hash": INPUT,
            },
        ),
        ("reading_links", {"links": [], "analysis_hash": "not-a-digest"}),
    ],
)
def test_nonempty_malformed_typed_content_fails_without_writes_or_truncation(source, feature, body):
    put(source, feature, body)
    before = source._owner.db_path.read_bytes()
    with pytest.raises(research_audit.AuditError, match="invalid_saved_content"):
        capture(source)
    assert source._owner.db_path.read_bytes() == before


@pytest.mark.parametrize(
    "value",
    [
        "{",
        "null",
        "{}",
        '[{"title":"Missing fields"}]',
        '[{"title":"A","title":"B","direction":"prior","why":"C"}]',
        "[1]",
        json.dumps([dict(title="A", direction="prior", why="B")] * 101),
    ],
)
def test_malformed_context_recommendations_fail_closed(source, value):
    context(source, reading_json=value)
    before = source._owner.db_path.read_bytes()
    with pytest.raises(research_audit.AuditError, match="invalid_saved_content"):
        capture(source)
    assert source._owner.db_path.read_bytes() == before


@pytest.mark.parametrize("feature", ["reading_links", "research_questions", "paper_context"])
def test_oversized_new_rows_fail_whole_capture_instead_of_truncating(source, feature):
    if feature == "paper_context":
        context(source, summary="x" * (research_audit.MAX_BYTES + 1))
    else:
        put(source, feature, {"unread": "x" * (research_audit.MAX_BYTES + 1)})
    before = source._owner.db_path.read_bytes()
    with pytest.raises(research_audit.AuditError, match="input_limit"):
        capture(source)
    assert source._owner.db_path.read_bytes() == before


@pytest.mark.parametrize("feature", ["reading_links", "research_questions", "paper_context"])
def test_added_A1_categories_cannot_expand_paid_appraisal_selection(source, monkeypatch, feature):
    if feature == "paper_context":
        context(source)
    else:
        put(source, feature, questions() if feature == "research_questions" else links())
    selected = capture(source)
    identity = next(
        row["id"] for row in json.loads(selected._items_json) if row["feature"] == feature
    )
    monkeypatch.setattr(llm, "capture_connections", lambda: pytest.fail("A1 captured a paid route"))
    with pytest.raises(research_audit.AuditError, match="invalid_selection"):
        audit_appraisal.AppraisalJob.prepare(selected, [identity])


@pytest.mark.parametrize(
    "mutation", ["extra", "old_feature", "fake_context_source", "digest", "borrowed", "state_shape"]
)
def test_optional_provenance_is_closed_and_only_new_categories_can_use_it(source, mutation):
    put(source, "reading_links", links())
    values = json.loads(capture(source)._items_json)
    item = next(row for row in values if row["feature"] == "reading_links")
    if mutation == "extra":
        item["provenance"]["workspace"] = "untrusted"
    elif mutation == "old_feature":
        item["feature"] = "claims"
    elif mutation == "fake_context_source":
        item["feature"] = "paper_context"
        item["provenance"]["link_state"] = None
    elif mutation == "digest":
        item["provenance"]["record_hash"] = "wrong"
    elif mutation == "state_shape":
        item["provenance"]["link_state"] = []
    else:
        item["passages"] = [dict(quote=UNIQUE, document_hash=source.sha256, page=2, anchor=None)]
    with pytest.raises(research_audit.AuditError):
        research_audit.validate(values)


@pytest.mark.parametrize("feature", ["reading_links", "research_questions", "paper_context"])
@pytest.mark.parametrize("shape", ["missing", "extra"])
def test_new_saved_nonempty_table_with_missing_or_unknown_shape_fails(source, feature, shape):
    table = "paper_context" if feature == "paper_context" else annotation_content.FEATURES[feature]
    with closing(sqlite3.connect(source._owner.db_path)) as conn, conn:
        conn.execute("BEGIN")
        annotation_content.initialize(conn)
        if shape == "missing":
            conn.execute(f"DROP TABLE {table}")
            conn.execute(f"CREATE TABLE {table}(paper_id TEXT,body_json TEXT)")
            conn.execute(f"INSERT INTO {table} VALUES('paper','nonempty saved data')")
        else:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN unknown TEXT")
            conn.execute(
                f"INSERT INTO {table}(paper_id,written_at,edited) VALUES('paper',?,0)", (STAMP,)
            ) if feature == "paper_context" else conn.execute(
                f"INSERT INTO {table}(paper_id,body_json,source_hash,written_at,unknown) "
                "VALUES('paper','nonempty',?,?,'unmodelled')",
                (INPUT, STAMP),
            )
    before = source._owner.db_path.read_bytes()
    with pytest.raises(research_audit.AuditError, match="invalid_saved_content"):
        capture(source)
    assert source._owner.db_path.read_bytes() == before


def test_linked_record_cannot_supply_another_papers_quote(source):
    from paper_daily.audit_saved_outputs import annotation_items

    related = put(source, "highlight_analysis", highlights())
    row = put(source, "reading_links", links())
    related["paper_id"] = "another-paper"
    with pytest.raises(research_audit.AuditError, match="invalid_saved_content"):
        annotation_items("reading_links", row, related=related)


def test_combined_new_output_budget_fails_without_silently_dropping_recommendations(source):
    context(
        source, reading_json=json.dumps([dict(title="A", direction="prior", why="x" * 8192)] * 100)
    )
    # The saved row is below 1 MiB but its combined explicit output corpus is over budget.
    put(
        source,
        "research_questions",
        {
            "items": [
                dict(question=str(i), why="x" * 800, evidence=UNIQUE + " " + "y" * 8000, page=2)
                for i in range(6)
            ]
        },
    )
    # The audit has no per-table truncation escape: an over-budget row fails before parsing.
    with closing(sqlite3.connect(source._owner.db_path)) as conn, conn:
        conn.execute("INSERT INTO dives VALUES('paper',?,'now',NULL)", ("x" * 120000,))
        conn.execute(
            "INSERT INTO close_readings(paper_id,body,written_at,spec) "
            "VALUES('paper',?,'now',NULL)",
            ("y" * 120000,),
        )
    before = source._owner.db_path.read_bytes()
    with pytest.raises(research_audit.AuditError, match="input_limit"):
        capture(source)
    assert source._owner.db_path.read_bytes() == before
