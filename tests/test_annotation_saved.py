"""Saved analysis authority works offline and never revives deleted cache content."""

import sqlite3
from contextlib import closing

import pytest
from test_annotation_archives import add
from test_annotation_archives import workspace as _workspace
from test_annotation_content import EXAMPLES

from paper_daily import annotation_content, annotation_reader, llm, store

workspace = _workspace


@pytest.mark.parametrize("feature", list(EXAMPLES))
def test_saved_annotations_are_readable_without_source_files_or_ai(workspace, monkeypatch, feature):
    _, database = workspace
    monkeypatch.setattr(
        llm, "capture_connections", lambda: pytest.fail("Viewing requested an account")
    )
    monkeypatch.setattr(llm, "complete_result", lambda *a, **k: pytest.fail("Viewing called AI"))
    assert annotation_reader.saved(database, "p", feature) is None
    with store.connect() as conn:
        add(conn, feature)
    value = annotation_reader.saved(database, "p", feature)
    assert value["known"] and value["paper_id"] == "p"
    assert value["document_hash"] is None and value["source_hash"] == "b" * 64
    assert all(value[key] == content for key, content in EXAMPLES[feature].items())


@pytest.mark.parametrize("feature", list(EXAMPLES))
def test_canonical_deletion_and_missing_parent_are_known_empty(workspace, feature):
    _, database = workspace
    with store.connect() as conn:
        add(conn, feature)
    with store.connect() as conn:
        conn.execute(f"DELETE FROM {annotation_content.FEATURES[feature]} WHERE paper_id='p'")
    expected = {"links" if feature == "reading_links" else "items": [], "known": True}
    assert annotation_reader.saved(database, "p", feature) == expected
    with store.connect() as conn:
        add(conn, feature)
        conn.execute("DELETE FROM papers WHERE id='p'")
    assert annotation_reader.saved(database, "p", feature) == expected


@pytest.mark.parametrize("feature", list(EXAMPLES))
def test_oversized_saved_annotation_fails_visibly_instead_of_legacy_fallback(workspace, feature):
    _, database = workspace
    with store.connect() as conn:
        add(conn, feature)
        conn.execute(
            f"UPDATE {annotation_content.FEATURES[feature]} SET body_json=?",
            (" " * (annotation_content.MAX_BYTES + 1),),
        )
    with pytest.raises(ValueError, match="budget"):
        annotation_reader.saved(database, "p", feature)


def test_saved_reader_rejects_unknown_feature_and_never_creates_missing_database(tmp_path):
    path = tmp_path / "absent.db"
    with pytest.raises(ValueError, match="Unsupported"):
        annotation_reader.saved(path, "paper", "arbitrary_table")
    with pytest.raises(FileNotFoundError):
        annotation_reader.saved(path, "paper", "highlight_analysis")
    assert not path.exists()


def test_uncommitted_annotation_does_not_become_visible_to_saved_reader(workspace):
    _, database = workspace
    with closing(sqlite3.connect(database)) as conn:
        add(conn, "highlight_analysis")
        assert annotation_reader.saved(database, "p", "highlight_analysis") is None
        conn.rollback()
    assert annotation_reader.saved(database, "p", "highlight_analysis") is None
