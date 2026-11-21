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


def test_disk_use_is_reported_per_list(workspace, monkeypatch):
    conn, root = workspace
    rows = {name: (papers, size) for name, papers, size in storage.by_list(conn)}
    assert rows["Cataract"][0] == 1 and rows["Cataract"][1] > 400
    assert rows["main queue"][0] == 1
    conn.execute("INSERT INTO lists(id,name,created_at) VALUES ('news','News','now')")
    conn.execute("INSERT INTO list_papers(list_id,paper_id,position,added_at) "
                 "VALUES ('news','ref:listed',0,'now')")
    scanned = []
    enumerate_files = bundle._paper_files

    def measured(paper_id):
        scanned.append(paper_id)
        return enumerate_files(paper_id)

    monkeypatch.setattr(bundle, "_paper_files", measured)
    pdf = root / "pdf" / "ref_listed.pdf"
    pdf.write_bytes(pdf.read_bytes() + b"extra")
    refreshed = {name: (papers, size) for name, papers, size in storage.by_list(conn)}
    assert refreshed["News"] == refreshed["Cataract"] == (1, rows["Cataract"][1] + 5)
    assert scanned.count("ref:listed") == 1
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


@pytest.mark.parametrize("claim", ["note", "offline"])
def test_claim_committed_during_cleanup_keeps_the_whole_paper(workspace, monkeypatch, claim):
    conn, root = workspace
    chosen = storage.plan(conn)
    conn.execute("CREATE TABLE research_paper_identity "
                 "(sync_id TEXT PRIMARY KEY,local_id TEXT NOT NULL UNIQUE)")
    conn.execute("INSERT INTO research_paper_identity VALUES ('portable', 'ref:stray')")
    conn.commit()
    target = root / "pdf" / "ref_stray.pdf"
    original = storage._size
    committed = []

    def late_claim(path):
        if path == target and not committed:
            with sqlite3.connect(root / "papers.db", timeout=0.1) as writer:
                if claim == "note":
                    writer.execute("INSERT INTO notes(paper_id,body,created_at) "
                                   "VALUES('ref:stray','Saved during cleanup','now')")
                else:
                    writer.execute("INSERT INTO kv(key,value) "
                                   "VALUES('ui.offline.paper.portable','true')")
            committed.append(True)
        return original(path)

    monkeypatch.setattr(storage, "_size", late_claim)
    storage.prune(conn, chosen)
    assert committed
    assert target.read_bytes() == b"%PDF" * 100
    assert (root / "text" / "ref_stray.txt").read_text(encoding="utf-8") == "text"
    assert (root / "figures" / "ref_stray" / "p01-Figure_1.png").read_bytes() == b"png"


def test_cleanup_does_not_commit_or_rollback_the_callers_unsaved_research(workspace):
    conn, root = workspace
    chosen = storage.plan(conn)
    conn.execute("INSERT INTO notes(paper_id,body,created_at) VALUES('ref:stray','Unsaved','now')")
    with pytest.raises(storage.RetentionReviewError) as raised:
        storage.prune(conn, chosen)
    assert not raised.value.cleanup_started and conn.in_transaction
    assert conn.execute("SELECT body FROM notes WHERE body='Unsaved'").fetchone()[0] == "Unsaved"
    assert (root / "pdf" / "ref_stray.pdf").exists()
    conn.rollback()
    assert storage.prune(conn, chosen) > 0 and not conn.in_transaction


def test_claim_reservation_is_held_during_the_actual_file_removal(workspace, monkeypatch):
    from pathlib import Path

    conn, root = workspace
    chosen = storage.plan(conn)
    target = root / "pdf" / "ref_stray.pdf"
    original, blocked = Path.unlink, []

    def remove(path, *args, **kwargs):
        if path == target:
            with (sqlite3.connect(root / "papers.db", timeout=0) as writer,
                  pytest.raises(sqlite3.OperationalError, match="locked")):
                writer.execute("INSERT INTO notes(paper_id,body,created_at) "
                               "VALUES('ref:stray','Concurrent claim','now')")
            blocked.append(True)
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", remove)
    assert storage.prune(conn, chosen) > 0
    assert blocked == [True] and not conn.in_transaction
    with sqlite3.connect(root / "papers.db", timeout=0) as writer:
        writer.execute("INSERT INTO notes(paper_id,body,created_at) "
                       "VALUES('ref:stray','After cleanup','now')")


def test_late_invalid_retention_pauses_remaining_cleanup_and_can_retry(workspace, monkeypatch):
    conn, root = workspace
    chosen = storage.plan(conn)
    target = root / "pdf" / "ref_stray.pdf"
    original, changed = storage._size, []

    def invalidated(path):
        if path == target and not changed:
            with sqlite3.connect(root / "papers.db", timeout=0) as writer:
                writer.execute("INSERT INTO kv(key,value) VALUES('ui.offline.paper.bad','invalid')")
            changed.append(True)
        return original(path)

    monkeypatch.setattr(storage, "_size", invalidated)
    with pytest.raises(storage.RetentionReviewError) as raised:
        storage.prune(conn, chosen)
    assert raised.value.cleanup_started and not conn.in_transaction
    assert not (root / "httpcache" / "ab" / "old.bin").exists()
    assert target.exists() and (root / "text" / "ref_stray.txt").exists()
    conn.execute("DELETE FROM kv WHERE key='ui.offline.paper.bad'")
    conn.commit()
    assert storage.prune(conn, chosen) > 0 and not target.exists()


def test_cli_reports_partial_cleanup_without_claiming_nothing_happened(
    workspace, monkeypatch, capsys,
):
    from contextlib import contextmanager
    from types import SimpleNamespace

    from paper_daily import cli

    @contextmanager
    def connection():
        yield workspace[0]

    def paused(*_args, **_kwargs):
        raise storage.RetentionReviewError("Synthetic late refusal", cleanup_started=True)

    monkeypatch.setattr(cli, "connect", connection)
    monkeypatch.setattr(storage, "prune", paused)
    result = cli.cmd_prune(SimpleNamespace(cache_days=30, yes=True, vacuum=False))
    message = capsys.readouterr().err
    assert result == 2 and "Earlier cleanup may have completed" in message
    assert "No cleanup was performed" not in message and "Traceback" not in message


def test_busy_writer_pauses_before_any_deletion_and_retry_is_safe(workspace):
    conn, root = workspace
    chosen = storage.plan(conn)
    conn.execute("PRAGMA busy_timeout=1")
    blocker = sqlite3.connect(root / "papers.db")
    try:
        blocker.execute("BEGIN IMMEDIATE")
        with pytest.raises(storage.RetentionReviewError) as raised:
            storage.prune(conn, chosen)
        assert not raised.value.cleanup_started and not conn.in_transaction
        assert (root / "httpcache" / "ab" / "old.bin").exists()
        assert (root / "pdf" / "ref_stray.pdf").exists()
    finally:
        blocker.rollback()
        blocker.close()
    assert storage.prune(conn, chosen) > 0
    assert not (root / "pdf" / "ref_stray.pdf").exists()
