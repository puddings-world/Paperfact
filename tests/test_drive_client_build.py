"""Build application configuration without copying any end-user authorization."""

import importlib.util
import json
from pathlib import Path

import pytest


def test_packaging_requires_desktop_client_and_preserves_target_on_invalid_input(tmp_path):
    script = Path(__file__).resolve().parents[1] / "scripts/prepare_google_client.py"
    spec = importlib.util.spec_from_file_location("prepare_google_client_for_test", script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    target = tmp_path / "google-client.json"
    module.prepare(json.dumps({"installed": {
        "client_id": "synthetic.apps.googleusercontent.com",
        "client_secret": "synthetic-app-config",
        "refresh_token": "must-never-ship", "project_id": "not-needed"}}), target)
    data = json.loads(target.read_text(encoding="utf-8"))
    assert set(data["installed"]) == {"client_id", "client_secret"}
    assert "must-never-ship" not in target.read_text(encoding="utf-8")
    before = target.read_bytes()
    for raw in ['{"web":{}}', '{"refresh_token":"not-a-client"}', 'invalid json']:
        with pytest.raises(ValueError, match="Desktop"):
            module.prepare(raw, target)
        assert target.read_bytes() == before
