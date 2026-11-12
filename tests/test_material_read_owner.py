"""A read workflow observes existing ownership, without creating editing state."""

import sqlite3
from contextlib import closing

import pytest
from test_research_generation import workspace as workspace

from paper_daily import manual_highlight_ops as ops
from paper_daily import store


def native(path):
    info = path.stat()
    return info.st_dev, info.st_ino


def rows(path):
    with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as conn:
        return list(conn.iterdump())


def test_existing_read_owner_and_marks_are_observed_without_writers(workspace, monkeypatch):
    database, _client, document = workspace
    # Existing real UI initialization establishes the parent before readonly use.
    original = ops.capture_owner(database, "paper")
    before = rows(database)

    def deny(*_args, **_kwargs):
        pytest.fail("Readonly observation must never initialize lifetimes or open a writer")

    with monkeypatch.context() as scoped:
        scoped.setattr(ops, "ensure_lifecycle", deny)
        scoped.setattr(ops.generation, "_connect", deny)
        owner = ops.observe_owner(database, "paper", expected_native=native(database))
        loaded = ops.load(owner, document.path, document.sha256, document=document, readonly=True)
        assert owner == original and loaded.marks == [] and loaded.document is document
    assert rows(database) == before


def test_read_owner_refuses_missing_lifecycle_without_creating_schema(tmp_path):
    database = tmp_path / "old.sqlite"
    with closing(sqlite3.connect(database)) as conn:
        conn.executescript(store.SCHEMA)
        conn.execute(
            "INSERT INTO papers(id,title,title_key,venue,year,source) "
            "VALUES('paper','Old','old','J',2026,'fixture')"
        )
        conn.commit()
    before = rows(database)
    with pytest.raises(ValueError):
        ops.observe_owner(database, "paper", expected_native=native(database))
    assert rows(database) == before


def test_read_owner_refuses_foreign_native_and_missing_paper_without_writes(workspace):
    database, _client, _document = workspace
    before = rows(database)
    with pytest.raises(ValueError):
        ops.observe_owner(database, "paper", expected_native=(0, 1))
    with pytest.raises(ValueError):
        ops.observe_owner(database, "absent-paper", expected_native=native(database))
    assert rows(database) == before
