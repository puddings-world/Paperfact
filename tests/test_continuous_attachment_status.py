"""Automatic-sync status must account for attachment work, not only metadata."""

import pytest
from test_continuous_sync import control as control_fixture
from test_continuous_sync import run
from test_sync_connection_dialog import wait
from test_workspace_sync import connect
from test_workspace_sync import enrolled as enrolled_fixture
from test_workspace_sync import research as research_fixture
from test_workspace_sync import service as service_fixture

from paper_daily.desktop.sync_connection_dialog import SyncConnectionDialog

research = research_fixture
enrolled = enrolled_fixture
service = service_fixture
control = control_fixture


@pytest.mark.parametrize("failed", [0, 1])
def test_pending_files_remain_visible_and_retry_without_click_flood(
    control, service, monkeypatch, failed
):
    app, parent, controller, clock = control
    connect(service)
    original = service[0].sync
    calls = []

    def incomplete(*args, **kwargs):
        calls.append(1)
        result = original(*args, **kwargs)
        result["attachments"] = {
            "pending": 2, "failed": failed, "steps": 1,
            "storage_registered": True, "complete_offline_verified": False,
        }
        return result

    monkeypatch.setattr(service[0], "sync", incomplete)
    view = SyncConnectionDialog(service[0], parent, language="en", automatic=controller)
    view.show()
    try:
        wait(app, lambda: view.binding is not None and not view.busy)
        controller.enable()
        run(control)
        assert controller.state == ("files_retry" if failed else "files_pending")
        assert "files" in view.automatic_status.text().lower()
        assert "pending 2" in view.automatic_status.text()
        assert "verify offline availability" in view.automatic_status.text()
        assert controller.summary()["result"]["attachments"]["pending"] == 2
        exposed = controller.summary()
        exposed["result"]["attachments"]["pending"] = 99
        assert controller.summary()["result"]["attachments"]["pending"] == 2
        assert controller.summary()["retry_in"] == (10 if failed else 2)
        for _ in range(30):
            controller.tick()
        assert len(calls) == 1
        clock[0] += 10 if failed else 2
        monkeypatch.setattr(service[0], "sync", original)
        run(control)
        assert controller.state == "idle" and controller.enabled
        assert controller.summary()["result"]["attachments"]["pending"] == 0
    finally:
        view.close()
