"""Closed portable later-outcome contract; activation hooks remain separate."""

import copy
import os
import sqlite3
from contextlib import closing

import pytest

from paper_daily import later_outcomes as outcomes
from paper_daily import store
from paper_daily.sync_files import canonical_json


def body(available=False):
    return {
        "format": outcomes.FORMAT,
        "state": "queried_no_judged_inputs",
        "policy": outcomes.POLICY,
        "input_hash": "a" * 64,
        "query": {
            "request_id": "11111111-1111-4111-8111-111111111111",
            "queried_at": "2026-11-01T00:00:00+00:00",
            "lookup": {"title": "Paper", "doi": None, "s2_id": None, "arxiv_id": None},
            "providers": {"openalex": "queried_empty", "semantic_scholar": "unknown"},
        },
        "source": {
            "availability": "available" if available else "unavailable",
            "document_hash": "b" * 64 if available else None,
            "desired_hash": None,
        },
    }


@pytest.mark.parametrize("available", [False, True])
def test_closed_body_and_wire_keep_actual_or_missing_source_distinct(available):
    value = body(available)
    before = copy.deepcopy(value)
    assert outcomes.decode(value) == value
    encoded = canonical_json(value).decode("utf-8")
    assert outcomes.decode(encoded) == value
    payload = {
        "scope": {"kind": "paper", "id": "22222222-2222-4222-8222-222222222222"},
        "feature": "later_outcome",
        "key": "main",
        "source_document_hash": value["source"]["document_hash"],
        "data": {
            "body_json": value,
            "document_hash": value["source"]["document_hash"],
            "written_at": value["query"]["queried_at"],
        },
    }
    outcomes.validate_wire(payload)
    assert value == before
    payload["source_document_hash"] = "c" * 64
    with pytest.raises(ValueError):
        outcomes.validate_wire(payload)


@pytest.mark.parametrize(
    "change",
    [
        "unknown-format",
        "unknown-state",
        "unknown-policy",
        "extra",
        "bad-hash",
        "no-success",
        "failed-query",
        "invented-provider",
        "bad-request",
        "naive-time",
        "unknown-lookup",
        "lookup-scalar",
        "missing-source-hash",
        "invented-source-hash",
        "unknown-source-field",
        "over-budget",
        "not-object",
    ],
)
def test_malformed_or_future_outcome_fails_closed_without_mutation(change):
    value = body()
    if change == "unknown-format":
        value["format"] = "future"
    elif change == "unknown-state":
        value["state"] = "succeeded"
    elif change == "unknown-policy":
        value["policy"] = "future"
    elif change == "extra":
        value["summary"] = "A fake overview"
    elif change == "bad-hash":
        value["input_hash"] = "x"
    elif change == "no-success":
        value["query"]["providers"]["openalex"] = "unknown"
    elif change == "failed-query":
        value["query"]["providers"]["openalex"] = "failed"
    elif change == "invented-provider":
        value["query"]["providers"]["other"] = "queried_empty"
    elif change == "bad-request":
        value["query"]["request_id"] = None
    elif change == "naive-time":
        value["query"]["queried_at"] = "2026-11-01"
    elif change == "unknown-lookup":
        value["query"]["lookup"]["path"] = "arbitrary"
    elif change == "lookup-scalar":
        value["query"]["lookup"]["title"] = 3
    elif change == "missing-source-hash":
        value["source"]["availability"] = "available"
    elif change == "invented-source-hash":
        value["source"]["document_hash"] = "b" * 64
    elif change == "unknown-source-field":
        value["source"]["owner"] = "untrusted"
    elif change == "over-budget":
        value["query"]["lookup"]["title"] = "x" * 32769
    elif change == "not-object":
        value = []
    before = copy.deepcopy(value)
    with pytest.raises(ValueError):
        outcomes.decode(value)
    assert value == before


@pytest.mark.parametrize("raw", ['{"format":1,"format":2}', '{"value":NaN}', "null", "[]"])
def test_malformed_json_never_becomes_completion(raw):
    with pytest.raises(ValueError):
        outcomes.decode(raw)


def test_input_inventory_includes_unjudged_rows_and_reads_without_writes(tmp_path):
    path = tmp_path / "research.sqlite"
    with closing(sqlite3.connect(path)) as conn, conn:
        conn.executescript(store.SCHEMA)
        conn.execute(
            "INSERT INTO papers(id,title,title_key,venue,year,source) "
            "VALUES('paper','Paper','paper','Fixture',2026,'fixture')"
        )
    before = path.read_bytes()
    with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as conn:
        conn.row_factory = sqlite3.Row
        first = outcomes.inputs(conn, "paper")
        assert first["cites"] == first["followups"] == []
    assert path.read_bytes() == before
    with closing(sqlite3.connect(path)) as conn, conn:
        conn.execute(
            "INSERT INTO followups(paper_id,work_id,title,fetched_at) "
            "VALUES('paper','W1','Not judged','2026-11-01T00:00:00+00:00')"
        )
    with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as conn:
        conn.row_factory = sqlite3.Row
        second = outcomes.inputs(conn, "paper")
        assert second != first and len(second["followups"]) == 1
        assert second["followups"][0]["verdict"] is None
        assert not outcomes._empty(second)
    renamed = path.with_suffix(".closed")
    os.replace(path, renamed)
    os.replace(renamed, path)


@pytest.mark.parametrize("available", [False, True])
def test_private_source_observation_cannot_skip_absence_guard(available):
    value = {
        "availability": "available" if available else "unavailable",
        "legacy_root": "/explicit-fixture/pdf",
        "marker": "[]",
    }
    document = {"sha256": "b" * 64} if available else None
    outcomes.validate_private(value, document=document)
    with pytest.raises(ValueError, match="availability"):
        outcomes.validate_private(value, document=None if available else {"sha256": "b" * 64})


def test_sql_formatting_is_not_wire_authority_and_wire_strings_still_refuse():
    value = body()
    assert outcomes.decode(__import__("json").dumps(value, indent=2)) == value
    payload = {
        "scope": {"kind": "paper", "id": "paper"},
        "source_document_hash": None,
        "data": {
            "body_json": __import__("json").dumps(value),
            "document_hash": None,
            "written_at": value["query"]["queried_at"],
        },
    }
    with pytest.raises(ValueError, match="object"):
        outcomes.validate_wire(payload)
    for raw in ['{"format":1,"format":2}', '{"unknown":Infinity}', '{"unknown":-Infinity}']:
        with pytest.raises(ValueError):
            outcomes.decode(raw)
