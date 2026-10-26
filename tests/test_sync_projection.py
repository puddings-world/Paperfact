"""Read projections use synthetic production-schema databases and never initialize them."""

import hashlib
import json
import sqlite3

import pytest

from paper_daily import sync_projection
from paper_daily.store import SCHEMA
from paper_daily.sync_client import SyncClient
from paper_daily.sync_journal import Journal
from paper_daily.sync_projection import read_manifest
from paper_daily.sync_research import prepare, research_writer

FINGERPRINT = "a" * 64
ANCHOR = {"p0": 0, "o0": 2, "p1": 0, "o1": 7}


@pytest.fixture
def path(tmp_path):
    path = tmp_path / "research.db"
    with sqlite3.connect(path) as conn:
        conn.executescript(SCHEMA)
        conn.executemany(
            "INSERT INTO papers(id,venue,year,title,title_key,source,authors_json,doi,page_url) "
            "VALUES(?, 'Fixture',2026,?,?,'fixture',?,?,?)",
            [
                (
                    "paper-a",
                    "Paper A",
                    "papera",
                    '["Ada",{"name":"Bob","secret":"not-exported"}]',
                    "10.1234/example",
                    "https://example.org/paper",
                ),
                ("paper-b", "Paper B", "paperb", "[]", None, "file:///private/document.pdf"),
            ],
        )
        conn.execute("INSERT INTO lists VALUES('reading','Research','Why these papers','old')")
        conn.executemany(
            "INSERT INTO list_papers(list_id,paper_id,position,state,added_at) "
            "VALUES('reading',?,?,?,'old')",
            [("paper-a", 7, "read"), ("paper-b", 2, "pending")],
        )
        conn.execute(
            "INSERT INTO notes(paper_id,body,created_at) VALUES('paper-a','Plain note','old')"
        )
        conn.execute(
            "INSERT INTO notes(paper_id,body,created_at,kind,page,anchor) "
            "VALUES('paper-a','Anchored note','old','note',1,?)",
            (
                json.dumps(
                    {**ANCHOR, "document_hash": FINGERPRINT, "local_path": "private-anchor-path"}
                ),
            ),
        )
        conn.execute(
            "INSERT INTO notes(paper_id,body,created_at,kind) "
            "VALUES('paper-a','Saved answer','old','ask')"
        )
        conn.execute(
            "INSERT INTO dives(paper_id,body,written_at) VALUES('paper-a','Deep explanation','old')"
        )
        conn.execute(
            "INSERT INTO close_readings(paper_id,body,written_at) "
            "VALUES('paper-a','Section explanation','old')"
        )
        conn.execute(
            "INSERT INTO list_surveys(list_id,body,written_at) "
            "VALUES('reading','Survey context','old')"
        )
        conn.execute(
            "INSERT INTO cites(paper_id,ref_key,title,year,purpose,gist,why,written_at) "
            "VALUES('paper-a','[1]','Prior work',2020,'Background','Main idea','Relevance','old')"
        )
        conn.execute(
            "INSERT INTO pdf_highlights(paper_id,document_hash,anchor,quote,created_at) "
            "VALUES('paper-a',?,?,'Manual quote','old')",
            (FINGERPRINT, json.dumps(ANCHOR)),
        )
        conn.execute(
            "INSERT INTO pdf_ai_highlights(paper_id,document_hash,source_key,analysis_hash,"
            "anchor,quote,reason,hidden) VALUES('paper-a',?,'source-a','analysis-a',?,"
            "'AI quote','Important limitation',1)",
            (FINGERPRINT, json.dumps(ANCHOR)),
        )
        conn.executemany(
            "INSERT INTO kv VALUES(?,?)",
            [
                ("llm.config", "credential-fixture-never-export"),
                ("ui.path", "private-workspace-path"),
                ("feedback.consent", "telemetry-fixture-never-export"),
            ],
        )
    prepare(path, workspace_id="workspace", device_id="device")
    return path


def read(path, **kwargs):
    return read_manifest(path, workspace_id="workspace", **kwargs)


def test_projection_contains_ordered_research_anchors_reasons_without_secrets(path):
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    manifest = read(path)
    assert manifest["schema_version"] == 1 and manifest["cursor"] == 0
    assert manifest["lists"][0]["members"] == [
        {"paper_id": "paper-b", "position": 2, "state": "pending"},
        {"paper_id": "paper-a", "position": 7, "state": "read"},
    ]
    assert manifest["lists"][0]["analysis_sections"][0]["body"] == "Survey context"
    first, second = manifest["papers"]
    assert first["authors"] == ["Ada", "Bob"]
    assert first["url"] == "https://example.org/paper"
    assert second["url"] is None
    assert [section["body"] for section in first["analysis_sections"]] == [
        "Deep explanation",
        "Section explanation",
    ]
    assert first["citations"][0]["why"] == "Relevance"
    plain, anchored, answer = manifest["notes"]
    assert (
        plain["editable"] is True and plain["revision"] is None and plain["sync_state"] == "local"
    )
    assert anchored["editable"] is False and answer["editable"] is False
    assert anchored["anchor"] == {"schema_version": 1, "kind": "word_range", **ANCHOR}
    assert anchored["pdf_hash"] == FINGERPRINT
    manual, automatic = manifest["highlights"]
    assert manual["quote"] == "Manual quote" and manual["origin"] == "manual"
    assert automatic["reason"] == "Important limitation" and automatic["hidden"] is True
    assert manual["pdf_hash"] == automatic["pdf_hash"] == FINGERPRINT
    assert len({item["id"] for item in manifest["notes"]}) == 3
    assert manifest["decks"] == manifest["assets"] == []
    assert first["pdf_asset_id"] is None
    assert manifest["capabilities"] == {
        "database_read_projection": True,
        "sync_bootstrap": False,
        "assets": False,
        "decks": False,
    }
    serialized = json.dumps(manifest)
    for forbidden in (
        "credential-fixture",
        "telemetry-fixture",
        "private-workspace-path",
        "private-anchor-path",
        "not-exported",
        "file://",
        "device",
    ):
        assert forbidden not in serialized
    assert hashlib.sha256(path.read_bytes()).hexdigest() == before


@pytest.mark.parametrize(
    "url",
    [
        "https://user:password@example.org/paper",
        "https://example.org/paper?token=private",
        "https://localhost/paper",
        "https://127.0.0.1/paper",
        "https://10.0.0.1/paper",
        "javascript:alert(1)",
        "http://example.org/paper",
        "https://host.local/paper",
    ],
)
def test_unsafe_urls_are_never_exported_as_fetch_capabilities(path, url):
    with sqlite3.connect(path) as conn:
        conn.execute("UPDATE papers SET page_url=? WHERE id='paper-a'", (url,))
    assert read(path)["papers"][0]["url"] is None


def test_untrusted_html_stays_text_and_unknown_anchor_is_read_only(path):
    with sqlite3.connect(path) as conn:
        conn.execute(
            "UPDATE notes SET body=?,anchor=? WHERE id=1",
            ("<script>untrusted text</script>", '{"path":"private-file","html":"bad"}'),
        )
    note = read(path)["notes"][0]
    assert note["body"] == "<script>untrusted text</script>"
    assert note["anchor"] is None and note["anchor_status"] == "unsupported"
    assert note["editable"] is False
    assert "private-file" not in json.dumps(note)


def test_unenrolled_or_reassigned_notes_fail_instead_of_disappearing(path):
    with sqlite3.connect(path) as conn:
        conn.execute(
            "INSERT INTO notes(paper_id,body,created_at) "
            "VALUES('paper-a','New unenrolled note','later')"
        )
    with pytest.raises(ValueError, match="unenrolled"):
        read(path)
    prepare(path, workspace_id="workspace", device_id="device")
    with sqlite3.connect(path) as conn:
        conn.execute("UPDATE notes SET created_at='changed' WHERE id=4")
    with pytest.raises(ValueError, match="reconciliation"):
        read(path)


@pytest.mark.parametrize(
    "mutation",
    [
        "DELETE FROM papers WHERE id='paper-b'",
        "UPDATE notes SET paper_id='missing' WHERE id=1",
        "DELETE FROM lists WHERE id='reading'",
        "UPDATE pdf_highlights SET paper_id='missing'",
    ],
)
def test_missing_references_are_reported_explicitly(path, mutation):
    with sqlite3.connect(path) as conn:
        conn.execute(mutation)
    with pytest.raises(ValueError, match="reference|reconciliation"):
        read(path)


def test_wrong_workspace_and_uninitialized_database_do_not_write(path, tmp_path):
    before = path.read_bytes()
    with pytest.raises(ValueError, match="workspace"):
        read_manifest(path, workspace_id="another-workspace")
    assert path.read_bytes() == before
    missing = tmp_path / "not-created.db"
    with pytest.raises(ValueError, match="unavailable"):
        read(missing)
    assert not missing.exists()
    uninitialized = tmp_path / "uninitialized.db"
    with sqlite3.connect(uninitialized) as conn:
        conn.executescript(SCHEMA)
    unchanged = uninitialized.read_bytes()
    with pytest.raises(ValueError, match="incompatible"):
        read(uninitialized)
    assert uninitialized.read_bytes() == unchanged


def test_record_and_byte_limits_fail_without_partial_output(path):
    with pytest.raises(ValueError, match="record limit"):
        read(path, max_records=1)
    with pytest.raises(ValueError, match="byte limit"):
        read(path, max_bytes=100)
    size = len(json.dumps(read(path), ensure_ascii=False, separators=(",", ":")).encode())
    assert read(path, max_bytes=size)
    with pytest.raises(ValueError, match="byte limit"):
        read(path, max_bytes=size - 1)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"max_records": True},
        {"max_records": 0},
        {"max_records": 100001},
        {"max_bytes": 0},
        {"max_bytes": 64 * 1024 * 1024 + 1},
    ],
)
def test_invalid_bounds_are_rejected(path, kwargs):
    with pytest.raises(ValueError, match="limit"):
        read(path, **kwargs)


def test_revisions_do_not_advertise_pending_or_deferred_content_as_synced(path):
    client = SyncClient(
        Journal(path, workspace_id="workspace", device_id="device"), research_writer
    )
    client.save(client.new_operation("list", "reading", {"name": "Pending rename", "note": ""}))
    with sqlite3.connect(path) as conn:
        conn.execute(
            "INSERT INTO paperfact_sync_heads(entity_type,entity_id,revision,operation,"
            "applied_revision) VALUES('list','reading',7,NULL,-1)"
        )
        conn.execute("UPDATE paperfact_sync_cursor SET sequence=7")
    manifest = read(path)
    assert manifest["cursor"] == 7
    assert manifest["lists"][0]["revision"] is None
    assert manifest["lists"][0]["sync_state"] == "pending"
    assert manifest["local_state"] == {
        "pending_operations": 1,
        "awaiting_receipts": 0,
        "deferred_entities": 1,
    }
    with sqlite3.connect(path) as conn:
        conn.execute("UPDATE paperfact_sync_operations SET server_revision=7")
    assert read(path)["lists"][0]["sync_state"] == "deferred"
    with sqlite3.connect(path) as conn:
        conn.execute("UPDATE paperfact_sync_heads SET applied_revision=revision")
    synced = read(path)["lists"][0]
    assert synced["revision"] == 7 and synced["sync_state"] == "synced"


def test_cursor_and_content_use_one_read_snapshot_during_concurrent_commit(path, monkeypatch):
    SyncClient(Journal(path, workspace_id="workspace", device_id="device"), research_writer)
    with sqlite3.connect(path) as conn:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("UPDATE paperfact_sync_cursor SET sequence=1")
    original_connect = sqlite3.connect
    changed = False

    def connect(*args, **kwargs):
        conn = original_connect(*args, **kwargs)

        def trace(statement):
            nonlocal changed
            if not changed and "FROM papers" in statement:
                changed = True
                with original_connect(path) as writer:
                    writer.execute("UPDATE papers SET title='Updated later' WHERE id='paper-a'")
                    writer.execute("UPDATE paperfact_sync_cursor SET sequence=2")

        conn.set_trace_callback(trace)
        return conn

    monkeypatch.setattr(sync_projection.sqlite3, "connect", connect)
    manifest = read(path)
    assert changed is True
    assert manifest["cursor"] == 1 and manifest["papers"][0]["title"] == "Paper A"
    next_manifest = read(path)
    assert next_manifest["cursor"] == 2 and next_manifest["papers"][0]["title"] == "Updated later"


def test_acknowledged_local_edit_is_awaiting_until_receipt_is_received(path):
    client = SyncClient(
        Journal(path, workspace_id="workspace", device_id="device"), research_writer
    )
    client.save(client.new_operation("list", "reading", {"name": "Awaiting rename", "note": ""}))
    with sqlite3.connect(path) as conn:
        conn.execute("UPDATE paperfact_sync_operations SET server_revision=8")
        conn.execute(
            "INSERT INTO paperfact_sync_heads(entity_type,entity_id,revision,operation,"
            "applied_revision) VALUES('list','reading',7,NULL,7)"
        )
        conn.execute("UPDATE paperfact_sync_cursor SET sequence=7")
    manifest = read(path)
    assert manifest["local_state"] == {
        "pending_operations": 0,
        "awaiting_receipts": 1,
        "deferred_entities": 0,
    }
    assert manifest["lists"][0]["sync_state"] == "awaiting"
    assert manifest["lists"][0]["revision"] == 7
    assert manifest["lists"][0]["name"] == "Awaiting rename"
