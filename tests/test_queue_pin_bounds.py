"""Closed import aliases and aggregate retained history remain bounded atomically."""

import copy
import json
import sqlite3
import zipfile
from contextlib import closing

import pytest
from test_queue_pin_packages import package as package

from paper_daily import bundle, enrollment_history, queue_pins, store


def changed_package(package, tmp_path, aliases):
    with zipfile.ZipFile(package) as z:
        entries = {name: z.read(name) for name in z.namelist()}
    tables = json.loads(entries["tables.json"])
    manifest = json.loads(entries["manifest.json"])
    paper = tables["papers"][0]
    pin = tables["queue_pins"][0]
    member = manifest["members"][0]
    tables["papers"] = [dict(copy.deepcopy(paper), id=alias) for alias in aliases]
    tables["queue_pins"] = [dict(pin, paper_id=alias) for alias in aliases]
    manifest["members"] = [dict(member, paper_id=alias) for alias in aliases]
    manifest["pdfs"] = {}
    entries["tables.json"] = json.dumps(tables).encode()
    entries["manifest.json"] = json.dumps(manifest).encode()
    out = tmp_path / "changed.zip"
    with zipfile.ZipFile(out, "w") as z:
        for name, value in entries.items():
            z.writestr(name, value)
    return out


@pytest.mark.parametrize("alias", [123, "", "x" * 4097], ids=["numeric", "empty", "oversized"])
def test_raw_queue_pin_owner_requires_bounded_nonempty_string(package, tmp_path, alias):
    archive = changed_package(package, tmp_path, [alias])
    with zipfile.ZipFile(archive) as z, pytest.raises(ValueError):
        bundle._validated(z)


def test_raw_queue_pin_count_is_bounded_before_import(package, tmp_path, monkeypatch):
    monkeypatch.setattr(bundle, "MAX_QUEUE_PINS", 2, raising=False)
    archive = changed_package(package, tmp_path, ["paper-a", "paper-b", "paper-c"])
    with zipfile.ZipFile(archive) as z, pytest.raises(ValueError):
        bundle._validated(z)


def test_export_refuses_oversized_queue_pin_subset_before_creating_package(
    package, tmp_path, monkeypatch
):
    monkeypatch.setattr(bundle, "MAX_QUEUE_PINS", 2, raising=False)
    with closing(sqlite3.connect(store.DB_PATH)) as conn, conn:
        for number in [1, 2]:
            identity = f"extra-{number}"
            conn.execute(
                "INSERT INTO papers(id,title,title_key,venue,year,source) "
                "VALUES(?,?,?,'Fixture',2026,'fixture')",
                (identity, identity, identity),
            )
            conn.execute(
                "INSERT INTO list_papers(list_id,paper_id,position,added_at) "
                "SELECT id,?,?,created_at FROM lists",
                (identity, number),
            )
            conn.execute(
                "INSERT INTO pins VALUES('queue',?,?)", (identity, "2026-10-30T00:00:00+00:00")
            )
        list_id = conn.execute("SELECT id FROM lists").fetchone()[0]
    out = tmp_path / "too-large.zip"
    with pytest.raises(ValueError):
        bundle.export(list_id, out, with_pdfs=False)
    assert not out.exists()


def record(stamp):
    return {
        "package_sha256": "a" * 64,
        "source_owner": "source",
        "receiver_owner": "receiver",
        "incoming_pinned_at": "2026-10-30T00:00:00+00:00",
        "receiver_pinned_at": stamp,
    }


@pytest.mark.parametrize("limit", ["records", "bytes"])
def test_aggregate_existing_plus_new_history_refuses_without_any_partial_record(
    tmp_path, monkeypatch, limit
):
    database = tmp_path / "history.sqlite"
    first = record("2026-11-01T00:00:00+00:00")
    second = record("2026-11-02T00:00:00+00:00")
    with closing(sqlite3.connect(database)) as conn:
        conn.execute("BEGIN IMMEDIATE")
        queue_pins.retain_imports_in(conn, [first])
        conn.commit()
        saved = enrollment_history.archived(conn)
        if limit == "records":
            monkeypatch.setattr(enrollment_history, "MAX_RECORDS", 1)
        else:
            body = enrollment_history.wrap("queue_pin_import_v1", second)["body_json"]
            monkeypatch.setattr(
                enrollment_history,
                "MAX_TOTAL",
                len(saved[0]["body_json"].encode()) + len(body.encode()) - 1,
            )
        # Identical retries do not consume another record or its bytes.
        conn.execute("BEGIN IMMEDIATE")
        queue_pins.retain_imports_in(conn, [first])
        conn.commit()
        assert enrollment_history.archived(conn) == saved
        before = database.read_bytes()
        conn.execute("BEGIN IMMEDIATE")
        with pytest.raises(ValueError):
            queue_pins.retain_imports_in(conn, [second])
        conn.rollback()
        assert enrollment_history.archived(conn) == saved
        assert database.read_bytes() == before
