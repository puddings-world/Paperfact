"""A held real adoption worker must not write after close or workspace switch."""

from threading import Event

import pytest
from test_lineage_matching_adoption_ui import app as app
from test_lineage_matching_adoption_ui import choose_matching, dump, wait
from test_lineage_matching_adoption_ui import codec as codec
from test_lineage_matching_adoption_ui import corpus as corpus
from test_lineage_matching_adoption_ui import dialog as dialog
from test_lineage_matching_adoption_ui import legacy as legacy
from test_lineage_matching_adoption_ui import native_shared as native_shared
from test_lineage_matching_adoption_ui import pair as pair
from test_lineage_matching_adoption_ui import shared as shared

from paper_daily import store
from paper_daily.desktop import lineage_import_dialog as comparison


@pytest.mark.parametrize("action", ["close", "workspace"])
def test_pending_adoption_does_not_escape_its_original_view(
    app, dialog, legacy, monkeypatch, tmp_path, action
):
    client, _importer, _archive, _receipt, _row, _review = legacy
    monkeypatch.setattr(comparison.LineageImportDialog, "exec", choose_matching)
    dialog.review()
    wait(app, lambda: dialog.reviewed and not dialog.busy)
    before = dump(client)
    original = dialog.session.apply
    entered, release = Event(), Event()

    def held(ticket):
        entered.set()
        assert release.wait(20)
        return original(ticket)

    monkeypatch.setattr(dialog.session, "apply", held)
    dialog.apply_button.click()
    other = tmp_path / "not-this-workspace.sqlite"
    try:
        wait(app, entered.is_set)
        if action == "close":
            dialog.reject()
            assert dialog.busy and dialog.isVisible()
        else:
            monkeypatch.setattr(store, "DB_PATH", other)
    finally:
        release.set()
    wait(app, lambda: not dialog.busy)
    if action == "close":
        wait(app, lambda: not dialog.isVisible())
    else:
        assert not dialog.apply_button.isEnabled() and not dialog.review_button.isEnabled()
    assert dialog.result_data is None and dump(client) == before
    assert not other.exists()
