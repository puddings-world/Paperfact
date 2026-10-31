"Workspace roots preserve exact offline capture text and user triage intent."

import json
import sqlite3
from contextlib import closing
from pathlib import Path
from uuid import uuid4

import pytest

from paper_daily import inbox_content as content
from paper_daily import store
from paper_daily.research_inbox import Inbox
from paper_daily.sync_client import SyncClient
from paper_daily.sync_journal import Journal, canonical_operation
from paper_daily.sync_research import prepare, research_order_writer, research_writer
from paper_daily.sync_service import ReferenceService
from paper_daily.workspace_service import Cancelled, Ticket, WorkspaceChanged

STAMP = "2026-10-30T12:00:00+00:00"


def payload(text="A short research idea", kind="idea", state="new"):
    return dict(kind=kind, text=text, state=state, created_at=STAMP, updated_at=STAMP)


def setup(path, *, device=None):
    with closing(sqlite3.connect(path)) as conn:
        conn.executescript(store.SCHEMA)
        store._migrate(conn)
        conn.commit()
    client = None
    if device:
        prepare(path, workspace_id="workspace", device_id=device)
        client = SyncClient(
            Journal(path, workspace_id="workspace", device_id=device),
            research_writer,
            order_writer=research_order_writer,
        )
    service = Inbox(path)
    service.read()  # Complete the initial worker binding before later fixture changes.
    return service, client


@pytest.fixture(params=[False, True], ids=["local", "enrolled"])
def inbox(tmp_path, request):
    service, client = setup(
        tmp_path / "research.sqlite", device="desktop" if request.param else None
    )
    return service, client


def rows(path, table):
    with closing(sqlite3.connect(path)) as conn:
        conn.row_factory = sqlite3.Row
        return [dict(row) for row in conn.execute(f"SELECT * FROM {table}")]


def saved(service, data=None):
    view = service.read()
    request, identity = str(uuid4()), str(uuid4())
    result = service.save(view, request_id=request, item_id=identity, payload=data or payload())
    return view, request, identity, result


def test_saved_first_read_does_not_initialize_owner_or_change_database(inbox):
    service, _ = inbox
    before = service.path.read_bytes()
    view = service.read()
    assert view.data == dict(items=[], offset=0, has_more=False, total=0, conflicts=0)
    assert rows(service.path, content.OWNER) == []
    assert service.path.read_bytes() == before
    assert service.current(view)


@pytest.mark.parametrize(
    "kind,text,display",
    [
        ("doi", "  DOI:10.1234/AbC  ", "10.1234/abc"),
        ("url", " https://example.test/research?q=study ", "https://example.test/research?q=study"),
        ("idea", "  Compare methods\nKeep this wording. ", "Compare methods\nKeep this wording."),
    ],
)
def test_exact_text_is_saved_separately_from_display_normalization(inbox, kind, text, display):
    service, client = inbox
    _view, _request, identity, result = saved(service, payload(text, kind))
    assert result["status"] == "saved"
    item = service.read().data["items"][0]
    assert item["id"] == identity and item["payload"]["text"] == text
    assert content.display_value(kind, text) == display
    assert len(rows(service.path, content.HISTORY)) == 1
    if client:
        operation = client.journal.pending()[0]
        assert operation["entity_type"] == "inbox_item" and operation["parents"] == []
        assert operation["workspace_id"] == "workspace"
        assert operation["payload"]["text"] == text


def test_same_request_restart_retry_is_exact_and_changed_retry_is_rejected(inbox):
    service, client = inbox
    view, request, identity, first = saved(service)
    assert service.save(view, request_id=request, item_id=identity, payload=payload()) == first
    restarted = Inbox(service.path)
    current = restarted.read()
    assert restarted.save(current, request_id=request, item_id=identity, payload=payload()) == first
    with pytest.raises(ValueError, match="retry changed"):
        restarted.save(current, request_id=request, item_id=identity, payload=payload("Changed"))
    assert len(rows(service.path, content.ITEMS)) == 1
    assert len(rows(service.path, content.HISTORY)) == 1
    assert len(rows(service.path, content.REQUESTS)) == 1
    assert len(client.journal.pending()) == 1 if client else True


def test_different_explicit_requests_do_not_merge_identical_text(inbox):
    service, _ = inbox
    saved(service)
    saved(service)
    items = service.read().data["items"]
    assert len(items) == 2 and len({row["id"] for row in items}) == 2


def test_stale_edit_is_retained_once_without_overwriting_newer_triage(inbox):
    service, _ = inbox
    saved(service)
    view = service.read()
    item = view.data["items"][0]
    observed = service.observe(item)
    service.save(
        view,
        request_id=str(uuid4()),
        item_id=item["id"],
        payload=payload(state="kept"),
        observed=observed,
    )
    request = str(uuid4())
    result = service.save(
        view,
        request_id=request,
        item_id=item["id"],
        payload=payload("Offline thought"),
        observed=observed,
    )
    assert result["status"] == "conflict"
    assert (
        service.save(
            view,
            request_id=request,
            item_id=item["id"],
            payload=payload("Offline thought"),
            observed=observed,
        )
        == result
    )
    assert service.read().data["items"][0]["payload"]["state"] == "kept"
    candidates = rows(service.path, content.CANDIDATES)
    assert (
        len(candidates) == 1 and json.loads(candidates[0]["body_json"])["text"] == "Offline thought"
    )


def test_delete_is_recoverable_and_restore_requires_a_fresh_explicit_incarnation(inbox):
    service, _ = inbox
    saved(service)
    view = service.read()
    item = view.data["items"][0]
    first_incarnation = item["incarnation"]
    service.save(
        view,
        request_id=str(uuid4()),
        item_id=item["id"],
        payload=None,
        observed=service.observe(item),
        action="delete",
    )
    assert service.read().data["items"] == []
    deleted = service.read(include_deleted=True).data["items"][0]
    assert deleted["payload"]["text"] == payload()["text"] and deleted["active"] == 0
    current = service.read(include_deleted=True)
    with pytest.raises(ValueError, match="explicit choice"):
        service.save(
            current,
            request_id=str(uuid4()),
            item_id=item["id"],
            payload=payload(),
            observed=service.observe(deleted),
        )
    service.save(
        current,
        request_id=str(uuid4()),
        item_id=item["id"],
        payload=payload(),
        observed=service.observe(deleted),
        restore=True,
    )
    restored = service.read().data["items"][0]
    assert (
        restored["incarnation"] != first_incarnation
        and len(rows(service.path, content.HISTORY)) == 3
    )


def test_cancellation_before_commit_rolls_back_item_owner_history_receipt_and_outbox(inbox):
    service, client = inbox
    view = service.read()
    ticket = Ticket()
    ticket.cancel()
    with pytest.raises(Cancelled):
        service.save(
            view, request_id=str(uuid4()), item_id=str(uuid4()), payload=payload(), ticket=ticket
        )
    assert all(not rows(service.path, table) for table in content.COLUMNS)
    if client:
        assert client.journal.pending() == []


@pytest.mark.parametrize("change", ["path", "replacement", "binding", "owner"])
def test_captured_workspace_is_never_rebound_for_late_save(inbox, change):
    service, _client = inbox
    saved(service)
    view = service.read()
    if change == "path":
        service.current_path = lambda: service.path.with_name("other.sqlite")
    elif change == "replacement":
        replacement = service.path.with_suffix(".replacement")
        replacement.write_bytes(service.path.read_bytes())
        replacement.replace(service.path)
    else:
        with closing(sqlite3.connect(service.path)) as conn, conn:
            if change == "owner":
                conn.execute(f"UPDATE {content.OWNER} SET token=?", (str(uuid4()),))
            elif _client:
                conn.execute("UPDATE paperfact_sync_identity SET device='other'")
            else:
                conn.execute(
                    "CREATE TABLE research_sync_binding(id INTEGER PRIMARY KEY,workspace,origin)"
                )
                conn.execute("INSERT INTO research_sync_binding VALUES(1,'other','other')")
    before = rows(service.path, content.ITEMS)
    with pytest.raises((ValueError, WorkspaceChanged)):
        service.save(view, request_id=str(uuid4()), item_id=str(uuid4()), payload=payload())
    assert rows(service.path, content.ITEMS) == before


@pytest.mark.parametrize(
    "bad",
    [
        dict(kind="other"),
        dict(state="synced"),
        dict(text=""),
        dict(text="x" * 2049),
        dict(kind="url", text="https://user:secret@example.test"),
        dict(kind="url", text="file:///private/paper.pdf"),
        dict(kind="doi", text="not a DOI"),
        dict(created_at="2026-10-30"),
        dict(workspace_id="sender-controlled"),
    ],
)
def test_closed_text_metadata_contract_rejects_invalid_capture(bad):
    with pytest.raises(ValueError):
        content.validate(dict(payload(), **bad))


def test_new_kind_uses_closed_uuid_root_not_any_paper_or_list_parent():
    operation = dict(
        version=2,
        operation_id="create",
        workspace_id="workspace",
        device_id="desktop",
        entity_type="inbox_item",
        entity_id=str(uuid4()),
        action="put",
        base_revision=0,
        depends_on=None,
        payload=payload(),
        incarnation="create",
        parents=[],
        structure_revision=0,
    )
    assert json.loads(canonical_operation(operation)) == operation
    with pytest.raises(ValueError):
        canonical_operation(
            dict(operation, parents=[dict(kind="paper", id=str(uuid4()), incarnation="paper")])
        )
    with pytest.raises(ValueError):
        canonical_operation(dict(operation, entity_id="fake-paper"))


def test_two_actual_clients_converge_and_retain_edit_delete_conflict(tmp_path):
    first, a = setup(tmp_path / "a.sqlite", device="a")
    second, b = setup(tmp_path / "b.sqlite", device="b")
    server = ReferenceService(tmp_path / "authority.sqlite")
    ta, tb = server.enroll("workspace", "a"), server.enroll("workspace", "b")
    saved(first)
    a.sync_once(server, ta)
    b.sync_once(server, tb)
    va, vb = first.read(), second.read()
    ia, ib = va.data["items"][0], vb.data["items"][0]
    assert ia["payload"] == ib["payload"]
    first.save(
        va,
        request_id=str(uuid4()),
        item_id=ia["id"],
        payload=None,
        observed=first.observe(ia),
        action="delete",
    )
    second.save(
        vb,
        request_id=str(uuid4()),
        item_id=ib["id"],
        payload=payload("Offline preserved thought"),
        observed=second.observe(ib),
    )
    a.sync_once(server, ta)
    b.sync_once(server, tb)
    assert first.read().data["items"] == second.read().data["items"] == []
    history = b.history(conflicts_only=True)
    assert (
        len(history) == 1
        and history[0]["operation"]["payload"]["text"] == "Offline preserved thought"
    )
    assert any(
        json.loads(row["body_json"])["text"] == "Offline preserved thought"
        for row in rows(second.path, content.HISTORY)
        if row["body_json"]
    )


@pytest.mark.parametrize(
    "case",
    json.loads(
        (Path(__file__).parent / "fixtures/inbox-contract.json").read_text(encoding="utf-8")
    ),
    ids=lambda case: case["name"],
)
def test_independent_runtime_contract_vectors(case):
    if case["valid"]:
        assert content.validate(case["payload"]) == case["payload"]
    else:
        with pytest.raises(ValueError):
            content.validate(case["payload"])


def test_initial_delayed_binding_and_corrupt_current_history_fail_closed(tmp_path):
    service, _ = setup(tmp_path / "inbox.sqlite")
    delayed = Inbox(service.path)
    with closing(sqlite3.connect(service.path)) as conn, conn:
        conn.execute("INSERT INTO kv VALUES('fixture','changed before worker')")
    with pytest.raises(WorkspaceChanged):
        delayed.read()
    assert delayed.needs_reopen
    saved(service)
    with closing(sqlite3.connect(service.path)) as conn, conn:
        conn.execute(
            f"UPDATE {content.ITEMS} SET body_json=?",
            (content.encode(payload("Unowned replacement")),),
        )
    with pytest.raises(ValueError, match="owned saved version"):
        service.read()


def test_enrolled_ordinary_connection_cannot_bypass_typed_inbox_root(tmp_path):
    service, client = setup(tmp_path / "enrolled.sqlite", device="desktop")
    saved(service)
    from paper_daily import sync_capture

    with closing(sqlite3.connect(service.path, factory=sync_capture.CaptureConnection)) as conn:
        conn.execute("BEGIN IMMEDIATE")
        sync_capture.install(conn, workspace_id="workspace", device_id="desktop")
        conn.commit()
    with closing(sqlite3.connect(service.path, factory=sync_capture.CaptureConnection)) as conn:
        conn.execute("BEGIN IMMEDIATE")
        with pytest.raises(sqlite3.DatabaseError):
            conn.execute(f"UPDATE {content.ITEMS} SET active=0")
        conn.rollback()
    assert Inbox(service.path).read().data["items"][0]["active"] == 1


def test_duplicate_fields_in_entry_import_and_unowned_receipt_fail_closed(inbox):
    service, _ = inbox
    with pytest.raises(ValueError, match="Duplicate"):
        service.import_entry(
            service.read(),
            ('{"format":"wrong","format":"paperfact-inbox-entry.v1","item":{}}'),
            request_id=str(uuid4()),
        )
    _view, request, identity, result = saved(service)
    with closing(sqlite3.connect(service.path)) as conn, conn:
        conn.execute(
            f"UPDATE {content.REQUESTS} SET result_json=? WHERE request_id=?",
            (content.encode(dict(result, item_id=str(uuid4()))), request),
        )
    with pytest.raises(ValueError, match="another capture"):
        service.save(service.read(), request_id=request, item_id=identity, payload=payload())
