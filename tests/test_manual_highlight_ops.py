"""Loaded source and parent ownership guard local highlight transactions."""

import json
import os
import shutil
import sqlite3
from contextlib import closing

import pytest
from test_research_generation import pdf, rows
from test_research_generation import workspace as _workspace

from paper_daily import manual_highlight_ops as ops
from paper_daily import research_generation as generation
from paper_daily import sync_capture

workspace = _workspace
ANCHOR = dict(p0=0, o0=0, p1=0, o1=1)
QUOTE = "Original experiment"


@pytest.fixture
def view(workspace):
    database, _client, document = workspace
    owner = ops.capture_owner(database, "paper")
    return ops.load(owner, document.path, document.sha256, document=document)


def refresh(view):
    return ops.load(view.owner, view.path, view.fingerprint, document=view.document)


def pending(workspace, feature):
    client = workspace[1]
    return [op for op in client.journal.pending()
            if op.get("payload", {}).get("feature") == feature] if client else []


def ai(view):
    with closing(generation._connect(view.owner.database)) as conn:
        conn.execute("BEGIN IMMEDIATE")
        observation = sync_capture.observe_target(
            conn, "paper", "paper", "ai_highlight", view.fingerprint + ":source"
        )
        with sync_capture.expecting(conn, [observation]):
            conn.execute(
                "INSERT INTO pdf_ai_highlights(paper_id,document_hash,source_key,analysis_hash,"
                "anchor,quote,reason) VALUES(?,?,?,?,?,?,?)",
                ("paper", view.fingerprint, "source", "a" * 64, json.dumps(ANCHOR), QUOTE,
                 "Important method"),
            )
            conn.commit()
    return refresh(view)


def test_add_exact_coordinates_and_repeat_remove_are_atomic_and_idempotent(view, workspace):
    for _ in range(20):
        ops.add(view, ANCHOR, QUOTE)
    displayed = refresh(view)
    assert len(displayed.marks) == 1
    mark = displayed.marks[0]
    assert mark["quote"] == QUOTE and mark["anchor"] == ANCHOR
    assert rows(view.owner.database, "SELECT document_hash FROM pdf_highlights") == [
        {"document_hash": view.fingerprint}
    ]
    if workspace[1]:
        assert len(pending(workspace, "manual_highlight")) == 1
        payload = pending(workspace, "manual_highlight")[0]["payload"]
        assert payload["source_document_hash"] == view.fingerprint
        assert payload["data"]["anchor"] == ANCHOR
    for _ in range(20):
        ops.remove(displayed, [mark["id"], mark["id"]])
    assert not refresh(view).marks
    if workspace[1]:
        operations = workspace[1].journal.pending()
        assert len([op for op in operations if op['entity_type'] == 'research_content']) == 2
        assert operations[-1]['action'] == 'delete'


@pytest.mark.parametrize("change", ["missing_parent", "recreated_parent", "database", "pdf"])
def test_loaded_owner_or_source_changes_never_modify_replacement(view, change):
    database = view.owner.database
    if change == "database":
        replacement = database.with_suffix(".replacement")
        shutil.copyfile(database, replacement)
        os.replace(replacement, database)
    elif change == "pdf":
        view.path.unlink()
        pdf(view.path, "Replacement experiment")
    else:
        with closing(generation._connect(database)) as conn, sync_capture.suppress_capture(conn):
            conn.execute("BEGIN IMMEDIATE")
            row = dict(conn.execute("SELECT * FROM papers WHERE id='paper'").fetchone())
            conn.execute("DELETE FROM papers WHERE id='paper'")
            if change == "recreated_parent":
                conn.execute(f"INSERT INTO papers({','.join(row)}) VALUES"
                             f"({','.join('?' for _ in row)})", tuple(row.values()))
            conn.commit()
    with pytest.raises((ValueError, OSError)):
        ops.add(view, ANCHOR, QUOTE)
    assert rows(database, "SELECT * FROM pdf_highlights") == []


@pytest.mark.parametrize("anchor,quote", [
    ({**ANCHOR, "document_hash": "f" * 64}, QUOTE),
    ({**ANCHOR, "o1": 999}, QUOTE),
    ({**ANCHOR, "p1": 999}, QUOTE),
    (ANCHOR, "Text from a different PDF"),
    ({**ANCHOR, "o0": True}, QUOTE),
])
def test_invalid_coordinates_or_unmatched_text_never_write(view, anchor, quote):
    with pytest.raises(ValueError):
        ops.add(view, anchor, quote)
    assert rows(view.owner.database, "SELECT * FROM pdf_highlights") == []


def test_failed_commit_rolls_back_rows_and_outbox_then_retry_succeeds(view, workspace, monkeypatch):
    original = sync_capture.CaptureConnection.commit

    def failed(conn):
        raise sqlite3.OperationalError("Fixture commit unavailable")

    before = workspace[1].journal.pending() if workspace[1] else []
    monkeypatch.setattr(sync_capture.CaptureConnection, "commit", failed)
    with pytest.raises(sqlite3.OperationalError):
        ops.add(view, ANCHOR, QUOTE)
    assert rows(view.owner.database, "SELECT * FROM pdf_highlights") == []
    if workspace[1]:
        assert workspace[1].journal.pending() == before
    monkeypatch.setattr(sync_capture.CaptureConnection, "commit", original)
    ops.add(view, ANCHOR, QUOTE)
    assert len(refresh(view).marks) == 1


def test_pdf_change_during_transaction_rolls_back_mark(view, monkeypatch):
    original = ops._source
    calls = []

    def changed(loaded):
        calls.append(1)
        if len(calls) == 3:
            with loaded.path.open("ab") as stream:
                stream.write(b"\n% changed")
        return original(loaded)

    monkeypatch.setattr(ops, "_source", changed)
    with pytest.raises(ValueError, match="PDF"):
        ops.add(view, ANCHOR, QUOTE)
    assert rows(view.owner.database, "SELECT * FROM pdf_highlights") == []


def test_ai_hide_uses_displayed_base_and_is_preserved_by_same_key_regeneration(view, workspace):
    displayed = ai(view)
    ident = displayed.marks[0]["id"]
    assert ident < 0
    for _ in range(10):
        ops.remove(displayed, [ident])
    assert not refresh(view).marks
    with closing(generation._connect(view.owner.database)) as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = dict(conn.execute("SELECT * FROM pdf_ai_highlights").fetchone())
        observed = sync_capture.observe_content(conn, "pdf_ai_highlights", row)
        with sync_capture.expecting(conn, [observed]):
            # Producer owns analysis/quote/reason; never the user's hidden field.
            conn.execute("UPDATE pdf_ai_highlights SET reason='New explanation',analysis_hash=?",
                         ("b" * 64,))
            conn.commit()
    row = rows(view.owner.database, "SELECT * FROM pdf_ai_highlights")[0]
    assert row['hidden'] == 1 and row['reason'] == 'New explanation'
    assert not refresh(view).marks
    if workspace[1]:
        operations = pending(workspace, "ai_highlight")
        assert len(operations) == 3
        assert operations[-1]['payload']['data']['hidden'] == 1


def test_newer_ai_row_is_not_hidden_using_stale_displayed_base(view):
    displayed = ai(view)
    ident = displayed.marks[0]["id"]
    with closing(generation._connect(view.owner.database)) as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = dict(conn.execute("SELECT * FROM pdf_ai_highlights").fetchone())
        with sync_capture.expecting(conn, [sync_capture.observe_content(
                conn, "pdf_ai_highlights", row)]):
            conn.execute("UPDATE pdf_ai_highlights SET reason='Newer explanation'")
            conn.commit()
    with pytest.raises(ValueError, match="changed"):
        ops.remove(displayed, [ident])
    row = rows(view.owner.database, "SELECT * FROM pdf_ai_highlights")[0]
    assert row['hidden'] == 0 and row['reason'] == 'Newer explanation'


def test_foreign_id_and_empty_selection_never_remove_other_marks(view):
    ops.add(view, ANCHOR, QUOTE)
    displayed = refresh(view)
    ops.remove(displayed, [])
    with pytest.raises(ValueError):
        ops.remove(displayed, [displayed.marks[0]['id'] + 100])
    assert len(refresh(view).marks) == 1


def canonical(view, items, *, source_hash="a" * 64, document_hash="current", delete=False):
    from paper_daily import store

    with closing(generation._connect(view.owner.database)) as conn:
        conn.execute("BEGIN IMMEDIATE")
        observed = sync_capture.observe_target(conn, "paper", "paper", "highlight_analysis")
        with sync_capture.expecting(conn, [observed]):
            if delete:
                conn.execute("DELETE FROM paper_highlight_analysis WHERE paper_id='paper'")
            else:
                body = dict(items=items, coverage=dict(
                    pages=1, empty_pages=[], chunks=1, has_page_numbers=True
                ))
                conn.execute(
                    "INSERT INTO paper_highlight_analysis VALUES(?,?,?,?,?) "
                    "ON CONFLICT(paper_id) DO UPDATE SET body_json=excluded.body_json,"
                    "source_hash=excluded.source_hash,document_hash=excluded.document_hash,"
                    "written_at=excluded.written_at",
                    ("paper", json.dumps(body), source_hash,
                     view.fingerprint if document_hash == "current" else document_hash,
                     store.now()),
                )
            conn.commit()


@pytest.fixture
def canonical_view(view):
    import hashlib

    from paper_daily import pdf_highlights

    text = "Original experiment establishes a useful result"
    view.path.unlink()
    pdf(view.path, text)
    loaded = ops.load(view.owner, view.path, pdf_highlights.document_hash(view.path))
    key = hashlib.sha256(f"1:{text}".encode()).hexdigest()
    with closing(generation._connect(view.owner.database)) as conn:
        conn.execute("BEGIN IMMEDIATE")
        observed = sync_capture.observe_target(conn, "paper", "paper", "ai_highlight",
                                               loaded.fingerprint + ":" + key)
        with sync_capture.expecting(conn, [observed]):
            conn.execute(
                "INSERT INTO pdf_ai_highlights(paper_id,document_hash,source_key,analysis_hash,"
                "anchor,quote,reason) VALUES(?,?,?,?,?,?,?)",
                ("paper", loaded.fingerprint, key, "a" * 64,
                 json.dumps({**ANCHOR, "o1": 5}), text, "Core evidence"),
            )
            conn.commit()
    item = dict(text=text, page=1, kind="evidence", reason="Core evidence", source="page:1")
    return loaded, item


@pytest.mark.parametrize("state", ["active", "other_input", "other_pdf", "unknown_pdf", "omitted",
                                   "deleted"])
def test_canonical_ai_visibility_requires_current_key_and_both_hashes(canonical_view, state):
    view, item = canonical_view
    assert len(refresh(view).marks) == 1  # Legacy-only display remains compatible.
    canonical(view, [item])
    if state == "other_input":
        canonical(view, [item], source_hash="b" * 64)
    elif state == "other_pdf":
        canonical(view, [item], document_hash="b" * 64)
    elif state == "unknown_pdf":
        canonical(view, [item], document_hash=None)
    elif state == "omitted":
        canonical(view, [])  # Same source digest, different selected quotes.
    elif state == "deleted":
        canonical(view, [], delete=True)
    visible = refresh(view).marks
    assert len(visible) == (1 if state == "active" else 0)
    assert len(rows(view.owner.database, "SELECT * FROM pdf_ai_highlights")) == 1


def test_hidden_preference_survives_omission_then_same_input_quote_return(canonical_view):
    view, item = canonical_view
    canonical(view, [item])
    displayed = refresh(view)
    ops.remove(displayed, [displayed.marks[0]["id"]])
    canonical(view, [])
    assert not refresh(view).marks
    canonical(view, [item])
    assert not refresh(view).marks
    assert rows(view.owner.database, "SELECT hidden FROM pdf_ai_highlights") == [{"hidden": 1}]


def test_inactive_historical_ai_ids_cannot_be_targeted_from_new_view(canonical_view):
    view, _item = canonical_view
    old = refresh(view).marks[0]["id"]
    canonical(view, [])
    with pytest.raises(ValueError, match="displayed view"):
        ops.remove(refresh(view), [old])
    assert rows(view.owner.database, "SELECT hidden FROM pdf_ai_highlights") == [{"hidden": 0}]


def test_incomplete_enrollment_cannot_silently_write_without_outbox(tmp_path):
    from paper_daily import store
    from paper_daily.sync_research import prepare

    database = tmp_path / "incomplete.sqlite"
    with sqlite3.connect(database) as conn:
        conn.executescript(store.SCHEMA)
        store.upsert_papers(conn, [dict(id="paper", title="Paper", year=2026, venue="Fixture",
                                       source="fixture")])
    prepare(database, workspace_id="workspace", device_id="device")
    with pytest.raises(ValueError, match="capture is not installed"):
        ops.capture_owner(database, "paper")
    assert rows(database, "SELECT * FROM pdf_highlights") == []


def test_remove_and_hide_roll_back_together_on_commit_failure(view, workspace, monkeypatch):
    ops.add(view, ANCHOR, QUOTE)
    displayed = ai(view)
    original = sync_capture.CaptureConnection.commit
    before = workspace[1].journal.pending() if workspace[1] else []

    def fail(_conn):
        raise sqlite3.OperationalError("Fixture removal commit failure")

    monkeypatch.setattr(sync_capture.CaptureConnection, "commit", fail)
    with pytest.raises(sqlite3.OperationalError):
        ops.remove(displayed, [mark["id"] for mark in displayed.marks])
    assert len(rows(view.owner.database, "SELECT * FROM pdf_highlights")) == 1
    assert rows(view.owner.database, "SELECT hidden FROM pdf_ai_highlights") == [{"hidden": 0}]
    if workspace[1]:
        assert workspace[1].journal.pending() == before
    monkeypatch.setattr(sync_capture.CaptureConnection, "commit", original)
    ops.remove(displayed, [mark["id"] for mark in displayed.marks])
    assert not refresh(view).marks


def test_snapshot_budget_refuses_unbounded_rows_without_deleting_them(view, monkeypatch):
    ops.add(view, ANCHOR, QUOTE)
    ops.add(view, {**ANCHOR, "o1": 0}, "Original")
    monkeypatch.setattr(ops, "MAX_MARKS", 1)
    with pytest.raises(ValueError, match="budget"):
        refresh(view)
    assert len(rows(view.owner.database, "SELECT * FROM pdf_highlights")) == 2


def test_malformed_pdf_fails_closed_without_raw_parser_exception(view):
    from paper_daily.pdf_highlights import document_hash

    path = view.path.with_name("malformed.pdf")
    path.write_bytes(b"This is not a PDF")
    with pytest.raises(ValueError, match="PDF verification failed"):
        ops.load(view.owner, path, document_hash(path))
    assert rows(view.owner.database, "SELECT * FROM pdf_highlights") == []


def test_capturing_owner_on_open_never_waits_behind_another_writer(workspace):
    import threading
    import time

    database = workspace[0]
    expected = ops.capture_owner(database, "paper")
    holding, release = threading.Event(), threading.Event()

    def hold_write_lock():
        with closing(sqlite3.connect(database)) as conn:
            conn.execute("BEGIN IMMEDIATE")
            holding.set()
            release.wait(5)
            conn.rollback()

    writer = threading.Thread(target=hold_write_lock)
    writer.start()
    try:
        assert holding.wait(5)
        started = time.perf_counter()
        owner = ops.capture_owner(database, "paper")
        elapsed = time.perf_counter() - started
    finally:
        release.set()
        writer.join()
    assert elapsed < 1
    assert owner == expected
