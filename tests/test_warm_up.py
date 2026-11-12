"""First-use costs paid while the window is idle."""

import sys

from PySide6.QtWidgets import QApplication

from paper_daily import diagnostics, executables
from paper_daily.desktop import warm_up


def test_warm_up_prepares_dialog_lookups_without_making_any_window(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    asked = []
    monkeypatch.setattr(executables.shutil, "which", lambda name: asked.append(name))
    # Modules are not unloaded first: a second copy of a dialog module left behind
    # makes other tests patch one copy while the app imports the other.
    windows = set(app.topLevelWidgets())
    warm_up.start().join(30)
    assert sorted(asked) == sorted(warm_up.PROGRAMS)
    assert all(module in sys.modules for module in warm_up.MODULES)
    assert set(app.topLevelWidgets()) == windows
    # The dialogs' own questions are answered from what was gathered.
    executables.which("claude")
    diagnostics.collect(tmp_path)
    assert sorted(asked) == sorted(warm_up.PROGRAMS)
