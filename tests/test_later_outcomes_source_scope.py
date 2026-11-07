"""Source root belongs to the explicit workspace, never mutable global B."""

import json
import sqlite3
from contextlib import closing

from test_research_generation import workspace as workspace

from paper_daily import config, followups, store
from paper_daily.document_reader import register_document_paths
from paper_daily.research_generation import _connect


def test_registered_source_wins_and_unregistered_foreign_workspace_stays_unknown(
    workspace, monkeypatch, tmp_path
):
    path, client, document = workspace
    wrong = tmp_path / "other-workspace"
    wrong.mkdir()
    other = wrong / "research.sqlite"
    with closing(sqlite3.connect(other)) as conn:
        conn.execute("CREATE TABLE unrelated(value)")
    if client:
        with closing(sqlite3.connect(path)) as conn, conn:
            conn.execute("BEGIN IMMEDIATE")
            register_document_paths(
                conn,
                workspace_id="workspace",
                blob_root=path.parent / "blobs",
                projection_root=path.parent / "projection",
                legacy_root=document.path.parent,
            )
    monkeypatch.setattr(store, "DB_PATH", other)
    monkeypatch.setattr(config, "PDF_DIR", wrong)
    monkeypatch.setattr(followups, "work_id", lambda _: "W1")
    monkeypatch.setattr(followups, "_citing_openalex", lambda _: [])
    monkeypatch.setattr(followups, "_citing_s2", lambda _: [])
    assert followups.fetch("paper", database=path) == 0
    with closing(_connect(path)) as conn:
        row = conn.execute("SELECT * FROM paper_later_outcomes").fetchone()
        if client:
            assert row is not None and row["document_hash"] == document.sha256
            assert json.loads(row["body_json"])["source"]["availability"] == "available"
        else:
            assert row is None
    with closing(sqlite3.connect(other)) as conn:
        assert conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall() == [
            ("unrelated",)
        ]
