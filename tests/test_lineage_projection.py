"""Unregistered metadata projection uses real fixture peers without live admission."""

import copy
import json
import sqlite3
from contextlib import closing
from uuid import uuid4

import pytest
from test_lineage_dependencies import compound
from test_lineage_observation import work
from test_lineage_peer_sources import codec as codec
from test_lineage_peer_sources import pair as pair
from test_lineage_peer_sources import selected as selected
from test_sync_files import drain

from paper_daily import (
    lineage_dependencies,
    lineage_projection,
    lineage_sets,
    lineage_wire,
    research_lineage,
    sync_content,
)
from paper_daily.sync_journal import canonical_operation as live_canonical


class CallerRollback(RuntimeError):
    """Fixture caller abort, using the journal's documented transaction contract."""


def verified_report(corpus):
    return work(
        research_lineage.verify_snapshot,
        corpus,
        dict(
            format=research_lineage.PROPOSALS,
            focal=corpus.focal,
            statements=[
                dict(
                    stage="current_change",
                    subject=corpus.focal,
                    text="The focal original contains the supplied fixture observation.",
                    function="unresolved",
                    judgment=dict(
                        status="unresolved", reason="No independent semantic validation."
                    ),
                    passages=[
                        dict(
                            source_id=corpus.focal,
                            role="change_evidence",
                            cites=None,
                            quote="Actual selected original 0.",
                            page=1,
                            anchor=None,
                        )
                    ],
                )
            ],
        ),
    )


def frame_for(selected):
    frame, operations = work(compound, selected)
    report = verified_report(selected[1])
    body = frame["payload"]["data"]["body_json"]
    body["report"] = report
    frame["payload"]["data"]["source_hash"] = lineage_sets.source_hash(body)
    lineage_dependencies.canonical_operation(frame)
    return frame, operations


def project(client, frame, *, visible=True, rollback=False):
    with client.journal.transaction() as conn:
        lineage_projection.initialize_in(conn)
        result = lineage_projection.write_in(conn, frame, visible=visible)
        if rollback:
            raise CallerRollback("fixture caller rollback")
        return result


def rows(client, table):
    with closing(client.journal._connect()) as conn:
        if not conn.execute("SELECT 1 FROM sqlite_master WHERE name=?", (table,)).fetchone():
            return []
        return [dict(r) for r in conn.execute("SELECT * FROM " + table)]


def test_staged_projection_preserves_report_pins_without_runtime_registration(
    selected,
):
    client = selected[0][1]
    frame, _operations = frame_for(selected)
    pending = client.journal.pending()
    with closing(client.journal._connect()) as conn:
        before = conn.execute("SELECT sequence FROM paperfact_sync_cursor WHERE id=1").fetchone()[0]
    assert work(project, client, frame)["state"] == "projected"
    assert work(project, client, frame)["state"] == "projected"
    saved = rows(client, lineage_sets.TABLE)
    markers = rows(client, lineage_projection.TABLE)
    assert len(saved) == len(markers) == 1 and markers[0]["active"] == 1
    body = json.loads(saved[0]["body_json"])
    assert body["report"] == frame["payload"]["data"]["body_json"]["report"]
    assert len(body["report"]["statements"]) == 1
    assert body["report"]["statements"][0]["passages"][0]["location"]["state"] == "located"
    assert lineage_projection.validate_record(markers[0]) == frame
    assert client.journal.pending() == pending and "lineage" not in sync_content.FEATURES
    with closing(client.journal._connect()) as conn:
        assert (
            conn.execute("SELECT sequence FROM paperfact_sync_cursor WHERE id=1").fetchone()[0]
            == before
        )
    assert json.loads(live_canonical(frame)) == frame


def test_second_fixture_peer_maps_existing_owners_without_minting_source_grants(selected):
    service, client, peer, files, _peer_files, token, peer_token = selected[0]
    frame, operations = frame_for(selected)
    for operation in operations.values():
        drain(lambda operation=operation: files.upload(operation), "uploaded")
    client.sync_once(service, token, prepare_push=files.ready_to_push)
    peer.sync_once(service, peer_token)
    pending = peer.journal.pending()
    work(project, peer, frame)
    saved = rows(peer, lineage_sets.TABLE)[0]
    with closing(peer.journal._connect()) as conn:
        expected = {
            r[0]: r[1] for r in conn.execute("SELECT sync_id,local_id FROM research_paper_identity")
        }
        assert not conn.execute(
            "SELECT 1 FROM sqlite_master WHERE name='research_local_source_owners'"
        ).fetchone()
    body = json.loads(saved["body_json"])
    assert [b["paper_id"] for b in body["bindings"]] == [
        expected[p["id"]] for p in frame["parents"]
    ]
    assert body["report"] == frame["payload"]["data"]["body_json"]["report"]
    assert saved["paper_id"] == expected[frame["parents"][0]["id"]]
    assert peer.journal.pending() == pending
    assert not (peer.journal.path.parent / ".paperfact-source-snapshots").exists()


def test_caller_rollback_keeps_no_projection_and_retry_commits_once(selected):
    client = selected[0][1]
    frame, _operations = frame_for(selected)
    with pytest.raises(CallerRollback, match="fixture caller rollback"):
        work(project, client, frame, rollback=True)
    assert rows(client, lineage_sets.TABLE) == [] and rows(client, lineage_projection.TABLE) == []
    work(project, client, frame)
    assert len(rows(client, lineage_sets.TABLE)) == len(rows(client, lineage_projection.TABLE)) == 1


def test_mid_projection_failure_preserves_caller_changes_and_can_retry(selected):
    client = selected[0][1]
    frame, _operations = frame_for(selected)

    def fail():
        with client.journal.transaction() as conn:
            lineage_projection.initialize_in(conn)
            local = conn.execute(
                "SELECT local_id FROM research_paper_identity WHERE sync_id=?",
                (frame["parents"][0]["id"],),
            ).fetchone()[0]
            conn.execute("UPDATE papers SET venue='caller work' WHERE id=?", (local,))
            conn.execute(
                "CREATE TRIGGER fail_lineage_marker BEFORE INSERT ON research_lineage_sync_sources "
                "BEGIN SELECT RAISE(ABORT, 'fixture marker failure'); END"
            )
            with pytest.raises(sqlite3.IntegrityError, match="fixture marker failure"):
                lineage_projection.write_in(conn, frame)

    work(fail)
    assert rows(client, lineage_sets.TABLE) == [] and rows(client, lineage_projection.TABLE) == []
    with client.journal.transaction() as conn:
        assert conn.execute("SELECT 1 FROM papers WHERE venue='caller work'").fetchone()
        conn.execute("DROP TRIGGER fail_lineage_marker")
    work(project, client, frame)
    assert len(rows(client, lineage_sets.TABLE)) == len(rows(client, lineage_projection.TABLE)) == 1


@pytest.mark.parametrize(
    "changed", ["workspace", "parent", "missing-mapping", "missing-pins", "visibility"]
)
def test_invalid_context_leaves_no_partial_projection(selected, changed):
    client = selected[0][1]
    frame, _operations = frame_for(selected)
    before = client.journal.pending()

    def reject():
        with client.journal.transaction() as conn:
            lineage_projection.initialize_in(conn)
            visible = True
            if changed == "workspace":
                frame["workspace_id"] = "different-workspace"
            elif changed == "parent":
                conn.execute(
                    "UPDATE research_paper_projection SET incarnation='different-life' "
                    "WHERE sync_id=?",
                    (frame["parents"][1]["id"],),
                )
            elif changed == "missing-mapping":
                conn.execute(
                    "DELETE FROM research_paper_identity WHERE sync_id=?",
                    (frame["parents"][1]["id"],),
                )
            elif changed == "missing-pins":
                frame.pop("source_dependencies")
            else:
                visible = 1
            with pytest.raises(ValueError):
                lineage_projection.write_in(conn, frame, visible=visible)
            assert not conn.execute("SELECT 1 FROM paper_lineage_sets").fetchone()
            assert not conn.execute("SELECT 1 FROM research_lineage_sync_sources").fetchone()
            raise CallerRollback("fixture context rollback")

    with pytest.raises(CallerRollback, match="fixture context rollback"):
        work(reject)
    assert client.journal.pending() == before


def test_existing_unowned_report_is_never_overwritten_even_when_scientifically_equal(selected):
    client = selected[0][1]
    frame, _operations = frame_for(selected)

    def unowned():
        with client.journal.transaction() as conn:
            lineage_projection.initialize_in(conn)
            old = lineage_wire.decode_row(conn, frame["payload"])
            old["body_json"] = json.dumps(json.loads(old["body_json"]), indent=2)
            conn.execute(
                "INSERT INTO paper_lineage_sets VALUES(?,?,?,?,?,?)",
                tuple(old[name] for name in lineage_sets.COLUMNS.split()),
            )
            with pytest.raises(ValueError, match="unowned Lineage"):
                lineage_projection.write_in(conn, frame)
            assert (
                conn.execute("SELECT body_json FROM paper_lineage_sets").fetchone()[0]
                == old["body_json"]
            )

    work(unowned)
    assert (
        len(rows(client, lineage_sets.TABLE)) == 1 and rows(client, lineage_projection.TABLE) == []
    )


def test_hidden_projection_preserves_put_provenance_and_reappears_without_new_operations(selected):
    client = selected[0][1]
    frame, _operations = frame_for(selected)
    pending = client.journal.pending()
    work(project, client, frame)
    work(project, client, frame, visible=False)
    assert rows(client, lineage_sets.TABLE) == []
    marker = rows(client, lineage_projection.TABLE)[0]
    assert marker["active"] == 0 and lineage_projection.validate_record(marker) == frame
    work(project, client, frame)
    assert len(rows(client, lineage_sets.TABLE)) == 1
    assert client.journal.pending() == pending


def test_retirement_retains_known_key_and_old_epoch_cannot_remove_restored_report(selected):
    client = selected[0][1]
    frame, _operations = frame_for(selected)
    work(project, client, frame)
    retired = dict(
        frame, operation_id=str(uuid4()), action="delete", payload={}, source_dependencies=[]
    )
    work(project, client, retired)
    assert rows(client, lineage_sets.TABLE) == []
    marker = rows(client, lineage_projection.TABLE)[0]
    assert marker["corpus_key"] == frame["content_address"]["key"] and marker["active"] == 0
    restored = copy.deepcopy(frame)
    restored["operation_id"] = restored["incarnation"] = str(uuid4())
    work(project, client, restored)
    assert work(project, client, retired)["state"] == "ignored_stale_retirement"
    assert len(rows(client, lineage_sets.TABLE)) == 1
    assert lineage_projection.validate_record(rows(client, lineage_projection.TABLE)[0]) == restored


def test_initialization_and_projection_do_not_create_a_transaction(selected):
    client = selected[0][1]
    frame, _operations = frame_for(selected)

    def reject():
        with closing(client.journal._connect()) as conn:
            assert not conn.in_transaction
            with pytest.raises(ValueError, match="caller transaction"):
                lineage_projection.initialize_in(conn)
            with pytest.raises(ValueError, match="caller transaction"):
                lineage_projection.write_in(conn, frame)
            assert not conn.in_transaction

    work(reject)
    assert rows(client, lineage_projection.TABLE) == []


def test_known_corpus_cannot_reorder_selected_papers_or_replace_its_source_scope(selected):
    client = selected[0][1]
    frame, _operations = frame_for(selected)
    work(project, client, frame)
    before = rows(client, lineage_sets.TABLE), rows(client, lineage_projection.TABLE)
    changed = copy.deepcopy(frame)
    changed["operation_id"] = str(uuid4())
    body = changed["payload"]["data"]["body_json"]
    body["bindings"][1], body["bindings"][2] = body["bindings"][2], body["bindings"][1]
    original = selected[1]
    local = [p["local_id"] for p in json.loads(original._json)["observed"]]
    reordered = work(
        research_lineage.capture,
        client.journal.path,
        local[0],
        [local[2], local[1]],
        legacy_root=original._documents[0].path.parent,
    )
    body["report"] = verified_report(reordered)
    changed["parents"][1], changed["parents"][2] = changed["parents"][2], changed["parents"][1]
    pins = changed["source_dependencies"]
    pins[1], pins[2] = pins[2], pins[1]
    changed["payload"]["data"]["source_hash"] = lineage_sets.source_hash(body)
    lineage_dependencies.canonical_operation(changed)
    with pytest.raises(ValueError, match="cannot move its known corpus/source owners"):
        work(project, client, changed)
    assert (rows(client, lineage_sets.TABLE), rows(client, lineage_projection.TABLE)) == before


@pytest.mark.parametrize("external", ["edit", "delete", "hidden-unowned-insert"])
def test_external_content_changes_are_preserved_instead_of_overwritten_or_resurrected(
    selected, external
):
    client = selected[0][1]
    frame, _operations = frame_for(selected)
    work(project, client, frame)
    if external == "hidden-unowned-insert":
        work(project, client, frame, visible=False)
    with client.journal.transaction() as conn:
        if external == "edit":
            conn.execute("UPDATE paper_lineage_sets SET written_at='2026-11-12T00:00:00+00:00'")
        elif external == "delete":
            conn.execute("DELETE FROM paper_lineage_sets")
        else:
            own = lineage_wire.decode_row(conn, frame["payload"])
            own["body_json"] = json.dumps(json.loads(own["body_json"]), indent=2)
            conn.execute(
                "INSERT INTO paper_lineage_sets VALUES(?,?,?,?,?,?)",
                tuple(own[name] for name in lineage_sets.COLUMNS.split()),
            )
    before = rows(client, lineage_sets.TABLE), rows(client, lineage_projection.TABLE)
    with pytest.raises(ValueError, match="changed outside its projection"):
        work(project, client, frame)
    assert (rows(client, lineage_sets.TABLE), rows(client, lineage_projection.TABLE)) == before
