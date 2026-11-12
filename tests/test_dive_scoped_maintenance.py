"""Maintained batch retry and follow-up behavior stays in its original workspace."""

import sqlite3
from contextlib import closing
from pathlib import Path

import pytest

from paper_daily import brief, closeread, dive, llm, store
from paper_daily.manual_highlight_ops import capture_owner


@pytest.fixture
def research(tmp_path, monkeypatch):
    from test_dive import conn

    database = conn.__wrapped__(monkeypatch, tmp_path)
    monkeypatch.setattr(dive, "init_db", lambda: None)
    yield database
    database.close()


def foreign_database(path):
    with closing(sqlite3.connect(path)) as other:
        other.executescript(store.SCHEMA)
        other.commit()


def test_success_followup_and_saved_dive_keep_database_account_and_owner(
    research, monkeypatch, tmp_path
):
    original = Path(store.DB_PATH).resolve()
    foreign = tmp_path / "foreign.db"
    foreign_database(foreign)
    captured = llm.capture_connections()
    monkeypatch.setattr(llm, "capture_connections", lambda: captured)
    seen = []

    def generate(pid, *, database, connections, expected_owner):
        assert database == original and connections is captured
        assert expected_owner.database == original and expected_owner.paper_id == pid
        monkeypatch.setattr(store, "DB_PATH", foreign)
        return "Original saved explanation" * 50, "ok"

    def close_read(pid, *, database, connections, expected_owner, expected_document_hash):
        assert database == original and connections is captured
        assert expected_owner.database == original and expected_owner.paper_id == pid
        assert expected_document_hash is None
        expected_owner.check(research)
        seen.append(pid)
        return "Section explanation", "ok"

    monkeypatch.setattr(dive, "_generate_for", generate)
    monkeypatch.setattr(closeread, "write", close_read)
    assert dive.dive_ahead(1) == 1
    assert seen == ["p1"]
    assert (
        research.execute("SELECT body FROM dives WHERE paper_id='p1'")
        .fetchone()[0]
        .startswith("Original")
    )
    with closing(sqlite3.connect(foreign)) as other:
        assert other.execute("SELECT count(*) FROM dives").fetchone()[0] == 0
        assert other.execute("SELECT count(*) FROM kv").fetchone()[0] == 0


@pytest.mark.parametrize(
    "reason,excluded",
    [
        ("API Error: usage policy rejected this document", True),
        ("HTTP 429: rate limited", False),
        ("claude API Error: 500；AI 服務回報錯誤，請稍後重試", False),
        ("timed out after 5s", False),
        ("deep dive is already in progress", False),
    ],
)
def test_failure_state_is_local_and_temporary_errors_do_not_exhaust_document_retries(
    research,
    monkeypatch,
    tmp_path,
    reason,
    excluded,
):
    original = Path(store.DB_PATH).resolve()
    foreign = tmp_path / "foreign.db"
    foreign_database(foreign)

    def fail(pid, *, database, connections, expected_owner):
        assert database == original
        monkeypatch.setattr(store, "DB_PATH", foreign)
        return None, reason

    monkeypatch.setattr(dive, "_generate_for", fail)
    assert dive.dive_ahead(1) == 0
    assert (store.get_kv(research, "dive.gave_up.p1") is not None) is excluded
    if not excluded:
        assert store.get_kv(research, "dive.failures.p1") is None
    assert research.execute("SELECT count(*) FROM dives").fetchone()[0] == 0
    with closing(sqlite3.connect(foreign)) as other:
        assert other.execute("SELECT count(*) FROM kv").fetchone()[0] == 0


def test_recreated_paper_cannot_receive_late_failure_or_followup(research, monkeypatch):
    row = dict(research.execute("SELECT * FROM papers WHERE id='p1'").fetchone())

    def fail(pid, **scope):
        research.execute("DELETE FROM papers WHERE id=?", (pid,))
        research.execute(
            "INSERT INTO papers(" + ",".join(row) + ") VALUES (" + ",".join("?" for _ in row) + ")",
            tuple(row.values()),
        )
        research.commit()
        return None, "API Error: usage policy refusal"

    monkeypatch.setattr(dive, "_generate_for", fail)
    assert dive.dive_ahead(1) == 0
    assert store.get_kv(research, "dive.gave_up.p1") is None
    assert store.get_kv(research, "dive.failures.p1") is None


def test_close_reading_checks_original_owner_before_preparing_model_input(research, monkeypatch):
    owner = capture_owner(store.DB_PATH, "p1")
    research.execute("DELETE FROM papers WHERE id='p1'")
    research.commit()
    monkeypatch.setattr(brief, "pack_text", lambda *a: pytest.fail("read a retired paper"))
    monkeypatch.setattr(llm, "complete", lambda *a, **k: pytest.fail("spent model call"))
    with pytest.raises(ValueError, match="changed"):
        closeread.write("p1", database=owner.database, expected_owner=owner)


def test_close_reading_refuses_unverified_original_before_model_call(research, monkeypatch):
    owner = capture_owner(store.DB_PATH, "p1")
    monkeypatch.setattr(brief, "pack_text", lambda *a: ("unverified pack", Path("p1.pdf")))
    monkeypatch.setattr(llm, "complete", lambda *a, **k: pytest.fail("spent model call"))
    result, reason = closeread.write(
        "p1",
        database=owner.database,
        expected_owner=owner,
        expected_document_hash="a" * 64,
    )
    assert result is None and "original changed" in reason
    assert research.execute("SELECT count(*) FROM close_readings").fetchone()[0] == 0


def test_close_reading_failure_keeps_saved_dives_and_continues_batch(research, monkeypatch):
    monkeypatch.setattr(dive, "_generate_for", lambda pid, **scope: ("Saved " + pid, "ok"))
    attempts = []

    def close_read(pid, **scope):
        attempts.append(pid)
        raise ValueError("Source changed before the second stage")

    monkeypatch.setattr(closeread, "write", close_read)
    messages = []
    assert dive.dive_ahead(2, log=messages.append) == 2
    assert attempts == ["p1", "p2"]
    assert [
        tuple(row) for row in research.execute("SELECT paper_id,body FROM dives ORDER BY paper_id")
    ] == [("p1", "Saved p1"), ("p2", "Saved p2")]
    assert sum("Source changed" in message for message in messages) == 2


def test_existing_close_reading_and_manual_retry_are_preserved(research, monkeypatch):
    research.execute(
        "INSERT INTO close_readings(paper_id,body,spec,written_at) "
        "VALUES('p1','Manual section notes',NULL,'2026-11-01T00:00:00+00:00')"
    )
    store.set_kv(research, "dive.failures.p1", {"count": 3})
    store.set_kv(research, "dive.gave_up.p1", "before")
    research.commit()
    monkeypatch.setattr(
        dive, "_generate_for", lambda pid, **scope: ("New requested explanation", "ok")
    )
    monkeypatch.setattr(
        closeread, "write", lambda *a, **k: pytest.fail("rewrote manual section notes")
    )
    assert dive.dive_ahead(paper_id="p1") == 1
    assert store.get_kv(research, "dive.failures.p1") is None
    assert store.get_kv(research, "dive.gave_up.p1") is None
    assert (
        research.execute("SELECT body FROM close_readings").fetchone()[0] == "Manual section notes"
    )


def test_selected_lifetime_is_rechecked_before_the_next_paper_uses_ai(research, monkeypatch):
    original = dict(research.execute("SELECT * FROM papers WHERE id='p2'").fetchone())
    calls = []
    monkeypatch.setattr(brief, "pack_text", lambda *a: ("Captured original pack", None))

    def complete(prompt, **kwargs):
        calls.append(prompt)
        research.execute("DELETE FROM papers WHERE id='p2'")
        research.execute(
            "INSERT INTO papers("
            + ",".join(original)
            + ") VALUES ("
            + ",".join("?" for _ in original)
            + ")",
            tuple(original.values()),
        )
        research.commit()
        return "Saved explanation " * 80, "ok"

    monkeypatch.setattr(llm, "complete", complete)
    assert dive.dive_ahead(2) == 1
    assert calls == ["Captured original pack"]
    assert [row[0] for row in research.execute("SELECT paper_id FROM dives")] == ["p1"]
    assert store.get_kv(research, "dive.failures.p2") is None
    assert store.get_kv(research, "dive.gave_up.p2") is None


def test_close_reading_cannot_use_another_selected_papers_owner(research, monkeypatch):
    owner = capture_owner(store.DB_PATH, "p1")
    monkeypatch.setattr(brief, "pack_text", lambda *a: pytest.fail("wrong paper prepared"))
    with pytest.raises(ValueError, match="another research owner"):
        closeread.write("p2", database=owner.database, expected_owner=owner)
    assert research.execute("SELECT count(*) FROM close_readings").fetchone()[0] == 0
