"""Sets map registered paper IDs only; saved reads never initialize or adopt."""

import copy
import sqlite3
from contextlib import closing

import pytest
from test_lineage_content_stage import valid_set as valid_set


def mapping_database(path, portable):
    with closing(sqlite3.connect(path)) as conn, conn:
        conn.execute("CREATE TABLE papers(id TEXT PRIMARY KEY)")
        conn.execute(
            "CREATE TABLE research_paper_identity(sync_id TEXT PRIMARY KEY,local_id TEXT UNIQUE)"
        )
        for index, binding in enumerate(portable["bindings"]):
            local = "local-" + str(index)
            conn.execute("INSERT INTO papers VALUES(?)", (local,))
            conn.execute(
                "INSERT INTO research_paper_identity VALUES(?,?)", (binding["paper_id"], local)
            )


def local_body(portable):
    body = copy.deepcopy(portable)
    for index, binding in enumerate(body["bindings"]):
        binding["paper_id"] = "local-" + str(index)
    return body


def row(body):
    from paper_daily import lineage_sets

    return dict(
        paper_id=body["bindings"][0]["paper_id"],
        corpus_key=body["corpus_id"],
        body_json=lineage_sets.canonical(body),
        source_hash=lineage_sets.source_hash(body),
        document_hash=body["report"]["sources"][0]["document_hash"],
        written_at="2026-10-30T00:00:00+00:00",
    )


def test_registered_conversion_preserves_exact_report_corpus_and_read_only_bytes(
    valid_set, tmp_path
):
    from paper_daily import lineage_sets

    path = tmp_path / "research.sqlite"
    mapping_database(path, valid_set)
    local = local_body(valid_set)
    original = copy.deepcopy(local)
    before = path.read_bytes()
    with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as conn:
        portable = lineage_sets.convert(conn, local, portable=True)
        assert portable == valid_set and portable["report"] == original["report"]
        assert lineage_sets.convert(conn, portable, portable=False) == local
        assert conn.total_changes == 0 and not conn.in_transaction
    assert local == original and path.read_bytes() == before
    assert lineage_sets.source_hash(local) == lineage_sets.source_hash(portable)


def test_distinct_paper_bindings_and_corpora_do_not_merge_identical_source_evidence(valid_set):
    from uuid import uuid4

    from paper_daily import lineage_sets

    first = local_body(valid_set)
    second = copy.deepcopy(first)
    second["corpus_id"] = str(uuid4())
    for binding in second["bindings"]:
        binding["paper_id"] += "-other-record"
    assert lineage_sets.validate(first) and lineage_sets.validate(second)
    assert first["report"] == second["report"]
    assert lineage_sets.source_hash(first) != lineage_sets.source_hash(second)
    assert first["bindings"][0]["paper_id"] != second["bindings"][0]["paper_id"]


@pytest.mark.parametrize(
    "change",
    [
        "extra",
        "uuid",
        "duplicate-owner",
        "binding-source",
        "focal-order",
        "unknown-input",
        "generation-task",
        "generation-score",
        "current-scope",
    ],
)
def test_closed_set_scope_and_metadata_reject_without_mutation(valid_set, change):
    from paper_daily import claim_content, lineage_sets

    if change == "extra":
        valid_set["workspace_authority"] = "sender-supplied"
    elif change == "uuid":
        valid_set["corpus_id"] = True
    elif change == "duplicate-owner":
        valid_set["bindings"][1]["paper_id"] = valid_set["bindings"][0]["paper_id"]
    elif change == "binding-source":
        valid_set["bindings"][1]["source_id"] = "0" * 64
    elif change == "focal-order":
        valid_set["bindings"].reverse()
    elif change == "unknown-input":
        valid_set["inputs"]["source_path"] = "ignored?"
    elif change == "generation-task":
        valid_set["generation"]["task"] = "unknown"
    elif change == "generation-score":
        valid_set["generation"]["score"] = 100
    else:
        report = valid_set["report"]
        report["verification_scope"] = "current_sources"
        report["id"] = claim_content.hashed({k: v for k, v in report.items() if k != "id"})
    before = copy.deepcopy(valid_set)
    with pytest.raises(ValueError):
        lineage_sets.validate(valid_set)
    assert valid_set == before


@pytest.mark.parametrize(
    "value", [True, None, "", "not-uuid", "AAAAAAAA-AAAA-4AAA-8AAA-AAAAAAAAAAAA"]
)
def test_corpus_uuid_is_canonical_and_not_an_alias(value):
    from paper_daily import lineage_sets

    with pytest.raises(ValueError):
        lineage_sets.uuid(value)


def test_decode_missing_scalar_duplicate_nonfinite_and_budget_errors_are_not_empty_success(
    valid_set,
):
    from paper_daily import lineage_sets

    encoded = lineage_sets.canonical(valid_set)
    invalid = [
        None,
        "null",
        "[]",
        "{}",
        "no-json",
        encoded.replace('"format":', '"format":0,"format":', 1),
        encoded.replace('"requested_model":null', '"requested_model":NaN', 1),
        "x" * (lineage_sets.MAX_BYTES + 1),
    ]
    for value in invalid:
        with pytest.raises(ValueError):
            lineage_sets.decode(value)
    assert lineage_sets.decode(encoded) == valid_set


def test_missing_or_deleted_registered_paper_never_mints_or_adopts_owner(valid_set, tmp_path):
    from paper_daily import lineage_sets

    path = tmp_path / "research.sqlite"
    mapping_database(path, valid_set)
    local = local_body(valid_set)
    with closing(sqlite3.connect(path)) as conn, conn:
        conn.execute("DELETE FROM research_paper_identity WHERE local_id='local-2'")
    before = path.read_bytes()
    original = copy.deepcopy(local)
    with (
        closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as conn,
        pytest.raises(ValueError, match="registered selected paper owner"),
    ):
        lineage_sets.convert(conn, local, portable=True)
    assert path.read_bytes() == before and local == original
    with closing(sqlite3.connect(path)) as conn, conn:
        conn.execute(
            "INSERT INTO research_paper_identity VALUES(?,'local-2')",
            (valid_set["bindings"][2]["paper_id"],),
        )
        conn.execute("DELETE FROM papers WHERE id='local-2'")
    with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as conn:
        with pytest.raises(ValueError, match="paper owner is missing"):
            lineage_sets.convert(conn, local, portable=True)
        assert not conn.execute(
            "SELECT 1 FROM sqlite_master WHERE name='research_parent_lifecycle'"
        ).fetchone()


def test_conversion_does_not_commit_or_rollback_callers_pending_transaction(valid_set, tmp_path):
    from paper_daily import lineage_sets

    path = tmp_path / "research.sqlite"
    mapping_database(path, valid_set)
    with closing(sqlite3.connect(path)) as conn:
        conn.execute("INSERT INTO papers VALUES('pending')")
        assert conn.in_transaction
        lineage_sets.convert(conn, local_body(valid_set), portable=True)
        assert conn.in_transaction
        with closing(sqlite3.connect(path)) as observer:
            assert not observer.execute("SELECT 1 FROM papers WHERE id='pending'").fetchone()
        conn.rollback()
        assert not conn.execute("SELECT 1 FROM papers WHERE id='pending'").fetchone()


@pytest.mark.parametrize(
    "field", ["paper_id", "corpus_key", "document_hash", "source_hash", "written_at"]
)
def test_saved_row_must_match_exact_focal_corpus_and_document(valid_set, field):
    from paper_daily import lineage_sets

    value = row(valid_set)
    value[field] = (
        "not-a-stamp" if field == "written_at" else "0" * 64 if field.endswith("hash") else "other"
    )
    with pytest.raises(ValueError):
        lineage_sets.validate_row(value)


def seed(path, bodies):
    from paper_daily import lineage_sets

    with closing(sqlite3.connect(path)) as conn, conn:
        conn.execute(
            lineage_sets.SCHEMA
        )  # Explicit fixture only; never application initialization.
        for body in bodies:
            saved = row(body)
            conn.execute(
                "INSERT INTO paper_lineage_sets VALUES(?,?,?,?,?,?)",
                tuple(saved[k] for k in lineage_sets.COLUMNS.split()),
            )


def test_saved_only_read_selects_corpus_closes_native_handles_and_never_calls_ai(
    valid_set, tmp_path, monkeypatch
):
    from uuid import uuid4

    from paper_daily import lineage_sets, llm

    path = tmp_path / "research.sqlite"
    second = copy.deepcopy(valid_set)
    second["corpus_id"] = str(uuid4())
    seed(path, [valid_set, second])
    before = path.read_bytes()
    monkeypatch.setattr(llm, "complete_result", lambda *a, **kw: pytest.fail("model on read"))
    monkeypatch.setattr(llm, "capture_connections", lambda: pytest.fail("route on read"))
    focal = valid_set["bindings"][0]["paper_id"]
    for _ in range(3):
        assert lineage_sets.saved(path, focal, corpus_id=valid_set["corpus_id"]) == [row(valid_set)]
        assert lineage_sets.saved(path, "unselected") == []
    assert path.read_bytes() == before
    replacement = path.with_name("replacement.sqlite")
    replacement.write_bytes(before)
    replacement.replace(path)  # Actual Windows native replacement after all read handles close.
    assert lineage_sets.saved(path, focal, corpus_id=second["corpus_id"]) == [row(second)]


def test_saved_read_missing_absent_and_malformed_table_never_creates_or_repairs(tmp_path):
    from paper_daily import lineage_sets

    missing = tmp_path / "missing.sqlite"
    with pytest.raises(FileNotFoundError):
        lineage_sets.saved(missing, "focal")
    assert not missing.exists()
    empty = tmp_path / "empty.sqlite"
    with closing(sqlite3.connect(empty)):
        pass
    before = empty.read_bytes()
    assert lineage_sets.saved(empty, "focal") == [] and empty.read_bytes() == before
    with closing(sqlite3.connect(empty)) as conn, conn:
        conn.execute("CREATE TABLE paper_lineage_sets(paper_id TEXT)")
    before = empty.read_bytes()
    with pytest.raises(sqlite3.OperationalError):
        lineage_sets.saved(empty, "focal")
    assert empty.read_bytes() == before


def test_saved_read_over_budget_is_whole_error_and_explicit_corpus_selection_still_works(
    valid_set, tmp_path
):
    from uuid import uuid4

    from paper_daily import lineage_sets

    path = tmp_path / "research.sqlite"
    bodies = []
    for _ in range(65):
        body = copy.deepcopy(valid_set)
        body["corpus_id"] = str(uuid4())
        bodies.append(body)
    seed(path, bodies)
    before = path.read_bytes()
    focal = valid_set["bindings"][0]["paper_id"]
    with pytest.raises(ValueError, match="bounded explicit selection"):
        lineage_sets.saved(path, focal)
    assert lineage_sets.saved(path, focal, corpus_id=bodies[0]["corpus_id"]) == [row(bodies[0])]
    with closing(sqlite3.connect(path)) as conn, conn:
        conn.execute(
            "UPDATE paper_lineage_sets SET body_json=? WHERE corpus_key=?",
            ("x" * (lineage_sets.MAX_BYTES + 1), bodies[0]["corpus_id"]),
        )
    too_large = path.read_bytes()
    with pytest.raises(ValueError):
        lineage_sets.saved(path, focal, corpus_id=bodies[0]["corpus_id"])
    assert path.read_bytes() == too_large and before != too_large
