"""Closed owned windows retire native resources on GUI, before unrelated worker GC."""

import gc
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, Qt
from shiboken6 import isValid
from test_highlight_draft_ui import close, editor
from test_highlight_draft_ui import ready as ready
from test_highlight_draft_ui import scene as scene
from test_highlight_draft_ui import source_pair as source_pair
from test_highlight_draft_ui import workspace as workspace
from test_review_dialog import app as app
from test_review_dialog import wait

pytestmark = pytest.mark.parametrize("workspace", [True], indirect=True)


@pytest.mark.parametrize("with_parent", [False, True], ids=["editor", "parent-and-editor"])
def test_closed_native_resources_retire_on_gui_before_worker_collection(
    source_pair, app, with_parent
):
    from paper_daily.desktop.review_dialog import ReviewDialog

    gui = threading.get_ident()
    destroyed = []
    if with_parent:
        parent = ReviewDialog(source_pair["path"])
        parent.show()
        wait(app, lambda: parent.preview is not None and not parent.busy)
        index = next(
            i
            for i in range(parent.list.count())
            if parent.list.item(i).data(Qt.ItemDataRole.UserRole)[1]
            == source_pair["original"].data["id"]
        )
        parent.list.setCurrentRow(index)
        wait(app, lambda: not parent.busy)
        parent.resume_button.click()
        wait(app, lambda: parent.claim_editor is not None and not parent.claim_editor.busy)
        dialog = parent.claim_editor
        parent.destroyed.connect(
            lambda: destroyed.append(("parent", threading.get_ident())),
            Qt.ConnectionType.DirectConnection,
        )
    else:
        parent = None
        dialog = editor(app, source_pair)
    dialog.destroyed.connect(
        lambda: destroyed.append(("editor", threading.get_ident())),
        Qt.ConnectionType.DirectConnection,
    )
    if parent is None:
        close(app, dialog)
    else:
        parent.close()
        wait(app, lambda: parent.disposed and dialog.disposed, timeout=20)
    # Tests drive processEvents rather than exec; explicitly deliver the GUI's
    # DeferredDelete events as the ordinary application loop would do.
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    assert not isValid(dialog), "A drained closed editor still owns native widgets"
    assert dialog.disposed and not dialog.isVisible()
    assert dialog.close() is True
    dialog.deleteLater()
    dialog.deleteLater()
    if parent is not None:
        assert not isValid(parent), "A closed parent still owns native widgets"
        assert parent.disposed and not parent.isVisible()
        assert parent.close() is True  # repeated closing stays safe after native retirement
        parent.deleteLater()
        parent.deleteLater()
    assert destroyed and all(thread == gui for _name, thread in destroyed)
    # A worker can later collect Python cycles, but no native widgets remain for it.
    with ThreadPoolExecutor(max_workers=1) as executor:
        executor.submit(gc.collect).result(timeout=10)
    expected = [("editor", gui)] if parent is None else [("editor", gui), ("parent", gui)]
    assert sorted(destroyed) == sorted(expected)
