"""The images the window's stylesheet draws (the dropdown arrow, the check mark)
live inside the package, so the build ships them, and Qt can read them: a missing
one fails silently, leaving a dropdown without an arrow and a check box that never
looks checked."""

import os
from pathlib import Path

import pytest

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QImage  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

import paper_daily  # noqa: E402
from paper_daily.desktop import main  # noqa: E402


@pytest.mark.parametrize("image", [main.CHEVRON, main.CHECK])
def test_stylesheet_images_ship_in_the_package_and_load(image):
    QApplication.instance() or QApplication([])
    path = Path(image)
    assert path.is_relative_to(Path(paper_daily.__file__).parent)
    assert not QImage(str(path)).isNull()
