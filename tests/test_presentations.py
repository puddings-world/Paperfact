"""Presentation provenance, safe exports, and preservation of research and edited decks."""

import json
import sqlite3
from dataclasses import asdict

import pymupdf
import pytest

from paper_daily import llm, store
from paper_daily import presentation_export as export
from paper_daily import presentations as slides
from paper_daily.ai_types import Completion, Settings


@pytest.fixture
def research(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DB_PATH", tmp_path / "papers.db")
    for name, folder in (
        ("PDF_DIR", "pdf"),
        ("TEXT_DIR", "text"),
        ("FIG_DIR", "figures"),
        ("DECK_DIR", "decks"),
    ):
        dest = tmp_path / folder
        dest.mkdir()
        monkeypatch.setattr(slides, name, dest)
    conn = sqlite3.connect(store.DB_PATH)
    conn.executescript(store.SCHEMA)
    store.upsert_papers(
        conn,
        [
            {
                "id": "ref:deck",
                "title": "Research fixture",
                "venue": "Journal",
                "year": 2025,
                "source": "test",
                "abstract": "The paper compares two methods.",
                "doi": "10.1/test",
            }
        ],
    )
    conn.execute(
        "INSERT INTO dives(paper_id,body,written_at) VALUES (?,?,?)",
        ("ref:deck", "The deep dive follows the method and experiment.", "today"),
    )
    conn.execute(
        "INSERT INTO notes(paper_id,body,kind,created_at,page) VALUES (?,?,?,?,?)",
        ("ref:deck", "Reader interpretation, not an author claim.", "note", "today", 2),
    )
    conn.execute(
        "INSERT INTO chat(paper_id,role,body,created_at) VALUES (?,?,?,?)",
        ("ref:deck", "user", "Which assumption matters?", "today"),
    )
    conn.execute(
        "INSERT INTO chat(paper_id,role,body,created_at) VALUES (?,?,?,?)",
        ("ref:deck", "assistant", "Check the assumptions in Section 2.", "today"),
    )
    conn.execute(
        "INSERT INTO cites(paper_id,ref_key,title,basis,written_at) VALUES (?,?,?,?,?)",
        ("ref:deck", "1", "Earlier work", "title", "today"),
    )
    conn.execute(
        "INSERT INTO paper_context(paper_id,summary,written_at) VALUES (?,?,?)",
        ("ref:deck", "A limitation motivates the later work.", "today"),
    )
    conn.commit()
    conn.close()
    (slides.TEXT_DIR / "ref_deck.txt").write_text(
        "1 Introduction\nMotivation.\n2 Methods\nMethod A.\n3 Experiments\nMethod B.",
        encoding="utf-8",
    )
    return tmp_path


@pytest.fixture
def deck():
    return slides.Deck(
        "ref:deck",
        "Research fixture",
        "A paper explained",
        "guide",
        "Researchers new to the paper",
        15,
        [
            slides.Slide(
                "Research question",
                "Introduction",
                "The problem and evidence",
                ["A claim backed by the original."],
                "Explain the background.",
                ["original"],
            )
            for _ in range(4)
        ],
        [
            {
                "id": "original",
                "label": "Original text",
                "kind": "original",
                "page": None,
                "url": "https://doi.org/10.1/test",
            }
        ],
        [],
        [],
        "2026-10-12",
    )


def reply():
    return json.dumps(
        {
            "title": "A clear introduction",
            "slides": [
                {
                    "title": f"Section {i + 1}",
                    "section": "Paper order",
                    "takeaway": "Specific result",
                    "bullets": ["The original supports this statement."],
                    "speaker_notes": "A transition to the next section.",
                    "sources": ["original", "dive"],
                    "figure": None,
                }
                for i in range(4)
            ],
        }
    )


def test_evidence_keeps_original_and_secondary_views_distinct(research):
    evidence = slides.collect_evidence("ref:deck", set(slides.INPUTS))
    by_id = {s["id"]: s for s in evidence["sources"]}
    assert by_id["original"]["kind"] == "original"
    assert by_id["dive"]["kind"] == "dive"
    assert by_id["note:1"]["kind"] == "notes"
    assert by_id["note:1"]["page"] == 2
    assert by_id["chat:2"]["kind"] == "chat"
    assert '"basis": "title"' in by_id["cite:1"]["text"]
    assert "僅標題推測" in by_id["cite:1"]["label"]
    assert by_id["context"]["kind"] == "citations"
    assert len(evidence["source_hash"]) == 64
    selected = slides.collect_evidence("ref:deck", {"original"})
    assert not any(s["kind"] in ("notes", "chat", "dive") for s in selected["sources"])


def test_pdf_sources_keep_page_numbers(research):
    doc = pymupdf.open()
    for i in range(3):
        doc.new_page().insert_text((72, 72), f"Section {i + 1}: the original evidence.")
    doc.save(slides.PDF_DIR / "ref_deck.pdf")
    evidence = slides.collect_evidence("ref:deck", {"original"})
    originals = [s for s in evidence["sources"] if s["kind"] == "original"]
    assert [s["page"] for s in originals] == [1, 2, 3]
    assert [s["id"] for s in originals] == ["page:1", "page:2", "page:3"]


def test_only_abstract_cannot_produce_a_paper_guide(research):
    with pytest.raises(ValueError, match="原文或完成深度講解"):
        slides.collect_evidence("ref:deck", {"chat", "notes"})


def test_generation_routes_slides_and_never_changes_research_records(research, monkeypatch):
    seen = {}

    def model(prompt, **kwargs):
        seen.update(kwargs)
        seen["payload"] = json.loads(prompt)
        with sqlite3.connect(store.DB_PATH) as conn:
            # The evidence read transaction must be closed before a paid/model call.
            conn.execute("UPDATE papers SET abstract=abstract WHERE id='ref:deck'")
        return Completion(reply(), model="mock", backend="gateway", request_id="test-operation")

    monkeypatch.setattr(llm, "complete_result", model)
    cfg = Settings("gateway", model="research", api_key="secret-not-in-deck")
    generated, reason = slides.generate(
        "ref:deck",
        mode="guide",
        audience="New researchers",
        minutes=15,
        slide_count=4,
        inputs={"original", "dive"},
        cfg=cfg,
    )
    assert reason == "ok" and len(generated.slides) == 4
    assert seen["task"] == "slides" and seen["cfg"] is cfg
    assert seen["payload"]["requested_slides"] == 4
    stored = slides.load_deck("ref:deck", "guide").to_dict()
    assert "secret-not-in-deck" not in json.dumps(stored)
    assert all("text" not in s for s in stored["sources"])
    assert generated.generation["request_id"] == "test-operation"
    assert (slides._folder("ref:deck") / "evidence" / (generated.source_hash + ".json")).exists()
    with sqlite3.connect(store.DB_PATH) as conn:
        assert conn.execute("SELECT body FROM notes").fetchone()[0].startswith("Reader")
        assert conn.execute("SELECT COUNT(*) FROM chat").fetchone()[0] == 2


@pytest.mark.parametrize(
    "bad",
    [
        '{"title":"Bad","slides":[]}',
        '{"title":"Bad","slides":[{"title":"Wrong","bullets":["x"],"sources":["invented"]}]}',
        "This is not a structured deck",
    ],
)
def test_invalid_generation_does_not_overwrite_an_edited_deck(research, deck, monkeypatch, bad):
    deck.edited = True
    slides.save_deck(deck)
    before = slides._path(deck.paper_id, deck.mode).read_bytes()
    monkeypatch.setattr(llm, "complete_result", lambda *a, **k: Completion(bad))
    result, reason = slides.generate(
        "ref:deck",
        mode="guide",
        audience="",
        minutes=10,
        slide_count=4,
        inputs={"original", "dive"},
    )
    assert result is None and "驗證" in reason
    assert slides._path(deck.paper_id, deck.mode).read_bytes() == before


def test_versions_and_modes_preserve_old_edits(research, deck):
    deck.edited = True
    deck.slides[0].title = "A reader's carefully edited title"
    slides.save_deck(deck)
    replacement = slides.deck_from_dict(deck.to_dict())
    replacement.deck_id = "next-generation"
    replacement.slides[0].title = "New draft"
    slides.save_deck(replacement)
    history = list((slides._folder(deck.paper_id) / "history").glob("*.json"))
    assert len(history) == 1
    assert json.loads(history[0].read_text(encoding="utf-8"))["slides"][0]["title"] == (
        "A reader's carefully edited title"
    )
    replacement.mode = "notes"
    slides.save_deck(replacement)
    assert slides.load_deck(deck.paper_id, "guide").mode == "guide"
    assert slides.load_deck(deck.paper_id, "notes").mode == "notes"


@pytest.mark.parametrize(
    "changes",
    [
        {"sources": ["fabricated"]},
        {"figure": "../../outside.png"},
        {"bullets": ["x" * 121]},
        {"bullets": ["x"] * 6},
        {"speaker_notes": None},
        {"sources": []},
    ],
)
def test_invalid_slide_evidence_and_density_are_rejected(deck, changes):
    raw = {**asdict(deck.slides[0]), **changes}
    with pytest.raises(ValueError):
        slides.validate_slide(raw, {"original"}, set())


def test_selected_figure_is_snapshotted_and_exported_inline(research, deck):
    images = slides.FIG_DIR / "ref_deck"
    images.mkdir()
    pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 80, 60), False)
    pix.clear_with(255)
    pix.save(images / "evidence.png")
    deck.sources.append({"id": "figure:1", "label": "Figure 1", "kind": "figure"})
    deck.figures.append(
        {
            "id": "figure:1",
            "file": "evidence.png",
            "label": "Figure 1",
            "caption": "Original comparison",
            "page": 1,
        }
    )
    deck.slides[0].figure = "figure:1"
    deck.slides[0].sources.append("figure:1")
    slides.save_deck(deck)
    assert deck.figures[0]["asset"]
    (images / "evidence.png").unlink()
    page = export.render_html(slides.load_deck("ref:deck", "guide"))
    assert "data:image/png;base64," in page and "Original comparison" in page
    assert str(research) not in page


def test_export_is_offline_escaped_and_can_omit_private_speaker_notes(research, deck):
    deck.slides[0].title = "<script>alert(1)</script>"
    deck.slides[0].speaker_notes = "A PRIVATE SPEAKER NOTE"
    deck.sources[0]["url"] = "javascript:alert(2)"
    page = export.render_html(deck, include_notes=False)
    assert "&lt;script&gt;" in page
    assert "javascript:" not in page
    assert "PRIVATE SPEAKER NOTE" not in page
    assert "<script src=" not in page and "fetch(" not in page
    assert page.count('class="slide" ') == 4
    export.export_markdown(deck, research / "deck.md", include_notes=False)
    assert "PRIVATE SPEAKER NOTE" not in (research / "deck.md").read_text(encoding="utf-8")


def test_json_export_has_no_private_notes_or_filesystem_dependency(research, deck):
    export.export_json(deck, research / "deck.json", include_notes=False)
    raw = json.loads((research / "deck.json").read_text(encoding="utf-8"))
    assert all(s["speaker_notes"] == "" for s in raw["slides"])
    assert all("file" not in f and "asset" not in f for f in raw["figures"])


def test_complete_model_reply_with_fabricated_sources_is_rejected(research, monkeypatch):
    raw = json.loads(reply())
    raw["slides"][0]["sources"] = ["invented-paper"]
    monkeypatch.setattr(llm, "complete_result", lambda *a, **k: Completion(json.dumps(raw)))
    result, reason = slides.generate(
        "ref:deck",
        mode="guide",
        audience="",
        minutes=10,
        slide_count=4,
        inputs={"original", "dive"},
    )
    assert result is None and "source IDs" in reason
    assert not slides._path("ref:deck", "guide").exists()


def test_deep_dive_input_includes_close_reading_sections_in_paper_order(research):
    with sqlite3.connect(store.DB_PATH) as conn:
        conn.execute(
            "INSERT INTO close_readings(paper_id,body,written_at) VALUES (?,?,?)",
            ("ref:deck", "## 3 Method\nA design choice.\n## 4 Experiments\nEvidence.", "today"),
        )
    evidence = slides.collect_evidence("ref:deck", {"dive"})
    sections = [s for s in evidence["sources"] if s["kind"] == "close_reading"]
    assert [s["id"] for s in sections] == ["close:1", "close:2"]
    assert sections[0]["label"].endswith("3 Method")
    assert sections[1]["label"].endswith("4 Experiments")
    assert "Evidence." in sections[1]["text"]
    excluded = slides.collect_evidence("ref:deck", {"original"})
    assert not any(s["kind"] == "close_reading" for s in excluded["sources"])


def test_restoring_archived_generation_also_preserves_current_draft(research, deck):
    from uuid import uuid4

    slides.save_deck(deck)
    old_id = deck.deck_id
    deck.deck_id = uuid4().hex
    deck.title = "Second version"
    slides.save_deck(deck)
    deck.slides[0].title = "Edited second version"
    slides.save_deck(deck)
    versions = slides.list_versions(deck.paper_id, deck.mode)
    assert len(versions) == 1
    restored = slides.restore_version(deck.paper_id, deck.mode, versions[0]["file"])
    assert restored.title == "A paper explained"
    assert restored.deck_id not in (old_id, deck.deck_id)
    assert len(slides.list_versions(deck.paper_id, deck.mode)) == 2
    versions = slides.list_versions(deck.paper_id, deck.mode)
    second = next(v for v in versions if v["title"] == "Second version")
    restored = slides.restore_version(deck.paper_id, deck.mode, second["file"])
    assert restored.slides[0].title == "Edited second version"
    with pytest.raises(ValueError):
        slides.restore_version(deck.paper_id, deck.mode, "../guide.json")


def _deck_reply(slides_):
    return json.dumps({"title": "A clear introduction", "slides": slides_})


def _slide(i, **over):
    s = {
        "title": f"Section {i + 1}",
        "section": "Paper order",
        "takeaway": "Specific result",
        "bullets": ["The original supports this statement."],
        "speaker_notes": "A transition to the next section.",
        "sources": ["original"],
        "figure": None,
    }
    s.update(over)
    return s


def _generate():
    return slides.generate(
        "ref:deck",
        mode="guide",
        audience="",
        minutes=10,
        slide_count=4,
        inputs={"original", "dive"},
    )


def test_unknown_source_ids_are_dropped_without_asking_again(research, monkeypatch):
    calls = []

    def model(prompt, **kwargs):
        calls.append(kwargs["system"])
        bad = _slide(2, sources=["original", "page:99", "invented", "original"])
        return Completion(_deck_reply([_slide(0), _slide(1), bad, _slide(3)]))

    monkeypatch.setattr(llm, "complete_result", model)
    deck, reason = _generate()
    assert reason == "ok" and len(calls) == 1
    assert deck.slides[2].sources == ["original"]


def test_only_the_slides_that_fail_are_sent_back(research, monkeypatch):
    calls = []
    too_long = _slide(1, bullets=["字" * 130])

    def model(prompt, **kwargs):
        calls.append(json.loads(prompt))
        if len(calls) == 1:
            return Completion(_deck_reply([_slide(0), too_long, _slide(2), _slide(3)]))
        fixed = _slide(1, bullets=["字" * 60, "字" * 60], speaker_notes="moved here")
        return Completion(json.dumps({"slides": [{"index": 1, "slide": fixed}]}))

    monkeypatch.setattr(llm, "complete_result", model)
    deck, reason = _generate()
    assert reason == "ok" and len(calls) == 2
    repair = calls[1]
    assert [s["index"] for s in repair["slides"]] == [1]
    assert "120" in repair["slides"][0]["error"]
    assert {s["id"] for s in repair["sources"]} >= {"original"}
    assert deck.slides[1].speaker_notes == "moved here"
    assert [s.title for s in deck.slides] == [f"Section {i + 1}" for i in range(4)]


def test_a_slide_that_cannot_be_fixed_is_named(research, monkeypatch):
    def model(prompt, **kwargs):
        if kwargs["system"] == slides.REPAIR_INSTRUCTIONS:
            return Completion("not json")
        return Completion(_deck_reply([_slide(0), _slide(1), _slide(2, bullets=[]), _slide(3)]))

    monkeypatch.setattr(llm, "complete_result", model)
    deck, reason = _generate()
    assert deck is None and "第 3 頁" in reason
