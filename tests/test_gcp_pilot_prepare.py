"""Offline pilot preparation renders reviewed inputs without cloud or host changes."""

import importlib.util
import json
import math
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
TEMPLATES = ROOT / "deploy" / "gcp"
spec = importlib.util.spec_from_file_location("gcp_pilot_prepare", TEMPLATES / "prepare.py")
pilot = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pilot)


@pytest.fixture
def config(tmp_path):
    value = json.loads((TEMPLATES / "pilot.example.json").read_text(encoding="utf-8"))
    value.update(project_id="synthetic-project", hostname="sync.research.test",
                 backup_bucket="synthetic-private-backup")
    path = tmp_path / "review-input.json"
    path.write_text(json.dumps(value), encoding="utf-8")
    return path, value


@pytest.mark.parametrize("browser", [True, False])
def test_review_files_agree_and_templates_are_unchanged(config, tmp_path, browser):
    import hashlib

    path, value = config
    value["browser_enabled"] = browser
    path.write_text(json.dumps(value), encoding="utf-8")
    before = {item: item.read_bytes() for item in TEMPLATES.glob("*.example")}
    output = tmp_path / "review"
    result = pilot.prepare(path, output)
    assert result == dict(state="prepared_for_review", files=4, resource_changes=False,
                          budget_enforced=False, artifacts_verified=False)
    service = (output / "paperfact-sync.service").read_text(encoding="utf-8")
    active = [line for line in service.splitlines() if line.startswith("ExecStart=")]
    assert len(active) == 1
    assert ("--browser-origin https://sync.research.test" in active[0]) == browser
    assert "--require-mount /mnt/paperfact" in active[0]
    assert "server_name sync.research.test;" in (output / "paperfact-nginx.conf").read_text()
    upload = (output / "paperfact-backup-upload.service").read_text()
    assert "--bucket synthetic-private-backup" in upload and "REPLACE_WITH" not in upload
    review = json.loads((output / "review.json").read_text())
    assert review["config"] == value and not review["credentials_accessed"]
    assert "authority history/anchoring/fencing" in review["pending"]
    for name, identity in review["files"].items():
        raw = (output / name).read_bytes()
        assert identity == dict(sha256=hashlib.sha256(raw).hexdigest(), size=len(raw))
        assert b"\r\n" not in raw
    assert all(item.read_bytes() == raw for item, raw in before.items())
    with pytest.raises(FileExistsError):
        pilot.prepare(path, output)
    assert json.loads((output / "review.json").read_text()) == review


@pytest.mark.parametrize("field,value", [
    ("hostname", "sync.example.org; include private.conf"),
    ("project_id", "project-$(gcloud auth login)"),
    ("zone", "other-region-a"),
    ("monthly_budget_usd", True),
    ("monthly_budget_usd", math.nan),
    ("backup_snapshot", "../../live-service"),
    ("source_commit", "HEAD"),
    ("unexpected_key", "synthetic-secret-never-print"),
], ids=["hostname-injection", "project-injection", "zone-mismatch", "boolean-budget",
        "nonfinite-budget", "snapshot-traversal", "unpinned-source", "unknown-field"])
def test_invalid_or_secret_input_creates_no_output(config, tmp_path, capsys, field, value):
    path, data = config
    data[field] = value
    path.write_text(json.dumps(data), encoding="utf-8")
    output = tmp_path / "refused"
    assert pilot.main(["--config", str(path), "--output", str(output)]) == 2
    message = capsys.readouterr().out
    assert json.loads(message)["state"] == "not_prepared"
    assert "synthetic-secret" not in message and not output.exists()


def test_partial_output_is_retained_and_never_replaced_on_retry(config, tmp_path, monkeypatch):
    path, _data = config
    output = tmp_path / "interrupted"
    original = Path.open

    def interrupted(self, mode="r", *args, **kwargs):
        if self.name == "paperfact-nginx.conf" and mode == "xb":
            raise OSError("Synthetic write failure")
        return original(self, mode, *args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(Path, "open", interrupted)
        with pytest.raises(OSError):
            pilot.prepare(path, output)
    saved = (output / "paperfact-sync.service").read_bytes()
    assert not (output / "review.json").exists()
    with pytest.raises(FileExistsError):
        pilot.prepare(path, output)
    assert (output / "paperfact-sync.service").read_bytes() == saved


def test_actual_cli_prepares_only_local_review_files(config, tmp_path):
    path, _data = config
    output = tmp_path / "cli-review"
    result = subprocess.run([sys.executable, str(TEMPLATES / "prepare.py"),
                             "--config", str(path), "--output", str(output)],
                            capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr
    assert not json.loads(result.stdout)["resource_changes"]
    assert len(list(output.iterdir())) == 4


@pytest.mark.parametrize("raw", [b'{"hostname":"first","hostname":"second"}',
                                 b"[" * 2000 + b"]" * 2000, b"x" * 16385],
                         ids=["duplicate-field", "excessive-nesting", "oversized"])
def test_malformed_duplicate_or_oversized_json_is_a_bounded_cli_failure(tmp_path, capsys, raw):
    path, output = tmp_path / "invalid.json", tmp_path / "not-created"
    path.write_bytes(raw)
    assert pilot.main(["--config", str(path), "--output", str(output)]) == 2
    assert json.loads(capsys.readouterr().out)["state"] == "not_prepared"
    assert not output.exists()
