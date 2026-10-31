"""Tolerant model envelopes never bypass research validators or publication."""

import json
from dataclasses import replace

import pytest
from test_highlight_generation import QUOTES
from test_highlight_generation import ready as _ready
from test_presentations import _generate, _slide
from test_presentations import deck as _deck
from test_presentations import reply as deck_reply
from test_presentations import research as _research
from test_reading_annotation_jobs import explained as _explained
from test_reading_annotation_jobs import run as annotations
from test_research_compound import driver as _driver
from test_research_compound import seed
from test_research_generation import rows
from test_research_generation import workspace as _workspace

from paper_daily import annotation_content, followups, llm, presentations, reading_links
from paper_daily import research_questions as questions
from paper_daily.ai_types import Completion, Settings
from paper_daily.reading_link_jobs import ReadingLinksJob
from paper_daily.research_question_jobs import QuestionJob

workspace = _workspace
driver = _driver
research = _research
deck = _deck
ready = _ready
explained = _explained


def envelope(text, style="prefaced"):
    if style == "prefaced":
        return "References [12] inform this reply.\n```json\n" + text + "\n```\nEnd of reply."
    if style == "fenced":
        return "```JSON\n" + text + "\n```"
    return "Analysis [12] is only context; answer follows:\n" + text


@pytest.mark.parametrize("style", ["prefaced", "fenced", "bracketed"])
def test_link_and_question_producers_keep_call_contract_and_validate_source(monkeypatch, style):
    part = {"id": "dive:0", "title": "Method", "text": "Explanation"}
    analysis = {
        "source_hash": "fixture",
        "items": [{"text": QUOTES[0], "page": 1, "reason": "Controlled evidence"}],
    }
    cfg = Settings("gateway", model="requested")
    calls = []
    payloads = [
        {
            "links": [
                {"quote": 0, "section": "dive:0", "explanation": "Explains the effect"},
                {"quote": 99, "section": "other", "explanation": "Invented"},
            ]
        },
        {
            "questions": [
                {
                    "question": "Why isolate the effect?",
                    "why": "Tests the assumption",
                    "evidence": QUOTES[0],
                }
            ]
        },
    ]

    def model(prompt, **kwargs):
        calls.append((prompt, kwargs))
        return Completion(envelope(json.dumps(payloads[len(calls) - 1]), style))

    monkeypatch.setattr(llm, "complete_result", model)
    linked, reason = reading_links.produce([part], analysis, cfg=cfg)
    assert reason == "ok" and linked["links"] == payloads[0]["links"][:1]
    source = {
        "pages": [{"page": 1, "text": QUOTES[0]}],
        "explanation": "Explanation",
        "close_reading": "Controlled comparison",
    }
    result = questions.produce(source)
    assert result["items"][0]["evidence"] == QUOTES[0]
    assert result["items"][0]["page"] == 1
    assert len(calls) == 2
    assert calls[0][1]["cfg"] is cfg and calls[0][1]["timeout"] == 300
    assert calls[0][1]["task"] == "paper_highlights"
    assert calls[1][1]["timeout"] == 240 and calls[1][1]["task"] == "ask"
    assert json.loads(calls[1][0]) == source


@pytest.mark.parametrize("phase", ["citations", "judge"])
@pytest.mark.parametrize("style", ["prefaced", "fenced", "bracketed"])
def test_real_compound_publication_accepts_typed_wrapped_array(driver, monkeypatch, phase, style):
    database, client, document, calls, install, invoke = driver
    install(phase)
    original = llm.complete
    options = []

    def model(*args, **kwargs):
        options.append(kwargs)
        text, reason = original(*args, **kwargs)
        payload = json.loads(text)
        invalid = dict(payload[0])
        invalid["key" if phase == "citations" else "id"] = "999" if phase == "citations" else 999
        payload.append(invalid)
        return envelope(json.dumps(payload), style), reason

    monkeypatch.setattr(llm, "complete", model)
    before = len(client.journal.pending()) if client else 0
    assert invoke(phase) == 2
    table, key = ("cites", "ref_key") if phase == "citations" else ("followups", "work_id")
    saved = rows(database, f"SELECT * FROM {table} ORDER BY {key}")
    assert len(saved) == 2 and all(row["verdict"] == followups.VERDICTS[0] for row in saved)
    assert calls == [phase] and len(options) == 1
    assert options[0]["timeout"] == 900
    assert options[0]["task"] == ("citations" if phase == "citations" else "followups")
    records = rows(database, "SELECT * FROM research_compound_requests")
    from paper_daily import research_compound as compound

    current = records[-1]
    compound.validate_request_record(current)
    assert (
        compound.retry_publication(compound.Context(current["context_json"])).status == "accepted"
    )
    assert len(rows(database, "SELECT * FROM research_compound_requests")) == len(records)
    assert calls == [phase]
    if client:
        assert len(client.journal.pending()) == before + 2


@pytest.mark.parametrize("phase", ["citations", "judge"])
@pytest.mark.parametrize("bad", ["No JSON answer", "mixed_array"])
def test_malformed_compound_reply_never_overwrites_saved_rows(driver, monkeypatch, phase, bad):
    database, client, _, _, install, invoke = driver
    seed(database, phase if phase == "citations" else "fetch", "curated", edited=1)
    install(phase)
    table, key = ("cites", "ref_key") if phase == "citations" else ("followups", "work_id")
    before = rows(database, f"SELECT * FROM {table} ORDER BY {key}")
    pending = len(client.journal.pending()) if client else 0
    mixed = bad == "mixed_array"
    if mixed:
        # This object is otherwise valid; the scalar alone makes the array invalid.
        item = (
            {"key": "1", "title": "First", "purpose": "Evidence", "gist": "Method"}
            if phase == "citations"
            else {"id": 0, "relation": "Extension"}
        )
        item.update(verdict=followups.VERDICTS[0], why="Core")
        bad = json.dumps([12, item])
    response = bad if mixed else envelope(bad)
    calls = []
    monkeypatch.setattr(llm, "complete", lambda *a, **kw: (calls.append(kw) or response, "ok"))
    assert invoke(phase) == 0
    assert rows(database, f"SELECT * FROM {table} ORDER BY {key}") == before
    assert len(calls) == 1
    if client:
        assert len(client.journal.pending()) == pending


def test_real_overview_publication_and_invalid_refresh_keep_receiver_content(driver, monkeypatch):
    database, _, _, _, install, invoke = driver
    install("judge")
    assert invoke("judge") == 2
    cfg = Settings("gateway", model="overview-model")
    monkeypatch.setattr(llm, "settings", lambda **kw: cfg)
    calls = []
    payload = {
        "summary": "A controlled comparison motivates later work.",
        "reading": [{"title": "Next work", "direction": "Extension", "why": "Tests limits"}],
    }

    def model(*args, **kwargs):
        calls.append(kwargs)
        return envelope(json.dumps(payload)), "ok"

    monkeypatch.setattr(llm, "complete", model)
    assert followups.overview("paper")[0]
    saved = rows(database, "SELECT * FROM paper_context")
    assert saved[0]["summary"] == payload["summary"]
    assert calls[0]["cfg"] is cfg and calls[0]["timeout"] == 600
    assert calls[0]["task"] == "overview"
    payload["reading"] = ["malformed"]
    assert not followups.overview("paper")[0]
    assert rows(database, "SELECT * FROM paper_context") == saved
    assert len(calls) == 2


@pytest.mark.parametrize("style", ["prefaced", "fenced", "bracketed"])
def test_saved_deck_keeps_sources_provenance_and_call_budget(research, monkeypatch, style):
    cfg = Settings("gateway", model="requested", api_key="fixture-private-key")
    calls = []

    def model(prompt, **kwargs):
        calls.append(kwargs)
        return Completion(
            envelope(deck_reply(), style),
            backend="gateway",
            profile="chosen",
            model="reported",
            request_id="initial-operation",
        )

    monkeypatch.setattr(llm, "complete_result", model)
    deck, reason = presentations.generate(
        "ref:deck",
        mode="guide",
        audience="Researchers",
        minutes=10,
        slide_count=4,
        inputs={"original", "dive"},
        cfg=cfg,
    )
    assert reason == "ok" and len(deck.slides) == 4
    saved = presentations.load_deck("ref:deck", "guide")
    assert saved.to_dict() == deck.to_dict()
    assert saved.generation == {
        "inputs": ["dive", "original"],
        "backend": "gateway",
        "profile": "chosen",
        "model": "reported",
        "request_id": "initial-operation",
    }
    assert all(set(slide.sources) <= {"original", "dive"} for slide in saved.slides)
    assert "fixture-private-key" not in json.dumps(saved.to_dict())
    assert len(calls) == 1 and calls[0]["cfg"] is cfg and calls[0]["timeout"] == 600


def test_repair_parses_wrapped_output_once_without_changing_generation(research, monkeypatch):
    raw = json.loads(deck_reply())
    raw["slides"][1]["bullets"] = ["x" * 130]
    calls = []

    def model(prompt, **kwargs):
        calls.append((json.loads(prompt), kwargs))
        payload = raw if len(calls) == 1 else {"slides": [{"index": 1, "slide": _slide(1)}]}
        return Completion(
            envelope(json.dumps(payload)), request_id="initial" if len(calls) == 1 else "repair"
        )

    monkeypatch.setattr(llm, "complete_result", model)
    generated, reason = _generate()
    assert reason == "ok" and len(generated.slides) == 4
    assert len(calls) == 2 and [row["index"] for row in calls[1][0]["slides"]] == [1]
    assert [call[1]["timeout"] for call in calls] == [600, 300]
    assert generated.generation["request_id"] == "initial"
    assert presentations.load_deck("ref:deck", "guide").to_dict() == generated.to_dict()


@pytest.mark.parametrize(
    "bad",
    [
        "not structured",
        '{"title":"wrong","slides":[]}',
        '{"title":"wrong","slides":[{"sources":["invented"]}]}',
    ],
)
def test_wrapped_invalid_deck_does_not_overwrite_curated_deck(research, deck, monkeypatch, bad):
    deck.edited = True
    deck.slides[0].title = "My curated research interpretation"
    presentations.save_deck(deck)
    before = presentations._path(deck.paper_id, deck.mode).read_bytes()
    calls = []
    monkeypatch.setattr(
        llm, "complete_result", lambda *a, **kw: calls.append(kw) or Completion(envelope(bad))
    )
    generated, _ = _generate()
    assert generated is None
    assert presentations._path(deck.paper_id, deck.mode).read_bytes() == before
    assert len(calls) == 1


@pytest.mark.parametrize("bad", ["malformed", "fabricated"])
def test_typed_question_job_saves_source_bound_wrapped_reply_and_keeps_old_on_failure(
    explained, monkeypatch, bad
):
    ready, _ = explained
    database, client, document = ready[:3]
    payload = {
        "questions": [
            {
                "question": "Why isolate independent observations?",
                "why": "Tests the core assumption",
                "evidence": QUOTES[0],
            }
        ]
    }
    calls = []
    monkeypatch.setattr(
        llm,
        "complete_result",
        lambda *a, **kw: calls.append(kw) or Completion(envelope(json.dumps(payload))),
    )
    job = QuestionJob.capture(database, "paper", legacy_root=document.path.parent)
    assert job.run().status == "accepted"
    assert job.run() == job.publication and len(calls) == 1
    saved = rows(database, "SELECT * FROM paper_research_questions")
    assert saved[0]["document_hash"] == document.sha256
    assert (
        annotation_content.decode("research_questions", saved[0]["body_json"])["items"][0][
            "evidence"
        ]
        == QUOTES[0]
    )
    payload["questions"][0]["evidence"] = "Fabricated quote not present in the original paper."
    if bad == "malformed":
        monkeypatch.setattr(
            llm, "complete_result", lambda *a, **kw: calls.append(kw) or Completion("No JSON")
        )
    with pytest.raises(ValueError):
        QuestionJob.capture(database, "paper", legacy_root=document.path.parent).run()
    assert rows(database, "SELECT * FROM paper_research_questions") == saved
    assert len(calls) == 2 and all(call["timeout"] == 240 for call in calls)
    if client:
        events = [
            op
            for op in client.journal.pending()
            if op.get("payload", {}).get("feature") == "research_questions"
        ]
        assert len(events) == 1 and events[0]["payload"]["source_document_hash"] == document.sha256


@pytest.mark.parametrize("bad", ["malformed", "unknown_quote", "unknown_section"])
def test_typed_links_job_keeps_group_source_and_failed_refresh_preserves_links(
    explained, monkeypatch, bad
):
    ready, link_calls = explained
    database, client, document = ready[:3]
    original = llm.complete_result

    def model(prompt, **kwargs):
        result = original(prompt, **kwargs)
        return replace(result, text=envelope(result.text)) if prompt.startswith("{") else result

    monkeypatch.setattr(llm, "complete_result", model)
    result, reason = annotations(ready)
    assert reason == "ok" and result["marks"]["mapped"] == 1
    assert result["explanation"]["links"][0]["quote"] == 0
    saved = rows(database, "SELECT * FROM paper_reading_links")
    marks = rows(database, "SELECT * FROM pdf_ai_highlights")
    assert saved[0]["document_hash"] == document.sha256
    assert len(link_calls) == 1
    assert annotations(ready)[1] == "cached" and len(link_calls) == 1
    failed = (
        "No JSON"
        if bad == "malformed"
        else envelope(
            json.dumps(
                {
                    "links": [
                        {
                            "quote": 99 if bad == "unknown_quote" else 0,
                            "section": "missing" if bad == "unknown_section" else "dive:0",
                            "explanation": "Invalid evidence reference",
                        }
                    ]
                }
            )
        )
    )
    monkeypatch.setattr(llm, "complete_result", lambda *a, **kw: Completion(failed))
    with pytest.raises(ValueError):
        ReadingLinksJob.capture(database, "paper", legacy_root=document.path.parent).run()
    assert rows(database, "SELECT * FROM paper_reading_links") == saved
    assert rows(database, "SELECT * FROM pdf_ai_highlights") == marks
    if client:
        events = [
            op
            for op in client.journal.pending()
            if op.get("payload", {}).get("feature") == "reading_links"
        ]
        assert len(events) == 1 and events[0]["payload"]["source_document_hash"] == document.sha256


@pytest.mark.parametrize("bad", ["malformed", "unknown_source"])
def test_failed_wrapped_repair_keeps_previous_editable_deck(research, deck, monkeypatch, bad):
    deck.edited = True
    deck.slides[0].title = "Retain this curated content"
    presentations.save_deck(deck)
    before = presentations._path(deck.paper_id, deck.mode).read_bytes()
    payload = json.loads(deck_reply())
    payload["slides"][1]["bullets"] = ["x" * 130]
    calls = []
    repair = (
        "No JSON"
        if bad == "malformed"
        else json.dumps(
            {
                "slides": [
                    {
                        "index": 1,
                        "slide": _slide(1, sources=["fabricated"]),
                    }
                ]
            }
        )
    )

    def model(prompt, **kwargs):
        calls.append(kwargs)
        return Completion(envelope(json.dumps(payload) if len(calls) == 1 else repair))

    monkeypatch.setattr(llm, "complete_result", model)
    generated, _ = _generate()
    assert generated is None
    assert len(calls) == 2 and [call["timeout"] for call in calls] == [600, 300]
    assert presentations._path(deck.paper_id, deck.mode).read_bytes() == before


def test_saved_deck_json_is_not_reinterpreted_as_a_model_envelope(research, deck):
    presentations.save_deck(deck)
    path = presentations._path(deck.paper_id, deck.mode)
    altered = b"An untrusted file preface\n" + path.read_bytes()
    path.write_bytes(altered)
    with pytest.raises(ValueError):
        presentations.load_deck(deck.paper_id, deck.mode)
    assert path.read_bytes() == altered
