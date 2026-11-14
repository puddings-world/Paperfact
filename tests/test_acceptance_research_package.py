"""Real synthetic package/import/audit/export; no providers, native apps or private data."""

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "verify_fixture", ROOT / "scripts/verify_built_app.py"
)
verify = importlib.util.module_from_spec(spec)
spec.loader.exec_module(verify)
compare_files, isolated_env = verify.compare_files, verify.isolated_env

SEED = """
import sys
sys.path.insert(0, 'scripts')
import demo_workspace
from pathlib import Path
from paper_daily import llm
import httpx

def forbidden(*args, **kwargs):
    raise AssertionError('No network or provider during synthetic acceptance')

llm.complete_result = forbidden
httpx.Client.request = forbidden
manifest = demo_workspace.acceptance_package(Path(sys.argv[1]))
print(manifest['counts']['files'])
"""


def child(code, env, *args):
    return subprocess.run(
        [sys.executable, "-c", code, *map(str, args)],
        cwd=ROOT,
        env={**env, "PYTHONPATH": str(ROOT / "src")},
        text=True,
        encoding="utf-8",
        capture_output=True,
        timeout=45,
    )


def test_real_acceptance_package_imports_all_sources_and_roundtrips_without_ai(tmp_path):
    original, returned = tmp_path / "synthetic.zip", tmp_path / "returned.zip"
    sender = isolated_env(tmp_path / "sender")
    made = child(SEED, sender, original)
    assert made.returncode == 0, made.stderr
    assert made.stdout.strip() == "4"
    recipient = isolated_env(tmp_path / "recipient")
    code = """
import json
import sys
from pathlib import Path
from paper_daily import bundle, lineage_sets, store
store.init_db()
bundle.import_(Path(sys.argv[1]))
bundle.import_(Path(sys.argv[1]))
rows = lineage_sets.saved(store.DB_PATH, 'demo:paperfact')
assert len(rows) == 1
assert lineage_sets.decode(rows[0]['body_json'])['generation']['backend'] == 'synthetic-fixture'
with store.connect() as conn:
    assert conn.execute('SELECT count(*) FROM list_papers').fetchone()[0] == 1
bundle.export('demo', Path(sys.argv[2]))
print(json.dumps(dict(paper_id='demo:paperfact', corpus_key=rows[0]['corpus_key'])))
"""
    result = child(code, recipient, original, returned)
    assert result.returncode == 0, result.stderr
    arguments = tmp_path / "audit-input.json"
    arguments.write_text(result.stdout, encoding="utf-8")
    audited = subprocess.run(
        [
            sys.executable,
            "-m",
            "paper_daily",
            "integration",
            "analysis.audit",
            "--workspace",
            recipient["PAPERFACT_DATA"],
            "--file",
            str(arguments),
        ],
        cwd=ROOT,
        env={**recipient, "PYTHONPATH": str(ROOT / "src")},
        text=True,
        encoding="utf-8",
        capture_output=True,
        timeout=45,
    )
    assert audited.returncode == 0, audited.stderr
    response = json.loads(audited.stdout)
    assert response["ok"]
    report = response["result"]
    assert report["originals_checked"] == report["originals_total"] == 3
    checks = [
        check
        for source in report["sources"]
        for check in source["report"]["checks"]
        if check["rule"] == "quote_location"
    ]
    assert len(checks) == 5 and all(check["state"] == "located" for check in checks)
    assert report["semantics"] == "not_checked"
    assert compare_files(original, returned) == 4
    for env in (sender, recipient):
        assert not (Path(env["PAPERFACT_DATA"]) / "llm.json").exists()


@pytest.mark.parametrize("blocked", ["workspace", "output", "unspecified"])
def test_fixture_guard_never_overwrites_existing_work_or_uses_default_data(tmp_path, blocked):
    env = isolated_env(tmp_path / "fixture")
    workspace = Path(env["PAPERFACT_DATA"])
    output = tmp_path / "synthetic.zip"
    if blocked == "workspace":
        workspace.mkdir()
        (workspace / "keep.txt").write_bytes(b"existing research")
    elif blocked == "output":
        output.write_bytes(b"previous package")
    else:
        env.pop("PAPERFACT_DATA")
    result = child(SEED, env, output)
    assert result.returncode != 0 and "ValueError" in result.stderr
    if blocked == "workspace":
        assert (workspace / "keep.txt").read_bytes() == b"existing research"
        assert list(workspace.iterdir()) == [workspace / "keep.txt"]
    else:
        assert not workspace.exists()
    if blocked == "output":
        assert output.read_bytes() == b"previous package"
    else:
        assert not output.exists()
