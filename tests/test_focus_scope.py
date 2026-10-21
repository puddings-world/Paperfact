"""A click anywhere in a panel puts the keys there, the innermost panel wins, and
panel shortcuts only act in their own panel."""

import os

import pytest

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint, Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication, QLabel, QLineEdit, QVBoxLayout, QWidget  # noqa: E402

from paper_daily.desktop.focus_scope import FocusScopes  # noqa: E402


def _pump():
    for _ in range(5):
        QApplication.processEvents()


@pytest.fixture
def window():
    app = QApplication.instance() or QApplication([])
    win = QWidget()
    outer = QWidget(win)
    QVBoxLayout(win).addWidget(outer)
    outer_layout = QVBoxLayout(outer)
    outer_edit = QLineEdit()
    inner = QWidget()
    inner_layout = QVBoxLayout(inner)
    inner_edit = QLineEdit()
    blank = QLabel("background")
    inner_layout.addWidget(inner_edit)
    inner_layout.addWidget(blank)
    outer_layout.addWidget(outer_edit)
    outer_layout.addWidget(inner)
    top = QLineEdit(win)
    win.layout().addWidget(top)
    scopes = FocusScopes("#2f5bd8")
    scopes.add(outer, "outer", target=lambda: outer_edit)
    scopes.add(inner, "inner", "keys", target=lambda: inner_edit)
    win.resize(400, 300)
    win.show()
    _pump()
    yield dict(scopes=scopes, outer=outer, inner=inner, blank=blank, top=top,
               outer_edit=outer_edit, inner_edit=inner_edit)
    app.removeEventFilter(scopes)
    scopes.deleteLater()
    win.deleteLater()
    _pump()


def test_a_click_on_a_panels_background_gives_it_the_keys(window):
    QTest.mouseClick(window["blank"], Qt.MouseButton.LeftButton, pos=QPoint(5, 5))
    _pump()
    assert window["scopes"].active.name == "inner"
    assert QApplication.focusWidget() is window["inner_edit"]
    assert window["scopes"].within(window["outer"]) and window["scopes"].within(window["inner"])


def test_the_innermost_panel_wins_and_outer_shortcuts_stay_outer(window):
    window["outer_edit"].setFocus()
    _pump()
    assert window["scopes"].active.name == "outer"
    assert not window["scopes"].within(window["inner"])


def test_focus_leaving_every_panel_clears_the_frame(window):
    window["inner_edit"].setFocus()
    _pump()
    QTest.mouseClick(window["top"], Qt.MouseButton.LeftButton)
    _pump()
    assert window["scopes"].active is None


def test_every_panel_on_the_key_path_is_lit_the_inner_one_strongest(window):
    window["inner_edit"].setFocus()
    _pump()
    scopes = window["scopes"]
    assert [r.name for r in scopes.path(scopes.active)] == ["outer", "inner"]
    frames = scopes._frames
    assert frames[window["inner"]].width_px == 2 and frames[window["outer"]].width_px == 1
    assert scopes._tag.text() == "outer › inner · keys"


def test_the_path_runs_outermost_first_whatever_the_registration_order():
    app = QApplication.instance() or QApplication([])
    win = QWidget()
    outer = QWidget(win)
    middle = QWidget(outer)
    inner = QLineEdit(middle)
    scopes = FocusScopes("#2f5bd8")
    for widget, name in ((middle, "middle"), (inner, "inner"), (outer, "outer")):
        scopes.add(widget, name)
    assert [r.name for r in scopes.path(scopes.region_of(inner))] == ["outer", "middle", "inner"]
    app.removeEventFilter(scopes)
    scopes.deleteLater()
    win.deleteLater()
    _pump()


def test_the_key_tag_sits_in_the_panels_bottom_corner_off_its_toolbar(window):
    from paper_daily.desktop.focus_scope import TAG_INSET

    window["inner_edit"].setFocus()
    _pump()
    tag, inner = window["scopes"]._tag, window["inner"]
    # Along the top it covered the panel's own buttons.
    assert tag.y() + tag.height() == inner.height() - TAG_INSET
    assert tag.x() + tag.width() == inner.width() - TAG_INSET


def test_the_active_frame_drifts_and_repaints_only_its_outline(window):
    window["inner_edit"].setFocus()
    _pump()
    frames = window["scopes"]._frames
    inner, outer = frames[window["inner"]], frames[window["outer"]]
    assert inner._timer.isActive() and not hasattr(outer, "_timer")
    # The animation must not repaint the panel it outlines.
    centre = inner.rect().center()
    assert not inner.mask().contains(centre)
    assert inner.mask().contains(inner.rect().topLeft())


@pytest.mark.parametrize("registry_first", [True, False])
def test_panel_and_focus_registry_can_be_destroyed_in_either_order(monkeypatch, registry_first):
    import sys
    import traceback

    from PySide6.QtCore import QCoreApplication, QEvent

    app = QApplication.instance() or QApplication([])
    failures = []
    monkeypatch.setattr(sys, "excepthook", lambda *error: failures.append(error))
    win = QWidget()
    scopes = FocusScopes("#2f5bd8")
    region = scopes.add(win, "reading")
    scopes._activate(region)
    first, second = (scopes, win) if registry_first else (win, scopes)
    first.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    second.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    app.processEvents()
    assert failures == [], "\n".join("".join(traceback.format_exception(*e)) for e in failures)
