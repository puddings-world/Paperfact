"""Legacy hints are never authority; exact typed duplication is omitted without writes."""

import json
import sqlite3
import zipfile
from contextlib import closing

import pytest
from test_later_outcome_bundle import source
from test_later_outcome_enrolled_package import receiver
from test_research_generation import workspace as workspace

from paper_daily import bundle, store
from paper_daily import research_generation as generation
from paper_daily.package_import import UnsupportedPackage


def test_matching_hint_omission_preserves_exact_sender_data(workspace, monkeypatch, tmp_path):
    database, _document, archive = source(workspace, monkeypatch, tmp_path)
    with closing(generation._connect(database)) as conn:
        before = conn.execute(
            "SELECT value FROM kv WHERE key='followups.checked.paper'"
        ).fetchone()[0]
        body = json.loads(conn.execute("SELECT body_json FROM paper_later_outcomes").fetchone()[0])
    unchanged = database.read_bytes()
    bundle.export("reading", archive)
    assert database.read_bytes() == unchanged
    with zipfile.ZipFile(archive) as zipped:
        tables = json.loads(zipped.read("tables.json"))
        assert not any(row["key"] == "followups.checked.paper" for row in tables["kv"])
        assert json.loads(tables["paper_later_outcomes"][0]["body_json"])["query"][
            "queried_at"
        ] == json.loads(before)
    with closing(generation._connect(database)) as conn:
        assert (
            conn.execute("SELECT value FROM kv WHERE key='followups.checked.paper'").fetchone()[0]
            == before
        )
    assert body["query"]["queried_at"] == json.loads(before)


@pytest.mark.parametrize("change", ["no-typed", "mismatched", "malformed"])
def test_legacy_or_mismatched_hint_remains_unsupported_before_enrolled_writes(
    workspace, monkeypatch, tmp_path, change
):
    database, _document, archive = source(workspace, monkeypatch, tmp_path)
    if change == "no-typed" and workspace[1] is not None:
        from paper_daily.sync_content import content_id

        client = workspace[1]
        with client.journal.transaction() as conn:
            portable = conn.execute(
                "SELECT sync_id FROM research_paper_identity WHERE local_id='paper'"
            ).fetchone()[0]
        identity = content_id({"kind": "paper", "id": portable}, "later_outcome", "main")
        client.save(client.new_graph_operation("research_content", identity, {}, action="delete"))
        with client.journal.transaction() as conn:
            assert conn.execute("SELECT COUNT(*) FROM paper_later_outcomes").fetchone()[0] == 0
    else:
        with store.connect() as conn:
            if change == "no-typed":
                conn.execute("DELETE FROM paper_later_outcomes")
            elif change == "mismatched":
                store.set_kv(conn, "followups.checked.paper", "2026-01-01T00:00:00Z")
            else:
                conn.execute("UPDATE kv SET value='not-json' WHERE key='followups.checked.paper'")
    before = database.read_bytes()
    bundle.export("reading", archive)
    assert database.read_bytes() == before
    with zipfile.ZipFile(archive) as zipped:
        tables = json.loads(zipped.read("tables.json"))
        assert any(row["key"] == "followups.checked.paper" for row in tables["kv"])
        manifest = json.loads(zipped.read("manifest.json"))
        if change == "no-typed":
            assert "later_outcome" not in manifest.get("capabilities", [])
    client, importer = receiver(tmp_path / "enrolled")
    with pytest.raises(UnsupportedPackage, match="legacy research KV"):
        importer.prepare(archive)
    assert client.journal.pending() == []
    with client.journal.transaction() as conn:
        assert conn.execute("SELECT COUNT(*) FROM paper_later_outcomes").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM papers").fetchone()[0] == 0


def test_real_failure_is_not_an_excludable_null_hint(workspace, monkeypatch, tmp_path):
    from paper_daily.later_outcome_history import redundant_hint

    database, _document, _archive = source(workspace, monkeypatch, tmp_path)
    with store.connect() as conn:
        store.set_kv(conn, "analyze.failed.later.paper", "Real researcher-visible failure")
        row = dict(
            conn.execute("SELECT * FROM kv WHERE key='analyze.failed.later.paper'").fetchone()
        )
        assert not redundant_hint(conn, row)
        assert store.get_kv(conn, row["key"]) == "Real researcher-visible failure"
        store.set_kv(conn, row["key"], None)
        assert redundant_hint(
            conn, dict(conn.execute("SELECT * FROM kv WHERE key=?", (row["key"],)).fetchone())
        )


def test_malformed_typed_row_is_not_repaired_or_promoted_by_hint_reader(tmp_path):
    from paper_daily import later_outcomes as outcomes
    from paper_daily.later_outcome_history import redundant_hint

    database = tmp_path / "raw.sqlite"
    with closing(sqlite3.connect(database)) as conn, conn:
        conn.execute("CREATE TABLE kv(key TEXT PRIMARY KEY,value TEXT)")
        conn.execute("BEGIN IMMEDIATE")
        outcomes.initialize(conn)
        conn.execute(
            "INSERT INTO paper_later_outcomes VALUES('paper','{}',NULL,'2026-11-01T00:00:00Z')"
        )
        conn.execute("INSERT INTO kv VALUES('followups.checked.paper','null')")
    before = database.read_bytes()
    with (
        closing(sqlite3.connect(database.as_uri() + "?mode=ro", uri=True)) as conn,
        pytest.raises(ValueError),
    ):
        redundant_hint(conn, {"key": "followups.checked.paper", "value": "null"})
    assert database.read_bytes() == before


def test_outcome_read_without_existing_lifecycle_stays_unknown_without_minting(
    workspace, monkeypatch, tmp_path
):
    from paper_daily import later_outcomes as outcomes
    from paper_daily.research_lifecycle import TABLE, TRIGGERS

    database, _document, _archive = source(workspace, monkeypatch, tmp_path)
    with closing(sqlite3.connect(database)) as conn, conn:
        for trigger in TRIGGERS:
            conn.execute("DROP TRIGGER " + trigger)
        conn.execute("DROP TABLE " + TABLE)
    before = database.read_bytes()
    with closing(sqlite3.connect(database.as_uri() + "?mode=ro", uri=True)) as conn:
        conn.row_factory = sqlite3.Row
        assert outcomes.coverage(conn, "paper")["state"] == "unknown"
        assert not conn.execute("SELECT 1 FROM sqlite_master WHERE name=?", (TABLE,)).fetchone()
    assert database.read_bytes() == before
