"""The shipped typefaces install only as the pinned files, and the UI names
shortcuts the way the platform does."""

from __future__ import annotations

import os

import pytest

from paper_daily import fonts


def test_a_download_that_is_not_the_pinned_file_is_refused(tmp_path, monkeypatch):
    monkeypatch.setattr(fonts, "FONT_DIR", tmp_path / "fonts")
    monkeypatch.setattr(fonts, "fetch", lambda url, **k: b"something else")
    with pytest.raises(ValueError, match="sha256"):
        fonts.install()
    assert not (tmp_path / "fonts").exists() or not any((tmp_path / "fonts").iterdir())


def test_install_keeps_what_is_there_and_fetches_the_rest(tmp_path, monkeypatch):
    monkeypatch.setattr(fonts, "FONT_DIR", tmp_path)
    blobs = {f["url"]: f["family"].encode() for f in fonts.FONTS}
    monkeypatch.setattr(
        fonts, "FONTS", tuple(f | {"sha256": fonts._sha256(blobs[f["url"]])} for f in fonts.FONTS)
    )
    first = fonts.FONTS[0]
    (tmp_path / first["file"]).write_bytes(b"already here")
    fetched = []
    monkeypatch.setattr(fonts, "fetch", lambda url, **k: fetched.append(url) or blobs[url])
    assert fonts.install() == [f["family"] for f in fonts.FONTS[1:]]
    assert first["url"] not in fetched and fonts.missing() == []


def test_shortcut_labels_follow_the_platform(monkeypatch):
    pytest.importorskip("PySide6")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtGui import QKeySequence
    from PySide6.QtWidgets import QApplication

    from paper_daily.desktop import fonts as ui

    # The platform's key bindings come from its theme, which needs an application.
    QApplication.instance() or QApplication([])

    label = ui.key(QKeySequence.StandardKey.Copy)
    assert label == ("⌘C" if ui.MAC else "Ctrl+C")
    assert ui.key("Ctrl+D") == ("⌘D" if ui.MAC else "Ctrl+D")
    assert "'Noto Sans TC'" in ui.css() and ui.css(ui.MONO).endswith("monospace")
