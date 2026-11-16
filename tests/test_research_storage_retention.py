"""Saved research retains legacy originals even outside lists and after a stale plan."""

import sqlite3

import pytest
from test_storage import workspace as workspace

from paper_daily import storage

WRITES = {
    "claims": (
        "INSERT INTO paper_claim_sets VALUES(?,?,?,?,?)",
        ("ref:stray", "{}", "a" * 64, "b" * 64, "now"),
    ),
    "context": (
        "INSERT INTO paper_context(paper_id,summary,reading_json,written_at) VALUES(?,?,?,?)",
        ("ref:stray", "Saved research context", "[]", "now"),
    ),
    "resource": (
        "INSERT INTO resources(paper_id,url,kind,own,source,checked_at) VALUES(?,?,?,?,?,?)",
        ("ref:stray", "https://fixture.invalid/code", "code", 1, "pdf", "now"),
    ),
}


def retained(root):
    assert (root / "pdf/ref_stray.pdf").read_bytes() == b"%PDF" * 100
    assert (root / "text/ref_stray.txt").read_text(encoding="utf-8") == "text"
    assert (root / "figures/ref_stray/p01-Figure_1.png").read_bytes() == b"png"


@pytest.mark.parametrize("kind", ["claims", "context", "resource"])
def test_saved_research_keeps_originals_from_new_and_stale_cleanup_plans(workspace, kind):
    conn, root = workspace
    previous = storage.plan(conn)
    assert "ref_stray" in previous.papers
    conn.execute(*WRITES[kind])
    conn.commit()
    assert "ref_stray" not in storage.plan(conn).papers
    storage.prune(conn, previous)
    retained(root)
    assert not (root / "pdf/ref_skipped.pdf").exists()


def test_citation_graph_alone_keeps_its_original_without_executing_or_rebuilding_it(workspace):
    conn, root = workspace
    previous = storage.plan(conn)
    conn.execute("INSERT INTO kv(key,value) VALUES(?,?)", ("citegraph.ref:stray", "{}"))
    conn.commit()
    storage.prune(conn, previous)
    retained(root)
    assert (
        conn.execute("SELECT value FROM kv WHERE key=?", ("citegraph.ref:stray",)).fetchone()[0]
        == "{}"
    )


def test_reference_edge_retains_originals_for_both_local_endpoints(workspace):
    conn, root = workspace
    previous = storage.plan(conn)
    conn.execute(
        "INSERT INTO refs(paper_id,ref_paper_id) VALUES(?,?)", ("ref:stray", "ref:skipped")
    )
    conn.commit()
    storage.prune(conn, previous)
    retained(root)
    assert (root / "pdf/ref_skipped.pdf").read_bytes() == b"%PDF" * 100


def test_research_saved_during_file_inspection_is_rechecked_before_removal(workspace, monkeypatch):
    conn, root = workspace
    previous = storage.plan(conn)
    target = root / "pdf/ref_stray.pdf"
    original = storage._size
    committed = []

    def during_inspection(path):
        if path == target and not committed:
            with sqlite3.connect(root / "papers.db", timeout=0.1) as writer:
                writer.execute(*WRITES["context"])
            committed.append(True)
        return original(path)

    monkeypatch.setattr(storage, "_size", during_inspection)
    storage.prune(conn, previous)
    assert committed
    retained(root)


@pytest.mark.parametrize("shape", ["columns", "view"])
def test_unknown_retained_owner_schema_refuses_cleanup_before_any_deletion(workspace, shape):
    conn, root = workspace
    previous = storage.plan(conn)
    conn.execute("DROP TABLE IF EXISTS paper_lineage_sets")
    if shape == "columns":
        conn.execute("CREATE TABLE paper_lineage_sets(unsupported TEXT)")
    else:
        conn.execute("CREATE VIEW paper_lineage_sets AS SELECT 'ref:stray' AS paper_id")
    conn.commit()
    with pytest.raises(storage.RetentionReviewError):
        storage.prune(conn, previous)
    retained(root)
    assert (root / "httpcache/ab/old.bin").exists()
