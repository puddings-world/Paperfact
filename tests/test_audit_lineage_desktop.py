"""Real saved Lineage cards navigate only the actual loaded source."""

import pytest
from PySide6.QtWidgets import QApplication, QLabel
from test_audit_lineage import equal_originals as equal_originals
from test_audit_ui import wait
from test_lineage_lifecycle import active as active
from test_research_lineage import corpus as corpus

from paper_daily.desktop.research_audit import FEATURE_TEXT, TEXT, AuditDialog
from paper_daily.document_reader import from_workspace


@pytest.mark.parametrize("language", ["en", "zh-TW"])
def test_lineage_cards_explain_other_originals_and_only_navigate_verified_loaded_source(
    active, corpus, language
):
    owner, _row = active
    app = QApplication.instance() or QApplication([])
    document = from_workspace(corpus[0], legacy_root=corpus[1]).resolve("focal")
    calls = []
    before = owner.database.read_bytes()
    dialog = AuditDialog(
        owner.database,
        owner.paper_id,
        document=document,
        owner=owner,
        current_view=lambda: (owner.database, owner.paper_id, document),
        source_callback=lambda source: calls.append(source) or True,
        language=language,
    )
    try:
        dialog.show()
        wait(app, lambda: not dialog.busy and dialog.report is not None)
        assert dialog.report is not None
        dialog.filter.setChecked(False)
        assert len(dialog.sections) == len(dialog.report["items"]) == 3
        assert FEATURE_TEXT[language]["lineage"] in str(
            [section.button.text() for section in dialog.sections]
        )
        labels = [label.text() for label in dialog.findChildren(QLabel)]
        assert TEXT[language]["source_mismatch"] in labels
        assert TEXT[language]["limits"] in labels
        located = [check for check in dialog.report["checks"] if check["state"] == "located"]
        mismatches = [
            check for check in dialog.report["checks"] if check["state"] == "source_mismatch"
        ]
        assert located and mismatches
        assert len(dialog.source_buttons) == len(located)
        for check in mismatches:
            assert dialog.open_source(check) is False
        assert calls == []
        dialog.source_buttons[0].click()
        wait(app, lambda: not dialog.busy)
        assert len(calls) == 1 and calls[0]["document_hash"] == document.sha256
        assert calls[0]["text"] == located[0]["quote"]
        assert owner.database.read_bytes() == before
    finally:
        if dialog.busy:
            dialog.cancel()
            wait(app, lambda: not dialog.busy)
        dialog.close()
        dialog.deleteLater()
        app.processEvents()


@pytest.mark.parametrize("language", ["en", "zh-TW"])
def test_equal_byte_other_owner_findings_are_visible_and_never_navigate(equal_originals, language):
    owner, _row, corpus = equal_originals
    app = QApplication.instance() or QApplication([])
    document = from_workspace(corpus[0], legacy_root=corpus[1]).resolve("focal")
    calls = []
    before = owner.database.read_bytes()
    dialog = AuditDialog(
        owner.database,
        owner.paper_id,
        document=document,
        owner=owner,
        current_view=lambda: (owner.database, owner.paper_id, document),
        source_callback=lambda source: calls.append(source) or True,
        language=language,
    )
    try:
        dialog.show()
        wait(app, lambda: not dialog.busy and dialog.report is not None)
        dialog.filter.setChecked(False)
        foreign = [
            check for check in dialog.report["checks"] if check["state"] == "source_owner_mismatch"
        ]
        assert foreign and TEXT[language]["source_owner_mismatch"] in [
            label.text() for label in dialog.findChildren(QLabel)
        ]
        for check in foreign:
            assert dialog.open_source(check) is False
        assert calls == []
        assert len(dialog.source_buttons) == sum(
            check["state"] == "located" for check in dialog.report["checks"]
        )
        dialog.source_buttons[0].click()
        wait(app, lambda: not dialog.busy)
        assert len(calls) == 1 and calls[0]["document_hash"] == document.sha256
        assert owner.database.read_bytes() == before
    finally:
        if dialog.busy:
            dialog.cancel()
            wait(app, lambda: not dialog.busy)
        dialog.close()
        dialog.deleteLater()
        app.processEvents()
