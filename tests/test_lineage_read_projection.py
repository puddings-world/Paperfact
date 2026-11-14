"""Real saved Lineage projects portably, read-only, with closed mobile interoperability."""

import json
import shutil
import subprocess
from contextlib import closing
from pathlib import Path

import pytest
from test_lineage_observation import work
from test_lineage_peer_sources import codec as codec
from test_lineage_peer_sources import pair as pair
from test_lineage_peer_sources import selected as selected
from test_lineage_projection import frame_for, project, rows

from paper_daily import lineage_sets, llm
from paper_daily.sync_projection import read_manifest


def saved(selected):
    client = selected[0][1]
    frame, _operations = frame_for(selected)
    work(project, client, frame)
    return client, frame


def test_exact_portable_report_and_quotes_without_sql_writes_bytes_or_model(selected, monkeypatch):
    client, frame = saved(selected)
    monkeypatch.setattr(
        llm, "complete_result", lambda *_a, **_k: pytest.fail("Saved-only projection")
    )
    before = client.journal.path.read_bytes(), client.journal.pending()
    result = read_manifest(
        client.journal.path, workspace_id=client.journal.workspace_id, schema_version=2
    )
    paper = next(p for p in result["papers"] if p["id"] == frame["parents"][0]["id"])
    assert result["required_capabilities"] == ["lineage"]
    assert paper["lineage"] == [
        dict(
            body=frame["payload"]["data"]["body_json"],
            **{
                k: frame["payload"]["data"][k]
                for k in ("source_hash", "document_hash", "written_at")
            },
        )
    ]
    assert len(paper["lineage"][0]["body"]["report"]["statements"]) == 1
    assert (client.journal.path.read_bytes(), client.journal.pending()) == before
    assert result["assets"] == [] and result["capabilities"]["sync_bootstrap"] is False


def test_legacy_projection_refuses_instead_of_silently_dropping_lineage(selected):
    client, _frame = saved(selected)
    with pytest.raises(ValueError, match="Lineage read projection requires portable"):
        read_manifest(client.journal.path, workspace_id=client.journal.workspace_id)
    assert len(rows(client, lineage_sets.TABLE)) == 1


@pytest.mark.parametrize("broken", ["body", "source-hash", "alias", "bytes", "records"])
def test_invalid_or_over_budget_projection_never_changes_saved_research(selected, broken):
    client, frame = saved(selected)
    options = {}
    with closing(client.journal._connect()) as conn, conn:
        if broken == "body":
            conn.execute("UPDATE paper_lineage_sets SET body_json='{}'")
        elif broken == "source-hash":
            conn.execute("UPDATE paper_lineage_sets SET source_hash=?", ("0" * 64,))
        elif broken == "alias":
            conn.execute(
                "DELETE FROM research_paper_identity WHERE sync_id=?", (frame["parents"][1]["id"],)
            )
        elif broken == "bytes":
            options["max_bytes"] = 100
        else:
            options["max_records"] = 3  # Three papers plus this corpus exceed the limit.
    before = client.journal.path.read_bytes()
    with pytest.raises(ValueError):
        read_manifest(
            client.journal.path,
            workspace_id=client.journal.workspace_id,
            schema_version=2,
            **options,
        )
    assert client.journal.path.read_bytes() == before


def test_python_snapshot_imports_in_actual_node_engine_without_authority_or_loss(selected):
    node = shutil.which("node")
    assert node, "Run the setup script to install the documented test toolchain"
    client, frame = saved(selected)
    snapshot = read_manifest(
        client.journal.path, workspace_id=client.journal.workspace_id, schema_version=2
    )
    script = """import assert from 'node:assert/strict';
import {pathToFileURL} from 'node:url';
import {resolve} from 'node:path';
const load=name=>import(pathToFileURL(resolve(process.argv[1],'mobile',name)));
const {Engine}=await load('engine.mjs'),{MemoryStore}=await load('store.mjs');
let raw='';for await(const part of process.stdin)raw+=part;
const snapshot=JSON.parse(raw),store=new MemoryStore(snapshot.workspace_id,'fixture-phone');
await store.update(s=>{s.drafts.note='Keep this draft';});
await new Engine(store).importProjection(snapshot);const state=await store.read();
const expected=snapshot.papers.find(p=>p.lineage);
const actual=state.readProjection.papers.find(p=>p.lineage);
assert.deepEqual(actual.lineage,expected.lineage);assert.equal(state.cursor,0);
assert.deepEqual(state.outbox,[]);assert.deepEqual(state.graph,{});assert.deepEqual(state.entities,{});
assert.equal(state.drafts.note,'Keep this draft');assert.deepEqual(state.readProjection.assets,[]);
console.log(JSON.stringify(actual.lineage));
"""
    result = subprocess.run(
        [node, "--input-type=module", "-e", script, str(Path(__file__).resolve().parents[1])],
        input=json.dumps(snapshot),
        text=True,
        encoding="utf-8",
        capture_output=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert (
        json.loads(result.stdout)[0]["body"]["report"]
        == frame["payload"]["data"]["body_json"]["report"]
    )


def test_same_named_view_cannot_bypass_lineage_record_budget_or_mutate_saved_rows(selected):
    client, _frame = saved(selected)
    with closing(client.journal._connect()) as conn, conn:
        conn.execute("ALTER TABLE paper_lineage_sets RENAME TO fixture_saved_lineage")
        conn.execute("CREATE VIEW paper_lineage_sets AS SELECT * FROM fixture_saved_lineage")
    before = client.journal.path.read_bytes()
    with pytest.raises(ValueError, match="stored research table"):
        read_manifest(
            client.journal.path,
            workspace_id=client.journal.workspace_id,
            schema_version=2,
            max_records=3,
        )
    assert client.journal.path.read_bytes() == before
    with closing(client.journal._connect()) as conn:
        assert conn.execute("SELECT count(*) FROM fixture_saved_lineage").fetchone()[0] == 1
