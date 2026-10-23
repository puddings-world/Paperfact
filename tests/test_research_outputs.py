import json
import threading
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QMessageBox
from test_research_plan import db as _db
from test_research_plan import fake_plan, paper, selection
from test_research_plan_ui import dialog as _dialog
from test_research_plan_ui import workspace as _workspace
from test_workspace_transfer_ui import _sync_runner

from paper_daily import llm
from paper_daily import research_plan as rp
from paper_daily.desktop import import_dialog

db = _db
dialog = _dialog
workspace = _workspace


def brief():
    return dict(question="How reliable is compression?", scope="Methods and counterevidence",
                inclusion=["Relevant empirical studies"], exclusion=["Unrelated tasks"],
                extraction=["Method and outcome"], appraisal="Assess full text after screening",
                open_questions=["Confirm dates and languages"])


def annotation(pid):
    return dict(id=pid, method="A described method", findings="A reported finding",
                limitations="Numbers not provided in abstract", evidence_ids=[0])


def output_plan(monkeypatch, output, depth="quick"):
    calls = fake_plan(monkeypatch, depth=depth)
    answers = [brief()] if output in ("staged", "protocol") else []
    answers += [dict(queries=["topic"])]
    answers += [dict(queries=[f"gap {i}"]) for i in range(rp.DEPTHS[depth]["rounds"] - 1)]
    answers += [selection()]
    if output == "annotated":
        answers += [dict(annotations=[annotation("p1"), annotation("p2")])]
    answers = iter(answers)
    monkeypatch.setattr(llm, "complete", lambda *a, **k: (json.dumps(next(answers)), "ok"))
    return calls


@pytest.mark.parametrize("output", list(rp.OUTPUTS))
@pytest.mark.parametrize("depth", list(rp.DEPTHS))
def test_output_and_depth_are_independent_and_preview_is_read_only(db, monkeypatch, output, depth):
    calls = output_plan(monkeypatch, output, depth)
    plan = rp.propose("Research need", depth, output=output)
    assert plan["output"] == output and plan["depth"] == depth
    assert len(calls) == rp.DEPTHS[depth]["rounds"]
    assert db.execute("SELECT count(*) FROM lists").fetchone()[0] == 0
    assert rp.OUTPUTS[output]["label"] in rp.report(plan)


@pytest.mark.parametrize("output", ["staged", "protocol"])
def test_scope_confirmation_is_required_and_saved(db, monkeypatch, output):
    output_plan(monkeypatch, output)
    plan = rp.propose("Research need", "quick", output=output)
    with pytest.raises(ValueError, match="核對"):
        rp.commit("My scope", plan, ["p1"])
    assert db.execute("SELECT count(*) FROM lists").fetchone()[0] == 0
    result = rp.commit("My scope", plan, ["p1"], confirmed=True)
    assert result["added"] == 1
    saved = db.execute("SELECT body FROM list_surveys").fetchone()[0]
    assert "已由使用者核對範圍" in saved and "仍待完成" in saved
    assert brief()["question"] in saved and brief()["open_questions"][0] in saved
    assert not plan.get("scope_confirmed")


@pytest.mark.parametrize("field,value", [("inclusion", []), ("extraction", "invented"),
                                        ("question", ""), ("open_questions", None)])
def test_invalid_scope_stops_before_search_or_writes(db, monkeypatch, field, value):
    draft = brief() | {field: value}
    monkeypatch.setattr(llm, "complete", lambda *a, **k: (json.dumps(draft), "ok"))
    monkeypatch.setattr(rp, "search", lambda *a: pytest.fail("searched before valid scope"))
    with pytest.raises(ValueError):
        rp.propose("Research need", "quick", output="protocol")
    assert db.execute("SELECT count(*) FROM lists").fetchone()[0] == 0


def test_annotations_store_exact_retrieved_passages_for_selected_papers(db, monkeypatch):
    output_plan(monkeypatch, "annotated")
    plan = rp.propose("Research need", "quick", output="annotated")
    rp.commit("Annotated", plan, ["p1"])
    saved = db.execute("SELECT body FROM list_surveys").fetchone()[0]
    assert "> Retrieved research evidence." in saved
    assert "A reported finding" in saved and "摘要層級" in saved
    assert "An opposing study" not in saved


@pytest.mark.parametrize("evidence", [[], [1], [-1], [True], ["0"], None])
def test_annotation_rejects_nonexistent_or_invalid_evidence(evidence):
    with pytest.raises(ValueError, match="摘要依據"):
        rp.validate_annotation(annotation("p1") | {"evidence_ids": evidence}, paper())


@pytest.mark.parametrize("ids", [("invented", "p2"), ("p1", "p1"), ("p1",)])
def test_annotation_rejects_unknown_duplicate_or_missing_papers(db, monkeypatch, ids):
    monkeypatch.setattr(llm, "complete", lambda *a, **k:
                        (json.dumps(dict(annotations=[annotation(p) for p in ids])), "ok"))
    with pytest.raises(ValueError):
        rp.annotate(selection()["papers"], {"p1": paper(), "p2": paper("p2")}, None, lambda _: None)
    assert db.execute("SELECT count(*) FROM lists").fetchone()[0] == 0


def test_missing_abstract_never_gets_invented_annotations(monkeypatch):
    monkeypatch.setattr(llm, "complete", lambda *a, **k: pytest.fail("invented abstract"))
    candidates = {"p1": paper() | {"abstract": None}}
    result = rp.annotate(selection(("p1",))["papers"], candidates, None, lambda _: None)
    assert result == {"p1": {"missing_abstract": True}}
    with pytest.raises(ValueError):
        rp.validate_annotation(annotation("p1"), candidates["p1"])


def test_annotation_batches_are_bounded_and_cancel_discards_pending_result(db, monkeypatch):
    ids = tuple(f"p{i}" for i in range(9))
    candidates = {pid: paper(pid, pid) for pid in ids}
    cancel, calls = threading.Event(), []

    def complete(prompt, **kwargs):
        batch = json.loads(prompt)["papers"]
        calls.append(batch)
        assert all(row["passages"][0]["text"] == "Retrieved research evidence." for row in batch)
        cancel.set()
        return json.dumps(dict(annotations=[annotation(row["id"]) for row in batch])), "ok"

    monkeypatch.setattr(llm, "complete", complete)
    with pytest.raises(rp.Cancelled):
        rp.annotate(selection(ids)["papers"], candidates, cancel, lambda _: None)
    assert len(calls) == 1 and len(calls[0]) == 4


@pytest.mark.parametrize("output", ["staged", "annotated", "protocol"])
def test_extra_output_calls_keep_the_initial_model_snapshot(db, monkeypatch, output):
    llm.save_settings(profile="fixture", backend="cli", model="initial-model")
    llm.use_profile("fixture")
    output_plan(monkeypatch, output)
    original, observed = llm.complete, []

    def complete(*args, **kwargs):
        observed.append(llm.settings(task="list_parse").model)
        llm.save_settings(profile="fixture", model="changed-model")
        return original(*args, **kwargs)

    monkeypatch.setattr(llm, "complete", complete)
    rp.propose("Research need", "quick", output=output)
    assert len(observed) == 3 and set(observed) == {"initial-model"}


def test_output_change_invalidates_preview_and_scope_confirmation(dialog, monkeypatch):
    _sync_runner(dialog, monkeypatch)
    dialog._start()
    dialog.confirm.setChecked(True)
    dialog.output.setCurrentIndex(dialog.output.findData("protocol"))
    assert dialog.plan is None and dialog.preview.isHidden()
    assert not dialog.confirm.isChecked()
    assert "PRISMA" in dialog.output.currentText()


@pytest.mark.parametrize("output", ["staged", "protocol"])
def test_scope_ui_requires_confirmation_before_saving(dialog, monkeypatch, output):
    output_plan(monkeypatch, output)
    _sync_runner(dialog, monkeypatch)
    dialog.output.setCurrentIndex(dialog.output.findData(output))
    dialog._start()
    assert dialog.confirm.isVisible()
    dialog._start()
    assert not dialog.imported and "範圍草案" in dialog.status.text()
    dialog.confirm.setChecked(True)
    dialog._start()
    assert dialog.imported and "已由使用者核對範圍" in dialog.explanation.toPlainText()


def test_fulltext_is_explicit_cancelable_and_repeated_clicks_confirm_once(dialog, monkeypatch):
    _sync_runner(dialog, monkeypatch)
    dialog._can_analyze = True
    dialog._start()
    assert dialog.fulltext.isHidden()
    dialog._start()
    assert dialog.fulltext.isVisible() and not dialog.analyze_after
    monkeypatch.setattr(QMessageBox, "question", lambda *a: QMessageBox.StandardButton.No)
    dialog.fulltext.click()
    assert not dialog.analyze_after and dialog.isVisible()
    calls = []

    def question(*args):
        calls.append(args)
        dialog._request_fulltext()  # Nested activation while confirmation is open.
        return QMessageBox.StandardButton.Yes

    monkeypatch.setattr(QMessageBox, "question", question)
    for _ in range(20):
        dialog._request_fulltext()
    assert dialog.analyze_after and not dialog.isVisible() and len(calls) == 1
    assert calls[0][-1] == QMessageBox.StandardButton.No


@pytest.mark.parametrize("analyze,imported", [(False, True), (True, True), (True, False)])
def test_analysis_handoff_occurs_only_after_dialog_and_keeps_created_id(workspace, monkeypatch,
                                                                     analyze, imported):
    called, queued = [], []

    class Dialog:
        list_id = "created-list"
        analyze_after = analyze

        def __init__(self, *a, **kw):
            self.imported = imported

        def exec(self):
            assert not called

    monkeypatch.setattr(import_dialog, "ImportListDialog", Dialog)
    monkeypatch.setattr(QTimer, "singleShot", lambda *a: queued.append(a[-1]))
    result = import_dialog.run_import({}, workspace[1], on_analysis=called.append)
    assert result == ("created-list" if imported else None) and not called
    assert len(queued) == int(analyze and imported)
    Dialog.list_id = "unrelated-list"
    for callback in queued:
        callback()
    assert called == (["created-list"] if analyze and imported else [])


def test_analysis_handoff_with_live_qt_parent_runs_once(workspace, monkeypatch):
    from PySide6.QtWidgets import QWidget

    parent, called = QWidget(), []

    class Dialog:
        imported, analyze_after, list_id = True, True, "created-list"

        def __init__(self, *a, **kw):
            pass

        def exec(self):
            pass

    monkeypatch.setattr(import_dialog, "ImportListDialog", Dialog)
    try:
        import_dialog.run_import({}, workspace[1], parent, on_analysis=called.append)
        assert not called
        QTest.qWait(10)
        assert called == ["created-list"]
    finally:
        parent.deleteLater()


def test_main_analysis_uses_created_list_and_existing_login_guard():
    from paper_daily.desktop.main import MainWindow

    opened, started = [], []
    window = SimpleNamespace(_open_list=opened.append,
                             queue_page=SimpleNamespace(_start=started.append))
    MainWindow._analyze_created_list(window, "created-list")
    assert opened == ["created-list"]
    assert started == [["analyze", "--list", "created-list", "--jobs", "1"]]
