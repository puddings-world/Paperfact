"""The optional deployment guard must fail before opening an authority/listener."""

import json

import pytest

from paper_daily import sync_admin


@pytest.mark.parametrize("case", ["missing", "ordinary-directory", "outside", "same", "relative"])
def test_mount_guard_refuses_before_authority_or_listener(tmp_path, monkeypatch, capsys, case):
    mount = tmp_path / "volume"
    state = mount / "service"
    if case != "missing":
        mount.mkdir()
    if case == "outside":
        state = tmp_path / "elsewhere"
    elif case == "same":
        state = mount
    elif case == "relative":
        mount = __import__("pathlib").Path("relative-volume")
    monkeypatch.setattr(sync_admin.os.path, "ismount", lambda path: case in {"outside", "same"})

    def forbidden(*_args, **_kwargs):
        pytest.fail("Refused deployment must not open authority or listener")

    monkeypatch.setattr(sync_admin, "authority", forbidden)
    monkeypatch.setattr(sync_admin, "make_server", forbidden)
    assert sync_admin.main([
        "serve", "--state", str(state), "--require-mount", str(mount),
    ]) == 2
    output = capsys.readouterr()
    assert not output.out
    assert "required data mount" in output.err
    assert not (state / sync_admin.DATABASE).exists()


def test_missing_mount_does_not_open_even_previously_initialized_state(tmp_path, monkeypatch):
    mount = tmp_path / "volume"
    state = mount / "service"
    sync_admin.initialize(state)
    before = (state / sync_admin.DATABASE).read_bytes()
    monkeypatch.setattr(sync_admin.os.path, "ismount", lambda _path: False)
    monkeypatch.setattr(sync_admin, "authority", lambda *_a: pytest.fail("must not open"))
    assert sync_admin.main([
        "serve", "--state", str(state), "--require-mount", str(mount),
    ]) == 2
    assert (state / sync_admin.DATABASE).read_bytes() == before


def test_mount_restored_allows_retry_and_listener_closes(tmp_path, monkeypatch, capsys):
    mount = tmp_path / "volume"
    state = mount / "service"
    sync_admin.initialize(state)
    mounted = False
    monkeypatch.setattr(sync_admin.os.path, "ismount", lambda path: mounted and path == mount)
    calls = []

    class Server:
        server_port = 8765

        def serve_forever(self):
            calls.append("serve")
            raise KeyboardInterrupt

        def server_close(self):
            calls.append("close")

    monkeypatch.setattr(sync_admin, "make_server", lambda *_a, **_k: Server())
    args = ["serve", "--state", str(state), "--require-mount", str(mount)]
    assert sync_admin.main(args) == 2
    assert calls == []
    mounted = True
    assert sync_admin.main(args) == 0
    assert calls == ["serve", "close"]
    assert json.loads(capsys.readouterr().out)["state"] == "serving"


def test_actual_unmounted_directory_is_refused_without_creating_state(tmp_path):
    mount = tmp_path / "ordinary-directory"
    mount.mkdir()
    state = mount / "service"
    with pytest.raises(ValueError, match="mounted data volume"):
        sync_admin.require_mount(state, mount)
    assert not state.exists()
