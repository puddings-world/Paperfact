"""Whole analysis cannot race an admitted reference/later/map child job."""

from types import SimpleNamespace

import pytest
from test_reader_chat import reader as reader_fixture
from test_research_chat import legacy as legacy_fixture

from paper_daily.desktop import ai_access

reader = reader_fixture
legacy = legacy_fixture


@pytest.mark.parametrize("attribute", ["_cites_job", "_follow_job", "_links_job"])
def test_whole_analysis_waits_for_existing_lookup(reader, monkeypatch, attribute):
    _app, window, _view = reader
    monkeypatch.setattr(ai_access, "_bridge", None)
    calls = []
    monkeypatch.setattr(window, "_spawn_job", lambda *args: calls.append(args))
    pane = window.reader_page.cites_pane
    status = [None]
    setattr(pane, attribute, SimpleNamespace(poll=lambda: status[0]))
    try:
        for _ in range(10):
            window.analyse_now("local-paper")
        assert calls == []
        status[0] = 0
        window.analyse_now("local-paper")
        assert calls == [(["analyze", "local-paper", "--retry"], "local-paper")]
    finally:
        setattr(pane, attribute, None)
