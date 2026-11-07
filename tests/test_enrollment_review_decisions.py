"""Real review decisions retain history and source bytes during first enrollment."""

import hashlib
import json
import sqlite3
import zipfile
from contextlib import closing
from pathlib import Path
from uuid import uuid4

import pytest
from test_workspace_enrollment import pdf
from test_workspace_enrollment import source as source

from paper_daily import enrollment_history, llm, sync_recovery
from paper_daily import research_generation as generation
from paper_daily.document_reader import DocumentReader
from paper_daily.research_review import ResearchReview
from paper_daily.workspace_enrollment import EnrollmentService

PROTOCOL = "research_review_receipts"


def output(body):
    return dict(
        paper_id="paper", body=body, spec="fixture-v1", written_at="2026-11-01T00:00:00+00:00"
    )


@pytest.fixture
def decision(source, monkeypatch, request):
    primary = pdf(source)
    original_bytes = primary.read_bytes()
    document = DocumentReader.from_workspace(source, legacy_root=primary.parent).resolve("paper")
    assert document.available and document.path == primary

    def context():
        with closing(generation._connect(source)) as conn:
            return generation.begin_generation(
                conn, table="close_readings", owner_id="paper", input_reader="target"
            )

    earlier = generation.bind_inputs(context(), document=document)
    assert (
        generation.publish_generation(context(), row=output("Current saved text")).status
        == "accepted"
    )
    retained = generation.publish_generation(earlier, row=output("Earlier proposed interpretation"))
    assert retained.status == "candidate"
    review = ResearchReview(source)
    selected = review.target_preview(review.preview("generation", retained.request_id), "paper")
    identity = str(uuid4())
    keep = getattr(request, "param", "applied") == "kept"
    options = dict(keep=keep, request_id=identity)
    if not keep:
        options.update(body="Human-reviewed interpretation", confirm_target=True)
    result = review.decide(selected, **options)
    assert review.decide(selected, **options) == result
    review.close()
    with closing(generation._connect(source)) as conn:
        rows = [dict(row) for row in conn.execute("SELECT * FROM research_review_receipts")]
        assert len(rows) == 1
        saved = dict(conn.execute("SELECT * FROM close_readings").fetchone())
    assert saved["body"] == ("Current saved text" if keep else "Human-reviewed interpretation")

    def deny(*_args, **_kwargs):
        pytest.fail("Review history migration must never invoke AI")

    monkeypatch.setattr(llm, "complete", deny)
    monkeypatch.setattr(llm, "complete_result", deny)
    return dict(
        database=source,
        primary=primary,
        original_bytes=original_bytes,
        source_hash=hashlib.sha256(original_bytes).hexdigest(),
        receipt=rows[0],
        saved=saved,
    )


def prepare(value, tmp_path, **kwargs):
    return EnrollmentService(value["database"]).prepare(
        tmp_path / "candidate",
        backup_output=tmp_path / "backup.zip",
        request_id=str(uuid4()),
        pdfs={"paper": value["primary"]},
        **kwargs,
    )


@pytest.mark.parametrize("decision", ["applied", "kept"], indirect=True)
def test_real_decision_enrolls_and_restores_exact_private_receipt_without_old_authority(
    decision, tmp_path
):
    value = decision
    before = value["database"].read_bytes()
    plan = EnrollmentService(value["database"]).plan(pdfs={"paper": value["primary"]})
    assert plan["supported"], plan["blockers"]
    assert plan["archived_history_by_protocol"][PROTOCOL] == 1
    result = prepare(value, tmp_path)
    database = Path(result["database"])
    assert not result["uploaded"] and not result["adopted"]
    with closing(generation._connect(database)) as conn:
        archived = enrollment_history.archived(conn)
        receipts = [
            enrollment_history.validate(row)[0] for row in archived if row["protocol"] == PROTOCOL
        ]
        assert receipts == [value["receipt"]]
        assert dict(conn.execute("SELECT * FROM close_readings").fetchone()) == value["saved"]
        for table in (PROTOCOL, "research_generation_requests"):
            assert not conn.execute("SELECT 1 FROM sqlite_master WHERE name=?", (table,)).fetchone()
        wire = "\n".join(
            row[0] for row in conn.execute("SELECT envelope FROM paperfact_sync_operations")
        )
        assert PROTOCOL not in wire and value["receipt"]["request_id"] not in wire
    with zipfile.ZipFile(result["backup"]) as bundle:
        assert bundle.read("objects/" + value["source_hash"]) == value["original_bytes"]
    assert sync_recovery.inspect(result["backup"])["workspace_id"] == result["workspace_id"]
    detached = tmp_path / "detached"
    sync_recovery.restore_detached(result["backup"], detached)
    with closing(generation._connect(detached / "papers.db")) as conn:
        restored = [
            json.loads(row[0])
            for row in conn.execute(
                "SELECT data FROM recovery_records WHERE table_name='research_history_archive'"
            )
        ]
        assert [
            enrollment_history.validate(row)[0] for row in restored if row["protocol"] == PROTOCOL
        ] == [value["receipt"]]
    assert value["database"].read_bytes() == before
    assert value["primary"].read_bytes() == value["original_bytes"]


@pytest.mark.parametrize("decision", ["kept"], indirect=True)
@pytest.mark.parametrize("change", ["present", "missing", "changed"])
def test_decision_only_original_is_backed_up_or_blocks_whole_copy(decision, tmp_path, change):
    from test_sync_source_files import pdf as pdf_bytes

    value = decision
    # A real receipt survives ordinary old-job cleanup. The saved current text
    # consumed no PDF; A is now declared only by the private decision history.
    with closing(generation._connect(value["database"])) as conn, conn:
        conn.execute("DELETE FROM research_generation_requests")
        saved = dict(conn.execute("SELECT * FROM close_readings").fetchone())
        assert saved == value["saved"] and "document_hash" not in saved
    original = value["primary"].with_name("retained-a.pdf")
    value["primary"].rename(original)
    value["primary"].write_bytes(pdf_bytes("Current primary B"))
    if change == "missing":
        original.unlink()
    elif change == "changed":
        original.write_bytes(pdf_bytes("Not original A"))
    before = value["database"].read_bytes()
    if change == "present":
        plan = EnrollmentService(value["database"]).plan(pdfs={"paper": value["primary"]})
        assert plan["supported"], plan["blockers"]
        result = prepare(value, tmp_path)
        with zipfile.ZipFile(result["backup"]) as bundle:
            assert bundle.read("objects/" + value["source_hash"]) == value["original_bytes"]
        assert original.read_bytes() == value["original_bytes"]
    else:
        with pytest.raises(ValueError, match="Original source PDF is missing or changed"):
            EnrollmentService(value["database"]).plan(pdfs={"paper": value["primary"]})
        with pytest.raises(ValueError, match="Original source PDF is missing or changed"):
            prepare(value, tmp_path)
        assert not (tmp_path / "candidate").exists() and not (tmp_path / "backup.zip").exists()
    assert value["database"].read_bytes() == before


def test_decision_archive_parser_is_pure_preserves_json_text_and_declares_only_source(
    decision, monkeypatch
):
    value = decision["receipt"]
    # Harmless whitespace remains part of the exact historical receipt.
    value = {**value, "result": json.dumps(json.loads(value["result"]), indent=2)}

    def deny(*_args, **_kwargs):
        pytest.fail("Archived paths/identity must never grant SQL or file access")

    monkeypatch.setattr(sqlite3, "connect", deny)
    monkeypatch.setattr(Path, "open", deny)
    row = enrollment_history.wrap(PROTOCOL, value)
    restored, sources = enrollment_history.validate(row)
    assert restored == value and sources == {decision["source_hash"]}


@pytest.mark.parametrize(
    "change",
    [
        "extra",
        "wrong_decision",
        "bad_fingerprint",
        "origin_type",
        "provenance_type",
        "duplicate_result",
        "duplicate_provenance",
        "nonfinite",
        "source_type",
        "parent_type",
        "target_type",
        "unknown_provenance",
        "wrong_result",
        "oversized",
    ],
)
def test_malformed_review_decision_is_refused_without_changing_source(decision, change):
    value = dict(decision["receipt"])
    before = decision["database"].read_bytes()
    provenance = json.loads(value["provenance"])
    if change == "extra":
        value["authority"] = "must not be accepted"
    elif change == "wrong_decision":
        value["decision"] = "publish"
    elif change == "bad_fingerprint":
        value["fingerprint"] = "g" * 64
    elif change == "origin_type":
        value["origin"] = []
    elif change == "provenance_type":
        value["provenance"] = None
    elif change == "duplicate_result":
        value["result"] = value["result"][:-1] + ',"operation_id":null}'
    elif change == "duplicate_provenance":
        value["provenance"] = value["provenance"][:-1] + ',"target_id":"paper"}'
    elif change == "nonfinite":
        value["result"] = '{"decision":"applied","operation_id":NaN}'
    elif change == "wrong_result":
        value["result"] = '{"decision":"kept","operation_id":null}'
    elif change == "oversized":
        value["request_id"] = "x" * 257
    else:
        key, replacement = {
            "source_type": ("source_document_hash", True),
            "parent_type": ("parent_token", "f" * 64),
            "target_type": ("target_kind", []),
            "unknown_provenance": ("path", "never read a path"),
        }[change]
        provenance[key] = replacement
        value["provenance"] = json.dumps(provenance)
    with pytest.raises(ValueError):
        enrollment_history.wrap(PROTOCOL, value)
    assert decision["database"].read_bytes() == before


def test_receipt_without_a_declared_original_remains_lossless_and_needs_no_file(decision):
    value = dict(decision["receipt"])
    provenance = json.loads(value["provenance"])
    provenance["source_document_hash"] = None
    value["provenance"] = json.dumps(provenance)
    wrapped = enrollment_history.wrap(PROTOCOL, value)
    assert enrollment_history.validate(wrapped) == (value, set())
    changed = {**wrapped, "body_json": wrapped["body_json"].replace(value["request_id"], "changed")}
    with pytest.raises(ValueError, match="identity changed"):
        enrollment_history.validate(changed)


@pytest.mark.parametrize("interruption", ["cancel", "changed_receipt", "publication"])
def test_interrupted_decision_copy_publishes_nothing_and_can_retry(
    decision, tmp_path, monkeypatch, interruption
):
    from paper_daily import workspace_enrollment
    from paper_daily.workspace_service import Cancelled, SnapshotChanged, Ticket

    value = decision
    original = value["database"].read_bytes()
    ticket = Ticket()
    changed = False
    real_publish = workspace_enrollment.publish_directory

    def progress(message):
        nonlocal changed
        if interruption == "cancel" and message.startswith("Coverage checked"):
            ticket.cancel()
        if interruption == "changed_receipt" and message.startswith("Creating") and not changed:
            changed = True
            with closing(generation._connect(value["database"])) as conn, conn:
                conn.execute("UPDATE research_review_receipts SET fingerprint=?", ("b" * 64,))

    def fail_publish(*_args, **_kwargs):
        raise OSError("fixture directory publication failure")

    if interruption == "publication":
        monkeypatch.setattr(workspace_enrollment, "publish_directory", fail_publish)
    error = {"cancel": Cancelled, "changed_receipt": SnapshotChanged, "publication": OSError}[
        interruption
    ]
    with pytest.raises(error):
        prepare(value, tmp_path, ticket=ticket, progress=progress)
    assert not (tmp_path / "candidate").exists() and not (tmp_path / "backup.zip").exists()
    assert value["primary"].read_bytes() == value["original_bytes"]
    if interruption != "changed_receipt":
        assert value["database"].read_bytes() == original
    with closing(generation._connect(value["database"])) as conn:
        expected = dict(conn.execute("SELECT * FROM research_review_receipts").fetchone())
    assert expected == {**value["receipt"], **({"fingerprint": "b" * 64} if changed else {})}
    monkeypatch.setattr(workspace_enrollment, "publish_directory", real_publish)
    result = prepare(value, tmp_path)
    with closing(generation._connect(result["database"])) as conn:
        receipts = [
            enrollment_history.validate(row)[0]
            for row in enrollment_history.archived(conn)
            if row["protocol"] == PROTOCOL
        ]
        assert receipts == [expected]
    with pytest.raises(ValueError, match="new paths"):
        prepare(value, tmp_path)
