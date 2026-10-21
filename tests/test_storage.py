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
