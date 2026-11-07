"""Distinct exact owners, retained conflicts, and all-or-nothing package boundaries."""

import hashlib
import json
import zipfile
from contextlib import closing

import pytest
from test_later_outcome_bundle import STAMP, receiver, source
from test_research_generation import pdf
from test_research_generation import workspace as workspace

from paper_daily import bundle, enrollment_history, followups, source_snapshots, store
from paper_daily import later_outcome_packages as packages
from paper_daily import later_outcomes as outcomes
from paper_daily import local_source_owners as owners
from paper_daily import research_generation as generation


def test_same_pdf_and_bibliography_remain_two_paper_owners(workspace, monkeypatch, tmp_path):
    database, document, archive = source(workspace, monkeypatch, tmp_path)
    with store.connect() as conn:
        store.upsert_papers(
            conn, [dict(id="second", title="Paper", venue="Fixture", year=2026, source="fixture")]
        )
        conn.execute(
            "INSERT INTO list_papers(list_id,paper_id,position,added_at) "
            "VALUES('reading','second',1,?)",
            (STAMP,),
        )
    (document.path.parent / "second.pdf").write_bytes(document.path.read_bytes())
    assert followups.fetch("second", database=database) == 0
    bundle.export("reading", archive)
    with zipfile.ZipFile(archive) as zipped:
        manifest, tables, _ = bundle._validated(zipped)
        assert len(tables[outcomes.TABLE]) == 2
        assert {item["sha256"] for item in manifest["later_sources"]} == {document.sha256}
        assert {item["paper_id"] for item in manifest["later_sources"]} == {"paper", "second"}
        assert len({item["path"] for item in manifest["later_sources"]}) == 2
        assert (
            len(
                {
                    json.loads(row["body_json"])["query"]["request_id"]
                    for row in tables[outcomes.TABLE]
                }
            )
            == 2
        )
    destination = receiver(tmp_path, monkeypatch)
    bundle.import_(archive, pdfs=False)
    with closing(generation._connect(destination)) as conn:
        assert conn.execute("SELECT COUNT(*) FROM papers").fetchone()[0] == 2
        assert conn.execute("SELECT COUNT(*) FROM paper_later_outcomes").fetchone()[0] == 2
        receipts = owners.records(conn)
        assert len(receipts) == 2
        assert {json.loads(row["owner_json"])["paper_id"] for row in receipts} == {
            "paper",
            "second",
        }
        assert len({json.loads(row["owner_json"])["parent_lifecycle"] for row in receipts}) == 2
        assert all(outcomes.settled(conn, paper) for paper in ("paper", "second"))


def test_actual_kept_outcome_conflict_retains_both_sources_and_never_replays(
    workspace, monkeypatch, tmp_path
):
    _sender, document, archive = source(workspace, monkeypatch, tmp_path)
    bundle.export("reading", archive)
    destination = receiver(tmp_path, monkeypatch)
    with store.connect() as conn:
        store.upsert_papers(
            conn, [dict(id="paper", title="Paper", venue="Fixture", year=2026, source="fixture")]
        )
    current = destination.parent / "pdf/paper.pdf"
    pdf(current, "Receiver C has its own successful query")
    current_bytes = current.read_bytes()
    assert followups.fetch("paper", database=destination) == 0
    with closing(generation._connect(destination)) as conn:
        before = packages.read(conn, "paper")
    result = bundle.import_(archive, pdfs=False)
    assert result["later_outcomes"] == 0 and result["later_outcomes_kept"] == 1
    assert current.read_bytes() == current_bytes
    with closing(generation._connect(destination)) as conn:
        assert packages.read(conn, "paper") == before and outcomes.settled(conn, "paper")
        rows = [
            r
            for r in enrollment_history.archived(conn)
            if r["protocol"] == "later_outcome_import_v1"
        ]
        assert len(rows) == 1
        original, hashes = enrollment_history.validate(rows[0])
        incoming = json.loads(original["incoming_json"])
        assert incoming["document_hash"] == document.sha256
        assert hashes == {document.sha256, hashlib.sha256(current_bytes).hexdigest()}
        receipt = owners.records(conn)[0]
        assert (
            hashlib.sha256(
                source_snapshots.source_path(destination, receipt).read_bytes()
            ).hexdigest()
            == document.sha256
        )
    bundle.import_(archive, pdfs=False)
    with closing(generation._connect(destination)) as conn:
        assert packages.read(conn, "paper") == before
        assert (
            len(
                [
                    r
                    for r in enrollment_history.archived(conn)
                    if r["protocol"] == "later_outcome_import_v1"
                ]
            )
            == 1
        )
        assert len(owners.records(conn)) == 1


def test_actual_local_late_sql_failure_rolls_back_and_retry_is_single(
    workspace, monkeypatch, tmp_path
):
    _sender, _document, archive = source(workspace, monkeypatch, tmp_path)
    bundle.export("reading", archive)
    destination = receiver(tmp_path, monkeypatch)
    real = packages.write_import_in

    def fail(*args, **kwargs):
        real(*args, **kwargs)
        raise OSError("Fixture late outcome import failure")

    monkeypatch.setattr(packages, "write_import_in", fail)
    with pytest.raises(OSError, match="late outcome"):
        bundle.import_(archive, pdfs=False)
    with closing(generation._connect(destination)) as conn:
        assert conn.execute("SELECT COUNT(*) FROM papers").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM paper_later_outcomes").fetchone()[0] == 0
        assert owners.records(conn) == []
    assert not (destination.parent / "pdf/paper.pdf").exists()
    monkeypatch.setattr(packages, "write_import_in", real)
    assert bundle.import_(archive, pdfs=False)["later_outcomes"] == 1
    assert bundle.import_(archive, pdfs=False)["later_outcomes"] == 0
    with closing(generation._connect(destination)) as conn:
        assert len(owners.records(conn)) == 1


def rewrite(archive, path, change):
    with zipfile.ZipFile(archive) as zipped:
        manifest = json.loads(zipped.read("manifest.json"))
        tables = json.loads(zipped.read("tables.json"))
        files = {name: zipped.read(name) for name in zipped.namelist() if name.startswith("files/")}
    item = manifest["later_sources"][0]
    if change == "missing":
        del files["files/" + item["path"]]
    elif change == "bytes":
        files["files/" + item["path"]] = b"not the declared original"
    elif change == "owner":
        item["paper_id"] = "foreign"
    elif change == "capability":
        manifest["capabilities"].append("future")
    elif change == "body":
        row = tables[outcomes.TABLE][0]
        body = json.loads(row["body_json"])
        body["truth_score"] = 100
        row["body_json"] = json.dumps(body)
    elif change == "budget":
        row = tables[outcomes.TABLE][0]
        body = json.loads(row["body_json"])
        body["query"]["lookup"]["title"] = "x" * 32769
        row["body_json"] = json.dumps(body)
    raw_manifest = json.dumps(manifest)
    raw_tables = json.dumps(tables)
    if change == "duplicate_manifest":
        raw_manifest = (
            raw_manifest[:-1] + ',"capabilities":' + json.dumps(manifest["capabilities"]) + "}"
        )
    if change == "duplicate_tables":
        raw_tables = raw_tables[:-1] + ',"papers":' + json.dumps(tables["papers"]) + "}"
    with zipfile.ZipFile(path, "w") as zipped:
        zipped.writestr("manifest.json", raw_manifest)
        zipped.writestr("tables.json", raw_tables)
        for name, data in files.items():
            zipped.writestr(name, data)


@pytest.mark.parametrize(
    "change",
    [
        "missing",
        "bytes",
        "owner",
        "capability",
        "body",
        "budget",
        "duplicate_manifest",
        "duplicate_tables",
    ],
)
def test_invalid_full_package_refuses_before_any_receiver_write(
    workspace, monkeypatch, tmp_path, change
):
    _sender, _document, archive = source(workspace, monkeypatch, tmp_path)
    bundle.export("reading", archive)
    altered = tmp_path / "altered.zip"
    rewrite(archive, altered, change)
    destination = receiver(tmp_path, monkeypatch)
    before = destination.read_bytes()
    with pytest.raises((ValueError, KeyError)):
        bundle.import_(altered, pdfs=False)
    assert destination.read_bytes() == before
    with closing(generation._connect(destination)) as conn:
        assert conn.execute("SELECT COUNT(*) FROM papers").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM paper_later_outcomes").fetchone()[0] == 0
        assert owners.records(conn) == []
