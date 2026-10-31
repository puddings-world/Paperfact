"Inbox backups/copies retain text/history while receiver authority starts fresh."

import hashlib
import json
import sqlite3
from contextlib import closing
from pathlib import Path
from uuid import uuid4

import pytest
from test_research_inbox import inbox as inbox_fixture
from test_research_inbox import payload, rows, saved, setup
from test_sync_recovery import rewrite

from paper_daily import inbox_content as content
from paper_daily import sync_recovery
from paper_daily.research_inbox import Inbox
from paper_daily.workspace_enrollment import EnrollmentService

inbox = inbox_fixture


def test_closed_entry_import_preserves_exact_text_with_fresh_id_and_durable_retry(inbox, tmp_path):
    source, _ = inbox
    _view, _request, identity, _result = saved(source, payload(" DOI:10.1234/Mixed ", "doi"))
    view = source.read()
    exported = source.export_entry(view, identity)
    target, _ = setup(tmp_path / "receiver.sqlite")
    receiver = target.read()
    request = str(uuid4())
    result = target.import_entry(receiver, exported, request_id=request)
    assert target.import_entry(receiver, exported, request_id=request) == result
    item = target.read().data["items"][0]
    assert item["id"] != identity and item["payload"]["text"] == " DOI:10.1234/Mixed "
    assert (
        rows(source.path, content.OWNER)[0]["token"] != rows(target.path, content.OWNER)[0]["token"]
    )
    assert set(json.loads(exported)) == {"format", "item"}
    with pytest.raises(ValueError):
        target.import_entry(
            target.read(),
            json.dumps(dict(json.loads(exported), workspace_id="sender")),
            request_id=str(uuid4()),
        )


def test_complete_backup_restore_archives_sender_receipts_and_mints_receiver_authority(
    inbox, tmp_path
):
    source, _ = inbox
    _view, request, identity, first = saved(source)
    observed = source.read()
    item = observed.data["items"][0]
    source.save(
        observed,
        request_id=str(uuid4()),
        item_id=identity,
        payload=payload("Newer saved text"),
        observed=source.observe(item),
    )
    stale = source.save(
        observed,
        request_id=str(uuid4()),
        item_id=identity,
        payload=payload("Retained stale text"),
        observed=source.observe(item),
    )
    assert stale["status"] == "conflict"
    before = source.path.read_bytes()
    package = tmp_path / "inbox.zip"
    sync_recovery.create(source.path, package)
    manifest = sync_recovery.inspect(package)
    assert any(
        row["name"] == content.ITEMS and row["section"] == "research" for row in manifest["tables"]
    )
    sync_recovery.restore_detached(package, tmp_path / "restored")
    database = tmp_path / "restored/papers.db"
    target = Inbox(database)
    view = target.read()
    restored = view.data["items"][0]
    assert restored["payload"]["text"] == "Newer saved text"
    assert (
        restored["incarnation"] != item["incarnation"] and restored["version"] != first["version"]
    )
    assert rows(database, content.REQUESTS) == []
    assert rows(database, content.OWNER)[0]["token"] != rows(source.path, content.OWNER)[0]["token"]
    assert any(
        json.loads(row["body_json"])["text"] == "Retained stale text"
        for row in rows(database, content.CANDIDATES)
    )
    with closing(sqlite3.connect(database)) as conn:
        names = {row[0] for row in conn.execute("SELECT name FROM sqlite_master")}
        assert "paperfact_sync_identity" not in names
        assert (
            conn.execute(
                "SELECT count(*) FROM recovery_records WHERE table_name=?", (content.REQUESTS,)
            ).fetchone()[0]
            == 3
        )
    # Sender request is historical evidence, never an executable receiver receipt.
    result = target.save(view, request_id=request, item_id=identity, payload=payload())
    assert (
        result["status"] == "conflict"
        and target.read().data["items"][0]["payload"]["text"] == "Newer saved text"
    )
    assert source.path.read_bytes() == before


def test_forged_workspace_receipt_is_refused_before_restore_destination_exists(inbox, tmp_path):
    source, _ = inbox
    saved(source)
    package = tmp_path / "backup.zip"
    sync_recovery.create(source.path, package)

    def mutate(manifest, files):
        table = next(row for row in manifest["tables"] if row["name"] == content.REQUESTS)
        name = "tables/" + content.REQUESTS + ".jsonl"
        values = [json.loads(line) for line in files[name].splitlines()]
        values[0]["owner_token"] = str(uuid4())
        files[name] = b"".join((json.dumps(value) + "\n").encode() for value in values)
        table.update(size=len(files[name]), sha256=hashlib.sha256(files[name]).hexdigest())

    forged = rewrite(package, tmp_path / "forged.zip", mutate)
    destination = tmp_path / "must-not-exist"
    with pytest.raises(ValueError, match="workspace lifetime"):
        sync_recovery.restore_detached(forged, destination)
    assert not destination.exists()


def test_unbound_first_enrollment_is_a_reviewed_copy_with_archived_receipts_and_new_root(tmp_path):
    folder = tmp_path / "source"
    folder.mkdir()
    source, _ = setup(folder / "papers.db")
    _view, _request, identity, _result = saved(source, payload("Desktop triage input"))
    before = source.path.read_bytes()
    plan = EnrollmentService(source.path).plan()
    assert plan["supported"], plan["blockers"]
    prepared = EnrollmentService(source.path).prepare(
        tmp_path / "candidate", backup_output=tmp_path / "backup.zip", request_id=str(uuid4())
    )
    assert not prepared["uploaded"] and not prepared["adopted"]
    database = Path(prepared["database"])
    target = Inbox(database)
    item = target.read().data["items"][0]
    assert item["id"] == identity and item["payload"]["text"] == "Desktop triage input"
    assert rows(database, content.REQUESTS) == []
    assert rows(database, content.OWNER)[0]["token"] != rows(source.path, content.OWNER)[0]["token"]
    with closing(sqlite3.connect(database)) as conn:
        operations = [
            json.loads(row[0])
            for row in conn.execute("SELECT envelope FROM paperfact_sync_operations")
        ]
        assert any(
            op["entity_type"] == "inbox_item"
            and op["entity_id"] == identity
            and op["parents"] == []
            for op in operations
        )
        archived = list(
            conn.execute(
                ("SELECT protocol,body_json FROM research_history_archive WHERE protocol IN (?,?)"),
                (content.OWNER, content.REQUESTS),
            )
        )
        assert len(archived) == 2
    assert source.path.read_bytes() == before


def test_baseline_comparator_refuses_unproven_history_or_changed_payload():
    from paper_daily.inbox_recovery import compare_baseline

    identity, version = str(uuid4()), str(uuid4())
    source = dict(
        id=identity,
        body_json=content.encode(payload()),
        incarnation=version,
        version=version,
        active=1,
    )
    operation = dict(
        version=2,
        entity_type="inbox_item",
        entity_id=identity,
        parents=[],
        incarnation="fresh",
        operation_id="fresh",
        action="put",
        payload=payload(),
    )
    with pytest.raises(ValueError, match="lost or changed"):
        compare_baseline(
            content.ITEMS,
            [source],
            [source],
            [source],
            {identity: operation},
            {identity: operation},
        )
    changed = dict(
        source,
        body_json=content.encode(payload("Lost original text")),
        incarnation="fresh",
        version="fresh",
    )
    with pytest.raises(ValueError, match="lost or changed"):
        compare_baseline(
            content.ITEMS,
            [source],
            [changed],
            [source],
            {identity: operation},
            {identity: operation},
        )
    with pytest.raises(ValueError, match="incomplete"):
        compare_baseline(content.HISTORY, [], [], [source], {}, {})


def test_local_retained_proposal_decision_is_explicit_durable_and_recovery_safe(inbox, tmp_path):
    service, _ = inbox
    saved(service)
    old = service.read()
    item = old.data["items"][0]
    service.save(
        old,
        request_id=str(uuid4()),
        item_id=item["id"],
        payload=payload("Newer kept text"),
        observed=service.observe(item),
    )
    service.save(
        old,
        request_id=str(uuid4()),
        item_id=item["id"],
        payload=payload("Retained draft"),
        observed=service.observe(item),
    )
    review = service.retained(service.read(), item_id=item["id"])
    record = review.data["retained"][0]
    assert record["payload"]["text"] == "Retained draft" and len(review.data["history"]) == 2
    request = str(uuid4())
    result = service.resolve(review, record["id"], choice="canonical", request_id=request)
    assert result["status"] == "resolved"
    assert service.resolve(review, record["id"], choice="canonical", request_id=request) == result
    assert service.read().data["items"][0]["payload"]["text"] == "Newer kept text"
    assert service.retained(service.read()).data["retained"] == []
    sync_recovery.create(service.path, tmp_path / "resolved-backup.zip")
    assert sync_recovery.inspect(tmp_path / "resolved-backup.zip")


def test_local_retained_incoming_choice_rechecks_displayed_base_and_publishes_once(inbox):
    service, _ = inbox
    saved(service)
    old = service.read()
    item = old.data["items"][0]
    service.save(
        old,
        request_id=str(uuid4()),
        item_id=item["id"],
        payload=payload("Newer"),
        observed=service.observe(item),
    )
    service.save(
        old,
        request_id=str(uuid4()),
        item_id=item["id"],
        payload=payload("Proposal to keep"),
        observed=service.observe(item),
    )
    review = service.retained(service.read())
    record = review.data["retained"][0]
    request = str(uuid4())
    result = service.resolve(review, record["id"], choice="incoming", request_id=request)
    assert result["status"] == "saved"
    assert service.resolve(review, record["id"], choice="incoming", request_id=request) == result
    assert service.read().data["items"][0]["payload"]["text"] == "Proposal to keep"
    assert service.retained(service.read()).data["retained"] == []


def test_server_conflict_uses_existing_explicit_observed_resolution_and_restore(tmp_path):
    from paper_daily.sync_service import ReferenceService

    first, a = setup(tmp_path / "first.sqlite", device="a")
    second, b = setup(tmp_path / "second.sqlite", device="b")
    server = ReferenceService(tmp_path / "authority.sqlite")
    ta, tb = server.enroll("workspace", "a"), server.enroll("workspace", "b")
    saved(first)
    a.sync_once(server, ta)
    b.sync_once(server, tb)
    va, vb = first.read(), second.read()
    ia, ib = va.data["items"][0], vb.data["items"][0]
    first.save(
        va,
        request_id=str(uuid4()),
        item_id=ia["id"],
        payload=None,
        action="delete",
        observed=first.observe(ia),
    )
    second.save(
        vb,
        request_id=str(uuid4()),
        item_id=ib["id"],
        payload=payload("Preserved incoming edit"),
        observed=second.observe(ib),
    )
    a.sync_once(server, ta)
    b.sync_once(server, tb)
    review = second.retained(second.read(include_deleted=True))
    record = review.data["retained"][0]
    assert record["source"] == "server" and record["payload"]["text"] == "Preserved incoming edit"
    with pytest.raises(ValueError, match="restore"):
        second.resolve(review, record["id"], choice="incoming", request_id=str(uuid4()))
    request = str(uuid4())
    result = second.resolve(
        review, record["id"], choice="incoming", request_id=request, restore=True
    )
    assert (
        second.resolve(review, record["id"], choice="incoming", request_id=request, restore=True)
        == result
    )
    assert len(b.journal.pending()) == 1
    b.sync_once(server, tb)
    a.sync_once(server, ta)
    assert first.read().data["items"][0]["payload"]["text"] == "Preserved incoming edit"
    assert second.retained(second.read()).data["retained"] == []


def test_conditional_projection_is_read_only_and_keeps_deleted_inbox_capability(tmp_path):
    from paper_daily.sync_projection import read_manifest

    source, client = setup(tmp_path / "source.sqlite", device="desktop")
    empty = read_manifest(source.path, workspace_id="workspace", schema_version=2)
    assert "inbox" not in empty and "required_capabilities" not in empty
    _view, _request, identity, _result = saved(source, payload("  Exact projected text  "))
    result = read_manifest(source.path, workspace_id="workspace", schema_version=2)
    assert result["required_capabilities"] == ["inbox"]
    row = result["inbox"]["items"][0]
    assert row["id"] == identity and row["payload"]["text"] == "  Exact projected text  "
    assert row["sync_state"] == "pending" and "editable" not in row and "graph" not in row
    view = source.read()
    item = view.data["items"][0]
    source.save(
        view,
        request_id=str(uuid4()),
        item_id=identity,
        payload=None,
        action="delete",
        observed=source.observe(item),
    )
    result = read_manifest(source.path, workspace_id="workspace", schema_version=2)
    assert (
        result["required_capabilities"] == ["inbox"] and not result["inbox"]["items"][0]["active"]
    )


def test_actual_older_python_parser_refuses_whole_batch_before_cursor_or_data_changes(
    tmp_path, monkeypatch
):
    import importlib.util

    from paper_daily import sync_schema_v2
    from paper_daily.sync_service import ReferenceService

    service, client = setup(tmp_path / "receiver.sqlite", device="receiver")
    authority = ReferenceService(tmp_path / "authority.sqlite")
    token = authority.enroll("workspace", "sender")
    identity = str(uuid4())

    def operation(kind, item_id, data, request):
        return dict(
            version=2,
            operation_id=request,
            workspace_id="workspace",
            device_id="sender",
            entity_type=kind,
            entity_id=item_id,
            action="put",
            base_revision=0,
            depends_on=None,
            payload=data,
            incarnation=request,
            parents=[],
            structure_revision=0,
        )

    authority.push(
        token, operation("list", "known-list", dict(name="Known list", note=None), "list-created")
    )
    authority.push(token, operation("inbox_item", identity, payload(), "inbox-created"))
    events = authority.pull(token)
    location = Path(__file__).parent / "fixtures/pre_inbox_schema_v2.py"
    spec = importlib.util.spec_from_file_location("_pre_inbox_schema_v2", location)
    older = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(older)
    before = service.path.read_bytes()
    monkeypatch.setattr(sync_schema_v2, "canonical_operation", older.canonical_operation)
    with pytest.raises(ValueError, match="Unsupported graph"):
        client.receive(events)
    assert service.path.read_bytes() == before
    assert client.status()["cursor"] == 0
    with closing(sqlite3.connect(service.path)) as conn:
        assert conn.execute("SELECT count(*) FROM lists").fetchone()[0] == 0
        assert conn.execute(f"SELECT count(*) FROM {content.ITEMS}").fetchone()[0] == 0


def test_workspace_inbox_does_not_leak_into_a_list_snapshot_package(tmp_path, monkeypatch):
    import zipfile

    from paper_daily import bundle, store

    root = tmp_path / "source"
    root.mkdir()
    service, _ = setup(root / "papers.db")
    saved(service, payload("Private workspace Inbox outside this list"))
    with closing(sqlite3.connect(service.path)) as conn, conn:
        store.upsert_papers(
            conn,
            [
                dict(
                    id="paper", title="Selected paper", year=2026, venue="Fixture", source="fixture"
                )
            ],
        )
        conn.execute("INSERT INTO lists(id,name,created_at) VALUES('list','Selected list','now')")
        conn.execute(
            "INSERT INTO list_papers(list_id,paper_id,posi"
            "tion,added_at) VALUES('list','paper',0,'now')"
        )
    monkeypatch.setattr(store, "DB_PATH", service.path)
    monkeypatch.setattr(bundle, "DATA_DIR", root)
    monkeypatch.setattr(bundle, "PDF_DIR", root / "pdf")
    monkeypatch.setattr(
        bundle, "fetch", lambda *a, **k: pytest.fail("Inbox caused package fetching")
    )
    result = bundle.export("list", tmp_path / "list.zip")
    with zipfile.ZipFile(result["out"]) as archive:
        content_bytes = b"".join(archive.read(name) for name in archive.namelist())
        assert b"Private workspace Inbox outside this list" not in content_bytes
        assert b"research_inbox" not in content_bytes
    assert (
        service.read().data["items"][0]["payload"]["text"]
        == "Private workspace Inbox outside this list"
    )
