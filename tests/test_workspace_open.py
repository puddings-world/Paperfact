import json
import sqlite3
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace

import pytest

from paper_daily import workspace_open as opening


@pytest.fixture
def destination(tmp_path):
    root = tmp_path / "new workspace"
    root.mkdir()
    with closing(sqlite3.connect(root / "papers.db")) as conn:
        conn.execute("CREATE TABLE papers(id TEXT PRIMARY KEY)")
        conn.execute("INSERT INTO papers VALUES ('paper')")
        conn.commit()
    return opening.WorkspaceDestination(root, root / "papers.db", "paper")


def test_new_process_binds_exact_workspace_without_inheriting_tokens(destination):
    calls = []
    source_environment = {
        "PATH": "fixture",
        "HOME": "fixture-home",
        "PAPERFACT_DATA": "old",
        "ANTHROPIC_API_KEY": "private-key",
        "PAPERFACT_SYNC_TOKEN": "private-token",
        "PAPERFACT_SMOKE_SECONDS": "1",
        "PYTHONPATH": "wrong-source",
    }
    original = dict(source_environment)
    selected = opening.open_workspace(
        destination,
        launch=lambda command, **options: calls.append((command, options)),
        environ=source_environment,
        executable="python",
        frozen=False,
    )
    command, options = calls[0]
    assert command == ["python", "-m", "paper_daily.integration_entry", "app"]
    assert source_environment == original
    assert options["shell"] is False and options["cwd"] == str(destination.workspace_root)
    assert options["env"]["PAPERFACT_DATA"] == str(destination.workspace_root)
    assert not any("private-" in value for value in options["env"].values())
    assert "PAPERFACT_SMOKE_SECONDS" not in options["env"]
    assert opening.consume_startup(destination.database_path, environ=options["env"]) == selected
    assert opening.STARTUP not in options["env"]


def test_packaged_app_keeps_gui_entrypoint(destination):
    calls = []
    opening.open_workspace(
        destination,
        frozen=True,
        executable="Paperfact.exe",
        environ={},
        launch=lambda command, **kwargs: calls.append((command, kwargs)),
    )
    assert calls[0][0] == ["Paperfact.exe"]
    assert "PYTHONPATH" not in calls[0][1]["env"]


def test_no_creation_or_launch_for_invalid_destination(destination, tmp_path):
    launched = []
    for chosen in (
        opening.WorkspaceDestination(tmp_path / "missing", tmp_path / "missing/papers.db"),
        opening.WorkspaceDestination(tmp_path, destination.database_path),
        opening.WorkspaceDestination(
            destination.workspace_root, destination.database_path, "absent"
        ),
    ):
        with pytest.raises((ValueError, OSError)):
            opening.open_workspace(chosen, launch=lambda *a, **k: launched.append(True))
    assert not launched and not (tmp_path / "missing").exists()


def test_replaced_database_rejected_before_startup_migrations(destination):
    calls = []
    opening.open_workspace(destination, launch=lambda *a, **kwargs: calls.append(kwargs))
    old = destination.database_path.with_suffix(".original")
    destination.database_path.rename(old)
    destination.database_path.write_bytes(old.read_bytes())
    before = destination.database_path.read_bytes()
    with pytest.raises(ValueError, match="changed"):
        opening.consume_startup(destination.database_path, environ=calls[0]["env"])
    assert destination.database_path.read_bytes() == before


def test_launch_failure_does_not_modify_database(destination):
    before = destination.database_path.read_bytes()

    def fail(*args, **kwargs):
        raise OSError("fixture launch failure")

    with pytest.raises(OSError):
        opening.open_workspace(destination, launch=fail)
    assert destination.database_path.read_bytes() == before


def test_focus_refuses_other_workspace_and_preserves_existing_drafts(destination, monkeypatch):
    from paper_daily import store

    calls = []
    window = SimpleNamespace(
        open_anywhere=lambda paper: calls.append(paper),
        reader_page=SimpleNamespace(
            paper=SimpleNamespace(id="other"),
            ask_box=SimpleNamespace(text=lambda: "Unsent question"),
            note_edit=SimpleNamespace(toPlainText=lambda: ""),
            presentation_pane=SimpleNamespace(_dirty=False, busy=False),
        ),
    )
    monkeypatch.setattr(store, "DB_PATH", destination.database_path)
    opening.focus_workspace(window, destination)
    assert not calls and window.reader_page.ask_box.text() == "Unsent question"
    monkeypatch.setattr(store, "DB_PATH", Path("different.db"))
    with pytest.raises(ValueError):
        opening.focus_workspace(window, destination)
    assert not calls


def test_closed_launch_envelope_and_no_implicit_startup(destination):
    assert opening.consume_startup(destination.database_path, environ={}) is None
    with pytest.raises(ValueError):
        opening.consume_startup(
            destination.database_path,
            environ={
                opening.STARTUP: json.dumps(
                    {"destination": destination.payload(), "identity": [1, 2], "token": "forbidden"}
                )
            },
        )


def test_missing_editable_copy_capability_fails_before_launch(destination, monkeypatch):
    import sys

    monkeypatch.setitem(sys.modules, "paper_daily.recovery_deck_copy", None)
    payload = destination.payload()
    payload["deck_id"] = "a-selected-copy"
    with pytest.raises(ValueError, match="editable recovered-deck support"):
        opening.open_workspace(payload, launch=lambda *a, **k: pytest.fail("Unsupported launch"))
