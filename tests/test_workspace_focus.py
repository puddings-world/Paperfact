import hashlib
import json
import ntpath
import posixpath
from types import SimpleNamespace

import pytest
from test_workspace_open import destination

from paper_daily import workspace_open as opening

__all__ = ["destination"]


def test_fragmented_focus_command_waits_for_complete_frame(destination):
    command = b"workspace-open:" + json.dumps(destination.payload()).encode() + b"\n"
    for count in (1, 8, 15, 25, len(command) - 1):
        assert opening.focus_command(command[:count]) is None
    assert opening.focus_command(command) == destination
    assert opening.focus_command(command, database_path=destination.database_path) == destination
    with pytest.raises(ValueError, match="another workspace"):
        opening.focus_command(
            command, database_path=destination.database_path.with_name("other.db"),
        )
    with pytest.raises(ValueError):
        opening.focus_command(command + command)
    with pytest.raises(ValueError):
        opening.focus_command(b"workspace-open:" + b"x" * 8192)


def test_existing_instance_handoff_preserves_workspace_focus(monkeypatch, destination):
    from paper_daily.desktop import main

    written = []

    class Socket:
        def connectToServer(self, key):
            written.append(key)

        def waitForConnected(self, _timeout):
            return True

        def write(self, payload):
            written.append(payload)

        def flush(self):
            pass

        def waitForBytesWritten(self, _timeout):
            return True

        def disconnectFromServer(self):
            written.append("closed")

    monkeypatch.setattr(main, "QLocalSocket", Socket)
    assert main._hand_off_to_running_instance(False, destination=destination)
    assert written[0] == main.SINGLE_INSTANCE_KEY and written[-1] == "closed"
    assert opening.focus_command(written[1]) == destination


def test_focus_same_paper_preserves_draft_and_does_not_reload(destination, monkeypatch):
    from paper_daily import store

    calls = []
    reader = SimpleNamespace(paper=SimpleNamespace(id=destination.paper_id))
    window = SimpleNamespace(reader_page=reader, open_anywhere=lambda value: calls.append(value))
    monkeypatch.setattr(store, "DB_PATH", destination.database_path)
    opening.focus_workspace(window, destination)
    assert calls == []


def test_startup_rejects_mismatched_workspace_before_any_initialization(destination, monkeypatch):
    from paper_daily import store
    from paper_daily.desktop import main

    calls = []
    monkeypatch.setattr(store, "DB_PATH", destination.database_path.with_name("other.db"))
    info = destination.database_path.stat()
    monkeypatch.setenv(
        opening.STARTUP,
        json.dumps({"destination": destination.payload(), "identity": [info.st_dev, info.st_ino]}),
    )
    monkeypatch.setattr(main, "ensure_dirs", lambda: calls.append("directory"))
    monkeypatch.setattr(main, "init_db", lambda: calls.append("database"))
    with pytest.raises(ValueError):
        main.run()
    assert calls == []


@pytest.mark.parametrize(
    "platform,normalizer", [("win32", ntpath.normcase), ("darwin", posixpath.normcase),
                            ("linux", posixpath.normcase)],
)
def test_instance_routing_respects_native_path_case_rules(
    tmp_path, monkeypatch, platform, normalizer,
):
    upper, lower = tmp_path / "Research", tmp_path / "research"
    monkeypatch.setattr(opening.sys, "platform", platform)
    monkeypatch.setattr(opening.os.path, "normcase", normalizer)
    same = normalizer(str(upper.resolve())) == normalizer(str(lower.resolve()))
    assert (opening.instance_key(upper) == opening.instance_key(lower)) == same
    assert opening.instance_key(upper / ".." / "Research") == opening.instance_key(upper)
    assert not upper.exists() and not lower.exists()
    upper.mkdir()
    if lower.exists():
        # Case-insensitive volumes must not launch twice for one physical directory.
        assert opening.instance_key(upper) == opening.instance_key(lower)
    else:
        lower.mkdir()
        assert opening.instance_key(upper) != opening.instance_key(lower)
    if platform == "win32":
        expected = hashlib.sha1(str(upper.resolve()).lower().encode("utf-8")).hexdigest()[:12]
        assert opening.instance_key(upper) == "paperfact-" + expected
