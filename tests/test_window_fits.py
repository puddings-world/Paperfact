"""The reader fits a 1280-pixel laptop screen, and its PDF toolbar never hides a
control behind the divider.

A 13-inch MacBook and a 1920-pixel Windows laptop at 150% scaling both give the app
1280 logical pixels; the reader's header used to need 1440, so the window ran off
the screen with its right-hand buttons out of reach.
"""

import os

import pytest

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QWidget  # noqa: E402

from paper_daily import llm, store  # noqa: E402
from paper_daily.desktop import fonts  # noqa: E402
from paper_daily.desktop import main as m  # noqa: E402

SCREEN = 1280
# Room for the window frame Windows draws outside the client area.
FRAME = 16


@pytest.fixture
def reader(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    m.style(app)
    fonts.load()
    monkeypatch.setattr(store, "DB_PATH", tmp_path / "papers.db")
    monkeypatch.setattr(llm, "SETTINGS_PATH", tmp_path / "llm.json")
    store.init_db()
    with store.connect() as conn:
        store.upsert_papers(
            conn, [dict(id="p", title="A paper", venue="ICLR", year=2026, source="test")]
        )
        conn.execute("INSERT INTO lists(id,name,created_at) VALUES ('l','A list','now')")
        conn.execute(
            "INSERT INTO list_papers(list_id,paper_id,position,added_at) VALUES ('l','p',0,'now')"
        )
    monkeypatch.setattr(m.ReaderPage, "_check_resources", lambda self: None)
    monkeypatch.setattr(m.ReaderPage, "_prepare_reading_highlights", lambda self: None)
    window = m.MainWindow()
    monkeypatch.setattr(window, "top_up_dives", lambda *a, **k: None)
    window.show()
    window.open_paper("p")
    for _ in range(10):
        app.processEvents()
    yield window, app
    window.close()
    window.deleteLater()
    app.processEvents()


def test_the_reader_fits_a_laptop_screen(reader):
    window, _app = reader
    assert window.minimumSizeHint().width() <= SCREEN - FRAME


def test_a_narrow_pdf_side_wraps_its_toolbar(reader):
    window, app = reader
    page = window.reader_page
    page.split.setSizes([300, 900])
    for _ in range(5):
        app.processEvents()
    bar = page.pdf_bar
    assert bar.height() > 50  # two rows
    shown = [w for w in bar.findChildren(QWidget) if w.isVisible() and w.width() > 0]
    assert page.find_box in shown and page.ask_page_btn in shown
    for widget in shown:
        assert widget.geometry().right() <= bar.width(), widget


def test_sizes_are_pixels_so_every_platform_draws_the_same():
    QApplication.instance() or QApplication([])
    title = fonts.font(fonts.SERIF, 16)
    # 16 points as Windows draws them, whatever the platform's own points are.
    assert title.pixelSize() == 21 and title.pointSizeF() < 0
    app = QApplication.instance()
    m.style(app)
    assert app.font().pixelSize() == fonts.UI_PIXELS
    assert app.font().families()[0] == fonts.SANS[0]


def test_the_pdf_side_opens_with_one_toolbar_row_and_more_tools_folded(reader):
    window, app = reader
    page = window.reader_page
    folded = (page.pdf_tools, page.highlight_row, page.open_external, page.layers_button,
              page.auto_highlights, page.reading_positions.remember_button)
    assert not any(widget.isVisible() for widget in folded)
    assert page.find_box.isVisible() and page.ask_page_btn.isVisible()
    page.more_tools.click()
    app.processEvents()
    assert all(widget.isVisible() for widget in folded)
    with store.connect() as conn:
        assert m.ui_state.read(conn, "ui.pdf_tools") == "1"
    page.more_tools.click()
    app.processEvents()
    assert not page.pdf_tools.isVisible() and not page.highlight_row.isVisible()


def test_page_record_keys_work_while_their_buttons_are_folded(reader):
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    window, app = reader
    page = window.reader_page
    pressed = []
    page.reading_positions.remember_button.setEnabled(True)
    page.reading_positions.remember_button.clicked.connect(lambda: pressed.append("remember"))
    assert not page.reading_positions.remember_button.isVisible()
    QTest.keyClick(page, Qt.Key.Key_M,
                   Qt.KeyboardModifier.AltModifier | Qt.KeyboardModifier.ShiftModifier)
    app.processEvents()
    assert "remember" in pressed


def test_one_key_folds_and_restores_the_toolbar_and_paper_details(reader):
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    window, app = reader
    header = window.reader_page.paper_header
    assert header.isVisible() and m.TOP_TOGGLE_KEY == "Ctrl+Shift+H"
    keys = Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier
    QTest.keyClick(window, Qt.Key.Key_H, keys)
    app.processEvents()
    assert not header.isVisible() and window.compact_header.isVisible()
    assert "Ctrl+Shift+H" in window.top_toggle.toolTip() or "⇧" in window.top_toggle.toolTip()
    QTest.keyClick(window, Qt.Key.Key_H, keys)
    app.processEvents()
    assert header.isVisible() and not window.compact_header.isVisible()
