"""Completed single-slide jobs survive navigation, storage errors and detached UI."""

import json
import sqlite3
import threading
import time
from contextlib import closing
from copy import deepcopy
from dataclasses import asdict

import pytest
from test_presentation_pane import pane as pane_fixture
from test_slide_revise_ui import finish, setup_revision
from test_sync_files import LOCAL, save_current
from test_sync_files import codec as codec_fixture
from test_sync_files import pair as pair_fixture

from paper_daily import llm, presentations, slide_revision, store
from paper_daily.ai_types import Completion

pane = pane_fixture
codec = codec_fixture
pair = pair_fixture


def retained(widget):
    job = widget._revision_job
    record = json.loads(job.receipt.read_text(encoding="utf-8"))
    slide_revision.validate_request_record(record)
    return job, record


@pytest.mark.parametrize("switch", ["page", "paper", "edit", "close", "workspace"])
def test_completed_output_persists_before_navigation_callback(pane, monkeypatch, switch):
    widget, callbacks, _ = setup_revision(pane, monkeypatch)
    original_id = widget.paper_id
    widget.canvas.revise_button.click()
    if switch == "page":
        widget._selected(1)
    elif switch == "paper":
        widget.paper_id = "another-paper"
    elif switch == "edit":
        widget.slide_title.setText("Unsaved human draft")
        widget._dirty = True
    elif switch == "workspace":
        monkeypatch.setattr(store, "DB_PATH", pane[3] / "another.sqlite")
    else:
        widget.close()
    visible = widget.deck.to_dict()
    answer, why = callbacks["call"]("")
    assert answer, why
    job, record = retained(widget)
    assert record["status"] == "accepted"
    assert record["instruction"] and record["prompt"] and record["system"]
    assert record["result"]["slides"][0]["title"] == "Clinical result"
    assert presentations.load_deck(original_id, "guide").slides[0].title == "Clinical result"
    # Deliberately omit callback for closed UI. Persistence is already complete.
    if switch != "close":
        callbacks["done"](answer)
        assert widget.deck.to_dict() == visible
        if switch == "edit":
            assert widget.slide_title.text() == "Unsaved human draft"
    assert len(list(job.receipt.parent.glob("*.json"))) == 1


def test_storage_failure_retains_result_and_restart_retry_does_not_call_ai(pane, monkeypatch):
    widget, callbacks, _ = setup_revision(pane, monkeypatch)
    widget.canvas.revise_button.click()
    save = presentations.save_deck
    monkeypatch.setattr(
        presentations, "save_deck", lambda *a, **k: (_ for _ in ()).throw(OSError("disk fixture"))
    )
    finish(callbacks)
    job, record = retained(widget)
    assert record["status"] == "candidate" and "disk fixture" in record["reason"]
    assert widget.deck.slides[0].title != "Clinical result"
    monkeypatch.setattr(presentations, "save_deck", save)
    monkeypatch.setattr(llm, "complete_result", lambda *a, **k: pytest.fail("Retry invoked AI"))
    reopened = slide_revision.load_request(
        job.receipt,
        database=job.database,
        deck_root=presentations.DECK_DIR,
        figures_root=presentations.FIG_DIR,
    )
    assert slide_revision.publish(reopened) == "accepted"
    assert slide_revision.publish(reopened) == "accepted"
    assert presentations.load_deck(widget.paper_id, "guide").slides[0].title == "Clinical result"
    assert len(list(job.receipt.parent.glob("*.json"))) == 1


def test_newer_saved_deck_is_not_replaced_by_completed_job(pane, monkeypatch):
    widget, callbacks, _ = setup_revision(pane, monkeypatch)
    original = llm.complete_result

    def model(*args, **kwargs):
        newer = deepcopy(widget.deck)
        newer.slides[1].title = "Human saved another slide"
        presentations.save_deck(newer)
        return original(*args, **kwargs)

    monkeypatch.setattr(llm, "complete_result", model)
    widget.canvas.revise_button.click()
    finish(callbacks)
    job, record = retained(widget)
    assert record["status"] == "candidate"
    assert record["result"]["slides"][0]["title"] == "Clinical result"
    saved = presentations.load_deck(widget.paper_id, "guide")
    assert saved.slides[1].title == "Human saved another slide"
    assert saved.slides[0].title != "Clinical result"
    assert slide_revision.publish(job) == "candidate"


def test_original_assets_survive_files_and_global_roots_changing_during_model(pane, monkeypatch):
    widget, callbacks, _ = setup_revision(pane, monkeypatch)
    original = llm.complete_result
    original_root = presentations.DECK_DIR

    def model(*args, **kwargs):
        (presentations.FIG_DIR / "ref_paper" / "table.png").unlink()
        monkeypatch.setattr(presentations, "DECK_DIR", original_root.parent / "other-decks")
        monkeypatch.setattr(presentations, "FIG_DIR", original_root.parent / "other-figures")
        return original(*args, **kwargs)

    monkeypatch.setattr(llm, "complete_result", model)
    widget.canvas.revise_button.click()
    finish(callbacks)
    job, record = retained(widget)
    assert record["status"] == "accepted"
    assert record["figures"]["figure:2"]["sha256"]
    assert job.destination.is_file()
    saved = json.loads(job.destination.read_text(encoding="utf-8"))
    assert (job.destination.parent / "assets" / saved["figures"][0]["asset"]).is_file()
    assert not presentations.DECK_DIR.exists()


def test_database_replacement_receives_no_tables_or_research(pane, monkeypatch, tmp_path):
    widget, callbacks, _ = setup_revision(pane, monkeypatch)
    database = tmp_path / "original.sqlite"
    with closing(sqlite3.connect(database)) as conn, conn:
        conn.execute("CREATE TABLE marker(value)")
    monkeypatch.setattr(store, "DB_PATH", database)
    original = llm.complete_result

    def model(*args, **kwargs):
        database.rename(tmp_path / "old.sqlite")
        with closing(sqlite3.connect(database)) as conn, conn:
            conn.execute("CREATE TABLE replacement(value)")
        return original(*args, **kwargs)

    monkeypatch.setattr(llm, "complete_result", model)
    widget.canvas.revise_button.click()
    finish(callbacks)
    _, record = retained(widget)
    assert record["status"] == "candidate"
    with sqlite3.connect(database) as conn:
        assert conn.execute("SELECT name FROM sqlite_master").fetchall() == [("replacement",)]


@pytest.mark.parametrize("navigation", ["page", "paper", "workspace", "close"])
def test_real_worker_close_and_duplicate_clicks_keep_one_completed_receipt(
    pane, monkeypatch, navigation
):
    widget = pane[0]
    original_id = widget.paper_id
    real_start = widget.runner.start
    widget, _, app = setup_revision(pane, monkeypatch)
    monkeypatch.setattr(widget.runner, "start", real_start)
    original = llm.complete_result
    entered, release = threading.Event(), threading.Event()
    calls = []

    def model(*args, **kwargs):
        calls.append(kwargs["cfg"])
        entered.set()
        assert release.wait(10)
        return original(*args, **kwargs)

    monkeypatch.setattr(llm, "complete_result", model)
    widget.canvas.revise_button.click()
    for _ in range(10):
        widget._revise_current_slide()
    deadline = time.monotonic() + 10
    while not entered.is_set() and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.01)
    assert entered.is_set()
    if navigation == "page":
        widget._selected(1)
    elif navigation == "paper":
        widget.paper_id = "other-paper"
    elif navigation == "workspace":
        monkeypatch.setattr(store, "DB_PATH", pane[3] / "other-workspace.sqlite")
    else:
        widget.close()
    release.set()
    assert widget.runner._thread.wait(10000)
    app.processEvents()
    _, record = retained(widget)
    assert len(calls) == 1 and record["status"] == "accepted"
    assert presentations.load_deck(original_id, "guide").slides[0].title == "Clinical result"


def _managed_response(monkeypatch, value, during=lambda: None):
    def model(*args, **kwargs):
        during()
        slide = asdict(value.slides[0])
        slide["elements"] = None
        slide["title"] = "Revised managed slide"
        return Completion(json.dumps({"slide": slide, "summary": "Updated"}))

    monkeypatch.setattr(llm, "complete_result", model)


def test_managed_binding_and_old_figure_closure_survive_global_workspace_switch(
    pair, codec, monkeypatch
):
    _, a, b, *_ = pair
    value = codec[0]
    save_current(pair, value)
    loaded = presentations.load_deck(LOCAL, "guide")
    original_operation = deepcopy(loaded._file_operation)
    job = slide_revision.begin(loaded, 0, "Clarify the method")
    _managed_response(
        monkeypatch, loaded, lambda: monkeypatch.setattr(store, "DB_PATH", b.journal.path)
    )
    answer, reason = slide_revision.run(job)
    assert answer, reason
    assert job.record["status"] == "accepted"
    assert job.record["file_operation"] == original_operation
    assert job.updated._file_operation["operation_id"] == job.request_id
    with b.journal.transaction() as conn:
        assert conn.execute("SELECT COUNT(*) FROM research_file_versions").fetchone()[0] == 0
    monkeypatch.setattr(store, "DB_PATH", a.journal.path)
    assert presentations.load_deck(LOCAL, "guide").slides[0].title == "Revised managed slide"


def test_managed_changed_deck_retains_candidate_with_original_sources(pair, codec, monkeypatch):
    value = codec[0]
    save_current(pair, value)
    loaded = presentations.load_deck(LOCAL, "guide")
    job = slide_revision.begin(loaded, 0, "Clarify")

    def newer():
        changed = presentations.load_deck(LOCAL, "guide")
        changed.title = "Newer deck title"
        presentations.save_deck(changed)

    _managed_response(monkeypatch, loaded, newer)
    assert slide_revision.run(job)[0]
    assert job.record["status"] == "candidate"
    assert presentations.load_deck(LOCAL, "guide").title == "Newer deck title"
    assert job.record["result"]["slides"][0]["title"] == "Revised managed slide"
    slide_revision.validate_request_record(job.record)


def test_corrupt_captured_image_is_rejected_before_any_retry(pane, monkeypatch):
    widget, callbacks, _ = setup_revision(pane, monkeypatch)
    widget.canvas.revise_button.click()
    finish(callbacks)
    job, record = retained(widget)
    record["figures"]["figure:2"]["sha256"] = "0" * 64
    job.receipt.write_text(json.dumps(record), encoding="utf-8")
    with pytest.raises(ValueError, match="hash"):
        slide_revision.load_request(
            job.receipt,
            database=job.database,
            deck_root=presentations.DECK_DIR,
            figures_root=presentations.FIG_DIR,
        )


def test_retry_button_saves_existing_result_and_one_undo_without_another_model(pane, monkeypatch):
    widget, callbacks, _ = setup_revision(pane, monkeypatch)
    before = widget.deck.to_dict()
    save = presentations.save_deck
    widget.canvas.revise_button.click()
    monkeypatch.setattr(
        presentations, "save_deck", lambda *a, **k: (_ for _ in ()).throw(OSError("retry me"))
    )
    finish(callbacks)
    identity = widget._revision_job.request_id
    assert widget.canvas.revise_button.text() == "重試儲存"
    monkeypatch.setattr(presentations, "save_deck", save)
    monkeypatch.setattr(llm, "complete_result", lambda *a, **k: pytest.fail("Retry called AI"))
    widget.canvas.revise_button.click()
    finish(callbacks)
    assert widget._revision_job.request_id == identity
    assert widget.deck.slides[0].title == "Clinical result"
    assert len(widget._undo) == 1
    widget._undo_edit()
    assert widget.deck.to_dict() == before


def test_account_model_and_credentials_are_pinned_but_not_serialized(pane, monkeypatch):
    widget, callbacks, _ = setup_revision(pane, monkeypatch)
    monkeypatch.setattr(llm, "SETTINGS_PATH", pane[3] / "routing.json")
    llm.save_settings(backend="codex", model="before", account_id="1" * 32)
    original = llm.complete_result
    received = []

    def model(*args, **kwargs):
        received.append((kwargs["cfg"].account_id, kwargs["cfg"].model))
        return original(*args, **kwargs)

    monkeypatch.setattr(llm, "complete_result", model)
    widget.canvas.revise_button.click()
    llm.save_settings(backend="codex", model="after", account_id="2" * 32)
    finish(callbacks)
    assert received == [("1" * 32, "before")]
    record = widget._revision_job.receipt.read_text(encoding="utf-8")
    assert "1" * 32 not in record and "2" * 32 not in record
    assert "api_key" not in record and "connections" not in record


def test_original_paper_delete_recreate_is_a_candidate_even_with_identical_row(pane, monkeypatch):
    widget, callbacks, _ = setup_revision(pane, monkeypatch)
    database = pane[3] / "research.sqlite"
    with closing(sqlite3.connect(database)) as conn, conn:
        conn.executescript(store.SCHEMA)
        conn.execute(
            "INSERT INTO papers(id,title,venue,year,source,title_key) VALUES(?,?,?,?,?,?)",
            (widget.paper_id, "Title", "Venue", 2026, "fixture", "title"),
        )
    monkeypatch.setattr(store, "DB_PATH", database)
    original = llm.complete_result

    def model(*args, **kwargs):
        with closing(sqlite3.connect(database)) as conn, conn:
            row = conn.execute("SELECT * FROM papers").fetchone()
            conn.execute("DELETE FROM papers")
            conn.execute("INSERT INTO papers VALUES(" + ",".join("?" for _ in row) + ")", row)
        return original(*args, **kwargs)

    monkeypatch.setattr(llm, "complete_result", model)
    widget.canvas.revise_button.click()
    finish(callbacks)
    assert retained(widget)[1]["status"] == "candidate"


def test_managed_commit_then_activation_failure_retries_same_operation(pair, codec, monkeypatch):
    from paper_daily import sync_deck_publication as publication

    value = codec[0]
    save_current(pair, value)
    loaded = presentations.load_deck(LOCAL, "guide")
    job = slide_revision.begin(loaded, 0, "Clarify")
    _managed_response(monkeypatch, loaded)
    materialize = publication.materialize
    monkeypatch.setattr(
        publication, "materialize", lambda *a: (_ for _ in ()).throw(OSError("activation fixture"))
    )
    assert slide_revision.run(job)[0]
    assert job.record["status"] == "candidate"
    monkeypatch.setattr(publication, "materialize", materialize)
    monkeypatch.setattr(llm, "complete_result", lambda *a, **k: pytest.fail("Retry called AI"))
    reopened = slide_revision.load_request(
        job.receipt,
        database=job.database,
        deck_root=presentations.DECK_DIR,
        figures_root=presentations.FIG_DIR,
    )
    assert slide_revision.publish(reopened) == "accepted"
    with pair[1].journal.transaction() as conn:
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM research_file_versions WHERE operation_id=?",
                (job.request_id,),
            ).fetchone()[0]
            == 1
        )
    assert presentations.load_deck(LOCAL, "guide").slides[0].title == "Revised managed slide"


def test_manual_save_between_initial_hash_check_and_write_is_preserved(pane, monkeypatch):
    widget, callbacks, _ = setup_revision(pane, monkeypatch)
    widget.canvas.revise_button.click()
    save = presentations.save_deck
    raced = []

    def save_with_concurrent_edit(deck, **kwargs):
        if kwargs.get("request_id") and not raced:
            raced.append(True)
            manual = deepcopy(widget.deck)
            manual.slides[1].title = "Concurrent human save"
            save(manual)
        return save(deck, **kwargs)

    monkeypatch.setattr(presentations, "save_deck", save_with_concurrent_edit)
    finish(callbacks)
    assert retained(widget)[1]["status"] == "candidate"
    assert (
        presentations.load_deck(widget.paper_id, "guide").slides[1].title == "Concurrent human save"
    )
    assert widget._revision_job.record["result"]["slides"][0]["title"] == "Clinical result"


def test_adopted_revision_can_add_new_material_after_worker_snapshot(pane, monkeypatch):
    widget, callbacks, _ = setup_revision(pane, monkeypatch)
    widget.canvas.revise_button.click()
    finish(callbacks)
    assert not any(name.startswith("_revision_") for name in vars(widget.deck))
    widget.deck.figures.append(dict(id="figure:new", file="table.png", label="New figure"))
    widget.deck.sources.append(dict(id="figure:new", label="New figure", kind="figure"))
    widget.deck.slides[0].figure = "figure:new"
    widget.deck.slides[0].sources = ["figure:new"]
    presentations.save_deck(widget.deck)
    loaded = presentations.load_deck(widget.paper_id, "guide")
    assert loaded.slides[0].figure == "figure:new"
    assert presentations.figure_bytes(loaded, "figure:new").startswith(b"\x89PNG")


def test_open_deck_from_rebound_workspace_is_rejected_before_generation(pair, codec):
    value = codec[0]
    save_current(pair, value)
    loaded = presentations.load_deck(LOCAL, "guide")
    loaded._file_observation["workspace_id"] = "another-workspace"
    with pytest.raises(ValueError, match="reopen"):
        slide_revision.begin(loaded, 0, "Do not spend AI on this stale editor")
