"""Workspace tasks remain discoverable without exposing all recovery tools at once."""

import os
from pathlib import Path

import pytest
from PySide6.QtGui import QFont, QFontDatabase
from test_workspace_dialog import app as app
from test_workspace_dialog import research as research
from test_workspace_dialog import wait

from paper_daily.desktop.workspace_dialog import WorkspaceDialog


@pytest.mark.parametrize("language", ["en", "zh-TW"])
def test_workspace_tasks_separate_sync_backup_and_advanced_without_starting_jobs(
    app, research, language
):
    view = WorkspaceDialog(research[0], language=language)
    font_path = Path(os.environ.get("WINDIR", "")) / "Fonts" / "msjh.ttc"
    if font_path.is_file():
        font_id = QFontDatabase.addApplicationFont(str(font_path))
        families = QFontDatabase.applicationFontFamilies(font_id)
        if families:
            view.setFont(QFont(families[0], 10))
    view.resize(675, 704)
    view.show()
    try:
        wait(app, lambda: view._ready and not view.busy)
        assert view.task_tabs.count() == 3 and view.task_tabs.currentIndex() == 0
        assert view.sync_connection_button.isVisible()
        assert not view.location.isVisible() and not view.backup_button.isVisible()
        screenshot = (
            Path(__file__).resolve().parents[1] / "build" / f"workspace-sync-{language}.png"
        )
        assert view.grab().save(str(screenshot))
        before = view.service.path.read_bytes()
        for _ in range(4):
            view.task_tabs.setCurrentIndex(1)
            app.processEvents()
            assert view.backup_button.isVisible() and view.inspect_button.isVisible()
            assert not view.enrollment_button.isVisible()
            view.task_tabs.setCurrentIndex(2)
            app.processEvents()
            assert view.location.isVisible() and view.enrollment_button.isVisible()
            assert not view.sync_connection_button.isVisible()
            view.task_tabs.setCurrentIndex(0)
        assert not view.busy and view.service.path.read_bytes() == before
        assert not view.restore_button.isEnabled()
    finally:
        view.close()
