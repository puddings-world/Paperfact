"""Actual rescue bytes -> native preview -> receiver retention -> explicit review."""

import hashlib
import time

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, Qt
from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox
from test_rescue_deck_import import TARGET, export_file, imports, pdf_bytes
from test_rescue_deck_import import case as _case
from test_rescue_deck_import import codec as _codec
from test_rescue_deck_import import no_external as _no_external
from test_rescue_deck_import import original as _original

from paper_daily import presentations
from paper_daily.desktop.pending_generation import PendingDeckHub
from paper_daily.desktop.rescue_import_dialog import RescueImportDialog
from paper_daily.desktop.window_workspace import WindowWorkspace

case, codec, original, no_external = _case, _codec, _original, _no_external


def settle(app, predicate, timeout=20):
    end = time.monotonic() + timeout
    while not predicate() and time.monotonic() < end:
        app.processEvents()
        time.sleep(0.005)
    app.processEvents()
    assert predicate()


@pytest.fixture
def native_ui(case, monkeypatch):
    app = QApplication.instance() or QApplication([])
    pending = PendingDeckHub(app)
    monkeypatch.setattr(app, '_pending_deck_hub', pending, raising=False)
    dialogs = []
    yield app, dialogs
    for dialog in reversed(dialogs):
        if isinstance(dialog, RescueImportDialog):
            settle(app, lambda dialog=dialog: not dialog.busy)
        else:
            settle(app, lambda dialog=dialog: not dialog.busy and not dialog.jobs)
        dialog.close()
        dialog.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    app.processEvents()
    assert not pending.results.pending


def open_preview(native_ui, monkeypatch, path, language='zh-TW'):
    app, dialogs = native_ui
    dialog = RescueImportDialog(WindowWorkspace.capture(), language=language)
    dialogs.append(dialog)
    dialog.show()
    settle(app, lambda dialog=dialog: not dialog.busy and dialog.targets.count() >= 2)
    assert dialog.targets.currentItem() is None
    monkeypatch.setattr(QFileDialog, 'getOpenFileName', lambda *a, **kw: (str(path), ''))
    dialog.choose()
    settle(app, lambda dialog=dialog: not dialog.busy)
    assert dialog.source is not None, dialog.status.text()
    assert dialog.images.count() == 3
    assert 'Keep every word of this synthetic explanation' in dialog.text.toPlainText()
    unused = next(
        dialog.images.item(i) for i in range(dialog.images.count())
        if dialog.images.item(i).data(Qt.ItemDataRole.UserRole)['id'] == 'figure:3'
    )
    dialog.images.setCurrentItem(unused)
    assert 'Complete unused scientific caption' in dialog.image_detail.toPlainText()
    assert not dialog.retain_button.isEnabled()
    target = next(
        dialog.targets.item(i) for i in range(dialog.targets.count())
        if dialog.targets.item(i).data(Qt.ItemDataRole.UserRole)['id'] == TARGET
    )
    dialog.targets.setCurrentItem(target)
    assert dialog.retain_button.isEnabled()
    return dialog


@pytest.mark.parametrize('language', ['en', 'zh-TW'])
def test_actual_native_rescue_retains_then_cancel_or_explicit_apply_once(
    case, native_ui, monkeypatch, language
):
    source = export_file(case, monkeypatch, name='study.paperfact-draft.json')
    source_bytes = source.read_bytes()
    before = case['a'].journal.pending()
    dialog = open_preview(native_ui, monkeypatch, source, language)
    for _ in range(25):
        dialog.retain_button.click()
    app, dialogs = native_ui
    settle(app, lambda dialog=dialog: not dialog.busy)
    assert dialog.result is not None, dialog.status.text()
    candidate = dialog.result['candidate_id']
    assert imports(case) == [(candidate,)]
    assert presentations.load_deck(TARGET, 'guide').to_dict() == case['before']
    assert case['a'].journal.pending() == before
    assert source.read_bytes() == source_bytes
    dialog.review_button.click()
    review = dialog.review_dialog
    dialogs.append(review)
    settle(app, lambda: review.preview is not None and not review.jobs)
    assert review.selection_key == ('file_draft', candidate)
    assert case['sender'].title in review.draft.toPlainText()
    assert not review.apply.isEnabled()
    review.refresh.click()
    settle(app, lambda: review.preview is not None and not review.jobs)
    assert review.apply.isEnabled(), review.status.text()
    confirmations = []

    def cancel(*args, **kwargs):
        confirmations.append(args[2])
        return QMessageBox.StandardButton.Cancel

    monkeypatch.setattr(QMessageBox, 'question', cancel)
    review.apply.click()
    assert confirmations and TARGET in confirmations[0]
    assert presentations.load_deck(TARGET, 'guide').to_dict() == case['before']
    assert case['a'].journal.pending() == before
    monkeypatch.setattr(
        QMessageBox, 'question', lambda *a, **kw: QMessageBox.StandardButton.Yes
    )
    for _ in range(25):
        review.apply.click()
    settle(app, lambda: not review.busy and not review.jobs)
    assert review.status.text() == review.words['saved']
    loaded = presentations.load_deck(TARGET, 'guide')
    assert loaded.title == case['sender'].title
    assert loaded.slides[0].speaker_notes == case['sender'].slides[0].speaker_notes
    expected_elements = [
        ({'size': 26, 'color': '#172238', 'bold': False, 'align': 'left'} | item)
        if item['kind'] == 'text' else item
        for item in case['sender'].slides[0].elements
    ]
    assert loaded.slides[0].elements == expected_elements
    for key in ('figure:1', 'figure:2'):
        assert presentations.figure_bytes(loaded, key) == case['images'][key]
    assert len(case['a'].journal.pending()) == len(before) + 1
    assert imports(case) == [(candidate,)]
    assert source.read_bytes() == source_bytes


@pytest.mark.parametrize('fault', ['file-changed', 'missing-original'])
def test_actual_native_refusal_preserves_preview_saved_deck_and_outbox(
    case, native_ui, monkeypatch, fault
):
    sha = hashlib.sha256(pdf_bytes('Unavailable receiver original')).hexdigest()
    source = export_file(
        case, monkeypatch, name='refusal.paperfact-draft.json',
        source_hash=sha if fault == 'missing-original' else None,
    )
    dialog = open_preview(native_ui, monkeypatch, source)
    before, text = case['a'].journal.pending(), dialog.text.toPlainText()
    if fault == 'file-changed':
        source.write_bytes(source.read_bytes() + b'\n')
    final_bytes = source.read_bytes()
    dialog.retain_button.click()
    settle(native_ui[0], lambda dialog=dialog: not dialog.busy)
    assert dialog.result is None and dialog.pending_key is None
    assert dialog.status.text().startswith(dialog.words['failed'].split('{reason}')[0])
    assert dialog.text.toPlainText() == text and dialog.images.count() == 3
    assert dialog.retain_button.isEnabled() and not dialog.review_button.isEnabled()
    assert imports(case) == []
    assert presentations.load_deck(TARGET, 'guide').to_dict() == case['before']
    assert case['a'].journal.pending() == before
    assert source.read_bytes() == final_bytes
