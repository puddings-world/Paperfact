"""Historical suggestions need explicit verified adoption, never a filename guess."""

import hashlib
import json
from contextlib import closing

import pytest
from test_question_generation import ITEM
from test_question_generation import ready as _ready
from test_research_generation import pdf, rows
from test_research_generation import workspace as _workspace

from paper_daily import annotation_reader, llm, question_legacy_adoption, store, sync_capture
from paper_daily import research_generation as generation
from paper_daily.research_question_jobs import _pages

workspace = _workspace
ready = _ready


@pytest.fixture
def old_questions(ready, monkeypatch):
    database, _, document, *_ = ready
    source = {
        "pages": _pages(document),
        "explanation": "dives original analysis",
        "close_reading": "close_readings original analysis",
    }
    content = {
        "paper_id": "paper",
        "items": [{**ITEM, "page": 1}],
        "source_hash": hashlib.sha256(
            json.dumps(source, ensure_ascii=False, sort_keys=True).encode()
        ).hexdigest(),
    }
    cache = database.parent / "research-questions"
    cache.mkdir()
    path = cache / (hashlib.sha256(b"paper").hexdigest() + ".json")
    path.write_text(json.dumps(content), encoding="utf-8")
    monkeypatch.setattr(llm, "capture_connections", lambda: pytest.fail("Adoption read accounts"))
    monkeypatch.setattr(llm, "complete_result", lambda *a, **k: pytest.fail("Adoption called AI"))
    return database, document, path, content


def prepare(old_questions):
    database, document, path, _ = old_questions
    return question_legacy_adoption.prepare(
        database, "paper", cache_root=path.parent, legacy_root=document.path.parent
    )


def test_preview_is_not_adoption_and_acceptance_is_retry_safe(old_questions):
    database, document, path, content = old_questions
    original = path.read_bytes()
    preview = prepare(old_questions)
    assert preview.items == content["items"]
    assert rows(database, "SELECT * FROM paper_research_questions") == []
    assert path.read_bytes() == original
    result = preview.adopt()
    assert result.status == "accepted" and preview.adopt() == result
    saved = rows(database, "SELECT * FROM paper_research_questions")
    assert len(saved) == 1 and saved[0]["document_hash"] == document.sha256
    assert json.loads(saved[0]["body_json"])["items"] == content["items"]
    assert path.read_bytes() == original
    assert annotation_reader.questions(database, "paper", cache_root=path.parent)["known"]
    with pytest.raises(ValueError, match="No unadopted"):
        prepare(old_questions)


@pytest.mark.parametrize("bad", ["digest", "page", "quote", "owner"])
def test_wrong_historical_inputs_remain_only_a_preview(old_questions, bad):
    database, _, path, content = old_questions
    if bad == "digest":
        content["source_hash"] = "0" * 64
    elif bad == "page":
        content["items"][0]["page"] = 2
    elif bad == "quote":
        content["items"][0]["evidence"] = "An invented source quote is not the original experiment."
    else:
        content["paper_id"] = "another-paper"
    path.write_text(json.dumps(content), encoding="utf-8")
    original = path.read_bytes()
    with pytest.raises(ValueError):
        prepare(old_questions)
    assert rows(database, "SELECT * FROM paper_research_questions") == []
    assert path.read_bytes() == original


@pytest.mark.parametrize("change", ["analysis", "pdf", "canonical-deletion"])
def test_change_after_preview_preserves_candidate_without_overwriting(old_questions, change):
    database, document, path, _ = old_questions
    preview = prepare(old_questions)
    if change == "pdf":
        document.path.unlink()
        pdf(document.path, "A replacement source")
    else:
        table = "dives" if change == "analysis" else "paper_research_questions"
        with closing(generation._connect(database)) as conn:
            observed = generation.begin_generation(
                conn, table=table, owner_id="paper", input_reader="target"
            )
        row = (
            {
                "paper_id": "paper",
                "body": "Changed analysis",
                "spec": None,
                "written_at": store.now(),
            }
            if change == "analysis"
            else {**preview.row, "document_hash": None}
        )
        assert generation.publish_generation(observed, row=row).status == "accepted"
        if change == "canonical-deletion":
            with closing(generation._connect(database)) as conn:
                observation = sync_capture.observe_target(
                    conn, "paper", "paper", "research_questions", "main"
                )
                with sync_capture.expecting(conn, [observation]):
                    conn.execute("DELETE FROM paper_research_questions WHERE paper_id='paper'")
                    conn.commit()
    result = preview.adopt()
    assert result.status == "candidate"
    assert rows(database, "SELECT * FROM paper_research_questions") == []
    assert preview.adopt() == result
    assert (
        len(
            rows(
                database,
                "SELECT * FROM research_generation_requests WHERE "
                f"request_id='{preview.context.request_id}'",
            )
        )
        == 1
    )
    if change == "canonical-deletion":
        assert annotation_reader.questions(database, "paper", cache_root=path.parent) == {
            "items": [],
            "known": True,
        }
        with pytest.raises(ValueError, match="No unadopted"):
            prepare(old_questions)


def test_missing_parent_cannot_claim_its_old_cache(old_questions):
    database, _, path, _ = old_questions
    # Fault injection only: normal enrolled parent deletion is unsupported.
    # Keep the database's required capture functions registered, but do not issue
    # an unsupported user operation merely to construct this missing-owner state.
    with closing(generation._connect(database)) as conn, sync_capture.suppress_capture(conn):
        conn.execute("DELETE FROM papers WHERE id='paper'")
        conn.commit()
    with pytest.raises(ValueError, match="No unadopted"):
        prepare(old_questions)
    assert path.exists()
    assert rows(database, "SELECT * FROM paper_research_questions") == []


def test_real_legacy_helper_output_can_be_adopted_without_another_model(ready, monkeypatch):
    from paper_daily import paper_highlights, research_questions

    database, _, document, _, _, requests = ready
    cache = database.parent / "legacy-helper-cache"
    monkeypatch.setattr(research_questions, "CACHE_DIR", cache)
    monkeypatch.setattr(paper_highlights, "PDF_DIR", document.path.parent)
    old, _ = research_questions.ensure("paper")
    assert old and len(requests) == 1
    monkeypatch.setattr(llm, "capture_connections", lambda: pytest.fail("Adoption read accounts"))
    monkeypatch.setattr(llm, "complete_result", lambda *a, **k: pytest.fail("Adoption called AI"))
    preview = question_legacy_adoption.prepare(
        database, "paper", cache_root=cache, legacy_root=document.path.parent
    )
    assert preview.items == old["items"]
    assert preview.adopt().status == "accepted"
    assert len(requests) == 1
