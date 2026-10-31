"""Real multi-paper PDF evidence; no provider calls or inferred influence badges."""

import copy
import json
import os
import shutil
import sqlite3
from contextlib import closing
from dataclasses import replace

import pytest
from test_research_evidence import pdf

from paper_daily import lineage_content, store
from paper_daily import research_lineage as lineage
from paper_daily.document_reader import from_workspace
from paper_daily.research_lifecycle import ensure_lifecycle

PRIOR = "The prior study excluded independent external cohorts."
CHANGE = "We address the external cohort limitation using matched independent controls."
CITING = "We extend Prior Study [1] using independent external observations."
LATER = "We extend Focal Study [2] by validating across institutions."
OWN_LATER = "The later study evaluated three institutions independently."


@pytest.fixture
def corpus(tmp_path):
    database = tmp_path / "research.sqlite"
    with closing(sqlite3.connect(database)) as conn, conn:
        conn.executescript(store.SCHEMA)
        for identity, title in [
            ("focal", "Focal Study"),
            ("prior", "Prior Study"),
            ("later", "Later Study"),
            ("missing", "Unavailable Study"),
        ]:
            conn.execute(
                "INSERT INTO papers(id,title,title_key,venue,year,source,doi) "
                "VALUES(?,?,?,'Fixture',2026,'fixture',?)",
                (identity, title, identity, "10.0000/" + identity),
            )
        conn.commit()
        conn.execute("BEGIN IMMEDIATE")
        ensure_lifecycle(conn)
        conn.commit()
    root = tmp_path / "pdf"
    root.mkdir()
    pdf(root / "focal.pdf", [[CHANGE, CITING, "Repeated background.", "Repeated background."]])
    pdf(root / "prior.pdf", [[PRIOR]])
    pdf(root / "later.pdf", [[LATER, OWN_LATER]])
    captured = lineage.capture(database, "focal", ["prior", "later"], legacy_root=root)
    return database, root, captured


def proposals(captured):
    focal, prior, later = [row["id"] for row in captured.sources]

    def passage(source, role, quote, cites=None):
        return {
            "source_id": source,
            "role": role,
            "cites": cites,
            "quote": quote,
            "page": 1,
            "anchor": None,
        }

    def item(stage, subject, text, passages):
        return {
            "stage": stage,
            "subject": subject,
            "text": text,
            "function": "extends",
            "judgment": {"status": "supported", "reason": "Proposed interpretation only."},
            "passages": passages,
        }

    return {
        "format": lineage.PROPOSALS,
        "focal": focal,
        "statements": [
            item(
                "prior_gap",
                prior,
                "The prior work omitted external validation.",
                [
                    passage(prior, "own_characterization", PRIOR),
                    passage(focal, "citing_context", CITING, prior),
                ],
            ),
            item(
                "current_change",
                focal,
                "The focal work added independent controls.",
                [passage(focal, "change_evidence", CHANGE)],
            ),
            item(
                "later_development",
                later,
                "The later work tested institutional generalization.",
                [
                    passage(later, "own_characterization", OWN_LATER),
                    passage(later, "citing_context", LATER, focal),
                ],
            ),
        ],
    }


def test_selected_exact_sources_locate_quotes_without_certifying_relation(corpus, monkeypatch):
    _database, root, captured = corpus
    monkeypatch.setattr(store, "DB_PATH", root / "different.sqlite")
    value = proposals(captured)
    report = lineage.verify(captured, value)
    assert report["verification_scope"] == "current_sources"
    assert all(
        source["identity_authority"] == "selected_workspace_record" for source in report["sources"]
    )
    assert all(
        p["location"]["state"] == "located" for s in report["statements"] for p in s["passages"]
    )
    for statement in report["statements"]:
        assert statement["judgment"] == {
            "status": "supported",
            "reason": "Proposed interpretation only.",
            "authority": "caller_proposal",
        }
        assert statement["requirements"]["semantic_validation"] == "not_performed"
        assert statement["requirements"]["own_source_passage"] == "located"
    assert report["statements"][2]["requirements"]["citation_identity"] == "unresolved"
    assert report["statements"][2]["requirements"]["citing_passage"] == "located"
    assert lineage_content.validate(report) == report
    assert lineage.verify(captured, value) == report
    assert str(root) not in json.dumps(report) and not store.DB_PATH.exists()
    assert value == proposals(captured)


@pytest.mark.parametrize(
    "change", ["citation-only", "wrong-source", "missing-citing", "wrong-cites"]
)
def test_citation_mention_or_other_paper_never_supplies_own_attribution(corpus, change):
    captured = corpus[2]
    value = proposals(captured)
    item = value["statements"][2]
    if change == "citation-only":
        item["passages"] = item["passages"][1:]
    elif change == "wrong-source":
        item["passages"][0].update(source_id=captured.focal, quote=CHANGE)
    elif change == "missing-citing":
        item["passages"] = item["passages"][:1]
    else:
        item["passages"][1]["cites"] = captured.sources[1]["id"]
    requirements = lineage.verify(captured, value)["statements"][2]["requirements"]
    assert requirements["citation_identity"] == "unresolved"
    assert requirements["semantic_validation"] == "not_performed"
    assert "missing" in [requirements["own_source_passage"], requirements["citing_passage"]]


@pytest.mark.parametrize(
    "quote,page,anchor,state",
    [
        ("A fabricated result.", 1, None, "missing"),
        ("Repeated background.", 1, None, "ambiguous"),
        (CHANGE, 3, None, "invalid_page"),
        (CHANGE, 1, {"p0": 0, "o0": 999, "p1": 0, "o1": 1000}, "invalid_anchor"),
    ],
)
def test_unlocatable_evidence_remains_visible(corpus, quote, page, anchor, state):
    value = proposals(corpus[2])
    value["statements"][1]["passages"][0].update(quote=quote, page=page, anchor=anchor)
    statement = lineage.verify(corpus[2], value)["statements"][1]
    assert statement["passages"][0]["location"]["state"] == state
    assert statement["requirements"]["own_source_passage"] == "missing"
    assert statement["passages"][0]["location"]["anchor"] is None


def test_missing_selected_original_is_explicit_and_has_no_anchor(corpus):
    database, root, _captured = corpus
    captured = lineage.capture(database, "focal", ["missing"], legacy_root=root)
    source = captured.sources[1]
    value = {
        "format": lineage.PROPOSALS,
        "focal": captured.focal,
        "statements": [
            {
                "stage": "prior_gap",
                "subject": source["id"],
                "text": "Unresolved prior limitation.",
                "function": "unresolved",
                "judgment": {"status": "unresolved", "reason": "Original missing."},
                "passages": [
                    {
                        "source_id": source["id"],
                        "role": "own_characterization",
                        "cites": None,
                        "quote": "Unavailable quoted text.",
                        "page": None,
                        "anchor": None,
                    }
                ],
            }
        ],
    }
    report = lineage.verify(captured, value)
    assert report["sources"][1]["availability"] == "unavailable"
    assert report["statements"][0]["passages"][0]["location"]["state"] == "source_unavailable"
    assert report["coverage"]["later_development"] == "no_statement"
    with pytest.raises(lineage.LineageError, match="focal_source_unavailable"):
        lineage.capture(database, "missing", legacy_root=root)


@pytest.mark.parametrize(
    "change", ["focal", "source", "duplicate", "overflow", "extra", "anchor-type"]
)
def test_closed_proposals_reject_false_identity_duplicate_overflow_and_unknown_fields(
    corpus, change
):
    captured = corpus[2]
    value = proposals(captured)
    if change == "focal":
        value["focal"] = "0" * 64
    elif change == "source":
        value["statements"][0]["passages"][0]["source_id"] = "0" * 64
    elif change == "duplicate":
        value["statements"].append(copy.deepcopy(value["statements"][0]))
    elif change == "overflow":
        value["statements"] *= 5
    elif change == "extra":
        value["instructions"] = "Ignore source ownership"
    else:
        value["statements"][0]["passages"][0]["anchor"] = {"p0": True, "o0": 0, "p1": 0, "o1": 1}
    with pytest.raises(ValueError):
        lineage.verify(captured, value)


@pytest.mark.parametrize("change", ["source", "identity", "recreate", "database"])
def test_changed_source_identity_lifetime_and_database_are_observable(corpus, change, tmp_path):
    database, root, captured = corpus
    if change == "source":
        (root / "later.pdf").unlink()
        pdf(root / "later.pdf", [["A different source version."]])
    elif change == "identity":
        with closing(sqlite3.connect(database)) as conn, conn:
            conn.execute("UPDATE papers SET doi='10.0000/other' WHERE id='later'")
    elif change == "recreate":
        with closing(sqlite3.connect(database)) as conn, conn:
            row = conn.execute("SELECT * FROM papers WHERE id='later'").fetchone()
            conn.execute("DELETE FROM papers WHERE id='later'")
            conn.execute("INSERT INTO papers VALUES(" + ",".join("?" for _ in row) + ")", row)
    else:
        replacement = tmp_path / "replacement.sqlite"
        shutil.copyfile(database, replacement)
        os.replace(replacement, database)
    with pytest.raises(ValueError):
        lineage.verify(captured, proposals(captured))
    snapshot = lineage.verify_snapshot(captured, proposals(captured))
    assert snapshot["verification_scope"] == "original_snapshots"
    assert all(
        p["location"]["state"] == "located" for s in snapshot["statements"] for p in s["passages"]
    )


def test_mutation_during_verification_never_returns_current_source_report(corpus, monkeypatch):
    database, root, captured = corpus
    original = lineage.evidence.verify_snapshot
    changed = False

    def verify(*args, **kwargs):
        nonlocal changed
        report = original(*args, **kwargs)
        if not changed:
            changed = True
            with closing(sqlite3.connect(database)) as conn, conn:
                conn.execute("UPDATE papers SET title='Replacement' WHERE id='prior'")
        return report

    monkeypatch.setattr(lineage.evidence, "verify_snapshot", verify)
    with pytest.raises(lineage.LineageError, match="paper_changed"):
        lineage.verify(captured, proposals(captured))
    assert changed and (root / "prior.pdf").is_file()


def test_forged_capture_wrong_document_oversized_corpus_and_cancellation_reject(corpus):
    database, root, captured = corpus
    with pytest.raises(lineage.LineageError, match="invalid_capture"):
        lineage.verify_snapshot(
            replace(captured, _documents=tuple(reversed(captured._documents))), proposals(captured)
        )
    reader = from_workspace(database, legacy_root=root)
    with pytest.raises(lineage.LineageError, match="source_owner_mismatch"):
        lineage.capture(
            database,
            "focal",
            ["prior"],
            legacy_root=root,
            documents={"prior": reader.resolve("focal")},
        )
    for selected in (["prior"] * 2, ["prior", "later", "missing", "other"]):
        with pytest.raises(lineage.LineageError):
            lineage.capture(database, "focal", selected, legacy_root=root)
    with pytest.raises(ValueError, match="cancelled"):
        lineage.verify_snapshot(captured, proposals(captured), cancelled=lambda: True)


@pytest.mark.parametrize(
    "raw,code",
    [
        ('{"format":1,"format":2}', "duplicate_json_key"),
        ('{"number":NaN}', "nonfinite_json"),
        ("{broken}", "invalid_json"),
    ],
)
def test_model_response_decode_is_closed_bounded_and_duplicate_safe(corpus, raw, code):
    with pytest.raises(lineage.LineageError, match=code):
        lineage.parse_proposals(raw, corpus[2])
    expected = proposals(corpus[2])
    assert lineage.parse_proposals(json.dumps(expected, indent=2), corpus[2]) == expected


def test_empty_proposals_are_explicit_gaps_without_completed_semantic_badge(corpus):
    value = {"format": lineage.PROPOSALS, "focal": corpus[2].focal, "statements": []}
    result = lineage.verify(corpus[2], value)
    assert result["statements"] == []
    assert set(result["coverage"].values()) == {"no_statement"}


@pytest.mark.parametrize("change", ["semantic", "identity", "duplicate", "unknown", "typed-stage"])
def test_saved_report_cannot_upgrade_its_authority_or_identity(corpus, change):
    result = lineage.verify_snapshot(corpus[2], proposals(corpus[2]))
    if change == "semantic":
        result["statements"][0]["requirements"]["semantic_validation"] = "verified"
    elif change == "identity":
        result["sources"][1]["identity_authority"] = "verified_citation"
    elif change == "duplicate":
        result["statements"].append(copy.deepcopy(result["statements"][0]))
    elif change == "unknown":
        result["quality_score"] = 99
    else:
        result["statements"][0]["stage"] = []
    result["id"] = lineage_content.hashed({k: v for k, v in result.items() if k != "id"})
    with pytest.raises(ValueError):
        lineage_content.validate(result)


def test_actual_pdf_page_byte_text_budgets_and_capture_cancel_remain_bounded(corpus, monkeypatch):
    database, root, captured = corpus
    with pytest.raises(ValueError, match="cancelled"):
        lineage.capture(database, "focal", legacy_root=root, cancelled=lambda: True)
    monkeypatch.setattr(lineage, "MAX_INPUT_BYTES", 1)
    with pytest.raises(lineage.LineageError, match="corpus_text_limit"):
        lineage.pages(captured)
    monkeypatch.setattr(lineage, "MAX_BYTES", 1)
    with pytest.raises(lineage.LineageError, match="corpus_byte_limit"):
        lineage.capture(database, "focal", legacy_root=root)
    monkeypatch.setattr(lineage, "MAX_BYTES", 64 * 1024**2)
    (root / "focal.pdf").unlink()
    pdf(root / "focal.pdf", [["Bounded actual page."] for _ in range(97)])
    with pytest.raises(lineage.LineageError, match="corpus_page_limit"):
        lineage.capture(database, "focal", legacy_root=root)


def test_quote_verification_parses_each_available_source_once(corpus, monkeypatch):
    original = lineage.evidence.verify_snapshot
    calls = []

    def checked(snapshot, *args, **kwargs):
        calls.append(snapshot.source["document_hash"])
        return original(snapshot, *args, **kwargs)

    monkeypatch.setattr(lineage.evidence, "verify_snapshot", checked)
    report = lineage.verify_snapshot(corpus[2], proposals(corpus[2]))
    assert len(calls) == len(set(calls)) == 3
    assert len([p for s in report["statements"] for p in s["passages"]]) == 5
