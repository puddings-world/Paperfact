"""Historical saved variants are readable and exportable without write authority."""

from contextlib import closing

import pytest
from test_enrollment_review_draft_journey import decision as decision
from test_enrollment_review_draft_journey import draft_variants as draft_variants
from test_enrollment_review_draft_journey import prepare
from test_enrollment_review_draft_journey import source as source
from test_review_dialog import app as app
from test_review_dialog import opened, wait

from paper_daily import enrollment_history
from paper_daily import research_generation as generation


@pytest.mark.parametrize(
    "language,label", [("en", "Saved historical draft"), ("zh-TW", "已存歷史草稿")]
)
def test_real_copied_variants_show_exact_text_and_disable_unsupported_decisions(
    draft_variants, tmp_path, app, language, label
):
    value = draft_variants
    result = prepare(value, tmp_path)
    database = result["database"]
    with closing(generation._connect(database)) as conn:
        before = enrollment_history.archived(conn)
        pending = [
            tuple(row) for row in conn.execute("SELECT envelope FROM paperfact_sync_operations")
        ]
    view = opened(app, database, language=language)
    try:
        assert view.list.count() == 2
        seen = set()
        for index in range(view.list.count()):
            item = view.list.item(index)
            assert item.text().startswith(label + " · ")
            key = tuple(item.data(256))
            view.list.setCurrentRow(index)
            wait(
                app, lambda key=key: view.preview is not None and view.preview.data["id"] == key[1]
            )
            assert view.draft.isReadOnly()
            assert not view.apply.isEnabled() and not view.keep.isEnabled()
            assert not view.target_button.isEnabled() and not view.draft_history.isVisible()
            seen.add(view.draft.toPlainText())
            for keep in (False, True):
                with pytest.raises(ValueError, match="Historical draft"):
                    view.service.decide(view.preview, keep=keep, body="Never overwrite research")
            view.copy.click()
            wait(app, lambda: not view.busy)
            text = app.clipboard().text()
            assert view.draft.toPlainText() in text
            assert str(value["database"]) not in text and "database_identity" not in text
        assert seen == {"First saved human interpretation", "Second independent draft"}
    finally:
        view.close()
        wait(app, lambda: view.disposed)
    with closing(generation._connect(database)) as conn:
        assert enrollment_history.archived(conn) == before
        assert [
            tuple(row) for row in conn.execute("SELECT envelope FROM paperfact_sync_operations")
        ] == pending
        assert not conn.execute(
            "SELECT 1 FROM sqlite_master WHERE name='research_review_receipts'"
        ).fetchone()
