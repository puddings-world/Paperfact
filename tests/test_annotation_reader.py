"""Canonical reads and tombstones never silently adopt or resurrect legacy caches."""

import hashlib
import json

import pytest
from test_annotation_archives import add
from test_annotation_archives import workspace as workspace
from test_annotation_content import EXAMPLES

from paper_daily import annotation_reader, llm, store


@pytest.fixture
def legacy(workspace, monkeypatch):
    root, database = workspace
    cache = root / "research-questions"
    cache.mkdir()
    data = {
        "paper_id": "p",
        "source_hash": "b" * 64,
        "items": EXAMPLES["research_questions"]["items"],
    }
    path = cache / (hashlib.sha256(b"p").hexdigest() + ".json")
    path.write_text(json.dumps(data), encoding="utf-8")
    monkeypatch.setattr(llm, "complete_result", lambda *a, **k: pytest.fail("Read invoked AI"))
    monkeypatch.setattr(
        llm, "capture_connections", lambda *a, **k: pytest.fail("Read checked accounts")
    )
    return database, cache, path


def read(legacy):
    database, cache, _ = legacy
    return annotation_reader.questions(database, "p", cache_root=cache)


def test_legacy_questions_are_an_explicit_unknown_source_preview(legacy):
    value = read(legacy)
    assert value["legacy_unverified"] and not value["known"]
    assert value["document_hash"] is None
    assert value["items"] == EXAMPLES["research_questions"]["items"]
    with store.connect() as conn:
        assert conn.execute("SELECT * FROM paper_research_questions").fetchall() == []
        assert conn.execute("SELECT * FROM paper_annotation_known").fetchall() == []


def test_canonical_questions_win_without_reading_legacy_cache(legacy):
    with store.connect() as conn:
        add(conn, "research_questions")
    legacy[2].write_text("corrupt legacy cache", encoding="utf-8")
    value = read(legacy)
    assert value["known"] and not value.get("legacy_unverified")
    assert value["items"] == EXAMPLES["research_questions"]["items"]


def test_deleted_canonical_questions_never_reappear_from_an_old_cache(legacy):
    with store.connect() as conn:
        add(conn, "research_questions")
    with store.connect() as conn:
        conn.execute("DELETE FROM paper_research_questions WHERE paper_id='p'")
    assert legacy[2].exists()
    assert read(legacy) == {"items": [], "known": True}
    assert read(legacy) == {"items": [], "known": True}


def test_rollback_does_not_create_a_canonical_ownership_marker(legacy):
    with store.connect() as conn:
        add(conn, "research_questions")
        conn.rollback()
    assert read(legacy)["legacy_unverified"]


def test_missing_parent_does_not_adopt_or_show_its_orphan_cache(legacy):
    with store.connect() as conn:
        conn.execute("DELETE FROM papers WHERE id='p'")
    assert read(legacy) == {"items": [], "known": True}
    assert legacy[2].exists()


@pytest.mark.parametrize("bad", ["not json", "[]", '{"paper_id":"other"}', "[" * 2000])
def test_malformed_legacy_cache_is_inert(legacy, bad):
    legacy[2].write_text(bad, encoding="utf-8")
    assert read(legacy) == {"items": [], "known": False}


def test_absent_database_is_never_created_by_reading(tmp_path):
    missing = tmp_path / "missing.sqlite"
    with pytest.raises(FileNotFoundError):
        annotation_reader.questions(missing, "p", cache_root=tmp_path)
    assert not missing.exists()


def test_annotation_change_invalidates_reader_polling_only_after_commit(legacy):
    with store.connect() as conn:
        old = conn.execute("SELECT revision FROM workspace_revision").fetchone()[0]
        add(conn, "research_questions")
        assert conn.execute("SELECT revision FROM workspace_revision").fetchone()[0] > old
        conn.rollback()
        assert conn.execute("SELECT revision FROM workspace_revision").fetchone()[0] == old
        add(conn, "research_questions")
    with store.connect() as conn:
        assert conn.execute("SELECT revision FROM workspace_revision").fetchone()[0] > old
