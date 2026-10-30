"""Deletion knowledge remains authoritative when business research travels."""

import hashlib
import json
import sqlite3
from contextlib import closing

from test_annotation_archives import EXAMPLES, add
from test_annotation_archives import workspace as _workspace

from paper_daily import annotation_reader, bundle, store, sync_recovery

workspace = _workspace


def remove_questions(path):
    with store.connect() as conn:
        add(conn, "research_questions")
        conn.execute("DELETE FROM paper_research_questions WHERE paper_id='p'")
    assert annotation_reader.saved(path, "p", "research_questions") == {"items": [], "known": True}


def legacy(root):
    cache = root / "research-questions"
    cache.mkdir(exist_ok=True)
    path = cache / (hashlib.sha256(b"p").hexdigest() + ".json")
    path.write_text(
        json.dumps({"paper_id": "p", "source_hash": "a" * 64, **EXAMPLES["research_questions"]}),
        encoding="utf-8",
    )
    return cache


def test_deleted_annotation_marker_survives_detached_restore_and_prevents_cache_resurrection(
    workspace,
):
    root, path = workspace
    remove_questions(path)
    package = root / "deleted-annotation.zip"
    sync_recovery.create(path, package)
    restored = root / "restored"
    sync_recovery.restore_detached(package, restored)
    cache = legacy(restored)
    assert annotation_reader.questions(restored / "papers.db", "p", cache_root=cache) == {
        "items": [],
        "known": True,
    }
    with closing(sqlite3.connect(restored / "papers.db")) as conn:
        assert conn.execute("SELECT feature,paper_id FROM paper_annotation_known").fetchall() == [
            ("research_questions", "p")
        ]


def test_shared_bundle_preserves_deleted_annotation_marker_over_stale_legacy_cache(
    workspace,
    monkeypatch,
):
    root, path = workspace
    remove_questions(path)
    legacy(root)
    package = root / "share.zip"
    bundle.export("l", package, with_pdfs=False)
    recipient = root / "recipient"
    recipient.mkdir()
    monkeypatch.setattr(store, "DB_PATH", recipient / "papers.db")
    monkeypatch.setattr(bundle, "DATA_DIR", recipient)
    monkeypatch.setattr(bundle, "PDF_DIR", recipient / "pdf")
    store.init_db()
    bundle.import_(package, pdfs=False)
    bundle.import_(package, pdfs=False)
    assert annotation_reader.questions(
        store.DB_PATH, "p", cache_root=recipient / "research-questions"
    ) == {"items": [], "known": True}
