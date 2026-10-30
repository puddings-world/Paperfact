"""Portable annotation business rows are bounded and independent of AI accounts."""

import json
import sqlite3
from contextlib import closing
from copy import deepcopy
from pathlib import Path

import pytest
from test_sync_content import database, envelope, insert, snapshot
from test_sync_graph_research import STAMP

from paper_daily import annotation_content as annotations
from paper_daily.sync_research import research_writer

EXAMPLES = {
    "research_questions": {
        "items": [
            {
                "question": "What assumption limits this result?",
                "why": "The experiment covers only one population.",
                "evidence": "The study only includes one experimental population.",
                "page": 3,
            }
        ]
    },
    "highlight_analysis": {
        "items": [
            {
                "text": "The study only includes one experimental population.",
                "page": 3,
                "kind": "limitation",
                "reason": "Defines the population boundary.",
                "source": "page:3",
            }
        ],
        "coverage": {"pages": 4, "empty_pages": [], "chunks": 1, "has_page_numbers": True},
    },
    "reading_links": {
        "analysis_hash": "a" * 64,
        "links": [
            {
                "quote": 0,
                "section": "dive:0",
                "explanation": "The quote qualifies the explanation's claim.",
            }
        ],
    },
}


@pytest.mark.parametrize("feature", list(EXAMPLES))
def test_annotation_contract_roundtrip_and_no_receipts(feature):
    example = deepcopy(EXAMPLES[feature])
    assert annotations.decode(feature, json.dumps(example)) == example
    example["generation"] = {"profile": "private"}
    with pytest.raises(ValueError):
        annotations.validate(feature, example)


@pytest.mark.parametrize("feature", list(EXAMPLES))
def test_actual_annotation_sql_roundtrip_preserves_typed_body(tmp_path, feature):
    source, local, _ = database(tmp_path, "source")
    receiver, remote, journal = database(tmp_path, "receiver")
    table = annotations.FEATURES[feature]
    with closing(sqlite3.connect(source)) as conn, conn:
        insert(
            conn,
            table,
            paper_id=local,
            body_json=json.dumps(EXAMPLES[feature]),
            source_hash="b" * 64,
            written_at=STAMP,
        )
    rows = snapshot(source)
    identity, payload = next(
        (key, value) for key, value in rows.items() if value.get("feature") == feature
    )
    assert payload["data"]["body_json"] == EXAMPLES[feature]
    operation = envelope(identity, payload)
    assert journal.apply(operation, research_writer)["applied"]
    assert not journal.apply(operation, research_writer)["applied"]
    with closing(sqlite3.connect(receiver)) as conn:
        row = conn.execute(f"SELECT paper_id,body_json,source_hash FROM {table}").fetchone()
    assert row[0] == remote and json.loads(row[1]) == EXAMPLES[feature]
    assert row[2] == "b" * 64


@pytest.mark.parametrize("bad", [0, -1, True, 1.5, "1"])
def test_invalid_question_page_is_rejected(bad):
    body = deepcopy(EXAMPLES["research_questions"])
    body["items"][0]["page"] = bad
    with pytest.raises(ValueError):
        annotations.validate("research_questions", body)


def test_duplicate_and_deep_or_huge_json_are_rejected():
    with pytest.raises(ValueError):
        annotations.decode("research_questions", '{"items":[],"items":[]}')
    with pytest.raises(ValueError):
        annotations.decode("research_questions", "[" * 2000 + "]" * 2000)
    with pytest.raises(ValueError):
        annotations.decode("research_questions", " " * (annotations.MAX_BYTES + 1))
    body = deepcopy(EXAMPLES["reading_links"])
    body["links"].append(dict(body["links"][0]))
    with pytest.raises(ValueError):
        annotations.validate("reading_links", body)


def test_annotation_schema_requires_and_preserves_caller_transaction():
    with closing(sqlite3.connect(":memory:")) as conn:
        with pytest.raises(ValueError, match="caller transaction"):
            annotations.initialize(conn)
        assert not conn.execute("SELECT name FROM sqlite_master").fetchall()
        conn.execute("BEGIN")
        annotations.initialize(conn)
        assert conn.in_transaction
        conn.rollback()
        assert not conn.execute("SELECT name FROM sqlite_master").fetchall()


SHARED = json.loads(
    (Path(__file__).parent / "fixtures/reading-annotations.json").read_text(encoding="utf-8")
)


@pytest.mark.parametrize("example", SHARED, ids=[item["name"] for item in SHARED])
def test_shared_mobile_and_python_annotation_contract(example):
    if example["valid"]:
        assert annotations.validate(example["feature"], example["body"]) == example["body"]
    else:
        with pytest.raises(ValueError):
            annotations.validate(example["feature"], example["body"])


@pytest.mark.parametrize("feature", list(EXAMPLES))
def test_annotation_source_pdf_identity_is_explicit_and_consistent(feature):
    from paper_daily.sync_content import validate_payload

    payload = {
        "scope": {"kind": "paper", "id": "11111111-1111-4111-8111-111111111111"},
        "feature": feature,
        "key": "main",
        "source_document_hash": "a" * 64,
        "data": {
            "body_json": EXAMPLES[feature],
            "source_hash": "b" * 64,
            "document_hash": "a" * 64,
            "written_at": STAMP,
        },
    }
    validate_payload(payload)
    payload["data"]["document_hash"] = "c" * 64
    with pytest.raises(ValueError, match="Contradictory"):
        validate_payload(payload)
    payload["data"]["document_hash"] = None
    with pytest.raises(ValueError, match="Contradictory"):
        validate_payload(payload)
    payload["source_document_hash"] = None
    validate_payload(payload)
