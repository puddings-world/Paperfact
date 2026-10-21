"""Colleagues get the app identity, never the developer's accounts or library."""

import json
import zipfile
from types import SimpleNamespace

from paper_daily import distribution, google_slides


def test_colleague_package_only_contains_source_and_desktop_client(tmp_path, monkeypatch):
    root = tmp_path / "repo"
    root.mkdir()
    files = {
        "src/paper_daily/app.py": "app",
        "README.md": "readme",
        ".gitignore": "/data/",
        "data/llm.json": "private-ai-key",
        "data/ai-accounts/claude/token.json": "private-login",
        "data/papers.db": "private-notes",
        ".env": "private-env",
        "src/.env": "private-nested-env",
    }
    for name, body in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body)
    client = tmp_path / "client.json"
    client.write_text(
        json.dumps(
            {
                "installed": {
                    "client_id": "app.apps.googleusercontent.com",
                    "client_secret": "desktop-identity",
                    "refresh_token": "must-not-ship",
                    "access_token": "must-not-ship",
                }
            }
        )
    )
    monkeypatch.setattr(
        distribution.subprocess,
        "run",
        lambda *a, **k: SimpleNamespace(stdout="\0".join(files).encode()),
    )
    dest = tmp_path / "app.zip"
    distribution.package(root, dest, client)
    with zipfile.ZipFile(dest) as archive:
        assert set(archive.namelist()) == {
            "Paperfact/src/paper_daily/app.py",
            "Paperfact/README.md",
            "Paperfact/.gitignore",
            "Paperfact/src/paper_daily/google-client.json",
        }
        contents = b"".join(archive.read(name) for name in archive.namelist())
        assert b"private-" not in contents and b"must-not-ship" not in contents


def test_fresh_install_can_sign_in_using_bundled_application_identity(tmp_path, monkeypatch):
    bundled = tmp_path / "bundled.json"
    bundled.write_text(
        json.dumps({"installed": {"client_id": "bundled.apps.googleusercontent.com"}})
    )
    local = tmp_path / "local.json"
    monkeypatch.setattr(google_slides, "CLIENT_FILE", local)
    monkeypatch.setattr(google_slides, "BUNDLED_CLIENT_FILE", bundled)
    monkeypatch.delenv("PAPERFACT_GOOGLE_CLIENT_ID", raising=False)
    assert google_slides.read_client()["client_id"] == "bundled.apps.googleusercontent.com"
    monkeypatch.setenv("PAPERFACT_GOOGLE_CLIENT_ID", "override.apps.googleusercontent.com")
    assert google_slides.read_client()["client_id"] == "override.apps.googleusercontent.com"
    local.write_text(json.dumps({"installed": {"client_id": "local.apps.googleusercontent.com"}}))
    assert google_slides.read_client()["client_id"] == "local.apps.googleusercontent.com"
