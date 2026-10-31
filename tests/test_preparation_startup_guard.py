"""A not-yet-created reader must leave the active-sync restart barrier intact."""

from types import SimpleNamespace

import pytest

from paper_daily.desktop.main import MainWindow


@pytest.mark.parametrize("reader_state", ["absent", "none", "not_prepared", "ready"])
def test_restart_with_optional_reader_still_stops_and_waits_for_active_sync(reader_state):
    stopped, preparation_calls = [], []
    automatic = SimpleNamespace(busy=True, stop=lambda: stopped.append(True))
    window = SimpleNamespace(_continuous_sync=automatic)
    if reader_state == "none":
        window.reader_page = None
    elif reader_state == "not_prepared":
        window.reader_page = SimpleNamespace()
    elif reader_state == "ready":
        def ready():
            preparation_calls.append(True)
            return True
        window.reader_page = SimpleNamespace(preparation=SimpleNamespace(request_close=ready))

    assert MainWindow._prepare_restart(window) is False
    assert stopped == [True]
    assert preparation_calls == ([True] if reader_state == "ready" else [])
    assert automatic.busy
