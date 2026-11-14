"""Importing helpers has no new registry, database, model or transport effect."""

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_fresh_helper_import_preserves_registered_ai_task_and_all_inactive_storage_boundaries(
    tmp_path,
):
    code = r"""
import importlib,json,os,socket,subprocess
from pathlib import Path
from paper_daily import ai_profiles,research_generation,store,sync_content
from paper_daily.sync_schema_v2 import OPTIONAL
from paper_daily import llm

def snapshot():
    return {
        'tasks': sorted(ai_profiles.TASKS),
        'features': sorted(sync_content.FEATURES),
        'producers': sorted(research_generation.REGISTRY),
        'schema': store.SCHEMA,
        'optional': sorted(OPTIONAL),
    }

attempts=[]
def forbidden(*args,**kwargs):
    attempts.append(True)
    raise AssertionError('Helper import must not start transport/model/process work')

llm.complete_result=forbidden
socket.socket.connect=forbidden
socket.getaddrinfo=forbidden
subprocess.Popen=forbidden
before=snapshot()
assert 'lineage' in before['tasks']
assert 'lineage' not in before['features']
assert 'paper_lineage_sets' not in before['producers']
assert 'paper_lineage_sets' not in before['schema']
assert 'content_address' not in before['optional']
for name in (
    'lineage_address','lineage_wire','lineage_dependencies','lineage_projection',
    'lineage_package_native','lineage_package_targets','lineage_direct_adoption',
    'desktop.lineage_adoption_action',
):
    importlib.import_module('paper_daily.'+name)
assert snapshot()==before
assert attempts==[]
assert not Path(os.environ['PAPERFACT_DATA']).exists()
assert Path(store.__file__).resolve().is_relative_to(Path(os.environ['PYTHONPATH']).resolve())
print(json.dumps({'registered_task_preserved':True,'registries_unchanged':True,
                  'default_workspace_created':False,'transport_or_model_started':False}))
"""
    child = subprocess.run(
        [sys.executable, "-c", code],
        cwd=tmp_path,
        env={
            **os.environ,
            "PYTHONPATH": str(ROOT / "src"),
            "PAPERFACT_DATA": str(tmp_path / "unused-workspace"),
            "PYTHONUTF8": "1",
        },
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
    )
    assert child.returncode == 0, child.stderr
    assert json.loads(child.stdout) == {
        "registered_task_preserved": True,
        "registries_unchanged": True,
        "default_workspace_created": False,
        "transport_or_model_started": False,
    }
