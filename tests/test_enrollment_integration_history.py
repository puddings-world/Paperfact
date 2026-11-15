"""Actual CLI/MCP import work enrolls without granting old request authority."""

import json
import sqlite3
from contextlib import closing
from copy import deepcopy
from pathlib import Path
from uuid import uuid4

import pytest
from test_enrollment_dialog import app as app
from test_enrollment_dialog import wait
from test_workspace_enrollment import pdf, prepare, rows
from test_workspace_enrollment import source as source

from paper_daily import enrollment_history, store, sync_recovery, updates
from paper_daily import local_operations as ops
from paper_daily.desktop.enrollment_dialog import EnrollmentDialog
from paper_daily.document_reader import DocumentReader
from paper_daily.workspace_enrollment import EnrollmentService
from paper_daily.workspace_service import Cancelled, SnapshotChanged, Ticket


@pytest.fixture
def imported(source, monkeypatch):
    monkeypatch.setattr(store, "DB_PATH", source)
    monkeypatch.setattr(store, "ensure_dirs", lambda: None)
    proposed = ops.propose("Agent reading route", [
        {"title": "Agent-selected paper", "doi": "10.1234/enrollment", "year": 2026},
        {"title": "Second agent-selected paper", "doi": "10.1234/second", "year": 2025},
    ])
    first = ops.commit(proposed["preview_id"], "agent-import-one", ["1", "0"])
    appended = ops.propose("Append", [{"title": "Agent-selected paper",
        "doi": "10.1234/enrollment"}], target_list_id=first["list_id"])
    ops.commit(appended["preview_id"], "agent-import-two", ["0"])
    original = pdf(source)
    with closing(sqlite3.connect(source)) as conn, conn:
        conn.row_factory = sqlite3.Row
        updates.check(conn, current="0.4.4", fetch=lambda: [], now=1000)
    return source, first, proposed, original



def records(database, table):
    with closing(sqlite3.connect(database)) as conn:
        conn.row_factory = sqlite3.Row
        return [dict(row) for row in conn.execute("SELECT * FROM " + table + " ORDER BY id")]


def archives(database, *, detached=False):
    with closing(sqlite3.connect(database)) as conn:
        conn.row_factory = sqlite3.Row
        result = {key: [] for key in ("integration_operations", "integration_previews",
                                     "integration_changes")}
        archived = [json.loads(row[0]) for row in conn.execute(
            "SELECT data FROM recovery_records WHERE table_name='research_history_archive' "
            "ORDER BY row_number"
        )] if detached else enrollment_history.archived(conn)
        for row in archived:
            record, _ = enrollment_history.validate(row)
            if row["protocol"] in result:
                result[row["protocol"]].append(record)
        return {key: sorted(values, key=lambda row: row["id"]) for key, values in result.items()}


def test_real_import_history_can_prepare_without_reactivating_receipts(
    imported, tmp_path, monkeypatch,
):
    source, first, proposed, original = imported
    assert rows(source, "SELECT position FROM list_papers WHERE list_id='" + first["list_id"]
                + "' ORDER BY position") == [(0,), (1,)]
    # Exercise a valid older/sparse ordinal layout without changing its reading order.
    with closing(sqlite3.connect(source)) as conn, conn:
        conn.execute("UPDATE list_papers SET position=(position+1)*10 WHERE list_id=?",
                     (first["list_id"],))
    expected = {key: records(source, key) for key in (
        "integration_operations", "integration_previews", "integration_changes",
    )}
    with closing(sqlite3.connect(source)) as conn:
        recorded = conn.execute("SELECT result FROM integration_operations WHERE id=?",
                                ("agent-import-one",)).fetchone()[0]
    assert json.loads(recorded) == first
    before = source.read_bytes()
    plan = EnrollmentService(source).plan(pdfs={first["paper_ids"][0]: original})
    assert plan["supported"], plan["blockers"]
    assert all(plan["archived_history_by_protocol"][key] == 2 for key in expected)
    result = prepare(source, tmp_path, pdfs={first["paper_ids"][0]: original})
    assert result["status"] == "prepared_for_review"
    destination = Path(result["database"])
    assert archives(destination) == expected
    assert not rows(destination, "SELECT 1 FROM kv WHERE key LIKE 'update.cache.%'")
    for table in expected:
        assert rows(destination, "SELECT COUNT(*) FROM " + table) == [(0,)]
    for table in ("papers", "lists", "notes"):
        assert rows(destination, "SELECT * FROM " + table + " ORDER BY id") == rows(
            source, "SELECT * FROM " + table + " ORDER BY id",
        )
    assert rows(destination, "SELECT paper_id,position,citation,added_at FROM list_papers "
                "WHERE list_id='" + first["list_id"] + "' ORDER BY position") == [
        (row[0], position, row[2], row[3]) for position, row in enumerate(rows(
            source, "SELECT paper_id,position,citation,added_at FROM list_papers "
            "WHERE list_id='" + first["list_id"] + "' ORDER BY position",
        ))
    ]
    reader = DocumentReader.from_workspace(destination)
    try:
        assert reader.resolve(first["paper_ids"][0]).path.read_bytes() == original.read_bytes()
    finally:
        reader.close()
    assert sync_recovery.inspect(result["backup"])["workspace_id"] == result["workspace_id"]
    restored = sync_recovery.restore_detached(result["backup"], tmp_path / "restored")
    restored_database = tmp_path / "restored/papers.db"
    assert restored["detached"] and archives(restored_database, detached=True) == expected
    for table in expected:
        assert rows(restored_database, "SELECT COUNT(*) FROM " + table) == [(0,)]
    with monkeypatch.context() as patch:
        patch.setattr(store, "DB_PATH", destination)
        assert ops.inspect_operation("agent-import-one")["state"] == "not_committed"
        with pytest.raises(ops.OperationError, match="expired"):
            ops.commit(proposed["preview_id"], "agent-import-one", ["1", "0"])
    assert source.read_bytes() == before
    assert not result["uploaded"] and not result["adopted"]


def test_unknown_or_malformed_import_history_never_publishes_a_copy(imported, tmp_path):
    source, first, _, original = imported
    receipts = records(source, "integration_operations")
    service = EnrollmentService(source)
    output, backup = tmp_path / "refused", tmp_path / "refused.zip"
    for fault in ("unknown", "duplicate-json", "identity", "fingerprint"):
        row = deepcopy(receipts[0])
        result = json.loads(row["result"])
        if fault == "unknown":
            result["credential"] = "private-token-must-not-migrate"
        elif fault == "identity":
            result["operation_id"] = "another-request"
        row["result"] = json.dumps(result)
        if fault == "duplicate-json":
            row["result"] = row["result"].replace('{', '{"selected":500,', 1)
        if fault == "fingerprint":
            row["fingerprint"] = "unrecognized"
        with closing(sqlite3.connect(source)) as conn, conn:
            conn.execute("UPDATE integration_operations SET fingerprint=?,result=? WHERE id=?",
                         (row["fingerprint"], row["result"], row["id"]))
        before = source.read_bytes()
        with pytest.raises(ValueError):
            service.prepare(output, backup_output=backup, request_id=str(uuid4()),
                            pdfs={first["paper_ids"][0]: original})
        assert not output.exists() and not backup.exists() and source.read_bytes() == before
        with closing(sqlite3.connect(source)) as conn, conn:
            conn.execute("UPDATE integration_operations SET fingerprint=?,result=? WHERE id=?",
                         (receipts[0]["fingerprint"], receipts[0]["result"], receipts[0]["id"]))
    from paper_daily.local_import_schema import PaperInput

    assert ops.PaperInput is PaperInput  # One pure validator, legacy public alias retained.
    preview = records(source, "integration_previews")[0]
    invalid = json.loads(preview["payload"])
    invalid["papers"][0]["url"] = "https://user:private-token@example.invalid/source"
    with closing(sqlite3.connect(source)) as conn, conn:
        conn.execute("UPDATE integration_previews SET payload=? WHERE id=?",
                     (json.dumps(invalid), preview["id"]))
    with pytest.raises(ValueError) as failure:
        service.prepare(output, backup_output=backup, request_id=str(uuid4()),
                        pdfs={first["paper_ids"][0]: original})
    assert "private-token" not in str(failure.value)
    assert not output.exists() and not backup.exists()
    with closing(sqlite3.connect(source)) as conn, conn:
        conn.execute("UPDATE integration_previews SET payload=? WHERE id=?",
                     (preview["payload"], preview["id"]))
    # Ambiguous ordinals cannot be silently tie-broken during preparation.
    with closing(sqlite3.connect(source)) as conn, conn:
        conn.execute("UPDATE list_papers SET position=0 WHERE list_id=?", (first["list_id"],))
    plan = service.plan(pdfs={first["paper_ids"][0]: original})
    assert not plan["supported"] and any("ordering" in item for item in plan["blockers"])


def test_cancel_or_changed_import_history_keeps_source_and_retry_is_safe(imported, tmp_path):
    source, first, _, original = imported
    service = EnrollmentService(source)
    for fault in ("cancel", "changed"):
        ticket, reached, token = Ticket(), [], str(uuid4())
        output, backup = tmp_path / fault, tmp_path / (fault + ".zip")

        def progress(message, fault=fault, reached=reached, ticket=ticket):
            if reached or "Creating and inspecting independent recovery backup" not in message:
                return
            reached.append(True)
            if fault == "cancel":
                ticket.cancel()
            else:
                with closing(sqlite3.connect(source)) as conn, conn:
                    conn.execute("UPDATE integration_operations SET created_at=? WHERE id=?",
                                 ("2026-11-16T00:00:00+00:00", "agent-import-one"))

        with pytest.raises(Cancelled if fault == "cancel" else SnapshotChanged):
            service.prepare(output, backup_output=backup, request_id=token,
                pdfs={first["paper_ids"][0]: original}, ticket=ticket, progress=progress)
        assert reached and not output.exists() and not backup.exists()
        result = service.prepare(output, backup_output=backup, request_id=token,
                                 pdfs={first["paper_ids"][0]: original})
        assert result["status"] == "prepared_for_review"
        assert archives(result["database"])["integration_operations"] == records(
            source, "integration_operations",
        )


def test_desktop_preview_archives_agent_records_and_preserves_active_research(
    imported, tmp_path, app,
):
    source, first, _, original = imported
    before = source.read_bytes()
    view = EnrollmentDialog(source, language="en",
        pdf_loader=lambda *_: {first["paper_ids"][0]: original})
    view.show()
    try:
        assert view.check_content()
        wait(app, lambda: not view.busy)
        assert view.preview["supported"], view.preview["blockers"]
        assert "Completed agent imports (history only): 2" in view.coverage.toPlainText()
        assert "Reference previews (history only): 2" in view.coverage.toPlainText()
        view.output_path.setText(str(tmp_path / "desktop-copy"))
        view.backup_path.setText(str(tmp_path / "desktop-copy.zip"))
        view.prepare_button.click()
        view.prepare_button.click()
        wait(app, lambda: not view.busy)
        assert view.result["status"] == "prepared_for_review"
        assert rows(
            view.result["database"], "SELECT COUNT(*) FROM integration_operations",
        ) == [(0,)]
        assert archives(view.result["database"])["integration_operations"] == records(
            source, "integration_operations",
        )
        assert view.guard.path == source and source.read_bytes() == before
        assert not view.result["uploaded"] and not view.result["adopted"]
    finally:
        if view.busy:
            view.cancel()
            wait(app, lambda: not view.busy)
        view.close()
        app.processEvents()
