"""Actual adoption record reads reuse definitions, never rows or identity proofs."""

import copy
import json
import threading
from concurrent.futures import ThreadPoolExecutor
from contextlib import nullcontext
from contextvars import copy_context
from types import SimpleNamespace

import pytest
from test_recovery_provenance_schema_budget import archive as archive_fixture
from test_recovery_provenance_schema_budget import nested

from paper_daily import recovery_adoption as adoption
from paper_daily import recovery_provenance as provenance
from paper_daily import sync_recovery as recovery

archive = archive_fixture


@pytest.fixture
def captured(archive):
    # Real archive/manifest/table hashes, with two complete historical snapshots.
    historical = nested(archive, archive.rows)
    envelopes = nested(archive, historical)
    decoded = [json.loads(row["body_json"]) for row in envelopes]
    manifest = decoded[0]["manifest"]
    tables = {table["name"]: [] for table in manifest["tables"]}
    for row in decoded[1:]:
        assert row["index"] == len(tables[row["table"]])
        tables[row["table"]].append(row["record"])
    row = next(row for row in historical if json.loads(row["body_json"])["kind"] == "row")
    return SimpleNamespace(
        value=dict(manifest=manifest, tables=tables), row=row, database=archive.database
    )


def counted_schema(monkeypatch):
    actual, calls = recovery._research_schema, []

    def counted():
        calls.append(threading.get_ident())
        return actual()

    monkeypatch.setattr(recovery, "_research_schema", counted)
    return calls


def assert_parsed(records, value):
    assert records.paper_ids == {"0", "1", "2"}
    assert records.refs == {} and records.pending == []
    assert records.recovered_provenance == value["tables"][provenance.TABLE]
    first = records._recovered_groups[0]
    assert first.paper_ids == {"0", "1", "2"}
    assert first._recovered_groups[0].paper_ids == {"0", "1", "2"}


def test_actual_record_read_has_constant_definition_budget_and_exact_nested_data(
    captured, monkeypatch
):
    before = copy.deepcopy(captured.value)
    database = captured.database.read_bytes()
    calls = counted_schema(monkeypatch)
    records = adoption._records(captured.value)
    assert_parsed(records, captured.value)
    assert captured.value == before and captured.database.read_bytes() == database
    assert len(calls) == 4, f"Real complete schema builds: {len(calls)} (budget: 4)"


def test_independent_record_reads_and_standalone_decodes_remain_fresh(captured, monkeypatch):
    calls = counted_schema(monkeypatch)
    for _ in range(2):
        assert_parsed(adoption._records(captured.value), captured.value)
    assert len(calls) == 8
    for _ in range(2):
        assert provenance.decode(captured.row) == json.loads(captured.row["body_json"])
    assert len(calls) == 10


def test_public_scope_always_creates_fresh_reentrant_definition_scope(captured, monkeypatch):
    calls = counted_schema(monkeypatch)
    with provenance.schema_definition_scope() as authority:
        assert authority is None
        provenance.decode(captured.row)
        with provenance.schema_definition_scope() as authority:
            assert authority is None
            provenance.decode(captured.row)
        provenance.decode(captured.row)
    assert len(calls) == 2
    provenance.decode(captured.row)
    assert len(calls) == 3


def test_row_hash_error_releases_operation_scope_before_retry(captured, monkeypatch):
    value = copy.deepcopy(captured.value)
    value["tables"][provenance.TABLE][-1]["body_json"] += " "
    calls = counted_schema(monkeypatch)
    with pytest.raises(ValueError, match="identity differs from its content"):
        adoption._records(value)
    assert len(calls) == 1
    assert provenance.decode(captured.row) == json.loads(captured.row["body_json"])
    assert len(calls) == 2
    assert_parsed(adoption._records(captured.value), captured.value)
    assert len(calls) == 6


def test_real_schema_factory_exception_clears_record_operation_scope(captured, monkeypatch):
    actual, calls = recovery._research_schema, []

    def first_failure():
        calls.append(True)
        result = actual()
        if len(calls) == 1:
            raise RuntimeError("synthetic real schema failure")
        return result

    monkeypatch.setattr(recovery, "_research_schema", first_failure)
    with pytest.raises(RuntimeError, match="synthetic real schema"):
        adoption._records(captured.value)
    assert_parsed(adoption._records(captured.value), captured.value)
    assert len(calls) == 5


def test_parallel_record_operations_own_separate_real_schema_definitions(captured, monkeypatch):
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
        futures = [workers.submit(adoption._records, captured.value) for _ in range(2)]
        for future in futures:
            assert_parsed(future.result(timeout=40), captured.value)
    assert sorted(counts.values()) == [4, 4]


@pytest.mark.parametrize("error", [False, True])
def test_copied_context_after_scope_exit_cannot_reuse_definition_metadata(
    captured, monkeypatch, error
):
    with (
        pytest.raises(RuntimeError) if error else nullcontext(),
        provenance.schema_definition_scope(),
    ):
        provenance.decode(captured.row)
        copied = copy_context()
        if error:
            raise RuntimeError("synthetic scope error")
    calls = counted_schema(monkeypatch)
    for _ in range(2):
        assert copied.run(provenance.decode, captured.row) == json.loads(captured.row["body_json"])
    assert len(calls) == 2
    assert_parsed(copied.run(adoption._records, captured.value), captured.value)
    assert len(calls) == 6


def test_reentrant_record_read_restores_the_original_operation_metadata(captured, monkeypatch):
    value = copy.deepcopy(captured.value)
    calls = counted_schema(monkeypatch)
    inner_results = []

    class ReentrantRows(list):
        def __iter__(self):
            for index, row in enumerate(super().__iter__()):
                yield row
                if index == 1:
                    inner_results.append(adoption._records(captured.value))

    value["tables"][provenance.TABLE] = ReentrantRows(value["tables"][provenance.TABLE])
    records = adoption._records(value)
    assert_parsed(records, captured.value)
    assert len(inner_results) == 1
    assert_parsed(inner_results[0], captured.value)
    assert len(calls) == 8
