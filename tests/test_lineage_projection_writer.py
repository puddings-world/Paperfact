"""Actual journal authority can project Lineage without granting transaction control."""

import copy
import json
import sqlite3
from contextlib import closing

import pytest
from test_lineage_dependencies import compound
from test_lineage_observation import work
from test_lineage_peer_sources import codec as codec
from test_lineage_peer_sources import pair as pair
from test_lineage_peer_sources import selected as selected
from test_lineage_projection import frame_for, rows, verified_report

from paper_daily import lineage_projection as projection
from paper_daily import lineage_sets
from paper_daily.sync_journal import canonical_operation


def protected(conn, client, frame, *, visible=True):
    conn.set_authorizer(client.journal._authorize_writer)
    try:
        return projection.apply_in(conn, frame, visible=visible)
    finally:
        conn.set_authorizer(None)


def test_journal_owned_projection_keeps_authority_restrictions_and_exact_source_metadata(selected):
    client = selected[0][1]
    frame, _originals = frame_for(selected)
    before = client.journal.pending()

    def run():
        with client.journal.transaction() as conn:
            projection.initialize_in(conn)
            conn.set_authorizer(client.journal._authorize_writer)
            try:
                # The compatibility fix must not weaken the real journal policy.
                for sql in ("SAVEPOINT untrusted", "COMMIT", "CREATE TABLE wrong(value)"):
                    with pytest.raises(sqlite3.DatabaseError, match="not authorized"):
                        conn.execute(sql)
                with pytest.raises(sqlite3.DatabaseError, match="not authorized"):
                    projection.write_in(conn, frame)
                assert projection.apply_in(conn, frame)["state"] == "projected"
                assert projection.apply_in(conn, frame)["state"] == "projected"
            finally:
                conn.set_authorizer(None)
            with closing(client.journal._connect()) as outside:
                assert outside.execute("SELECT COUNT(*) FROM paper_lineage_sets").fetchone()[0] == 0

    work(run)
    assert len(rows(client, projection.TABLE)) == len(rows(client, projection.HISTORY)) == 1
    assert rows(client, lineage_sets.TABLE)[0]["corpus_key"] == frame["payload"]["key"]
    assert client.journal.pending() == before
    assert json.loads(canonical_operation(frame)) == frame


def test_late_protected_write_failure_rolls_back_the_real_journal_transaction(selected):
    client = selected[0][1]
    frame, _originals = frame_for(selected)
    # This case proves rollback of newly created metadata. Native setup now
    # provides empty metadata beforehand; make schema absence explicit here.
    # The separate initialized-baseline case preserves every existing SQL row.
    with client.journal.transaction() as conn:
        for table in (projection.TABLE, projection.HISTORY):
            if conn.execute("SELECT 1 FROM sqlite_master WHERE name=?", (table,)).fetchone():
                assert conn.execute("SELECT count(*) FROM " + table).fetchone()[0] == 0
                conn.execute("DROP TABLE " + table)
        names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert projection.TABLE not in names and projection.HISTORY not in names
    before = client.journal.pending()

    def run():
        with client.journal.transaction() as conn:
            projection.initialize_in(conn)
            conn.execute("INSERT INTO kv VALUES('caller-fixture','keep only on success')")
            conn.execute(
                "CREATE TRIGGER fixture_late BEFORE INSERT ON "
                + projection.TABLE
                + " BEGIN SELECT RAISE(ABORT,'fixture late projection'); END"
            )
            protected(conn, client, frame)

    with pytest.raises(sqlite3.IntegrityError, match="late projection"):
        work(run)
    assert rows(client, lineage_sets.TABLE) == []
    with closing(client.journal._connect()) as conn:
        assert conn.execute("SELECT value FROM kv WHERE key='caller-fixture'").fetchone() is None
        names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert projection.TABLE not in names and projection.HISTORY not in names
    assert client.journal.pending() == before


@pytest.mark.parametrize(
    "change", ["missing", "retired", "restored", "wrong-incarnation", "foreign-parent"]
)
def test_current_original_metadata_is_required_before_any_scientific_write(selected, change):
    client = selected[0][1]
    frame, originals = frame_for(selected)
    original = next(iter(originals.values()))
    with client.journal.transaction() as conn:
        projection.initialize_in(conn)
        if change == "missing":
            conn.execute(
                "DELETE FROM research_file_desired WHERE entity_id=?", (original["entity_id"],)
            )
        elif change == "wrong-incarnation":
            frame = copy.deepcopy(frame)
            frame["source_dependencies"][0]["incarnation"] = "other-file-lifetime"
        elif change == "foreign-parent":
            changed = copy.deepcopy(original)
            changed["parents"][0]["incarnation"] = "another-paper-lifetime"
            conn.execute(
                "UPDATE research_file_desired SET operation=? WHERE entity_id=?",
                (json.dumps(changed), original["entity_id"]),
            )
        else:
            retired = client.new_graph_operation_in(
                conn, "research_file", original["entity_id"], {}, action="delete"
            )
            client.journal.apply_in(conn, retired, client.writer)
            if change == "restored":
                restored = client.new_graph_operation_in(
                    conn, "research_file", original["entity_id"], original["payload"], restore=True
                )
                client.journal.apply_in(conn, restored, client.writer)
        before = list(conn.iterdump())
        with pytest.raises(ValueError, match="original"):
            protected(conn, client, frame)
        assert list(conn.iterdump()) == before and conn.in_transaction
    assert rows(client, lineage_sets.TABLE) == []


def test_hidden_put_retains_history_after_original_retirement_and_never_hashes_pdf(
    selected, monkeypatch
):
    client = selected[0][1]
    frame, originals = frame_for(selected)

    def unexpected(*_args, **_kwargs):
        pytest.fail("PDF work must stay outside protected SQL projection")

    from paper_daily import local_source_owners, research_evidence, sync_source_files

    monkeypatch.setattr(local_source_owners, "_read_pdf", unexpected)
    monkeypatch.setattr(research_evidence, "_extract", unexpected)
    monkeypatch.setattr(sync_source_files, "validate_pdf", unexpected)

    def run():
        with client.journal.transaction() as conn:
            projection.initialize_in(conn)
            protected(conn, client, frame)
            original = next(iter(originals.values()))
            retired = client.new_graph_operation_in(
                conn, "research_file", original["entity_id"], {}, action="delete"
            )
            client.journal.apply_in(conn, retired, client.writer)
            assert protected(conn, client, frame, visible=False)["state"] == "hidden"

    work(run)
    assert rows(client, lineage_sets.TABLE) == []
    marker = rows(client, projection.TABLE)[0]
    assert projection.validate_record(marker) == frame and marker["active"] == 0
    assert projection.validate_history(rows(client, projection.HISTORY)[0]) == frame


@pytest.mark.parametrize("change", ["source", "paper"])
def test_standalone_late_input_change_rolls_back_all_projection_writes(selected, change):
    client = selected[0][1]
    frame, _originals = frame_for(selected)
    with client.journal.transaction() as conn:
        projection.initialize_in(conn)
        conn.execute("INSERT INTO kv VALUES('keep-fixture','caller work')")
        mutation = (
            "UPDATE research_file_desired SET active=0;"
            if change == "source"
            else "UPDATE research_paper_projection SET incarnation='changed-paper';"
        )
        conn.execute(
            "CREATE TRIGGER fixture_change_input AFTER INSERT ON "
            + projection.TABLE
            + " BEGIN "
            + mutation
            + " END"
        )
        before = list(conn.iterdump())
        with pytest.raises(ValueError, match="original|paper lifetime"):
            projection.write_in(conn, frame)
        assert list(conn.iterdump()) == before and conn.in_transaction


@pytest.mark.parametrize("fail", [False, True])
def test_real_source_outboxes_and_protected_science_share_one_owner_transaction(selected, fail):
    from test_lineage_peer_sources import file_counts

    client = selected[0][1]
    verified = verified_report(selected[1])  # Actual PDF work finishes before SQL.
    before = client.journal.pending()
    assert file_counts(client) == (0, 0)

    def run():
        with client.journal.transaction() as conn:
            projection.initialize_in(conn)
            frame, originals = compound(selected, connection=conn, verified=verified)
            if fail:
                conn.execute(
                    "CREATE TRIGGER fixture_compound_failure BEFORE INSERT ON "
                    + projection.TABLE
                    + " BEGIN SELECT RAISE(ABORT,'compound failure'); END"
                )
            assert protected(conn, client, frame)["state"] == "projected"
            assert len(originals) == 3
            with closing(client.journal._connect()) as outside:
                assert (
                    outside.execute("SELECT COUNT(*) FROM research_file_versions").fetchone()[0]
                    == 0
                )
            return frame

    if fail:
        with pytest.raises(sqlite3.IntegrityError, match="compound failure"):
            work(run)
        assert file_counts(client) == (0, 0)
        assert rows(client, lineage_sets.TABLE) == []
        assert client.journal.pending() == before
    else:
        frame = work(run)
        assert file_counts(client) == (3, 3)
        assert len(client.journal.pending()) == len(before) + 3
        assert rows(client, lineage_sets.TABLE)[0]["corpus_key"] == frame["content_address"]["key"]
        # This seam creates no fake Lineage journal receipt while admission is off.
        assert all(op["payload"].get("feature") != "lineage" for op in client.journal.pending())
