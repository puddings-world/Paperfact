"""Local display metadata preserves research and never supplies decision authority."""

import hashlib
import pickle
import sqlite3
from contextlib import closing
from uuid import uuid4

import pytest
from test_research_review import candidate
from test_research_review import workspace as workspace

from paper_daily import research_generation as generation
from paper_daily import review_decisions as decisions
from paper_daily import sync_capture
from paper_daily.research_review import ResearchReview, _setup


def receipt(conn, origin, identity, decision="applied"):
    ResearchReview._receipt(
        conn,
        str(uuid4()),
        "a" * 64,
        dict(origin=origin, id=identity, source_hash=None, scope={}),
        dict(decision=decision, operation_id=None),
    )


@pytest.mark.parametrize(
    "origin,identity,alias",
    [
        ("generation", "candidate", "claim_resume"),
        ("sidecar", "namespace/request.json", "claim_resume"),
        ("remote", "10", "claim_resume"),
        ("archived_draft", "a" * 64, "claim_resume"),
        ("archived_draft", "a" * 64, "archived_resume"),
        ("archived_draft", "a" * 64, "archived_note_resume"),
    ],
)
def test_original_item_projects_latest_typed_local_decision_without_writes(origin, identity, alias):
    with closing(sqlite3.connect(":memory:")) as conn:
        _setup(conn)
        reference = identity if origin == "archived_draft" else origin + ":" + identity
        receipt(conn, origin, identity, "kept")
        receipt(conn, alias, reference)
        receipt(conn, alias, reference + "-other", "kept")
        before = conn.total_changes
        assert decisions.latest_in(conn, origin, identity) == "applied"
        receipt(conn, origin, identity, "kept")
        assert decisions.latest_in(conn, origin, identity) == "kept"
        assert conn.total_changes == before + 1


def test_absent_and_invalid_decision_metadata_never_becomes_a_badge_or_schema():
    with closing(sqlite3.connect(":memory:")) as conn:
        assert decisions.latest_in(conn, "generation", "item") is None
        assert conn.execute("SELECT name FROM sqlite_master").fetchall() == []
        _setup(conn)
        receipt(conn, "generation", "item", "untrusted status text")
        assert decisions.latest_in(conn, "generation", "item") is None
        for origin, identity in (
            ([], "item"),
            ("unknown", "item"),
            ("remote", ""),
            ("remote", []),
            ("remote", "x" * 4097),
        ):
            with pytest.raises(ValueError):
                decisions.latest_in(conn, origin, identity)


@pytest.fixture
def saved(workspace):
    path, client = workspace
    identity = candidate(path)
    service = ResearchReview(path)
    service.decide(service.preview("generation", identity), keep=True, request_id="local-keep")
    try:
        yield service, identity, client
    finally:
        service.close()


def test_captured_status_is_readonly_native_only_and_cannot_apply_or_serialize(saved, monkeypatch):
    service, identity, client = saved
    before = service.path.read_bytes(), client.journal.pending()
    snapshot = decisions.capture(service, "generation", identity)
    assert snapshot.decision == "kept" and snapshot.key == ("generation", identity)
    assert before == (service.path.read_bytes(), client.journal.pending())

    def forbidden(*args, **kwargs):
        raise AssertionError("GUI metadata admission performed SQL or hashing")

    with monkeypatch.context() as patch:
        patch.setattr(sqlite3, "connect", forbidden)
        patch.setattr(hashlib, "sha256", forbidden)
        assert decisions.current(snapshot)
    with pytest.raises(TypeError, match="process-only"):
        pickle.dumps(snapshot)
    with pytest.raises(ValueError):
        service.decide(snapshot)
    assert before == (service.path.read_bytes(), client.journal.pending())


@pytest.mark.parametrize("change", ["close", "binding", "session", "write", "replace"])
def test_intervening_lifetime_or_database_change_rejects_old_display_metadata(saved, change):
    service, identity, _client = saved
    snapshot = decisions.capture(service, "generation", identity)
    if change == "close":
        service.close()
    elif change == "binding":
        service.binding = dict(service.binding, device_id="another-device")
    elif change == "session":
        service.session = "replacement-session"
    elif change == "write":
        with closing(generation._connect(service.path)) as conn, conn:
            conn.execute("UPDATE papers SET title='Later title' WHERE id='paper'")
    else:
        replacement = service.path.with_suffix(".replacement")
        with (
            closing(sqlite3.connect(service.path)) as source,
            closing(sqlite3.connect(replacement)) as target,
        ):
            source.backup(target)
        replacement.replace(service.path)
    before = service.path.read_bytes()
    assert not decisions.current(snapshot)
    assert service.path.read_bytes() == before
    if change == "write":
        assert decisions.capture(service, "generation", identity).decision == "kept"


def test_missing_original_does_not_mint_display_metadata(saved):
    service, _identity, _client = saved
    before = service.path.read_bytes()
    with pytest.raises(ValueError):
        decisions.capture(service, "generation", str(uuid4()))
    assert service.path.read_bytes() == before


def test_empty_wal_lifecycle_is_neutral_but_nonempty_log_invalidates_metadata(saved):
    service, identity, _client = saved
    snapshot = decisions.capture(service, "generation", identity)
    wal = service.path.with_name(service.path.name + "-wal")
    before = service.path.read_bytes()
    assert wal.exists() and wal.stat().st_size == 0
    wal.unlink()
    assert decisions.current(snapshot)
    wal.write_bytes(b"")
    assert decisions.current(snapshot)
    wal.write_bytes(b"Synthetic nonempty log invalidates display metadata")
    assert not decisions.current(snapshot)
    wal.write_bytes(b"")
    assert service.path.read_bytes() == before


def test_real_uncheckpointed_write_invalidates_even_when_database_bytes_are_unchanged(saved):
    service, identity, _client = saved
    snapshot = decisions.capture(service, "generation", identity)
    before = service.path.read_bytes()
    with closing(generation._connect(service.path)) as conn:
        with sync_capture.suppress_capture(conn):
            conn.execute("PRAGMA wal_autocheckpoint=0")
        conn.execute("BEGIN IMMEDIATE")
        conn.execute("UPDATE papers SET title='Uncheckpointed title' WHERE id='paper'")
        conn.commit()
        wal = service.path.with_name(service.path.name + "-wal")
        assert wal.stat().st_size > 0 and service.path.read_bytes() == before
        assert not decisions.current(snapshot)
