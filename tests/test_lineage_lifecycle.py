"""Real observed lifecycle actions preserve science, sources, caller work and retry intent."""

import sqlite3
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from uuid import uuid4

import pytest
from test_lineage_jobs import work
from test_lineage_recovery import published
from test_research_lineage import corpus as corpus

from paper_daily import lineage_lifecycle as lifecycle
from paper_daily import lineage_sets, llm
from paper_daily import research_generation as generation
from paper_daily.manual_highlight_ops import observe_owner


@pytest.fixture
def active(corpus, monkeypatch):
    published(corpus, monkeypatch)
    owner = observe_owner(corpus[0], "focal", expected_native=generation._identity(corpus[0]))
    row = lineage_sets.saved(corpus[0], "focal")[0]
    monkeypatch.setattr(llm, "complete_result", lambda *_a, **_k: pytest.fail("No lifecycle AI"))
    return owner, row


def change(active, action, request_id=None, origin=None, **options):
    owner, row = active
    return work(
        lifecycle.change,
        owner,
        row,
        request_id=request_id or str(uuid4()),
        action=action,
        origin=origin,
        **options,
    )


def test_unbound_retire_restore_and_exact_retries_preserve_originals_and_models(active):
    owner, row = active
    with closing(sqlite3.connect(owner.database)) as conn:
        originals = conn.execute(
            "SELECT * FROM research_local_source_owners ORDER BY request_id"
        ).fetchall()
    request = str(uuid4())
    removed = change(active, "retire", request)
    assert removed["state"] == "saved_local" and removed["applied"]
    assert lineage_sets.saved(owner.database, owner.paper_id) == []
    assert not change(active, "retire", request)["applied"]
    history = work(lifecycle.history, owner)
    assert len(history["items"]) == 1 and not history["more"]
    item = history["items"][0]
    assert item["row"] == row and item["origin"]["kind"] == "generated"
    restored_id = str(uuid4())
    assert change(active, "restore", restored_id, item["origin"])["applied"]
    assert not change(active, "restore", restored_id, item["origin"])["applied"]
    assert lineage_sets.saved(owner.database, owner.paper_id) == [row]
    with pytest.raises(ValueError, match="target changed"):
        change(active, "retire", request)
    with closing(sqlite3.connect(owner.database)) as conn:
        assert (
            conn.execute(
                "SELECT * FROM research_local_source_owners ORDER BY request_id"
            ).fetchall()
            == originals
        )
        assert conn.execute("SELECT count(*) FROM " + lifecycle.TABLE).fetchone()[0] == 2


def test_concurrent_same_request_creates_one_removal_and_one_history_receipt(active):
    owner, _row = active
    identity = str(uuid4())
    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(lambda _: change(active, "retire", identity), range(2)))
    assert sorted(r["applied"] for r in outcomes) == [False, True]
    assert lineage_sets.saved(owner.database, owner.paper_id) == []
    assert len(work(lifecycle.history, owner)["items"]) == 1


def test_action_failure_rolls_back_removal_but_retains_earlier_caller_work(active):
    owner, row = active

    def run():
        with closing(generation._connect(owner.database)) as conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(lifecycle.SCHEMA)
            conn.execute("INSERT INTO kv VALUES('prior-work','keep')")
            conn.execute(
                "CREATE TRIGGER fail_lifecycle BEFORE INSERT ON research_lineage_actions "
                "BEGIN SELECT RAISE(ABORT,'fixture lifecycle failure'); END"
            )
            with pytest.raises(sqlite3.IntegrityError, match="lifecycle failure"):
                lifecycle.apply_in(conn, owner, row, action="retire", request_id=str(uuid4()))
            assert conn.in_transaction
            conn.commit()

    work(run)
    assert lineage_sets.saved(owner.database, owner.paper_id) == [row]
    with closing(sqlite3.connect(owner.database)) as conn:
        assert conn.execute("SELECT value FROM kv WHERE key='prior-work'").fetchone()[0] == "keep"
        assert conn.execute("SELECT count(*) FROM " + lifecycle.TABLE).fetchone()[0] == 0


@pytest.mark.parametrize("late", [False, True])
def test_cancel_before_or_after_write_changes_no_science_or_receipts(active, late):
    owner, row = active
    calls = [0]

    def cancelled():
        calls[0] += 1
        return not late or calls[0] == 2

    with pytest.raises(ValueError, match="cancelled"):
        change(active, "retire", cancelled=cancelled)
    assert lineage_sets.saved(owner.database, owner.paper_id) == [row]
    assert work(lifecycle.history, owner)["items"] == []


def test_changed_displayed_row_and_request_reuse_never_overwrite_newer_research(active):
    owner, row = active
    with closing(sqlite3.connect(owner.database)) as conn, conn:
        conn.execute("UPDATE paper_lineage_sets SET written_at='2026-11-20T00:00:00+00:00'")
    with pytest.raises(ValueError, match="target changed"):
        change(active, "retire")
    assert (
        lineage_sets.saved(owner.database, owner.paper_id)[0]["written_at"]
        == "2026-11-20T00:00:00+00:00"
    )
    with closing(sqlite3.connect(owner.database)) as conn, conn:
        conn.execute("UPDATE paper_lineage_sets SET written_at=?", (row["written_at"],))
    identity = str(uuid4())
    change(active, "retire", identity)
    with pytest.raises(ValueError, match="request ID reused"):
        change(active, "restore", identity, work(lifecycle.history, owner)["items"][0]["origin"])
    assert lineage_sets.saved(owner.database, owner.paper_id) == []


@pytest.mark.parametrize("source_change", ["association", "parent"])
def test_restore_refuses_lost_original_grant_or_recreated_selected_parent(active, source_change):
    owner, _row = active
    change(active, "retire")
    item = work(lifecycle.history, owner)["items"][0]
    with closing(sqlite3.connect(owner.database)) as conn, conn:
        if source_change == "association":
            conn.execute("DELETE FROM research_local_source_owners")
        else:
            previous = conn.execute("SELECT * FROM papers WHERE id='prior'").fetchone()
            assert previous is not None
            conn.execute("DELETE FROM papers WHERE id='prior'")
            conn.execute(
                "INSERT INTO papers VALUES(" + ",".join("?" for _ in previous) + ")", previous
            )
    with pytest.raises(ValueError, match="association|lifetime"):
        change(active, "restore", origin=item["origin"])
    assert lineage_sets.saved(owner.database, owner.paper_id) == []
    assert len(work(lifecycle.history, owner)["items"]) == 1


def test_restoration_preserves_renamed_selected_paper(active):
    owner, row = active
    change(active, "retire")
    item = work(lifecycle.history, owner)["items"][0]
    with closing(sqlite3.connect(owner.database)) as conn, conn:
        conn.execute("UPDATE papers SET title='Renamed prior paper' WHERE id='prior'")
    assert change(active, "restore", origin=item["origin"])["applied"]
    assert lineage_sets.saved(owner.database, owner.paper_id) == [row]
    with closing(sqlite3.connect(owner.database)) as conn:
        assert conn.execute("SELECT title FROM papers WHERE id='prior'").fetchone()[0] == (
            "Renamed prior paper"
        )


@pytest.mark.parametrize("restored", [False, True])
def test_backup_preserves_removed_history_and_sources_without_live_action_authority(
    active, tmp_path, restored
):
    import json
    import zipfile

    from test_sync_recovery import archive_rows

    from paper_daily import enrollment_history, sync_recovery

    owner, row = active
    change(active, "retire")
    item = work(lifecycle.history, owner)["items"][0]
    if restored:
        change(active, "restore", origin=item["origin"])
    package = tmp_path / "lifecycle.zip"
    manifest = sync_recovery.create(owner.database, package)
    assert sync_recovery.inspect(package) == manifest
    actions = archive_rows(package, lifecycle.TABLE)
    assert len(actions) == (2 if restored else 1)
    assert archive_rows(package, lineage_sets.TABLE) == ([row] if restored else [])
    for action in actions:
        wrapped = enrollment_history.wrap(lifecycle.TABLE, action)
        enrollment_history.validate(wrapped)
    publications = archive_rows(package, "research_lineage_publications")
    originals = json.loads(publications[0]["sources_json"])
    with zipfile.ZipFile(package) as archive:
        for source in originals:
            assert archive.read("objects/" + source["sha256"])
    destination = tmp_path / "detached"
    sync_recovery.restore_detached(package, destination)
    with closing(sqlite3.connect(destination / "papers.db")) as conn:
        assert not conn.execute(
            "SELECT 1 FROM sqlite_master WHERE name=?", (lifecycle.TABLE,)
        ).fetchone()
        archived = [
            json.loads(r[0])
            for r in conn.execute(
                "SELECT data FROM recovery_records WHERE table_name=?", (lifecycle.TABLE,)
            )
        ]
    assert sorted(archived, key=lambda r: r["request_id"]) == sorted(
        actions, key=lambda r: r["request_id"]
    )
    assert lineage_sets.saved(destination / "papers.db", owner.paper_id) == (
        [row] if restored else []
    )


def test_removed_history_cannot_be_backed_up_without_its_exact_generation_provenance(
    active, tmp_path
):
    from paper_daily import sync_recovery

    owner, _row = active
    change(active, "retire")
    with closing(sqlite3.connect(owner.database)) as conn, conn:
        conn.execute("DELETE FROM research_lineage_publications")
    output = tmp_path / "missing-provenance.zip"
    with pytest.raises(ValueError, match="generation provenance"):
        sync_recovery.create(owner.database, output)
    assert not output.exists()
    assert len(work(lifecycle.history, owner)["items"]) == 1
