import hashlib
import json
import sqlite3
from contextlib import closing

import pytest

from paper_daily import store
from paper_daily.activity_projection import project_activity, resume_matches
from paper_daily.sync_client import SyncClient
from paper_daily.sync_journal import Journal
from paper_daily.sync_research import prepare, research_order_writer, research_writer
from paper_daily.sync_service import ReferenceService
from paper_daily.workspace_activity import ActivityReader
from paper_daily.workspace_service import Cancelled, Ticket, WorkspaceChanged

PAPER = "11111111-1111-4111-8111-111111111111"
NOTE = "22222222-2222-4222-8222-222222222222"
HASH = "a" * 64
STAMP = "2026-10-30T10:00:00+00:00"
ANCHOR = dict(p0=0, o0=1, p1=0, o1=2, document_hash=HASH)


def operation(kind, identity, payload, request, *, base=0, action="put", incarnation=None):
    return dict(
        version=2,
        operation_id=request,
        workspace_id="workspace",
        device_id="peer",
        entity_type=kind,
        entity_id=identity,
        action=action,
        base_revision=base,
        depends_on=None,
        payload=payload,
        incarnation=incarnation or request,
        parents=[]
        if kind == "paper"
        else [dict(kind="paper", id=PAPER, incarnation="paper-created")],
        structure_revision=0,
    )


@pytest.fixture
def activity(tmp_path):
    path = tmp_path / "papers.sqlite"
    with closing(sqlite3.connect(path)) as conn:
        conn.executescript(store.SCHEMA)
        conn.commit()
    prepare(path, workspace_id="workspace", device_id="local")
    client = SyncClient(
        Journal(path, workspace_id="workspace", device_id="local"),
        research_writer,
        order_writer=research_order_writer,
    )
    authority = ReferenceService(
        tmp_path / "authority.sqlite", blob_root=tmp_path / "authority-blobs"
    )
    token = authority.enroll("workspace", "peer")
    paper = dict(
        title="Recorded research",
        authors=[],
        year=None,
        venue=None,
        abstract=None,
        doi=None,
        arxiv_id=None,
        s2_id=None,
        page_url=None,
        pdf_url=None,
        source="fixture",
    )
    note = dict(
        paper_id=PAPER, body="Saved thought", kind="note", created_at=STAMP, page=1, anchor=ANCHOR
    )
    authority.push(token, operation("paper", PAPER, paper, "paper-created"))
    authority.push(token, operation("note", NOTE, note, "note-created"))
    client.receive(authority.pull(token))
    reader = ActivityReader(path)
    reader.snapshot()  # Complete the initial worker binding before later fixture mutations.
    return path, reader, client, authority, token, note


def test_actual_received_note_is_recorded_activity_with_owned_source(activity):
    path, reader, _, _, _, _ = activity
    before = path.read_bytes()
    value = reader.snapshot()
    assert value["cursor"] == 2
    assert [row["sequence"] for row in value["recent"]] == [2, 1]
    assert [row["status"] for row in value["recent"]] == ["applied", "applied"]
    (row,) = value["continue"]
    assert row["title"] == "Recorded research"
    assert row["resume"] == dict(note_id=NOTE, source_hash=HASH, anchor=ANCHOR)
    selected = reader.resolve(row, locate=True)
    assert selected["local_note_id"] is not None
    assert selected["local_paper_id"] is not None
    assert selected["current_hash"] is None  # No current PDF is inferred from this note.
    assert not resume_matches(row, paper_id=PAPER, loaded_hash=HASH, current_hash=None)
    assert resume_matches(row, paper_id=PAPER, loaded_hash=HASH, current_hash=HASH)
    assert not resume_matches(row, paper_id=PAPER, loaded_hash="b" * 64, current_hash=HASH)
    assert path.read_bytes() == before


def test_manifest_is_received_without_any_download_or_byte_availability_claim(activity):
    _, reader, client, server, token, _ = activity
    pdf = b"%PDF-1.4\nfixture\n%%EOF\n"
    declared = dict(sha256=hashlib.sha256(pdf).hexdigest(), size=len(pdf))
    upload = server.blob_begin(token, declared)
    server.blob_append(token, upload["upload_id"], 0, pdf)
    server.blob_commit(token, upload["upload_id"])
    payload = dict(paper_id=PAPER, **declared, media_type="application/pdf")
    assert (
        server.push(token, operation("paper_document", PAPER, payload, "pdf-metadata"))["outcome"]
        == "accepted"
    )
    client.receive(server.pull(token, after=2))
    row = reader.snapshot()["recent"][0]
    assert row["entity_type"] == "paper_document"
    assert row["status"] == "manifest_waiting"
    assert reader.resolve(reader.snapshot()["continue"][0])["current_hash"] == declared["sha256"]


def test_conflict_is_retained_and_never_becomes_a_continue_suggestion(activity):
    _, reader, client, server, token, note = activity
    changed = dict(note, body="Competing thought")
    result = server.push(
        token, operation("note", NOTE, changed, "stale-note", incarnation="note-created")
    )
    assert result["outcome"] == "conflict"
    client.receive(server.pull(token, after=2))
    value = reader.snapshot()
    assert value["recent"][0]["status"] == "conflict_retained"
    assert value["continue"][0]["operation_id"] == "note-created"
    assert value["continue"][0]["resume"]["anchor"] == ANCHOR


def test_cancellation_empty_selection_and_read_only_missing_database(activity, tmp_path):
    _, reader, _, _, _, _ = activity
    ticket = Ticket()
    ticket.cancel()
    with pytest.raises(Cancelled):
        reader.snapshot(ticket)
    with pytest.raises(WorkspaceChanged):
        reader.resolve({})
    missing = tmp_path / "missing.sqlite"
    with pytest.raises(FileNotFoundError):
        ActivityReader(missing)
    assert not missing.exists()


def test_unenrolled_database_stays_unenrolled_and_empty(tmp_path):
    path = tmp_path / "local.sqlite"
    with closing(sqlite3.connect(path)) as conn:
        conn.execute("CREATE TABLE fixture(value)")
        conn.commit()
    before = path.read_bytes()
    assert ActivityReader(path).snapshot() == {
        "available": False,
        "recent": [],
        "continue": [],
        "window": 0,
    }
    assert path.read_bytes() == before


@pytest.mark.parametrize("change", ["workspace", "replace", "binding"])
def test_late_binding_changes_are_rejected_with_actual_closed_handles(activity, tmp_path, change):
    path, reader, _, _, _, _ = activity
    row = reader.snapshot()["continue"][0]
    if change == "workspace":
        reader.current_path = lambda: tmp_path / "other.sqlite"
    elif change == "binding":
        with closing(sqlite3.connect(path)) as conn:
            conn.execute("UPDATE paperfact_sync_identity SET workspace='other'")
            conn.commit()
    else:
        replacement = tmp_path / "replacement.sqlite"
        with closing(sqlite3.connect(replacement)) as conn:
            conn.execute("CREATE TABLE other(value)")
            conn.commit()
        replacement.replace(path)  # Real replacement, with no GC/sleep/retry.
    with pytest.raises(WorkspaceChanged):
        reader.resolve(row, locate=True)


def test_malformed_and_oversized_received_rows_fail_without_partial_suggestions(activity):
    path, reader, _, _, _, _ = activity
    with closing(sqlite3.connect(path)) as conn:
        conn.execute("UPDATE paperfact_sync_inbox SET event=? WHERE sequence=2", ("x" * 540673,))
        conn.commit()
    with pytest.raises(ValueError, match="bounded"):
        reader.snapshot()


def test_projection_filters_only_accepted_own_echo_and_preserves_retained_conflict():
    paper = operation(
        "paper",
        PAPER,
        dict(
            title="Only title",
            authors=[],
            year=None,
            venue=None,
            abstract=None,
            doi=None,
            arxiv_id=None,
            s2_id=None,
            page_url=None,
            pdf_url=None,
            source="fixture",
        ),
        "paper-created",
    )
    accepted = dict(
        sequence=1, outcome="accepted", operation=paper, head=dict(revision=1, operation=paper)
    )
    conflict_op = dict(paper, operation_id="conflict", base_revision=0)
    conflict = dict(
        sequence=2,
        outcome="conflict",
        operation=conflict_op,
        head=dict(revision=1, operation=paper),
    )
    result = project_activity(
        workspace_id="workspace",
        device_id="peer",
        cursor=2,
        events=[accepted, conflict],
        heads={},
        graph={},
        papers={},
        notes={},
    )
    assert [row["operation_id"] for row in result["recent"]] == ["conflict"]
    assert result["recent"][0]["origin"] == "this_device"
    assert result["recent"][0]["status"] == "conflict_retained"
    assert result["continue"] == []


def test_note_remap_or_changed_anchor_cannot_reuse_old_resume_proof(activity):
    path, reader, _, _, _, _ = activity
    row = reader.snapshot()["continue"][0]
    with closing(sqlite3.connect(path)) as conn:
        conn.execute(
            "UPDATE notes SET anchor=?", (json.dumps(dict(ANCHOR, document_hash="b" * 64)),)
        )
        conn.commit()
    assert reader.snapshot()["continue"][0]["resume"] is None
    with pytest.raises(WorkspaceChanged):
        reader.resolve(row, locate=True)


def test_boolean_anchor_is_not_an_integer_observation(activity):
    reader = activity[1]
    row = reader.snapshot()["continue"][0]
    row["resume"]["anchor"]["p0"] = False
    with pytest.raises(WorkspaceChanged):
        reader.resolve(row, locate=True)


@pytest.mark.parametrize("corruption", ["duplicate-key", "sequence", "outcome"])
def test_canonical_received_receipt_is_checked_before_projection(activity, corruption):
    path, reader, _, _, _, _ = activity
    with closing(sqlite3.connect(path)) as conn:
        original = conn.execute(
            "SELECT event FROM paperfact_sync_inbox WHERE sequence=2"
        ).fetchone()[0]
        if corruption == "duplicate-key":
            changed = original.replace(
                '"outcome":"accepted"', '"outcome":"conflict","outcome":"accepted"'
            )
            conn.execute("UPDATE paperfact_sync_inbox SET event=? WHERE sequence=2", (changed,))
        elif corruption == "sequence":
            conn.execute("UPDATE paperfact_sync_inbox SET sequence=3 WHERE sequence=2")
            conn.execute("UPDATE paperfact_sync_cursor SET sequence=3")
        else:
            conn.execute("UPDATE paperfact_sync_inbox SET outcome='conflict' WHERE sequence=2")
        conn.commit()
    before = path.read_bytes()
    with pytest.raises(ValueError):
        reader.snapshot()
    assert path.read_bytes() == before


def test_total_activity_budget_is_fail_closed(activity, monkeypatch):
    from paper_daily import workspace_activity

    monkeypatch.setattr(workspace_activity, "MAX_BYTES", 8)
    with pytest.raises(ValueError, match="bounded"):
        activity[1].snapshot()
