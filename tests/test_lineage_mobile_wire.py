"""Mobile consumes real native staged Lineage bytes without enabling server admission."""

import copy
import json
import shutil
import subprocess
from contextlib import closing
from pathlib import Path

import pytest
from test_lineage_peer_sources import codec as codec
from test_lineage_peer_sources import pair as pair
from test_lineage_peer_sources import selected as selected
from test_lineage_projection import frame_for

from paper_daily import lineage_dependencies
from paper_daily.sync_journal import canonical_operation

ROOT = Path(__file__).resolve().parents[1]


def node(data, program):
    executable = shutil.which("node")
    assert executable, "Install the documented Node.js toolchain before this integration test"
    result = subprocess.run(
        [executable, "--input-type=module", "-e", program],
        cwd=ROOT,
        input=json.dumps(data),
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return json.loads(result.stdout)


def test_real_three_original_native_frame_reaches_mobile_projection_without_source_activation(
    selected,
):
    frame, sources = frame_for(selected)
    lineage_dependencies.canonical_operation(frame)
    assert json.loads(canonical_operation(frame)) == frame
    client = selected[0][1]
    with closing(client.journal._connect()) as conn:
        papers = [
            json.loads(row[0])
            for row in conn.execute(
                "SELECT envelope FROM paperfact_sync_operations "
                "WHERE entity_type='paper' ORDER BY sequence"
            )
        ]
    result = node(
        dict(frame=frame, prefix=[*papers, *sources.values()]),
        """
import {readFileSync} from 'node:fs';
import {validateOperation,receive,projection} from './mobile/domain.mjs';
import {emptyState} from './mobile/store.mjs';
const {frame,prefix}=JSON.parse(readFileSync(0,'utf8'));
const state=emptyState(frame.workspace_id,'phone');
const event=(operation,i)=>({sequence:i+1,outcome:'accepted',operation,
 head:{revision:i+1,operation}});
validateOperation(frame,frame.workspace_id);
receive(state,[...prefix,frame].map(event));
const view=projection(state),paper=view.papers.find(p=>p.id===frame.parents[0].id);
console.log(JSON.stringify({row:paper.lineage[0],cursor:state.cursor,files:state.files,
 artifacts:state.artifactFiles,outbox:state.outbox,originals:view.original_sources}));
""",
    )
    expected = frame["payload"]["data"]
    assert result["row"] == dict(
        body=expected["body_json"],
        **{name: expected[name] for name in ("source_hash", "document_hash", "written_at")},
    )
    assert result["cursor"] == len(papers) + len(sources) + 1
    assert len(result["originals"]) == 3
    assert result["files"] == result["artifacts"] == {} and result["outbox"] == []


def test_native_multiple_peer_pin_mutations_have_matching_mobile_rejection(selected):
    frame, _sources = frame_for(selected)
    cases = []
    for field in ("source_id", "paper_id", "file_id", "incarnation"):
        changed = copy.deepcopy(frame)
        changed["source_dependencies"][1][field] = "invalid value"
        cases.append(changed)
    changed = copy.deepcopy(frame)
    changed["source_dependencies"].reverse()
    cases.append(changed)
    changed = copy.deepcopy(frame)
    changed["parents"].reverse()
    cases.append(changed)
    for value in cases:
        with pytest.raises(ValueError):
            lineage_dependencies.canonical_operation(value)
    result = node(
        dict(cases=cases),
        """
import {readFileSync} from 'node:fs';
import {validateOperation} from './mobile/domain.mjs';
const {cases}=JSON.parse(readFileSync(0,'utf8'));
console.log(JSON.stringify(cases.map(op=>{
 try{validateOperation(op,op.workspace_id);return true;}catch{return false;}
})));
""",
    )
    assert result == [False] * len(cases)
