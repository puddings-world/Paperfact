"""Real detached backups preserve staged bound Lineage without replay/source grants."""

import copy
import hashlib
import json
import sqlite3
import zipfile
from contextlib import closing
from uuid import uuid4

import pytest
from test_lineage_observation import work
from test_lineage_peer_sources import codec as codec
from test_lineage_peer_sources import pair as pair
from test_lineage_peer_sources import selected as selected
from test_lineage_projection import frame_for, project, rows
from test_sync_recovery import archive_rows, rewrite

from paper_daily import lineage_projection, lineage_sets, sync_recovery


def test_real_bound_projection_backup_restores_science_and_archives_authority_only(
    selected, tmp_path
):
    client = selected[0][1]
    frame, _operations = frame_for(selected)
    work(project, client, frame)
    expected = rows(client, lineage_sets.TABLE)
    output = tmp_path / "bound.zip"
    manifest = sync_recovery.create(client.journal.path, output, blob_store=selected[0][3].store)
    assert sync_recovery.inspect(output) == manifest
    assert archive_rows(output, lineage_sets.TABLE) == expected
    assert archive_rows(output, lineage_projection.TABLE) == rows(client, lineage_projection.TABLE)
    target = tmp_path / "detached"
    sync_recovery.restore_detached(output, target)
    assert lineage_sets.saved(target / "papers.db", expected[0]["paper_id"]) == expected
    with closing(sqlite3.connect(target / "papers.db")) as conn:
        assert not conn.execute(
            "SELECT 1 FROM sqlite_master WHERE name IN "
            "('research_lineage_sync_sources','paperfact_sync_identity','research_sync_binding')"
        ).fetchall()
        archived = [
            json.loads(row[0])
            for row in conn.execute(
                "SELECT data FROM recovery_records WHERE table_name='research_lineage_sync_sources'"
            )
        ]
    assert archived == rows(client, lineage_projection.TABLE)
    assert {s["document_hash"] for s in selected[1].sources} <= {
        blob["sha256"] for blob in manifest["blobs"]
    }


@pytest.mark.parametrize("state", ["hidden", "retired", "restored-original"])
def test_hidden_or_retired_reports_keep_scientific_history_and_exact_originals(
    selected, tmp_path, state
):
    client = selected[0][1]
    frame, operations = frame_for(selected)
    work(project, client, frame)
    if state == "retired":
        retired = dict(
            frame, operation_id=str(uuid4()), action="delete", payload={}, source_dependencies=[]
        )
        work(project, client, retired)
    else:
        work(project, client, frame, visible=False)
    if state == "restored-original":
        old = next(iter(operations.values()))
        with client.journal.transaction() as conn:
            deleted = client.new_graph_operation_in(
                conn, "research_file", old["entity_id"], {}, action="delete"
            )
            client.journal.apply_in(conn, deleted, client.writer)
            restored = client.new_graph_operation_in(
                conn, "research_file", old["entity_id"], old["payload"], restore=True
            )
            client.journal.apply_in(conn, restored, client.writer)
            assert old["incarnation"] != restored["incarnation"]
    output = tmp_path / "history.zip"
    manifest = sync_recovery.create(client.journal.path, output, blob_store=selected[0][3].store)
    assert sync_recovery.inspect(output) == manifest
    assert archive_rows(output, lineage_sets.TABLE) == []
    history = archive_rows(output, lineage_projection.HISTORY)
    assert frame in [lineage_projection.validate_history(row) for row in history]
    assert len(history) == (2 if state == "retired" else 1)
    target = tmp_path / "history-detached"
    sync_recovery.restore_detached(output, target)
    assert lineage_sets.saved(target / "papers.db", frame["payload"]["scope"]["id"]) == []
    with closing(sqlite3.connect(target / "papers.db")) as conn:
        archived = [
            json.loads(r[0])
            for r in conn.execute(
                "SELECT data FROM recovery_records WHERE table_name=? ORDER BY row_number",
                (lineage_projection.HISTORY,),
            )
        ]
        assert not conn.execute(
            "SELECT 1 FROM sqlite_master WHERE name=?", (lineage_projection.HISTORY,)
        ).fetchone()
    assert archived == history
    with zipfile.ZipFile(output) as archive:
        for index, source in enumerate(selected[1].sources):
            assert archive.read("objects/" + source["document_hash"]) == (
                selected[1]._documents[index].path.read_bytes()
            )


def rewrite_table(manifest, files, name, transform):
    table = next(row for row in manifest["tables"] if row["name"] == name)
    path = "tables/" + name + ".jsonl"
    data = [json.loads(line) for line in files[path].splitlines()]
    data = transform(data)
    files[path] = b"".join((json.dumps(row) + "\n").encode() for row in data)
    table.update(
        count=len(data), size=len(files[path]), sha256=hashlib.sha256(files[path]).hexdigest()
    )


@pytest.mark.parametrize(
    "broken",
    ["history", "marker", "file-version", "pin", "alias", "row", "current-receipt", "fingerprint"],
)
def test_valid_container_hashes_cannot_hide_broken_lineage_source_history_closure(
    selected, tmp_path, broken
):
    client = selected[0][1]
    frame, _operations = frame_for(selected)
    work(project, client, frame)
    original = tmp_path / "complete.zip"
    sync_recovery.create(client.journal.path, original, blob_store=selected[0][3].store)

    def mutate(manifest, files):
        def update(name, transform):
            rewrite_table(manifest, files, name, transform)

        if broken == "history":
            update(lineage_projection.HISTORY, lambda rows: [])
        elif broken == "marker":
            update(lineage_projection.TABLE, lambda rows: [])
        elif broken == "file-version":
            identity = frame["source_dependencies"][0]["file_id"]
            update(
                "research_file_versions",
                lambda rows: [r for r in rows if r["entity_id"] != identity],
            )
        elif broken == "fingerprint":
            update(
                lineage_projection.TABLE,
                lambda rows: [{**row, "fingerprint": "0" * 64} for row in rows],
            )
        elif broken == "current-receipt":

            def change_identity(rows):
                changed = copy.deepcopy(rows)
                for row in changed:
                    operation = json.loads(row["operation_json"])
                    row["operation_id"] = operation["operation_id"] = str(uuid4())
                    from paper_daily.lineage_dependencies import canonical_operation

                    row["operation_json"] = canonical_operation(operation)
                return changed

            update(lineage_projection.HISTORY, change_identity)
        elif broken == "pin":
            changed = copy.deepcopy(frame)
            changed["source_dependencies"][0]["incarnation"] = str(uuid4())
            encoded = json.dumps(changed, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            for name in (lineage_projection.HISTORY, lineage_projection.TABLE):
                update(name, lambda rows: [{**row, "operation_json": encoded} for row in rows])
        elif broken == "alias":
            identity = frame["parents"][1]["id"]
            update(
                "research_paper_identity",
                lambda rows: [r for r in rows if r["sync_id"] != identity],
            )
        else:
            update(
                lineage_sets.TABLE,
                lambda rows: [{**row, "written_at": "2026-11-13T01:00:00+00:00"} for row in rows],
            )

    damaged = rewrite(original, tmp_path / "damaged.zip", mutate)
    with pytest.raises(ValueError, match="Lineage"):
        sync_recovery.inspect(damaged)
    target = tmp_path / "must-not-restore"
    with pytest.raises(ValueError, match="Lineage"):
        sync_recovery.restore_detached(damaged, target)
    assert not target.exists()


def test_missing_original_bytes_refuses_complete_backup_without_partial_output(selected, tmp_path):
    from paper_daily.sync_blobs import BlobManifest

    client = selected[0][1]
    frame, operations = frame_for(selected)
    work(project, client, frame)
    asset = next(iter(operations.values()))["payload"]["assets"][0]
    store = selected[0][3].store
    store.verified_path(BlobManifest(asset["sha256"], asset["size"])).unlink()
    output = tmp_path / "missing.zip"
    with pytest.raises((ValueError, OSError)):
        sync_recovery.create(client.journal.path, output, blob_store=store)
    assert not output.exists()
    assert len(rows(client, lineage_sets.TABLE)) == 1


def refreshed(selected):
    from paper_daily import lineage_observation, lineage_peer_sources, research_lineage

    peers, previous, _observed, _prepared = selected
    client, files = peers[1], peers[3]
    local = [p["local_id"] for p in json.loads(previous._json)["observed"]]
    captured = work(
        research_lineage.capture,
        client.journal.path,
        local[0],
        local[1:],
        legacy_root=previous._documents[0].path.parent,
    )
    observation = work(lineage_observation.observe, captured, str(uuid4()), str(uuid4()))
    prepared = work(
        lineage_peer_sources.prepare,
        observation,
        store=files.store,
        version_root=files.root,
        client=client,
    )
    return peers, captured, observation, prepared


def test_older_scientific_report_and_source_bytes_survive_new_focal_original(selected, tmp_path):
    from test_research_evidence import pdf

    client = selected[0][1]
    first, _operations = frame_for(selected)
    work(project, client, first)
    old_source = selected[1].sources[0]["document_hash"]
    pdf(selected[1]._documents[0].path, [["Actual selected original 0. Revised fixture version."]])
    revised = refreshed(selected)
    second, _operations = frame_for(revised)
    # Model an incoming typed update, not native permission to publish an existing
    # unregistered target. Fresh sources/report were prepared for an absent corpus;
    # live admission continues to refuse this staged frame.
    from paper_daily import lineage_dependencies
    from paper_daily.sync_journal import canonical_operation as live_canonical

    key = first["payload"]["key"]
    second["payload"]["key"] = second["content_address"]["key"] = key
    second["payload"]["data"]["body_json"]["corpus_id"] = key
    second["payload"]["data"]["source_hash"] = lineage_sets.source_hash(
        second["payload"]["data"]["body_json"]
    )
    second["entity_id"] = first["entity_id"]
    lineage_dependencies.canonical_operation(second)
    assert json.loads(live_canonical(second)) == second
    assert second["payload"]["key"] == first["payload"]["key"]
    assert second["payload"]["source_document_hash"] != old_source
    work(project, client, second)
    output = tmp_path / "two-versions.zip"
    manifest = sync_recovery.create(client.journal.path, output, blob_store=selected[0][3].store)
    assert sync_recovery.inspect(output) == manifest
    history = archive_rows(output, lineage_projection.HISTORY)
    assert {row["operation_id"] for row in history} == {
        first["operation_id"],
        second["operation_id"],
    }
    with zipfile.ZipFile(output) as archive:
        assert archive.read("objects/" + old_source) != archive.read(
            "objects/" + second["payload"]["source_document_hash"]
        )
    target = tmp_path / "two-versions-detached"
    sync_recovery.restore_detached(output, target)
    canonical = rows(client, lineage_sets.TABLE)
    assert lineage_sets.saved(target / "papers.db", canonical[0]["paper_id"]) == canonical
    assert canonical[0]["document_hash"] == second["payload"]["source_document_hash"]


def test_equal_original_bytes_keep_separate_selected_paper_and_file_incarnations(
    selected, tmp_path
):
    import shutil

    shutil.copyfile(selected[1]._documents[1].path, selected[1]._documents[2].path)
    same_bytes = refreshed(selected)
    frame, operations = frame_for(same_bytes)
    work(project, selected[0][1], frame)
    sources = same_bytes[1].sources
    assert sources[1]["document_hash"] == sources[2]["document_hash"]
    pins = frame["source_dependencies"]
    assert pins[1]["paper_id"] != pins[2]["paper_id"]
    assert pins[1]["file_id"] != pins[2]["file_id"]
    assert operations[sources[1]["id"]]["entity_id"] != operations[sources[2]["id"]]["entity_id"]
    output = tmp_path / "same-bytes.zip"
    manifest = sync_recovery.create(
        selected[0][1].journal.path, output, blob_store=selected[0][3].store
    )
    assert sync_recovery.inspect(output) == manifest
    assert len(archive_rows(output, "research_file_versions")) == 3
    assert sum(b["sha256"] == sources[1]["document_hash"] for b in manifest["blobs"]) == 1
