"""Visible next-call intent stays distinct from saved model-run provenance."""

import threading
from contextlib import suppress
from dataclasses import replace

import pytest
from PySide6.QtWidgets import QLabel, QPushButton
from test_claim_evidence_ui import generate, wait
from test_claim_evidence_ui import view as view_fixture
from test_claim_jobs import claims as claims_fixture
from test_claim_jobs import ready as ready_fixture
from test_claim_jobs import workspace as workspace_fixture

from paper_daily import llm
from paper_daily.ai_types import Settings

workspace = workspace_fixture
ready = ready_fixture
claims = claims_fixture


@pytest.fixture
def disclosed(claims, monkeypatch):
    state = {"cfg": Settings("fixture", model="claims-next", profile="Claims account")}

    def settings(**kwargs):
        if kwargs.get("task") == "ask":
            return Settings("fixture", model="ask-other", profile="Ask account")
        return state["cfg"]

    monkeypatch.setattr(llm, "settings", settings)
    fixture = view_fixture.__wrapped__(claims, monkeypatch)
    value = next(fixture)
    value.route_state = state
    yield value
    with suppress(StopIteration):
        next(fixture)


def label(dialog, name):
    found = dialog.findChild(QLabel, name)
    assert found is not None and found.isVisible()
    return found


def test_next_claims_intent_is_visible_before_generate_without_ask_or_external_calls(
    disclosed, monkeypatch
):
    view = disclosed
    monkeypatch.setattr(llm, "capture_connections", lambda: pytest.fail("Read captured AI"))
    monkeypatch.setattr(llm, "complete_result", lambda *a, **k: pytest.fail("Read called AI"))
    text = label(view.d, "claimsNextRoute").text()
    assert "Claims account" in text and "claims-next" in text and "fixture" in text
    assert "ask-other" not in text and "Ask account" not in text
    assert not view.claims[2]
    assert view.question.text() == "Unsent question" and view.note.toPlainText() == "Unsent notes"


@pytest.mark.parametrize("returned", ["returned", None])
def test_saved_requested_and_reported_models_do_not_follow_new_intent(
    disclosed, monkeypatch, returned
):
    view = disclosed
    complete = llm.complete_result
    monkeypatch.setattr(
        llm, "complete_result", lambda *a, **k: replace(complete(*a, **k), model=returned)
    )
    generate(view)
    original = view.d.saved
    view.route_state["cfg"] = Settings("fixture", model="future-model", profile="Future account")
    view.d.request_refresh()
    wait(view.app, lambda: not view.d.busy)
    intent = label(view.d, "claimsNextRoute").text()
    history = label(view.d, "claimsSavedRun").text()
    assert "future-model" in intent and "Future account" in intent
    assert "Requested model: claims-next" in history
    assert "Reported model: " + (returned or "Not reported") in history
    assert "future-model" not in history and "Future account" not in history
    assert view.d.saved == original and len(view.claims[2]) == 1


def test_settings_is_claims_scoped_single_flight_and_refreshes_only_current_context(
    disclosed, monkeypatch
):
    from paper_daily.desktop import ai_picker

    view, opened = disclosed, []
    button = view.d.findChild(QPushButton, "claimsModelSettings")
    assert button is not None and button.isEnabled()

    class Picker:
        def __init__(self, parent, *, task):
            opened.append(task)

        def exec(self):
            button.click()
            view.route_state["cfg"] = Settings("fixture", model="new-model", profile="New account")

        def deleteLater(self):
            pass

    monkeypatch.setattr(ai_picker, "AIPickerDialog", Picker)
    button.click()
    assert opened == ["claims"]
    assert "new-model" in label(view.d, "claimsNextRoute").text()
    assert "New account" in label(view.d, "claimsNextRoute").text()
    assert not view.claims[2] and view.d.saved is None
    assert view.question.text() == "Unsent question" and view.note.toPlainText() == "Unsent notes"


@pytest.mark.parametrize("outcome", ["cancel", "error", "paper", "close"])
def test_settings_cancel_failure_and_late_context_preserve_drafts(disclosed, monkeypatch, outcome):
    from paper_daily.desktop import ai_picker

    view, opened = disclosed, []
    original = label(view.d, "claimsNextRoute").text()

    class Picker:
        def __init__(self, parent, *, task):
            opened.append(task)

        def exec(self):
            if outcome == "error":
                raise OSError("private account detail must not be shown")
            if outcome in {"paper", "close"}:
                view.route_state["cfg"] = Settings("fixture", model="late", profile="Other account")
                if outcome == "paper":
                    view.active[1] = "different-paper"
                else:
                    view.d.close()

        def deleteLater(self):
            pass

    monkeypatch.setattr(ai_picker, "AIPickerDialog", Picker)
    view.d.findChild(QPushButton, "claimsModelSettings").click()
    assert opened == ["claims"] and not view.claims[2]
    assert view.d.saved is None
    assert view.question.text() == "Unsent question" and view.note.toPlainText() == "Unsent notes"
    text = view.d.findChild(QLabel, "claimsNextRoute").text()
    if outcome == "error":
        assert "settings unavailable" in text and "private" not in text
    else:
        assert text == original
    if outcome == "paper":
        assert not view.d.generate_button.isEnabled()
    if outcome == "close":
        assert view.d.disposed


def test_unavailable_intent_does_not_fall_back_to_ask_or_read_accounts(disclosed, monkeypatch):
    view, requested = disclosed, []

    def invalid(**kwargs):
        requested.append(kwargs.get("task"))
        raise ValueError("profile unavailable")

    monkeypatch.setattr(llm, "settings", invalid)
    monkeypatch.setattr(llm, "capture_connections", lambda: pytest.fail("Read captured accounts"))
    view.d.refresh()
    wait(view.app, lambda: not view.d.busy)
    assert requested and set(requested) == {"claims"}
    assert "settings unavailable" in label(view.d, "claimsNextRoute").text()
    assert not view.claims[2]


def test_account_change_during_captured_generation_keeps_saved_run_separate(disclosed, monkeypatch):
    view = disclosed
    entered, release = threading.Event(), threading.Event()
    complete = llm.complete_result

    def held(*args, **kwargs):
        entered.set()
        assert release.wait(10)
        return complete(*args, **kwargs)

    monkeypatch.setattr(llm, "complete_result", held)
    try:
        assert view.d.generate()
        wait(view.app, entered.is_set)
        view.route_state["cfg"] = Settings("fixture", model="later-model", profile="Later account")
        assert not view.d.generate()
        assert not view.d.findChild(QPushButton, "claimsModelSettings").isEnabled()
        view.d.request_refresh()
        release.set()
        wait(view.app, lambda: not view.d.busy and not view.d._refresh_pending)
        history = label(view.d, "claimsSavedRun").text()
        assert "Requested model: claims-next" in history and "Reported model: returned" in history
        assert "later-model" not in history
        assert "later-model" in label(view.d, "claimsNextRoute").text()
        assert len(view.claims[2]) == 1
        assert (
            view.question.text() == "Unsent question" and view.note.toPlainText() == "Unsent notes"
        )
    finally:
        release.set()


@pytest.mark.parametrize("language", ["en", "zh-TW"])
def test_compact_localized_current_and_saved_labels_keep_unreported_identity(
    disclosed, monkeypatch, language
):
    from paper_daily.desktop.claim_evidence import TEXT, ClaimEvidenceDialog

    view = disclosed
    complete = llm.complete_result
    monkeypatch.setattr(
        llm, "complete_result", lambda *a, **k: replace(complete(*a, **k), model=None)
    )
    generate(view)
    other = ClaimEvidenceDialog(
        view.ready[0],
        "paper",
        view.parent,
        legacy_root=view.ready[2].path.parent,
        owner=view.d.owner,
        document=view.ready[2],
        language=language,
    )
    other.show()
    try:
        wait(view.app, lambda: not other.busy and other.saved is not None)
        other.resize(460, 660)
        view.app.processEvents()
        intent, history = label(other, "claimsNextRoute"), label(other, "claimsSavedRun")
        assert TEXT[language]["route"] in intent.text()
        assert TEXT[language]["unreported_model"] in history.text()
        assert "claims-next" in history.text() and "returned" not in history.text()
        for item in (intent, history):
            assert item.wordWrap() and item.width() <= other.width() - 40
            assert item.height() >= item.heightForWidth(item.width())
        assert len(view.claims[2]) == 1
    finally:
        other.close()
        other.deleteLater()
        view.app.processEvents()
