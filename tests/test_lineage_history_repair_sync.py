"""Real sync repairs legacy saved history and bounded passes remain visibly pending."""

import pytest
from test_continuous_sync import connect, run
from test_continuous_sync import control as control
from test_continuous_sync import enrolled as enrolled
from test_continuous_sync import research as research
from test_continuous_sync import service as service
from test_lineage_history_repair import compared as compared
from test_lineage_history_repair import corpus as corpus
from test_lineage_history_repair import legacy as legacy
from test_lineage_history_repair import native_shared as native_shared
from test_lineage_history_repair import shared as shared
from test_sync_files import codec as codec
from test_sync_files import pair as pair
from test_workspace_sync import Native

from paper_daily import lineage_projection
from paper_daily.desktop.continuous_sync import status_text
from paper_daily.desktop.history_index_text import progress_text
from paper_daily.lineage_history_repair import HistoryRepair
from paper_daily.workspace_service import Ticket
from paper_daily.workspace_sync import SyncSession


def test_real_sync_session_repairs_old_beta_catalog_without_an_ai_call(legacy, pair):
    client, _files, _receipt, _old = legacy
    authority, _origin, _peer, _of, _pf, _ot, token = pair
    calls, progress = [], []
    session = SyncSession(
        client.journal.path, transport_factory=lambda endpoint: Native(endpoint, authority, calls)
    )
    try:
        session.connect("http://127.0.0.1:8765", "workspace", "b", token, Ticket())
        result = session.sync(Ticket(), progress.append)
        assert result["lineage_history"]["restored"] == 1
        assert not result["lineage_history"]["more"]
        assert any(row.get("stage") == "history_reindex" for row in progress)
        with client.journal.transaction() as conn:
            assert (
                conn.execute("SELECT count(*) FROM " + lineage_projection.HISTORY).fetchone()[0]
                == 2
            )
    finally:
        session.disconnect()


def test_continuous_sync_keeps_scheduling_actual_bounded_index_until_complete(
    control,
    service,
    monkeypatch,
):
    _app, _parent, controller, clock = control
    original = HistoryRepair.drain

    def one_event(repair, ticket=None, progress=lambda _value: None, **options):
        return original(repair, ticket, progress, **{**options, "max_steps": 1, "limit": 1})

    monkeypatch.setattr(HistoryRepair, "drain", one_event)
    connect(service)
    controller.enable()
    run(control)
    result = controller.summary()["result"]
    assert result["lineage_history"]["more"] and controller.state == "waiting"
    assert "Version index:" in status_text(controller.summary())
    snapshot = controller.summary()
    snapshot["result"]["lineage_history"]["through"] = -100
    assert controller.summary()["result"]["lineage_history"]["through"] >= 0
    for _ in range(8):
        clock[0] += 2
        run(control)
        if not controller.summary()["result"]["lineage_history"]["more"]:
            break
    assert (
        controller.state == "idle" and not controller.summary()["result"]["lineage_history"]["more"]
    )


@pytest.mark.parametrize("language", ["en", "zh-TW"])
def test_local_progress_reports_actual_event_counts_without_time_estimates(language):
    text = progress_text(dict(through=2, target=5, restored=1), language)
    assert "2/5" in text and "1" in text
    assert "%" not in text


def test_invalid_local_progress_cannot_render_a_made_up_completed_percentage():
    with pytest.raises(ValueError, match="progress counts"):
        progress_text(dict(through=6, target=5, restored=1))
