"""Saved-reader change signatures reflect actual loaded data without writes."""

from contextlib import closing

import pytest
from PySide6.QtWidgets import QApplication
from test_reader_saved_inputs import work
from test_research_generation import workspace as workspace

from paper_daily import manual_highlight_ops, store
from paper_daily import reader_saved_inputs as saved
from paper_daily import reading_change_inputs as changes
from paper_daily.audit_inputs import _connect
from paper_daily.desktop.workspace_changes import WorkspaceChanges

STAMP = "2026-10-26T00:00:00+00:00"


def add(feature, body, client=None):
    if client is not None and feature == "dive":
        from paper_daily.sync_content import content_id
        from paper_daily.sync_research import paper_identity

        with client.journal.transaction() as conn:
            portable = paper_identity(conn, "paper")
        scope = dict(kind="paper", id=portable)
        payload = dict(
            scope=scope,
            feature="dive",
            key="main",
            source_document_hash=None,
            data=dict(body=body, written_at=STAMP, spec=None),
        )
        client.save(
            client.new_graph_operation(
                "research_content",
                content_id(scope, "dive", "main"),
                payload,
            )
        )
        return
    with store.connect() as conn:
        if feature == "notes":
            conn.execute(
                "INSERT INTO notes(paper_id,body,kind,created_at) VALUES(?,?,?,?)",
                ("paper", body, "note", STAMP),
            )
        elif feature == "chat":
            conn.execute(
                "INSERT INTO chat(paper_id,role,body,created_at) VALUES(?,?,?,?)",
                ("paper", "user", body, STAMP),
            )
        else:
            conn.execute("INSERT INTO dives VALUES(?,?,?,?)", ("paper", body, STAMP, None))


def read(owner):
    with closing(_connect(owner.database)) as conn:
        conn.execute("BEGIN")
        return changes.read(conn, owner)


def test_signatures_match_actual_saved_reader_snapshot_and_notes_without_mutation(workspace):
    database, _client, _document = workspace
    owner = manual_highlight_ops.capture_owner(database, "paper")
    add("dive", "Saved explanation", workspace[1])
    add("notes", "Note", workspace[1])
    before = database.read_bytes()
    result = read(owner)
    snapshot = work(saved.read, saved.capture(owner))
    with closing(_connect(database)) as conn:
        notes = [dict(row) for row in conn.execute("SELECT * FROM notes WHERE paper_id='paper'")]
    assert result == {"notes": changes.notes(notes), **changes.snapshot(snapshot, ("chat", "dive"))}
    assert database.read_bytes() == before


@pytest.mark.parametrize("feature", ["notes", "chat", "dive"])
def test_only_changed_saved_text_group_changes_its_signature(workspace, feature):
    database, _client, _document = workspace
    owner = manual_highlight_ops.capture_owner(database, "paper")
    before = read(owner)
    add(feature, "New saved text", workspace[1])
    after = read(owner)
    assert [key for key in before if before[key] != after[key]] == [feature]


def test_observer_reports_open_unlisted_paper_notes_without_list_refresh_or_duplicate_jobs(
    workspace,
):
    app = QApplication.instance() or QApplication([])
    owner = manual_highlight_ops.capture_owner(workspace[0], "paper")
    observer = WorkspaceChanges()
    observer.timer.stop()
    events, lists = [], []
    observer.research.connect(events.append)
    observer.changed.connect(lambda: lists.append(True))
    try:
        observer.watch_research(owner, "view-one")
        observer.poll()
        baseline = events[-1]
        add("notes", "Remote note", workspace[1])
        observer.poll()
        observer.poll()
        assert len(events) == 3 and events[-1] == events[-2]
        assert events[-1]["signatures"]["notes"] != baseline["signatures"]["notes"]
        assert events[-1]["token"] == "view-one" and events[-1]["paper_id"] == "paper"
        assert lists == []
        assert observer.close()
        observer.poll()
        assert len(events) == 3
    finally:
        observer.close()
        observer.deleteLater()
        app.processEvents()


def test_previous_paper_observation_cannot_deliver_to_rebound_view(workspace):
    app = QApplication.instance() or QApplication([])
    owner = manual_highlight_ops.capture_owner(workspace[0], "paper")
    observer = WorkspaceChanges()
    observer.timer.stop()
    events = []
    observer.research.connect(events.append)
    try:
        observer.watch_research(owner, "old-view")
        queued = observer._revision()
        observer.watch_research(owner, "new-view")
        observer._apply(queued)
        assert events == []
        observer.poll()
        assert len(events) == 1 and events[0]["token"] == "new-view"
    finally:
        observer.close()
        observer.deleteLater()
        app.processEvents()


def test_research_delivery_rechecks_window_before_list_refresh(workspace, tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    owner = manual_highlight_ops.capture_owner(workspace[0], "paper")
    observer = WorkspaceChanges()
    observer.timer.stop()
    lists = []
    observer.changed.connect(lambda: lists.append(True))
    try:
        observer.watch_research(owner, "view")
        queued = observer._revision()
        before = observer.revision
        # Force a list revision change in the owned queued record.
        queued = (queued[0], queued[1] + 1, *queued[2:])
        observer.research.connect(
            lambda _value: monkeypatch.setattr(store, "DB_PATH", tmp_path / "other.db")
        )
        observer._apply(queued)
        assert not lists and observer.revision == before
    finally:
        observer.close()
        observer.deleteLater()
        app.processEvents()
