import pytest
from PySide6.QtWidgets import QApplication, QMessageBox

from paper_daily import ai_profiles, llm
from paper_daily.desktop import ai_recovery


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    monkeypatch.setattr(llm, "SETTINGS_PATH", tmp_path / "llm.json")
    llm.SETTINGS_PATH.write_bytes(b'{"broken": "fixture-secret"')
    return tmp_path


def test_recovery_preserves_exact_backup_and_disables_ai(workspace):
    original = llm.SETTINGS_PATH.read_bytes()
    unrelated = workspace / "notes.txt"
    unrelated.write_text("research")
    backup = ai_recovery.backup_and_reset()
    assert backup.read_bytes() == original
    assert llm.settings().backend == "none"
    assert unrelated.read_text() == "research"


def test_failed_replacement_keeps_original_and_backup(workspace, monkeypatch):
    original = llm.SETTINGS_PATH.read_bytes()

    def fail(*args):
        raise OSError("fixture disk full")

    monkeypatch.setattr(ai_profiles, "write", fail)
    with pytest.raises(OSError):
        ai_recovery.backup_and_reset()
    assert llm.SETTINGS_PATH.read_bytes() == original
    assert next(workspace.glob("llm-recovery-*.json")).read_bytes() == original


def test_declining_recovery_does_not_change_or_copy_settings(workspace, monkeypatch):
    app = QApplication.instance() or QApplication([])
    before = llm.SETTINGS_PATH.read_bytes()
    monkeypatch.setattr(QMessageBox, "question", lambda *a: QMessageBox.StandardButton.No)
    assert not ai_recovery.offer(None)
    assert llm.SETTINGS_PATH.read_bytes() == before
    assert not list(workspace.glob("llm-recovery-*"))
    app.processEvents()


def test_invalid_settings_do_not_break_background_polling(workspace, monkeypatch):
    from PySide6.QtWidgets import QWidget

    from paper_daily import usage_cache
    from paper_daily.desktop.usage_monitor import UsageMonitor

    app = QApplication.instance() or QApplication([])
    owner = QWidget()
    calls = []
    monkeypatch.setattr(usage_cache.cache, "refresh_background", lambda cfg: calls.append(cfg))
    monitor = UsageMonitor(owner)
    monitor.tick()
    assert calls == []
    assert llm.SETTINGS_PATH.read_bytes() == b'{"broken": "fixture-secret"'
    owner.deleteLater()
    app.processEvents()
