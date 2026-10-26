"""The real presentation pane preserves observed drafts and immutable revisions."""

import os

import pytest
from test_sync_files import LOCAL, save_current
from test_sync_files import codec as codec_fixture
from test_sync_files import pair as pair_fixture

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtCore import QCoreApplication, QEvent  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from paper_daily import presentations  # noqa: E402
from paper_daily.desktop.presentation_pane import PresentationPane  # noqa: E402

codec = codec_fixture
pair = pair_fixture


@pytest.fixture
def bound_pane(pair, codec):
    app = QApplication.instance() or QApplication([])
    save_current(pair, codec[0])
    pane = PresentationPane()
    pane.load(LOCAL, "Paper")
    assert pane.deck is not None
    yield pane, app
    pane._dirty = False
    pane._autosave.stop()
    pane.close()
    pane.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    app.processEvents()


def test_actual_pane_save_repeat_undo_and_redo_publish_revisions(bound_pane, pair):
    pane, _ = bound_pane
    pane.slide_title.setText("Edited through pane")
    assert pane.save_changes()
    assert presentations.load_deck(LOCAL, "guide").slides[0].title == "Edited through pane"
    assert pane.save_changes()
    with pair[1].journal.transaction() as conn:
        assert conn.execute("SELECT count(*) FROM research_file_versions").fetchone()[0] == 2
    pane._undo_edit()
    assert presentations.load_deck(LOCAL, "guide").slides[0].title == "Method"
    pane._redo_edit()
    assert presentations.load_deck(LOCAL, "guide").slides[0].title == "Edited through pane"
    with pair[1].journal.transaction() as conn:
        assert conn.execute("SELECT count(*) FROM research_file_versions").fetchone()[0] == 4


def test_actual_pane_stale_edit_keeps_text_and_version_keyed_recovery(bound_pane):
    pane, _ = bound_pane
    original_recovery = pane._recovery_path()
    pane.slide_title.setText("Keep this unsaved edit")
    pane.save_recovery()
    assert original_recovery.is_file()
    other = presentations.load_deck(LOCAL, "guide")
    other.slides[0].title = "Other editor saved"
    presentations.save_deck(other)
    assert not pane.save_changes()
    assert pane.slide_title.text() == "Keep this unsaved edit"
    assert pane._dirty
    assert presentations.load_deck(LOCAL, "guide").slides[0].title == "Other editor saved"
    assert original_recovery.is_file()
    pane._dirty = False
    pane.load(LOCAL, "Paper")
    assert pane._recovery_path() != original_recovery
    assert pane.slide_title.text() == "Other editor saved"
