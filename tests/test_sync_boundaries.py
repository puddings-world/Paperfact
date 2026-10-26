"""The sync library must not implicitly activate the application or its AI accounts."""

import json
import os
import subprocess
import sys
from pathlib import Path


def test_importing_sync_modules_never_initializes_default_research_or_ai(tmp_path):
    source = Path(__file__).resolve().parents[1] / "src"
    default_workspace = tmp_path / "must-not-be-created"
    code = """
import importlib
import json
import socket
import sys

def denied_network(*args, **kwargs):
    raise AssertionError('Sync import attempted a network connection')

socket.create_connection = denied_network
for name in ('sync_journal', 'sync_research', 'sync_service', 'sync_client',
             'sync_blobs', 'sync_http', 'sync_projection', 'sync_schema_v2',
             'sync_graph', 'sync_operations', 'sync_ordering'):
    importlib.import_module('paper_daily.' + name)
forbidden = {'paper_daily.config', 'paper_daily.store', 'paper_daily.llm',
             'paper_daily.ai_accounts', 'paper_daily.feedback'}
print(json.dumps(sorted(forbidden.intersection(sys.modules))))
"""
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=tmp_path,
        env={
            **os.environ,
            "PYTHONPATH": str(source),
            "PAPERFACT_DATA": str(default_workspace),
            "PAPER_DAILY_DATA": str(default_workspace),
        },
        text=True,
        capture_output=True,
        timeout=20,
        check=True,
    )
    assert json.loads(result.stdout) == []
    assert not default_workspace.exists()
