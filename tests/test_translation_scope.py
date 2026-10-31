"""Delayed translations preserve the actual loaded source, selection and drafts."""

import copy
import hashlib
import json
import os
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from threading import Event
from types import SimpleNamespace

import pytest
from test_managed_reader_ui import open_pdf, wait_for
from test_managed_reader_ui import workspace as _workspace

from paper_daily import feedback, llm, store, sync_capture, translate
from paper_daily.desktop.translation_scope import controller
from paper_daily.manual_highlight_ops import capture_owner

workspace = _workspace


@pytest.fixture
def translating(workspace, monkeypatch):
    w = workspace
    with store.connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        sync_capture.install(conn, workspace_id="workspace", device_id="a")
    w.widget._highlight_owner = capture_owner(w.root / "papers.db", w.widget.paper.id)
    open_pdf(w)
    selection = w.widget.pdf.selection
    assert selection.focus(selection.find(0, "Alpha original"))
    real_capture, real_settings = llm.capture_connections, llm.settings
    monkeypatch.setattr(llm, "SETTINGS_PATH", w.root / "ai.json")

    class PersistedRoute(dict):
        def __setitem__(self, key, value):
            super().__setitem__(key, value)
            llm.SETTINGS_PATH.write_text(json.dumps(self), encoding="utf-8")

    route = PersistedRoute(account="fixture-a", model="fixture-one")
    llm.SETTINGS_PATH.write_text(json.dumps(route), encoding="utf-8")
    monkeypatch.setattr(
        llm, "capture_connections", lambda: (copy.deepcopy(dict(route)), {}, w.root)
    )
    cfg = SimpleNamespace(model="fixture-one")
    monkeypatch.setattr(llm, "settings", lambda **kw: cfg)
    monkeypatch.setattr(llm, "complete", lambda *a, **kw: ("MODEL RESULT", "ok"))
    monkeypatch.setattr(translate, "machine", lambda text: ("GOOGLE RESULT", "ok"))
    real_starts = [w.widget.translate_runner.start, w.widget.refine_runner.start]
    shown, calls = [], []
    original_show = selection.show_result

    def show(title, text, **kw):
        shown.append((title, text))
        original_show(title, text, **kw)

    monkeypatch.setattr(selection, "show_result", show)
    for runner in (w.widget.translate_runner, w.widget.refine_runner):

        def start(prompt, done, failed, **kw):
            calls.append(
                SimpleNamespace(prompt=prompt, done=done, failed=failed, call=kw.get("call"))
            )

        monkeypatch.setattr(runner, "start", start)
    w.widget.note_edit.setPlainText("UNSENT NOTE")
    w.widget.ask_box.setText("UNSENT QUESTION")
    result = SimpleNamespace(
        w=w,
        selection=selection,
        shown=shown,
        calls=calls,
        route=route,
        cfg=cfg,
        real_starts=real_starts,
        real_capture=real_capture,
        real_settings=real_settings,
    )
    yield result
    controller(w.widget).cancel()
    assert w.widget.note_edit.toPlainText() == "UNSENT NOTE"
    assert w.widget.ask_box.text() == "UNSENT QUESTION"


def start(t, *, model=False):
    handler = t.w.widget._translate_with_model if model else t.w.widget._translate_selection
    handler(t.selection.selected_text())
    assert t.calls
    return t.calls[-1]


def complete(call, *, deliver=True):
    with ThreadPoolExecutor(max_workers=1) as executor:
        answer, reason = executor.submit(call.call, call.prompt).result(timeout=10)
    if deliver:
        (call.done if answer else call.failed)(answer or reason)
    return answer, reason


def test_delayed_translation_rejects_clear_same_selection_aba(translating):
    t = translating
    call = start(t)
    complete(call, deliver=False)
    anchor = t.selection.anchor()
    t.selection.clear()
    assert t.selection.focus(anchor)
    call.done("STALE TRANSLATION")
    assert all(text != "STALE TRANSLATION" for _, text in t.shown)
    call.failed("offline")
    assert len(t.calls) == 1


@pytest.mark.parametrize("model", [False, True])
def test_current_translation_is_visible_without_gui_sql_or_hash(translating, monkeypatch, model):
    t = translating
    call = start(t, model=model)
    answer, _ = complete(call, deliver=False)
    assert answer == ("MODEL RESULT" if model else "GOOGLE RESULT")
    with monkeypatch.context() as patch:
        patch.setattr(llm, "capture_connections", lambda: pytest.fail("GUI config read"))
        patch.setattr(
            type(llm.SETTINGS_PATH), "read_text", lambda *a, **kw: pytest.fail("GUI JSON read")
        )
        patch.setattr(sqlite3, "connect", lambda *a, **kw: pytest.fail("GUI SQL"))
        patch.setattr(hashlib, "sha256", lambda *a, **kw: pytest.fail("GUI hash"))
        call.done(answer)
    assert t.selection.result.isVisible()
    assert t.selection.result.body.text() == answer


def test_machine_failure_hands_frozen_route_to_model_once(translating, monkeypatch):
    t = translating
    monkeypatch.setattr(translate, "machine", lambda text: (None, "unavailable"))
    first = start(t)
    for _ in range(20):
        t.w.widget._translate_selection(t.selection.selected_text())
        t.w.widget._translate_with_model(t.selection.selected_text())
    assert len(t.calls) == 1
    complete(first)
    assert len(t.calls) == 2
    complete(t.calls[1])
    assert t.selection.result.body.text() == "MODEL RESULT"


@pytest.mark.parametrize(
    "change",
    [
        "paper",
        "view",
        "account",
        "model",
        "workspace",
        "hide",
        "selection",
        "same_anchor",
        "cancel",
        "close",
    ],
)
def test_pending_scope_changes_drop_results_and_fallback(translating, change, monkeypatch):
    t = translating
    call = start(t)
    complete(call, deliver=False)
    r = t.w.widget
    if change == "paper":
        r.paper = SimpleNamespace(id="other", pdf_path=r.paper.pdf_path)
    elif change == "view":
        r._qa_epoch += 1
    elif change in ("account", "model"):
        t.route[change] = "different"
    elif change == "workspace":
        monkeypatch.setattr(store, "DB_PATH", t.w.root / "different.db")
    elif change == "hide":
        r.hide()
    elif change == "close":
        r.close()
    elif change == "selection":
        t.selection.focus(t.selection.find(0, "evidence"))
    elif change == "same_anchor":
        t.selection.focus(t.selection.anchor())
    elif change == "cancel":
        controller(r).cancel()
    call.done("STALE")
    call.failed("offline")
    assert all(text != "STALE" for _, text in t.shown)
    assert len(t.calls) == 1


def test_source_native_revision_change_after_worker_never_draws(translating):
    t = translating
    call = start(t)
    complete(call, deliver=False)
    path = t.w.widget._active_document.path
    old = path.stat()
    data = path.read_bytes()
    path.write_bytes(data.replace(b"Alpha", b"Omega"))
    os.utime(path, ns=(old.st_atime_ns, old.st_mtime_ns))
    call.done("STALE")
    assert all(text != "STALE" for _, text in t.shown)
    assert not t.selection.result.isVisible()


def test_db_edit_in_delivery_gap_is_fail_closed(translating):
    t = translating
    call = start(t)
    complete(call, deliver=False)
    with store.connect() as conn:
        conn.execute("INSERT INTO kv(key,value) VALUES('ui.translation.fixture','changed')")
    call.done("STALE")
    assert all(text != "STALE" for _, text in t.shown)


def test_historical_loaded_a_stays_translatable_when_b_becomes_primary(translating):
    t = translating
    t.w.attach("Beta replacement evidence", "second")
    loaded = t.w.widget._active_document
    assert loaded.sha256 == t.w.first.sha256
    complete(start(t, model=True))
    assert t.selection.result.body.text() == "MODEL RESULT"
    assert t.w.widget._active_document is loaded
    assert "Alpha original evidence" in t.w.widget.pdf.page_text(0)


def test_model_failure_and_exception_are_retryable_without_raw_error(translating, monkeypatch):
    t = translating
    monkeypatch.setattr(llm, "complete", lambda *a, **kw: (None, "Model unavailable"))
    complete(start(t, model=True))
    assert t.selection.result.body.text() == "Model unavailable"

    def broken(*a, **kw):
        raise RuntimeError("PRIVATE TOKEN VALUE")

    monkeypatch.setattr(llm, "complete", broken)
    complete(start(t, model=True))
    assert "PRIVATE TOKEN" not in t.selection.result.body.text()
    assert "try again" in t.selection.result.body.text()
    monkeypatch.setattr(llm, "complete", lambda *a, **kw: ("RETRIED", "ok"))
    complete(start(t, model=True))
    assert t.selection.result.body.text() == "RETRIED"
    assert len(t.calls) == 3


def test_empty_selection_or_missing_owner_creates_no_job(translating):
    t = translating
    t.w.widget._translate_selection("")
    t.w.widget._translate_with_model(" ")
    t.selection.clear()
    t.w.widget._translate_selection("Alpha original")
    assert not t.calls
    t.selection.focus(t.selection.find(0, "Alpha original"))
    t.w.widget._highlight_owner = None
    t.w.widget._translate_with_model(t.selection.selected_text())
    assert not t.calls


def test_cancel_before_dispatch_spends_nothing_and_can_retry(translating, monkeypatch):
    t = translating
    call = start(t, model=True)
    controller(t.w.widget).cancel()
    monkeypatch.setattr(llm, "complete", lambda *a, **kw: pytest.fail("Cancelled AI call"))
    assert complete(call)[0] is None
    monkeypatch.setattr(llm, "complete", lambda *a, **kw: ("RETRY", "ok"))
    complete(start(t, model=True))
    assert t.selection.result.body.text() == "RETRY"


@pytest.mark.parametrize("change", ["source", "parent", "recreated_parent"])
def test_source_and_owner_changes_during_model_drop_response(translating, monkeypatch, change):
    t = translating

    def during_call(*args, **kwargs):
        if change == "source":
            with t.w.widget._active_document.path.open("ab") as stream:
                stream.write(b"\n% changed source bytes\n")
        else:
            with store.connect() as conn, sync_capture.suppress_capture(conn):
                row = dict(
                    conn.execute(
                        "SELECT * FROM papers WHERE id=?", (t.w.widget.paper.id,)
                    ).fetchone()
                )
                conn.execute("DELETE FROM papers WHERE id=?", (row["id"],))
                if change == "recreated_parent":
                    fields = list(row)
                    conn.execute(
                        "INSERT INTO papers("
                        + ",".join(fields)
                        + ") VALUES("
                        + ",".join("?" for _ in fields)
                        + ")",
                        list(row.values()),
                    )
        return "STALE", "ok"

    monkeypatch.setattr(llm, "complete", during_call)
    answer, _ = complete(start(t, model=True))
    assert answer is None
    assert all(text != "STALE" for _, text in t.shown)
    assert not t.selection.result.isVisible()


def test_resolved_route_is_captured_before_worker_and_never_reselected(translating, monkeypatch):
    t = translating
    seen = []
    monkeypatch.setattr(llm, "complete", lambda *a, **kw: (seen.append(kw["cfg"]) or "OK", "ok"))
    call = start(t, model=True)
    monkeypatch.setattr(llm, "settings", lambda **kw: pytest.fail("Worker reselected route"))
    complete(call)
    assert seen == [t.cfg]
    assert t.selection.result.body.text() == "OK"


def test_free_translation_works_with_invalid_ai_configuration(translating, monkeypatch):
    t = translating
    monkeypatch.setattr(llm, "settings", lambda **kw: (_ for _ in ()).throw(ValueError("invalid")))
    complete(start(t))
    assert t.selection.result.body.text() == "GOOGLE RESULT"


def test_config_file_aba_and_empty_wal_have_distinct_meaning(translating):
    t = translating
    path = llm.SETTINGS_PATH
    path.write_text("A", encoding="utf-8")
    call = start(t)
    complete(call, deliver=False)
    before = path.stat()
    path.write_text("B", encoding="utf-8")
    path.write_text("A", encoding="utf-8")
    os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns))
    call.done("STALE")
    assert all(text != "STALE" for _, text in t.shown)


def test_late_old_callback_does_not_hide_or_replace_new_request(translating):
    t = translating
    old = start(t)
    complete(old, deliver=False)
    controller(t.w.widget).cancel()
    newer = start(t, model=True)
    assert t.selection.result.isVisible()
    old.done("OLD")
    assert t.selection.result.isVisible()
    complete(newer)
    assert t.selection.result.body.text() == "MODEL RESULT"


@pytest.mark.parametrize("change", ["none", "selection", "account", "hide", "close"])
def test_actual_qthread_completion_and_active_close_preserve_drafts(
    translating, monkeypatch, change
):
    t = translating
    entered, release = Event(), Event()
    seen = []

    def delayed(*args, **kwargs):
        seen.append(kwargs["cfg"])
        entered.set()
        assert release.wait(10)
        return "THREADED RESULT", "ok"

    monkeypatch.setattr(llm, "complete", delayed)
    monkeypatch.setattr(t.w.widget.refine_runner, "start", t.real_starts[1])
    t.w.widget._translate_with_model(t.selection.selected_text())
    try:
        wait_for(t.w.app, entered.is_set)
        for _ in range(10):
            t.w.widget._translate_with_model(t.selection.selected_text())
        if change == "selection":
            t.selection.clear()
        elif change == "account":
            t.route["account"] = "different"
        elif change == "hide":
            t.w.widget.hide()
        elif change == "close":
            t.w.widget.close()
        t.w.app.processEvents()
    finally:
        release.set()
        wait_for(t.w.app, lambda: not t.w.widget.refine_runner.busy)
    assert len(seen) == 1
    if change == "none":
        assert t.selection.result.body.text() == "THREADED RESULT"
        assert t.selection.result.isVisible()
    else:
        assert all(text != "THREADED RESULT" for _, text in t.shown)


def test_readonly_verification_and_empty_wal_leave_research_bytes_intact(translating):
    t = translating
    database = t.w.root / "papers.db"
    original = database.read_bytes()
    call = start(t)
    answer, _ = complete(call, deliver=False)
    assert answer == "GOOGLE RESULT"
    assert database.read_bytes() == original
    wal = database.with_name(database.name + "-wal")
    assert not wal.exists() or wal.stat().st_size == 0
    wal.write_bytes(b"")
    call.done(answer)
    assert t.selection.result.isVisible()
    assert t.selection.result.body.text() == answer
    assert database.read_bytes() == original


@pytest.mark.parametrize("change", ["account", "model"])
def test_actual_persisted_profile_and_model_switch_drop_old_delivery(
    translating, monkeypatch, change
):
    t = translating
    llm.SETTINGS_PATH.unlink()
    monkeypatch.setattr(llm, "capture_connections", t.real_capture)
    monkeypatch.setattr(llm, "settings", t.real_settings)
    llm.save_settings(
        profile="first", backend="openai", model="first-model", isolated=True, requires_key=False
    )
    llm.save_settings(
        profile="second", backend="openai", model="second-model", isolated=True, requires_key=False
    )
    llm.use_profile("first", task="translate", desktop=True)
    seen = []
    monkeypatch.setattr(llm, "complete", lambda *a, **kw: (seen.append(kw["cfg"]) or "OLD", "ok"))
    call = start(t, model=True)
    answer, _ = complete(call, deliver=False)
    assert seen[0].profile == "first" and seen[0].model == "first-model"
    if change == "account":
        llm.use_profile("second", task="translate", desktop=True)
    else:
        llm.save_settings(profile="first", model="changed-model")
    call.done(answer)
    assert all(text != "OLD" for _, text in t.shown)
    assert not t.selection.result.isVisible()


def test_provider_default_timeout_and_existing_flow_are_preserved(translating, monkeypatch):
    t = translating
    cfg = llm.Settings(backend="openai", model=None)
    monkeypatch.setattr(llm, "settings", lambda **kw: cfg)
    seen, flows = [], []

    @contextmanager
    def flow(task):
        outcome = {}
        flows.append((task, outcome))
        yield outcome

    def complete_model(*args, **kwargs):
        seen.append(kwargs)
        return "DEFAULT RESULT", "ok"

    monkeypatch.setattr(feedback, "flow", flow)
    monkeypatch.setattr(llm, "complete", complete_model)
    complete(start(t, model=True))
    assert seen[0]["cfg"] is cfg and seen[0]["cfg"].model is None
    assert seen[0]["timeout"] == 300
    assert flows == [("translate", {"success": True})]
    monkeypatch.setattr(llm, "complete", lambda *a, **kw: (None, "unavailable"))
    complete(start(t, model=True))
    assert flows[-1] == ("translate", {"success": False})


def test_environment_change_before_delivery_drops_translation(translating, monkeypatch):
    t = translating
    call = start(t, model=True)
    complete(call, deliver=False)
    monkeypatch.setenv("PAPERFACT_MODEL", "another-model")
    call.done("STALE")
    assert all(text != "STALE" for _, text in t.shown)


def test_configuration_mutation_during_capture_starts_no_job(translating, monkeypatch):
    t = translating
    original = llm.capture_connections

    def changed_capture():
        snapshot = original()
        t.route["account"] = "changed-during-capture"
        return snapshot

    monkeypatch.setattr(llm, "capture_connections", changed_capture)
    t.w.widget._translate_with_model(t.selection.selected_text())
    assert not t.calls
    assert not t.selection.result.isVisible()
