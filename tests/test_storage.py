"""Pruning gives back only what can be fetched or rebuilt again: old HTTP cache and
the files of papers nobody claims. A list paper, a queued one, or one with notes or
analysis keeps every file."""

from __future__ import annotations

import os
import sqlite3

import pytest

from paper_daily import bundle, storage, store


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DB_PATH", tmp_path / "papers.db")
    monkeypatch.setattr(bundle, "DATA_DIR", tmp_path)
    for name, folder in (
        ("DATA_DIR", tmp_path),
        ("HTTP_CACHE", tmp_path / "httpcache"),
        ("PDF_DIR", tmp_path / "pdf"),
        ("TEXT_DIR", tmp_path / "text"),
        ("FIGURES_DIR", tmp_path / "figures"),
    ):
        monkeypatch.setattr(storage, name, folder)
        folder.mkdir(exist_ok=True)
    store.init_db()
    conn = sqlite3.connect(tmp_path / "papers.db")
    store.upsert_papers(
        conn,
        [
            {"id": f"ref:{k}", "title": k, "venue": "MICCAI", "year": 2025, "source": "t"}
            for k in ("listed", "noted", "queued", "skipped", "stray")
        ],
    )
    conn.executescript(
        """
        INSERT INTO lists(id, name, created_at) VALUES ('cat', 'Cataract', 'now');
        INSERT INTO list_papers(list_id, paper_id, position, added_at)
            VALUES ('cat', 'ref:listed', 0, 'now');
        INSERT INTO notes(paper_id, body, created_at) VALUES ('ref:noted', 'mine', 'now');
        INSERT INTO queue(paper_id, rank, state) VALUES ('ref:queued', 1, 'pending'),
                                                        ('ref:skipped', 2, 'skipped');
        """
    )
    conn.commit()
    for key in ("listed", "noted", "queued", "skipped", "stray"):
        (tmp_path / "pdf" / f"ref_{key}.pdf").write_bytes(b"%PDF" * 100)
        (tmp_path / "text" / f"ref_{key}.txt").write_text("text", encoding="utf-8")
        (tmp_path / "figures" / f"ref_{key}").mkdir()
        (tmp_path / "figures" / f"ref_{key}" / "p01-Figure_1.png").write_bytes(b"png")
    old = tmp_path / "httpcache" / "ab" / "old.bin"
    new = tmp_path / "httpcache" / "cd" / "new.bin"
    for path in (old, new):
        path.parent.mkdir()
        path.write_bytes(b"cached")
    os.utime(old, (0, 1_000_000))
    yield conn, tmp_path
    conn.close()


def test_the_plan_offers_only_old_cache_and_unclaimed_papers(workspace):
    conn, root = workspace
    chosen = storage.plan(conn, cache_days=30, now=1_000_000 + 31 * 86400)
    assert [p.name for p in chosen.cache] == ["old.bin"]
    assert sorted(chosen.papers) == ["ref_skipped", "ref_stray"]
    assert {p.parent.name for p in chosen.papers["ref_stray"]} == {"pdf", "text", "figures"}


def test_prune_deletes_the_plan_and_keeps_every_claimed_file(workspace):
    conn, root = workspace
    chosen = storage.plan(conn, cache_days=30, now=1_000_000 + 31 * 86400)
    assert storage.prune(conn, chosen, vacuum=True) > 0
    assert not (root / "httpcache" / "ab" / "old.bin").exists()
    assert (root / "httpcache" / "cd" / "new.bin").exists()
    for key in ("listed", "noted", "queued"):
        assert (root / "pdf" / f"ref_{key}.pdf").exists()
        assert (root / "text" / f"ref_{key}.txt").exists()
        assert (root / "figures" / f"ref_{key}").is_dir()
    assert not (root / "pdf" / "ref_stray.pdf").exists()
    assert not (root / "figures" / "ref_stray").exists()


def test_a_paper_claimed_after_planning_is_not_deleted(workspace):
    conn, root = workspace
    chosen = storage.plan(conn, cache_days=30)
    conn.execute("INSERT INTO notes(paper_id, body, created_at) VALUES ('ref:stray', 'x', 'now')")
    conn.commit()
    storage.prune(conn, chosen)
    assert (root / "pdf" / "ref_stray.pdf").exists()


def test_disk_use_is_reported_per_list(workspace):
    conn, root = workspace
    rows = {name: (papers, size) for name, papers, size in storage.by_list(conn)}
    assert rows["Cataract"][0] == 1 and rows["Cataract"][1] > 400
    assert rows["main queue"][0] == 1
    assert storage.human(1536) == "1.5 KB" and storage.human(12) == "12 B"


@pytest.mark.parametrize("reason", ["offline", "desired", "applied", "retained-intent"])
def test_prune_preserves_offline_and_managed_originals_even_after_planning(workspace, reason):
    from paper_daily.sync_documents import initialize

    conn, root = workspace
    chosen = storage.plan(conn)
    portable = "11111111-1111-4111-8111-111111111111"
    conn.execute("CREATE TABLE research_paper_identity "
                 "(sync_id TEXT PRIMARY KEY,local_id TEXT NOT NULL UNIQUE)")
    conn.execute("INSERT INTO research_paper_identity VALUES (?,?)", (portable, "ref:stray"))
    initialize(conn)
    if reason == "offline":
        conn.execute("INSERT INTO kv(key,value) VALUES (?, 'true')",
                     ("ui.offline.paper." + portable,))
    elif reason == "desired":
        conn.execute("INSERT INTO research_document_desired VALUES (?, '{}', 0)", (portable,))
    elif reason == "applied":
        conn.execute("INSERT INTO research_document_applied VALUES (?, '{}')", (portable,))
    else:
        conn.execute("INSERT INTO research_document_intents VALUES ('old', ?, '{}', 'superseded')",
                     (portable,))
    conn.commit()
    before = {path: path.read_bytes() for path in (root / "pdf" / "ref_stray.pdf",
                                                   root / "text" / "ref_stray.txt")}
    assert "ref_stray" not in storage.plan(conn).papers
    storage.prune(conn, chosen)
    storage.prune(conn, chosen)
    assert all(path.read_bytes() == body for path, body in before.items())
    assert (root / "figures" / "ref_stray" / "p01-Figure_1.png").read_bytes() == b"png"


def test_plan_cannot_disguise_claimed_paper_as_cache_or_another_paper(workspace):
    conn, root = workspace
    protected = root / "pdf" / "ref_noted.pdf"
    chosen = storage.Plan(cache=[protected, root / "pdf"],
                          papers={"unclaimed": [protected, root / "text"]})
    assert storage.prune(conn, chosen) == 0
    assert protected.read_bytes() == b"%PDF" * 100
    assert (root / "text" / "ref_noted.txt").read_text(encoding="utf-8") == "text"


@pytest.mark.parametrize("reason", ["unmapped-pin", "invalid-pin", "unmapped-original"])
def test_invalid_retention_metadata_stops_cleanup_before_deleting_cache(workspace, reason):
    from paper_daily.sync_documents import initialize

    conn, root = workspace
    old_cache = root / "httpcache" / "ab" / "old.bin"
    chosen = storage.Plan(cache=[old_cache])
    if reason == "unmapped-original":
        conn.execute("BEGIN")
        initialize(conn)
        conn.execute("INSERT INTO research_document_applied VALUES ('unmapped', '{}')")
    else:
        conn.execute("INSERT INTO kv(key,value) VALUES ('ui.offline.paper.unknown', ?)",
                     ("invalid" if reason == "invalid-pin" else "true",))
    conn.commit()
    before = (root / "pdf" / "ref_stray.pdf").read_bytes()
    with pytest.raises(ValueError, match="Review"):
        storage.prune(conn, chosen)
    assert old_cache.read_bytes() == b"cached"
    assert (root / "pdf" / "ref_stray.pdf").read_bytes() == before


def test_removing_offline_intent_restores_ordinary_unclaimed_cleanup(workspace):
    conn, root = workspace
    conn.execute("CREATE TABLE research_paper_identity "
                 "(sync_id TEXT PRIMARY KEY,local_id TEXT NOT NULL UNIQUE)")
    conn.execute("INSERT INTO research_paper_identity VALUES ('portable', 'ref:stray')")
    conn.execute("INSERT INTO kv(key,value) VALUES ('ui.offline.paper.portable', 'true')")
    conn.commit()
    assert "ref_stray" not in storage.plan(conn).papers
    conn.execute("DELETE FROM kv WHERE key='ui.offline.paper.portable'")
    conn.commit()
    chosen = storage.plan(conn)
    assert "ref_stray" in chosen.papers
    assert storage.prune(conn, chosen) > 0
    assert not (root / "pdf" / "ref_stray.pdf").exists()


@pytest.mark.parametrize("action,yes", [("storage", False), ("prune", False), ("prune", True)])
def test_cli_pauses_invalid_retention_with_actionable_message(workspace, monkeypatch, capsys,
                                                            action, yes):
    from contextlib import contextmanager
    from types import SimpleNamespace

    from paper_daily import cli

    conn, root = workspace
    conn.execute("INSERT INTO kv(key,value) VALUES ('ui.offline.paper.unmapped', 'true')")
    conn.commit()

    @contextmanager
    def connect():
        yield conn

    monkeypatch.setattr(cli, "connect", connect)
    monkeypatch.setattr(storage, "folders", lambda: [])
    result = getattr(cli, "cmd_" + action)(SimpleNamespace(cache_days=30, yes=yes, vacuum=False))
    assert result == 2
    message = capsys.readouterr().err
    assert "Review offline selections" in message and "No cleanup was performed" in message
    assert "Traceback" not in message and "unmapped" not in message
    assert (root / "httpcache" / "ab" / "old.bin").read_bytes() == b"cached"
