"""Captured-input generation and mapping cannot accidentally read/write another workspace."""

import copy
import json

import pymupdf
import pytest
from test_paper_highlights import PAGES, choice, fake_reply

from paper_daily import paper_highlights, pdf_highlights, reading_links
from paper_daily.ai_types import Completion


def forbidden(*args, **kwargs):
    pytest.fail("Captured producer accessed global research storage")


def test_highlight_production_uses_only_captured_pages_and_configuration(monkeypatch):
    for name in ("read_original", "cached", "_path", "_atomic_json"):
        monkeypatch.setattr(paper_highlights, name, forbidden)
    monkeypatch.setattr(paper_highlights.llm, "settings", forbidden)
    pages = copy.deepcopy(PAGES)
    calls = []

    def complete(prompt, **kwargs):
        calls.append(kwargs)
        assert all(page["text"] in prompt for page in pages)
        return fake_reply({"items": [choice(1), choice(0)]})

    monkeypatch.setattr(paper_highlights.llm, "complete_result", complete)
    result, reason = paper_highlights.produce(pages, cfg="captured-route")
    assert reason == "ok"
    assert [item["text"] for item in result["items"]] == [PAGES[1]["text"], PAGES[0]["text"]]
    assert result["coverage"]["pages"] == 2
    assert result["source_hash"] == paper_highlights._hash(PAGES)
    assert "paper_id" not in result
    assert calls[0]["cfg"] == "captured-route"
    assert pages == PAGES


def test_empty_highlight_source_never_calls_model(monkeypatch):
    monkeypatch.setattr(paper_highlights.llm, "complete_result", forbidden)
    result, reason = paper_highlights.produce([{"page": 1, "text": ""}], cfg="route")
    assert result is None and "沒有可讀取" in reason


def test_link_production_uses_captured_sections_without_cache_or_database(monkeypatch):
    for name in ("_context", "cached", "_path", "_atomic_json", "connect"):
        monkeypatch.setattr(reading_links, name, forbidden)
    parts = reading_links.sections("## Method\nA controlled comparison.", None)
    analysis = {"source_hash": "a" * 64, "items": [{"text": PAGES[0]["text"], "page": 1}]}
    original = copy.deepcopy((parts, analysis))

    def model(prompt, **kwargs):
        payload = json.loads(prompt)
        assert payload["sections"][0]["id"] == "dive:0"
        assert payload["quotes"][0]["text"] == PAGES[0]["text"]
        assert kwargs["cfg"] == "captured-route"
        return Completion(
            json.dumps(
                {
                    "links": [
                        {
                            "quote": 0,
                            "section": "dive:0",
                            "explanation": "Supports the controlled comparison.",
                        }
                    ]
                }
            )
        )

    monkeypatch.setattr(reading_links.llm, "complete_result", model)
    result, reason = reading_links.produce(parts, analysis, cfg="captured-route")
    assert reason == "ok" and result["links"][0]["section"] == "dive:0"
    assert (parts, analysis) == original


def test_link_failure_keeps_captured_materials_unchanged(monkeypatch):
    monkeypatch.setattr(reading_links, "_atomic_json", forbidden)
    monkeypatch.setattr(
        reading_links.llm, "complete_result", lambda *a, **k: Completion(None, reason="unavailable")
    )
    parts = reading_links.sections("## Method\nA comparison.", None)
    analysis = {"source_hash": "a" * 64, "items": [{"text": PAGES[0]["text"], "page": 1}]}
    original = copy.deepcopy(analysis)
    assert reading_links.produce(parts, analysis) == (None, "unavailable")
    assert analysis == original


def test_pdf_mapping_returns_exact_anchors_without_saving_marks(tmp_path, monkeypatch):
    monkeypatch.setattr(pdf_highlights, "connect", forbidden)
    path = tmp_path / "source.pdf"
    with pymupdf.open() as document:
        document.new_page().insert_text((40, 60), "Alpha beta gamma evidence")
        document.save(path)
    found = {"page": 1, "text": "Alpha beta", "reason": "Original evidence"}
    missing = {"page": 1, "text": "An invented quotation", "reason": "Not present"}
    fingerprint, marks, unmatched = pdf_highlights.locate(path, {"items": [found, missing]})
    assert fingerprint == pdf_highlights.document_hash(path)
    assert len(marks) == 1 and marks[0][2] == found
    assert marks[0][1] == {"p0": 0, "o0": 0, "p1": 0, "o1": 1}
    assert unmatched == [missing]


def test_pdf_change_during_mapping_rejects_anchors(tmp_path, monkeypatch):
    monkeypatch.setattr(pdf_highlights, "connect", forbidden)
    path = tmp_path / "source.pdf"
    with pymupdf.open() as document:
        document.new_page().insert_text((40, 60), "Alpha beta gamma evidence")
        document.save(path)
    hashes = iter(["a" * 64, "b" * 64])
    monkeypatch.setattr(pdf_highlights, "document_hash", lambda _path: next(hashes))
    with pytest.raises(ValueError, match="PDF 已變更"):
        pdf_highlights.locate(path, {"items": [{"page": 1, "text": "Alpha beta"}]})
