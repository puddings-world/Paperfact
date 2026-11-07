"""Actual composite SQL/source observations; no new domain activation."""

import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from dataclasses import replace
from uuid import uuid4

import pytest
from test_research_lineage import corpus as _corpus
from test_research_lineage import proposals

from paper_daily import lineage_sets, research_lineage
from paper_daily import research_generation as generation

corpus = _corpus
STAMP = "2026-10-31T00:00:00+00:00"


def work(call, *args, **kwargs):
    with ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(call, *args, **kwargs).result(timeout=10)


def initialized(corpus):
    database = corpus[0]
    with closing(sqlite3.connect(database)) as conn, conn:
        conn.execute(lineage_sets.SCHEMA)
    return database


def check(database, observed):
    from paper_daily.lineage_observation import check_in

    with closing(generation._connect(database)) as conn:
        conn.execute("BEGIN")
        return check_in(conn, observed)


def make_row(captured, corpus_id):
    report = research_lineage.verify_snapshot(captured, proposals(captured))
    body = dict(
        format=lineage_sets.FORMAT,
        corpus_id=corpus_id,
        inputs=dict(dive=None, close_reading=None),
        generation=dict(
            task="lineage", backend="fixture", requested_model=None, returned_model=None
        ),
        report=report,
        bindings=[
            dict(source_id=s["id"], paper_id=p["local_id"])
            for s, p in zip(captured.sources, json.loads(captured._json)["observed"], strict=True)
        ],
    )
    return dict(
        paper_id="focal",
        corpus_key=corpus_id,
        body_json=json.dumps(body, indent=2),
        source_hash=lineage_sets.source_hash(body),
        document_hash=captured.sources[0]["document_hash"],
        written_at=STAMP,
    )


def test_actual_absent_target_is_composite_and_metadata_reads_write_nothing(corpus):
    from paper_daily.lineage_observation import observe

    database = initialized(corpus)
    before = database.read_bytes()
    key, request = str(uuid4()), str(uuid4())
    observed = work(observe, corpus[2], key, request)
    assert observed.data["target"] is None
    assert observed.data["corpus_id"] == key and observed.data["request_id"] == request
    assert [s["local_id"] for s in observed.data["sources"]] == ["focal", "prior", "later"]
    assert work(check, database, observed)
    assert database.read_bytes() == before
    assert all(s["parent"] is None and s["source_graph"] is None for s in observed.data["sources"])


def test_two_corpus_keys_do_not_alias_and_historical_json_bytes_remain_exact(corpus):
    from paper_daily.lineage_observation import observe

    database = initialized(corpus)
    key, other = str(uuid4()), str(uuid4())
    row = make_row(corpus[2], key)
    with closing(sqlite3.connect(database)) as conn, conn:
        conn.execute("INSERT INTO paper_lineage_sets VALUES(?,?,?,?,?,?)", tuple(row.values()))
    observed = work(observe, corpus[2], key, str(uuid4()))
    absent = work(observe, corpus[2], other, str(uuid4()))
    assert observed.data["target"]["body_json"] == row["body_json"]
    assert absent.data["target"] is None
    with closing(sqlite3.connect(database)) as conn, conn:
        conn.execute(
            "UPDATE paper_lineage_sets SET body_json=? WHERE corpus_key=?",
            (lineage_sets.canonical(json.loads(row["body_json"])), key),
        )
    with pytest.raises(research_lineage.LineageError, match="lineage_observation_changed"):
        work(check, database, observed)
    assert work(check, database, absent)


def test_capture_is_process_sealed_and_wrong_database_or_parent_cannot_match(corpus, tmp_path):
    from paper_daily.lineage_observation import checked, observe

    database = initialized(corpus)
    observed = work(observe, corpus[2], str(uuid4()), str(uuid4()))
    with pytest.raises(research_lineage.LineageError, match="invalid_lineage_observation"):
        checked(replace(observed, _json=observed._json.replace('"focal"', '"other"')))
    wrong = tmp_path / "other.sqlite"
    with closing(sqlite3.connect(wrong)) as conn, conn:
        conn.execute(lineage_sets.SCHEMA)
    with pytest.raises(research_lineage.LineageError, match="lineage_database_or_binding_changed"):
        work(check, wrong, observed)
    with closing(sqlite3.connect(database)) as conn, conn:
        conn.execute("UPDATE papers SET title='Different actual parent' WHERE id='prior'")
    with pytest.raises(research_lineage.LineageError, match="lineage_parent_changed"):
        work(check, database, observed)


def test_publication_metadata_recheck_does_not_parse_or_hash_pdf_under_sql_lock(
    corpus, monkeypatch
):
    from paper_daily import lineage_observation

    database = initialized(corpus)
    observed = work(lineage_observation.observe, corpus[2], str(uuid4()), str(uuid4()))
    monkeypatch.setattr(research_lineage, "_checked", lambda *_: pytest.fail("No PDF seal hash"))
    monkeypatch.setattr(
        lineage_observation,
        "_checked_snapshot",
        lambda *_: pytest.fail("No PDF byte hash under SQL lock"),
    )
    assert work(check, database, observed)


def test_native_file_version_change_refuses_old_observation_without_reading_pdf(corpus):
    from paper_daily.lineage_observation import observe

    database = initialized(corpus)
    observed = work(observe, corpus[2], str(uuid4()), str(uuid4()))
    path = corpus[2]._documents[1].path
    path.write_bytes(b"changed exact original bytes")
    with pytest.raises(research_lineage.LineageError, match="lineage_observation_changed"):
        work(check, database, observed)


def test_missing_or_tampered_schema_is_not_installed_by_observation(corpus):
    from paper_daily.lineage_observation import observe

    with pytest.raises(research_lineage.LineageError, match="lineage_schema_required"):
        work(observe, corpus[2], str(uuid4()), str(uuid4()))
    with closing(sqlite3.connect(corpus[0])) as conn, conn:
        conn.execute("CREATE TABLE paper_lineage_sets(wrong TEXT)")
    with pytest.raises(research_lineage.LineageError, match="lineage_schema_changed"):
        work(observe, corpus[2], str(uuid4()), str(uuid4()))
