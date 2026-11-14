"""Private operator-key setup and actual console restart, using synthetic authority state."""

import json
import os
import runpy
import secrets
import stat
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from paper_daily import sync_admin
from paper_daily.connection_vault import Connection
from paper_daily.sync_authority_backup import export
from paper_daily.sync_browser_key import FORMAT, _validate_stat, create_key, load_key
from paper_daily.sync_http import HttpTransport
from paper_daily.sync_pairing import Invitation


def test_create_retry_receipts_and_backup_keep_key_private_and_stable(
    tmp_path, capsys, monkeypatch
):
    state, key = tmp_path / "service", tmp_path / "operator-browser-key.json"
    sync_admin.initialize(state)
    before = (state / sync_admin.DATABASE).read_bytes()
    args = ["create-browser-key", "--output", str(key)]
    assert sync_admin.main(args) == 0
    assert json.loads(capsys.readouterr().out) == {"state": "created", "key_file": str(key)}
    raw, material = key.read_bytes(), load_key(key)
    assert len(material) == 32
    from paper_daily import sync_browser_key

    with monkeypatch.context() as context:
        context.setattr(
            sync_browser_key.secrets,
            "token_bytes",
            lambda *_: pytest.fail("Existing key retry generated new material"),
        )
        assert sync_admin.main(args) == 0
    receipt = capsys.readouterr().out
    assert json.loads(receipt)["state"] == "already_exists"
    assert json.loads(raw)["key"] not in receipt and key.read_bytes() == raw
    assert (state / sync_admin.DATABASE).read_bytes() == before
    sync_admin.authority(state).enroll("workspace", "desktop")
    snapshot = tmp_path / "backup"
    export(state, snapshot)
    for entry in snapshot.rglob("*"):
        if entry.is_file():
            assert raw not in entry.read_bytes() and material not in entry.read_bytes()
    with pytest.raises(SystemExit) as stopped:
        sync_admin.main(["create-browser-key", "--help"])
    assert stopped.value.code == 0 and "--output" in capsys.readouterr().out


def test_invalid_existing_records_and_hardlinks_never_rotate_or_overwrite(tmp_path):
    key = tmp_path / "operator-browser-key.json"
    good = create_key(key)
    assert good["state"] == "created"
    canonical = key.read_bytes()
    for raw in (
        b"",
        b"{" + b"x" * 1024,
        b"[]",
        b'{"format":"unknown","key":"x"}',
        json.dumps({"format": FORMAT, "key": "not-a-valid-key"}).encode(),
        ('{"format":' + json.dumps(FORMAT) + ',"key":"x","key":"y"}').encode(),
    ):
        key.write_bytes(raw)
        with pytest.raises(ValueError):
            create_key(key)
        assert key.read_bytes() == raw
    key.write_bytes(canonical)
    alias = tmp_path / "linked.json"
    os.link(key, alias)
    with pytest.raises(ValueError):
        load_key(key)
    assert key.read_bytes() == canonical and alias.read_bytes() == canonical


def test_private_posix_permission_and_owner_contract_has_no_windows_acl_claim():
    info = SimpleNamespace(st_mode=stat.S_IFREG | 0o600, st_nlink=1, st_size=100, st_uid=1000)
    _validate_stat(info, uid=1000)
    for changed in (
        {"st_mode": stat.S_IFREG | 0o644},
        {"st_uid": 1001},
        {"st_mode": stat.S_IFDIR | 0o600},
    ):
        with pytest.raises(ValueError):
            _validate_stat(SimpleNamespace(**(vars(info) | changed)), uid=1000)
    # No simulated POSIX mode check is advertised as a real Windows ACL check.
    _validate_stat(SimpleNamespace(**(vars(info) | {"st_mode": stat.S_IFREG | 0o666})), uid=None)


def test_key_replacement_during_read_refuses_without_removing_replacement(tmp_path, monkeypatch):
    from paper_daily import sync_browser_key

    path, replacement = tmp_path / "key.json", tmp_path / "replacement.json"
    create_key(path)
    create_key(replacement)
    expected = load_key(replacement)
    original = sync_browser_key.os.read

    def changed(fd, count):
        body = original(fd, count)
        if os.name == "nt":
            # Windows refuses rename over this open handle. Exercise its allowed
            # in-place update instead; the changed snapshot must still be refused.
            before = path.stat()
            path.write_bytes(replacement.read_bytes())
            os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns + 1_000_000_000))
        else:
            os.replace(replacement, path)
        return body

    with monkeypatch.context() as context:
        context.setattr(sync_browser_key.os, "read", changed)
        with pytest.raises(ValueError):
            load_key(path)
    assert load_key(path) == expected


def test_browser_options_fail_before_authority_or_listener_and_preserve_state(
    tmp_path, monkeypatch, capsys
):
    state, key = tmp_path / "service", tmp_path / "operator-browser-key.json"
    sync_admin.initialize(state)
    create_key(key)
    inside = state / "operator-browser-key.json"
    create_key(inside)
    before = (state / sync_admin.DATABASE).read_bytes()

    def forbidden(*_args, **_kwargs):
        pytest.fail("Rejected browser setup opened authority or listener")

    monkeypatch.setattr(sync_admin, "authority", forbidden)
    monkeypatch.setattr(sync_admin, "make_server", forbidden)
    for options in (
        ["--browser-origin", "https://sync.example.org"],
        ["--browser-key-file", str(key)],
        ["--browser-origin", "https://sync.example.org", "--browser-key-file", str(inside)],
        ["--browser-origin", "http://remote.example.org", "--browser-key-file", str(key)],
        ["--browser-origin", "https://SYNC.example.org:443", "--browser-key-file", str(key)],
    ):
        assert sync_admin.main(["serve", "--state", str(state), *options]) == 2
        output = capsys.readouterr()
        assert not output.out and "browser" in output.err
        assert (state / sync_admin.DATABASE).read_bytes() == before
    assert len(load_key(key)) == 32


@contextmanager
def console(state, key, unused):
    source = Path(__file__).resolve().parents[1] / "src"
    child = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "paper_daily",
            "sync-admin",
            "serve",
            "--state",
            str(state),
            "--port",
            "0",
            "--browser-origin",
            "https://sync.example.org",
            "--browser-key-file",
            str(key),
        ],
        env={**os.environ, "PYTHONPATH": str(source), "PAPERFACT_DATA": str(unused)},
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    reader = ThreadPoolExecutor(max_workers=1)
    try:
        ready = json.loads(reader.submit(child.stdout.readline).result(timeout=15))
        assert ready["state"] == "serving" and ready["browser_origin"] == "https://sync.example.org"
        yield ready["url"]
        assert not unused.exists()
    finally:
        child.terminate()
        child.wait(timeout=10)
        reader.shutdown(wait=True)
        child.stdout.close()
        child.stderr.close()


def test_actual_cli_restart_reuses_pending_cookie_and_private_key_without_new_device(tmp_path):
    state, key, output = (
        tmp_path / "service",
        tmp_path / "operator-browser-key.json",
        tmp_path / "desktop.json",
    )
    sync_admin.initialize(state)
    create_key(key)
    sync_admin.issue(state, "https://sync.example.org", "workspace", "desktop", output)
    record = Connection.decoded(output.read_text(encoding="utf-8"))
    headers = {"Origin": "https://sync.example.org", "X-Paperfact-Browser": "1"}

    def request(url, route, cookie=None, body=None, identity=None):
        options = dict(headers)
        if cookie:
            options["Cookie"] = "__Host-paperfact-device=" + cookie
        if identity:
            options.update(
                {
                    "X-Paperfact-Workspace": identity["workspace_id"],
                    "X-Paperfact-Device": identity["device_id"],
                }
            )
        return httpx.post(
            url + "/v1/browser/" + route,
            json=body or {},
            headers=options,
            trust_env=False,
            timeout=3,
        )

    with console(state, key, tmp_path / "unused-research") as url:
        with HttpTransport(url) as transport:
            code = secrets.token_urlsafe(32)
            grant = transport.create_pairing(record.token, code)
        invitation = Invitation("https://sync.example.org", code=code, **grant).encoded()
        response = request(url, "pairing/prepare", body={"invitation": invitation})
        assert response.status_code == 200
        cookie = response.headers["set-cookie"].split(";", 1)[0].partition("=")[2]
        identity = response.json()
        assert request(url, "pairing/complete", cookie).json() == identity
    before = key.read_bytes()
    with console(state, key, tmp_path / "unused-research") as url:
        response = request(url, "pairing/complete", cookie)
        assert response.status_code == 200 and response.json() == identity
        active = response.headers["set-cookie"].split(";", 1)[0].partition("=")[2]
        assert request(url, "session/info", active, identity=identity).json() == identity
        with HttpTransport(url) as transport:
            assert len(transport.device_catalog(record.token)["devices"]) == 2
    assert key.read_bytes() == before


def test_renamed_signing_key_cannot_pass_commit_scan_and_findings_never_echo(tmp_path):
    root = Path(__file__).resolve().parents[1]
    scanner = runpy.run_path(str(root / "scripts/check.py"))["scan_privacy"]
    secret = tmp_path / "ordinary-config.json"
    create_key(secret)
    material = json.loads(secret.read_text())["key"]
    findings = scanner(tmp_path, [secret], [])
    assert findings == ["ordinary-config.json:1: Paperfact browser signing key"]
    assert material not in str(findings)
    secret.write_text(json.dumps({"format": FORMAT, "key": "REPLACE_WITH_BROWSER_SIGNING_KEY"}))
    assert scanner(tmp_path, [secret], []) == []
