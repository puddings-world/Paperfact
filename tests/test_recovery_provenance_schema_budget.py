"""Real trusted schema construction is bounded per closed archive-validation call."""

import copy
import hashlib
import json
import sqlite3
import threading
import zipfile
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from contextvars import copy_context
from types import SimpleNamespace
from uuid import uuid4

import pytest

from paper_daily import recovery_provenance as provenance
from paper_daily import sync_recovery as recovery


@pytest.fixture
def archive(tmp_path):
    database = tmp_path / "papers.db"
    with closing(sqlite3.connect(database)) as conn, conn:
        conn.executescript(recovery.SCHEMA)
        recovery._migrate(conn)
        for index in range(3):
            conn.execute(
                "INSERT INTO papers(id,title,title_key,year,venue,source) VALUES(?,?,?,?,?,?)",
                (str(index), "Fixture " + str(index), "fixture-" + str(index), 2026, "", "fixture"),
            )
    package = tmp_path / "source.zip"
    manifest = recovery.create(database, package)
    with zipfile.ZipFile(package) as saved:
        tables = {
            item["name"]: [
                json.loads(line)
                for line in saved.read("tables/" + item["name"] + ".jsonl").splitlines()
            ]
            for item in manifest["tables"]
        }
    rows = provenance.encode(manifest, tables)
    return SimpleNamespace(database=database, manifest=manifest, tables=tables, rows=rows)


def nested(archive, rows):
    tables = copy.deepcopy(archive.tables)
    tables[provenance.TABLE] = rows
    registry = recovery._registry()
    manifest = copy.deepcopy(archive.manifest)
    manifest["backup_id"] = str(uuid4())
    manifest["tables"] = []
    for name, values in sorted(tables.items()):
        data = b"".join((recovery._json(row) + "\n").encode() for row in values)
        section, columns = registry[name]
        manifest["tables"].append(
            dict(name=name, section=section, columns=columns, count=len(values),
                 size=len(data), sha256=hashlib.sha256(data).hexdigest())
        )
    return provenance.encode(manifest, tables)


def count_real_schema(monkeypatch):
    actual, calls = recovery._research_schema, []

    def counted():
        calls.append(threading.get_ident())
        return actual()

    monkeypatch.setattr(recovery, "_research_schema", counted)
    return calls


def test_real_schema_budget_and_complete_parsed_rows_are_independent_of_row_count(
    archive, monkeypatch
):
    before = archive.database.read_bytes()
    calls = count_real_schema(monkeypatch)
    groups = provenance.validate_groups(archive.rows)
    assert len(groups) == 1 and groups[0].paper_ids == {"0", "1", "2"}
    assert groups[0].refs == {} and groups[0].pending == []
    assert archive.database.read_bytes() == before
    assert len(calls) == 2, f"Real complete schema builds: {len(calls)} (budget: 2)"


def test_nested_groups_share_only_schema_metadata_and_still_validate_each_manifest(
    archive, monkeypatch
):
    rows = nested(archive, archive.rows)
    calls = count_real_schema(monkeypatch)
    groups = provenance.validate_groups(rows)
    assert groups[0].paper_ids == {"0", "1", "2"}
    assert groups[0]._recovered_groups[0].paper_ids == {"0", "1", "2"}
    assert len(calls) == 3, f"Real complete schema builds: {len(calls)} (budget: 3)"


def test_independent_calls_and_standalone_decode_always_build_fresh_metadata(archive, monkeypatch):
    calls = count_real_schema(monkeypatch)
    row = next(row for row in archive.rows if json.loads(row["body_json"])["kind"] == "row")
    expected = json.loads(row["body_json"])
    assert provenance.decode(row) == expected
    assert provenance.decode(row) == expected
    assert len(calls) == 2
    for _ in range(2):
        assert provenance.validate_groups(archive.rows)[0].paper_ids == {"0", "1", "2"}
    assert len(calls) == 6


@pytest.mark.parametrize("change", ["fields", "hash", "missing", "closure"])
def test_rejections_are_complete_and_error_scope_does_not_survive(archive, monkeypatch, change):
    rows = copy.deepcopy(archive.rows)
    if change == "fields":
        value = json.loads(rows[-1]["body_json"])
        value["record"]["unexpected"] = 1
        rows[-1] = provenance.wrap(value.pop("backup_id"), value.pop("kind"), **{
            key: item for key, item in value.items() if key != "version"
        })
        message = "Unexpected recovery row fields"
    elif change == "missing":
        rows.pop()
        message = "Incomplete recovered provenance rows"
    else:
        manifest = copy.deepcopy(archive.manifest)
        if change == "hash":
            manifest["tables"][0]["sha256"] = "a" * 64
            message = "table differs from its inspected manifest"
        else:
            manifest["blobs"] = [{"sha256": "a" * 64, "size": 1}]
            message = "complete blob closure"
        rows[0] = provenance.wrap(manifest["backup_id"], "manifest", manifest=manifest)
    calls = count_real_schema(monkeypatch)
    with pytest.raises(ValueError, match=message):
        provenance.validate_groups(rows)
    calls.clear()
    assert provenance.validate_groups(archive.rows)[0].paper_ids == {"0", "1", "2"}
    assert len(calls) == 2


def test_depth_and_empty_input_need_no_schema_and_keep_original_bounds(archive, monkeypatch):
    calls = count_real_schema(monkeypatch)
    assert provenance.validate_groups([]) == []
    with pytest.raises(ValueError, match="nesting exceeds"):
        provenance.validate_groups(archive.rows, depth=provenance.MAX_DEPTH)
    assert calls == []


def test_factory_error_resets_scope_without_reusing_a_partial_schema(archive, monkeypatch):
    actual, calls = recovery._research_schema, []

    def fails_once():
        calls.append(True)
        result = actual()
        if len(calls) == 1:
            raise RuntimeError("synthetic schema construction failure")
        return result

    monkeypatch.setattr(recovery, "_research_schema", fails_once)
    with pytest.raises(RuntimeError, match="synthetic schema"):
        provenance.validate_groups(archive.rows)
    assert provenance.validate_groups(archive.rows)[0].paper_ids == {"0", "1", "2"}
    assert len(calls) == 3


def test_concurrent_independent_validations_build_separate_real_metadata(archive, monkeypatch):
    actual, counts = recovery._research_schema, {}
    lock, rendezvous = threading.Lock(), threading.Barrier(2)

    def counted():
        identity = threading.get_ident()
        with lock:
            counts[identity] = counts.get(identity, 0) + 1
            first = counts[identity] == 1
        if first:
            rendezvous.wait(20)
        return actual()

    monkeypatch.setattr(recovery, "_research_schema", counted)
    with ThreadPoolExecutor(max_workers=2) as workers:
        futures = [workers.submit(provenance.validate_groups, archive.rows) for _ in range(2)]
        assert [future.result(timeout=40)[0].paper_ids for future in futures] == [
            {"0", "1", "2"}, {"0", "1", "2"}
        ]
    assert sorted(counts.values()) == [2, 2]


def test_copied_finished_context_cannot_keep_validation_metadata(archive, monkeypatch):
    copied = []

    def rows():
        yield archive.rows[0]
        yield archive.rows[1]
        copied.append(copy_context())
        yield from archive.rows[2:]

    provenance.validate_groups(rows())
    calls = count_real_schema(monkeypatch)
    row = archive.rows[1]
    assert copied[0].run(provenance.decode, row) == json.loads(row["body_json"])
    assert copied[0].run(provenance.decode, row) == json.loads(row["body_json"])
    assert len(calls) == 2


def test_archive_publication_rollback_and_retry_store_exact_original_rows(archive, tmp_path):
    database = tmp_path / "retained.db"
    with closing(sqlite3.connect(database)) as conn:
        conn.execute("BEGIN")
        provenance.retain_in(conn, archive.rows)
        conn.rollback()
        assert conn.execute(
            "SELECT name FROM sqlite_master WHERE name=?", (provenance.TABLE,)
        ).fetchone() is None
        for _ in range(2):
            conn.execute("BEGIN")
            provenance.retain_in(conn, archive.rows)
            conn.commit()
        saved = [dict(zip(provenance.COLUMNS.split(), row, strict=True)) for row in conn.execute(
            "SELECT " + provenance.COLUMNS.replace(" ", ",") + " FROM " + provenance.TABLE
        )]
    assert sorted(saved, key=lambda row: row["record_id"]) == sorted(
        archive.rows, key=lambda row: row["record_id"]
    )


def test_reentrant_independent_top_level_call_restores_the_outer_operation(archive, monkeypatch):
    calls = count_real_schema(monkeypatch)

    def rows():
        yield archive.rows[0]
        yield archive.rows[1]
        inner = provenance.validate_groups(archive.rows)
        assert inner[0].paper_ids == {"0", "1", "2"}
        yield from archive.rows[2:]

    assert provenance.validate_groups(rows())[0].paper_ids == {"0", "1", "2"}
    assert len(calls) == 4
