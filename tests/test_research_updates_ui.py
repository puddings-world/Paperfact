import json
import sqlite3
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from types import SimpleNamespace

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from test_activity_worker_proofs import actual_source as actual_source_fixture
from test_list_navigation import window as navigation_window_fixture
from test_workspace_activity import ANCHOR, HASH, PAPER
from test_workspace_activity import activity as activity_fixture

from paper_daily.desktop import recorded_navigation
from paper_daily.desktop.research_updates import COPY, ResearchUpdatesDialog

activity = activity_fixture
actual_source = actual_source_fixture
navigation_window = navigation_window_fixture


def wait(app, predicate):
    deadline = time.monotonic() + 5
    while not predicate():
        app.processEvents()
        assert time.monotonic() < deadline, "Activity UI did not finish"
        QTest.qWait(1)
    app.processEvents()


@pytest.fixture
def view(activity, monkeypatch):
    from paper_daily import connection_vault, llm

    monkeypatch.setattr(llm, "complete", lambda *a, **k: pytest.fail("Activity called AI"))
    monkeypatch.setattr(
        connection_vault.ConnectionVault,
        "__init__",
        lambda *a, **k: pytest.fail("Activity opened native vault"),
    )
    app = QApplication.instance() or QApplication([])
    calls, draft = [], [False]
    dialog = ResearchUpdatesDialog(
        activity[1],
        language="en",
        activate=lambda row, locate: calls.append((row, locate)) or "opened",
        can_locate=lambda row: True,
        blocked=lambda: draft[0],
    )
    dialog.show()
    wait(app, lambda: not dialog.busy and dialog.trees[0].topLevelItemCount() == 1)
    yield app, dialog, calls, draft
    if dialog.busy:
        dialog._worker.ticket.cancel()
        wait(app, lambda: not dialog.busy)
    dialog.close()


def select(dialog):
    tree = dialog.trees[0]
    tree.setCurrentItem(tree.topLevelItem(0))
    return tree


def test_actual_dialog_shows_recorded_not_last_page_and_has_no_implicit_action(view, activity):
    _, dialog, calls, _ = view
    before = activity[0].read_bytes()
    assert dialog.windowTitle() == "Research activity"
    assert dialog.trees[0].topLevelItem(0).text(2) == "Saved passage"
    assert "last opened" in COPY["en"]["coverage"]
    assert not dialog.open_button.isEnabled()
    assert not dialog.open_selected()
    assert not calls and activity[0].read_bytes() == before


def test_keyboard_activation_opens_exact_selected_record_once_without_writes(view, activity):
    app, dialog, calls, _ = view
    before = activity[0].read_bytes()
    tree = select(dialog)
    tree.setFocus()
    QTest.keyClick(tree, Qt.Key.Key_Return)
    wait(app, lambda: dialog.disposed)
    assert len(calls) == 1 and calls[0][0]["paper_id"] == PAPER and not calls[0][1]
    assert activity[0].read_bytes() == before


def test_duplicate_activation_and_refresh_do_not_create_duplicate_navigation(view, monkeypatch):
    app, dialog, calls, _ = view
    select(dialog)
    service, original = dialog.service, dialog.service.resolve
    release, started = threading.Event(), threading.Event()

    def held(*args, **kwargs):
        started.set()
        assert release.wait(3)
        return original(*args, **kwargs)

    monkeypatch.setattr(service, "resolve", held)
    try:
        assert dialog.open_selected()
        assert started.wait(1)
        for _ in range(20):
            assert not dialog.open_selected() and not dialog.refresh()
        assert not calls
    finally:
        release.set()
    wait(app, lambda: dialog.disposed)
    assert len(calls) == 1


def test_failure_retry_and_bilingual_plain_text_rows(view, monkeypatch, activity):
    app, dialog, calls, _ = view
    original = dialog.service.snapshot
    monkeypatch.setattr(
        dialog.service, "snapshot", lambda ticket: (_ for _ in ()).throw(ValueError())
    )
    dialog.refresh()
    wait(app, lambda: not dialog.busy)
    assert dialog.status.text() == COPY["en"]["failed"] and dialog.refresh_button.isEnabled()
    monkeypatch.setattr(dialog.service, "snapshot", original)
    with closing(sqlite3.connect(activity[0])) as conn:
        conn.execute("UPDATE papers SET title=?", ("<script>literal 中文😀</script>",))
        conn.commit()
    dialog.refresh()
    wait(app, lambda: not dialog.busy)
    assert dialog.trees[0].topLevelItem(0).text(0) == "<script>literal 中文😀</script>"
    other = ResearchUpdatesDialog(activity[1], language="zh-TW")
    other.show()
    wait(app, lambda: not other.busy and other.trees[0].topLevelItemCount() == 1)
    assert other.windowTitle() == "研究動態" and other.open_button.text() == "開啟論文"
    other.close()
    assert not calls


@pytest.mark.parametrize("change", ["anchor", "parent", "draft", "workspace"])
def test_worker_finished_before_delivery_cannot_move_stale_source_or_discard_draft(
    view,
    activity,
    change,
):
    app, dialog, calls, draft = view
    select(dialog)
    assert dialog.open_selected(locate=True)
    worker = dialog._worker
    assert worker.wait(2000)  # Completion queued; no GUI delivery yet.
    if change == "anchor":
        with closing(sqlite3.connect(activity[0])) as conn:
            conn.execute(
                "UPDATE notes SET anchor=?", (json.dumps(dict(ANCHOR, document_hash="b" * 64)),)
            )
            conn.commit()
    elif change == "parent":
        with closing(sqlite3.connect(activity[0])) as conn:
            row = conn.execute(
                "SELECT metadata FROM paperfact_sync_graph WHERE entity_type='paper'"
            ).fetchone()
            metadata = json.loads(row[0])
            metadata["incarnation"] = "replacement-paper"
            conn.execute(
                "UPDATE paperfact_sync_graph SET metadata=? WHERE entity_type='paper'",
                (json.dumps(metadata),),
            )
            conn.commit()
    elif change == "draft":
        draft[0] = True
    else:
        dialog.service.current_path = lambda: activity[0].with_name("other.sqlite")
    wait(app, lambda: not dialog.busy)
    assert not calls
    expected = "drafts" if change == "draft" else "context" if change == "workspace" else "changed"
    assert dialog.status.text() == COPY["en"][expected]
    assert not dialog.locate_button.isEnabled()
    if change in {"anchor", "parent"}:
        assert dialog.refresh_button.isEnabled()
        dialog.refresh()
        wait(app, lambda: not dialog.busy)


def test_close_while_refresh_active_waits_for_worker_and_discards_late_render(view, monkeypatch):
    app, dialog, calls, _ = view
    original, release, started = dialog.service.snapshot, threading.Event(), threading.Event()

    def held(ticket):
        started.set()
        assert release.wait(3)
        return original(ticket)

    monkeypatch.setattr(dialog.service, "snapshot", held)
    dialog.refresh()
    assert started.wait(1)
    dialog.close()
    assert dialog._closing and dialog.busy and not dialog.disposed
    release.set()
    wait(app, lambda: dialog.disposed)
    assert not calls


def prepared_activate(window, service, row, *, locate=False):
    from paper_daily.workspace_service import Ticket

    task = recorded_navigation.capture(window, service, row, locate=locate)
    with ThreadPoolExecutor(max_workers=1) as executor:
        prepared = executor.submit(task, Ticket()).result(timeout=3)
    return recorded_navigation.activate(window, service, prepared, locate=locate)


def fake_window(activity):
    service = activity[1]
    chosen = service.resolve(service.snapshot()["continue"][0], locate=True)
    status = SimpleNamespace(
        managed=True, status="available", reason=None, paper_id=PAPER, sha256=HASH
    )
    active = SimpleNamespace(local_id=chosen["local_paper_id"], sha256=HASH)
    resolver = SimpleNamespace(inspect=lambda _: status, intact=lambda _: True)
    reader = SimpleNamespace(
        paper=SimpleNamespace(
            id=chosen["local_paper_id"], _document_status=status, _document_reader=resolver
        ),
        _active_document=active,
        _pdf_fingerprint=HASH,
        _qa_view_database=service.path,
        note_edit=SimpleNamespace(toPlainText=lambda: ""),
        ask_box=SimpleNamespace(text=lambda: ""),
        presentation_pane=SimpleNamespace(busy=False),
        runner=SimpleNamespace(busy=False),
    )
    moves, opens = [], []
    reader.pdf = SimpleNamespace(
        selection=SimpleNamespace(focus=lambda anchor: moves.append(anchor) or True)
    )

    def actual_note(paper, note):
        with closing(sqlite3.connect(activity[0])) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM notes WHERE paper_id=? AND id=?", (paper, note)
            ).fetchone()
            return {"row": dict(row)} if row else None

    window = SimpleNamespace(
        reader_page=reader,
        data=SimpleNamespace(note_for_edit=actual_note),
        stack=SimpleNamespace(setCurrentWidget=lambda _: None),
        analysis_running=lambda: False,
        open_anywhere=lambda paper: opens.append(paper) or True,
    )
    return window, chosen, moves, opens


def record_current_source(activity):
    from paper_daily.sync_documents import initialize

    target = dict(
        workspace_id="workspace",
        paper_id=PAPER,
        operation_id="fixture-pdf",
        incarnation="fixture-pdf",
        parent_incarnation="paper-created",
        sha256=HASH,
        size=24,
        media_type="application/pdf",
    )
    with closing(sqlite3.connect(activity[0])) as conn:
        conn.execute("BEGIN")
        initialize(conn)
        conn.execute(
            "INSERT INTO research_document_desired VALUES(?,?,1)", (PAPER, json.dumps(target))
        )
        conn.commit()


@pytest.mark.parametrize(
    "change", ["source", "owner", "draft", "busy", "current-source", "database"]
)
def test_passage_action_never_opens_another_reader_or_moves_wrong_source(activity, change):
    if change != "current-source":
        record_current_source(activity)
    window, selected, moves, opens = fake_window(activity)
    if change == "source":
        window.reader_page._pdf_fingerprint = "b" * 64
    elif change == "owner":
        window.reader_page.paper.id = "different-local-paper"
    elif change == "draft":
        window.reader_page.note_edit.toPlainText = lambda: "Keep these words"
    elif change == "busy":
        window.reader_page.runner.busy = True
    elif change == "database":
        window.reader_page._qa_view_database = activity[0].with_name("other.sqlite")
    assert prepared_activate(window, activity[1], selected["row"], locate=True) in {
        "source",
        "drafts",
    }
    assert not moves and not opens


def test_explicit_open_uses_guarded_read_only_navigation_and_restores_flag(activity):
    window, selected, moves, opens = fake_window(activity)
    window.reader_page.paper.id = "another-paper"
    assert prepared_activate(window, activity[1], selected["row"]) == "opened"
    assert opens == [selected["local_paper_id"]] and not moves
    assert not window._recorded_navigation


def test_explicit_open_of_loaded_paper_retains_its_source_viewport(activity):
    window, selected, moves, opens = fake_window(activity)
    assert prepared_activate(window, activity[1], selected["row"]) == "opened"
    assert not opens and not moves


def test_matching_loaded_current_source_locates_only_the_owned_note(actual_source):
    window, service, row, moves, opens = actual_source
    assert prepared_activate(window, service, row, locate=True) == "located"
    assert moves == [row["resume"]["anchor"]] and not opens


def test_main_read_only_open_does_not_record_open_or_trigger_background_work(monkeypatch):
    from paper_daily.desktop import main

    def forbidden(*_args, **_kwargs):
        pytest.fail("Read-only activity changed research or started work")

    monkeypatch.setattr(main.ui_state, "save", forbidden)
    paper = SimpleNamespace(
        id="local",
        state="pending",
        opened_at=None,
        read=False,
        _document_status=SimpleNamespace(managed=True),
    )
    loaded = []
    button = SimpleNamespace(setText=lambda _: None, show=lambda: None)
    reader = SimpleNamespace(
        presentation_pane=SimpleNamespace(save_changes=lambda: True),
        load=lambda value: loaded.append(value),
    )
    window = SimpleNamespace(
        _recorded_navigation=True,
        reader_page=reader,
        papers=[paper],
        data=SimpleNamespace(set_state=forbidden),
        top_up_dives=forbidden,
        stack=SimpleNamespace(setCurrentWidget=lambda _: None),
        _refresh_ai_summary=forbidden,
        back_btn=button,
        read_btn=button,
    )
    main.MainWindow.open_paper(window, "local")
    assert loaded == [paper] and paper.state == "pending" and paper.opened_at is None
    main.MainWindow.top_up_dives(SimpleNamespace(_recorded_navigation=True))


def test_main_close_restart_and_update_honor_activity_worker_lifetime():
    from paper_daily.desktop import main

    ignored = []
    dialog = SimpleNamespace(disposed=False, close=lambda: False)
    window = SimpleNamespace(_research_activity_dialog=dialog, findChildren=lambda _type: [])
    main.MainWindow.closeEvent(window, SimpleNamespace(ignore=lambda: ignored.append(True)))
    assert ignored == [True]
    assert not main.MainWindow._prepare_restart(window)
    assert not main.MainWindow._prepare_update(window)


def test_dialog_controls_fit_small_desktop_window_and_escape_is_safe(view):
    app, dialog, calls, _ = view
    dialog.resize(640, 400)
    app.processEvents()
    assert dialog.minimumSizeHint().width() <= 720
    for button in (
        dialog.refresh_button,
        dialog.open_button,
        dialog.locate_button,
        dialog.close_button,
    ):
        assert button.geometry().right() < dialog.width()
    assert dialog.trees[0].height() > 0
    QTest.keyClick(dialog, Qt.Key.Key_Escape)
    wait(app, lambda: dialog.disposed)
    assert not calls


def test_main_activity_menu_is_discoverable_and_reuses_one_dialog(navigation_window):
    window, app = navigation_window
    action = window.research_activity_action
    assert action in window.research_data_button.menu().actions()
    assert action.text() == COPY["zh-TW"]["title"]
    action.trigger()
    dialog = window._research_activity_dialog
    wait(app, lambda: not dialog.busy and bool(dialog.status.text()))
    assert dialog.status.text() == COPY["zh-TW"]["unavailable"]
    action.trigger()
    assert window._research_activity_dialog is dialog
    dialog.close()
