"""Real list export/import must retain a rescue proposal, without sender authority."""

import hashlib
import json
import sqlite3
import zipfile
from contextlib import closing

from test_package_import import enroll_capture
from test_rescue_deck_import import (
    RECEIVER,
    TARGET,
    attach,
    export_file,
    pdf_bytes,
    target,
)
from test_rescue_deck_import import (
    case as case,
)
from test_rescue_deck_import import (
    codec as codec,
)
from test_rescue_deck_import import (
    no_external as no_external,
)
from test_rescue_deck_import import (
    original as original,
)

from paper_daily import bundle, presentations, raw_deck_receipts, rescue_deck_import
from paper_daily.document_reader import register_document_paths
from paper_daily.package_import import PackageImporter
from paper_daily.research_review import ResearchReview
from paper_daily.sync_artifacts import desired_file
from paper_daily.sync_files import file_id
from paper_daily.sync_schema_v2 import membership_id
from paper_daily.sync_source_files import publish as publish_source


def test_public_list_package_retains_rescue_draft_all_images_and_source_evidence(case, monkeypatch):
    """A real retained proposal travels as a fresh reviewable draft, never active state."""
    sender, receiver = case["a"], case["b"]
    with sender.journal.transaction() as conn:
        register_document_paths(
            conn,
            workspace_id="workspace",
            blob_root=case["transfer"].store.root,
            projection_root=case["root"] / "sender-projections",
            legacy_root=case["root"] / "pdf",
        )
    original_a = pdf_bytes("Rescue-declared original A")
    digest_a = hashlib.sha256(original_a).hexdigest()
    owned_a = case["root"] / "declared-original-a.pdf"
    owned_a.write_bytes(original_a)
    with sender.journal.transaction() as conn:
        parent = sender._optimistic_graph(conn)[0][("paper", RECEIVER)]["incarnation"]
    publish_source(
        sender,
        RECEIVER,
        owned_a,
        document_hash=digest_a,
        parent_incarnation=parent,
        store=case["transfer"].store,
        version_root=case["transfer"].root,
        request_id="raw-package-source-a",
    )
    primary_b = attach(
        sender,
        case["transfer"].store,
        RECEIVER,
        pdf_bytes("Current primary B remains separate"),
        "raw-package-primary-b",
    )
    source = export_file(case, monkeypatch, source_hash=digest_a)
    retained = rescue_deck_import.run(
        rescue_deck_import.prepare(
            target(case, request="portable-proposal"), rescue_deck_import.inspect_file(source)
        )
    )
    assert retained.durable and retained.context_current
    assert retained.retention.deck._revision_figures == case["images"]
    with sender.journal.transaction() as conn:
        row = dict(
            conn.execute(
                "SELECT * FROM research_file_drafts WHERE candidate_id=?", (retained.candidate_id,)
            ).fetchone()
        )
        header, objects, _files = raw_deck_receipts.read_owned(conn, row)
    assert all(
        objects[hashlib.sha256(value).hexdigest()] == value for value in case["images"].values()
    )
    sender_review = ResearchReview(sender.journal.path)
    try:
        assert sender_review.prepare_file(
            sender_review.preview("file_draft", retained.candidate_id)
        ).data["apply"]
    finally:
        sender_review.close()

    listing = "rescue-reading-list"
    sender.save(
        sender.new_graph_operation("list", listing, {"name": "Rescue readings", "note": None})
    )
    sender.save(
        sender.new_graph_operation(
            "membership",
            membership_id(listing, RECEIVER),
            {
                "list_id": listing,
                "paper_id": RECEIVER,
                "citation": None,
                "added_at": "2026-11-01T00:00:00+00:00",
            },
        )
    )
    pending_before = sender.journal.pending()
    saved_before = presentations.load_deck(TARGET, "guide").to_dict()
    original_file = source.read_bytes()
    monkeypatch.setattr(bundle, "DATA_DIR", case["root"])
    monkeypatch.setattr(bundle, "PDF_DIR", case["root"] / "pdf")
    archive = case["root"] / "rescue-list.zip"
    exported = bundle.export(listing, archive, with_pdfs=True)
    with zipfile.ZipFile(archive) as zipped:
        manifest = json.loads(zipped.read("manifest.json"))
        tables = json.loads(zipped.read("tables.json"))
        archive_hashes = {
            hashlib.sha256(zipped.read(name)).hexdigest()
            for name in zipped.namelist()
            if not name.endswith("/")
        }
    assert exported["papers"] == 1 and exported["pdf_packed"] == 1
    assert sender.journal.pending() == pending_before
    assert presentations.load_deck(TARGET, "guide").to_dict() == saved_before
    assert source.read_bytes() == original_file

    enroll_capture(receiver)
    destination = case["root"] / "fresh-editable-receiver"
    destination.mkdir()
    importer = PackageImporter(receiver.journal.path, destination)
    prepared = importer.prepare(archive, request_id="rescue-list-copy")
    report = importer.apply(prepared)
    assert report["papers"] == 1
    mapped = report["identity_mapping"][TARGET]
    review = ResearchReview(receiver.journal.path)
    try:
        visible = review.page(limit=100)["items"]
        drafts = [item for item in visible if item["origin"] == "file_draft"]
    finally:
        review.close()
    with closing(sqlite3.connect(receiver.journal.path)) as conn:
        names = {row[0] for row in conn.execute("SELECT name FROM sqlite_master")}
        raw_count = (
            conn.execute("SELECT COUNT(*) FROM research_file_drafts").fetchone()[0]
            if "research_file_drafts" in names
            else 0
        )
        receiver_active = (
            desired_file(conn, file_id(mapped["portable_id"], "deck", "guide")) is not None
        )
    observation = dict(
        sender_candidate=retained.candidate_id,
        sender_state=retained.state,
        sender_unique_images=len(case["images"]),
        sender_source_hash=digest_a,
        current_primary_hash=primary_b["sha256"],
        sender_draft_deck=json.loads(header["raw"]["deck"]),
        package_capabilities=manifest.get("capabilities", []),
        package_table_names=sorted(tables),
        package_image_presence={
            key: hashlib.sha256(value).hexdigest() in archive_hashes
            for key, value in case["images"].items()
        },
        original_a_in_package=digest_a in archive_hashes,
        receiver_mapping=mapped,
        receiver_report=report,
        receiver_visible_review_items=visible,
        receiver_raw_count=raw_count,
        sender_saved_unchanged=True,
        sender_outbox_unchanged=True,
        receiver_active_deck=receiver_active,
    )
    (case["root"] / "carrier-observed.json").write_text(
        json.dumps(observation, indent=2, default=str)
    )
    assert len(drafts) == 1, "The supported list package silently dropped a durable rescue proposal"
    assert raw_count == 1 and not receiver_active
    review = ResearchReview(receiver.journal.path)
    try:
        verified = review.prepare_file(review.preview("file_draft", drafts[0]["id"]))
        assert verified.data["retained"]["title"] == retained.retention.deck.title
        with receiver.journal.transaction() as conn:
            incoming = dict(
                conn.execute(
                    "SELECT * FROM research_file_drafts WHERE candidate_id=?", (drafts[0]["id"],)
                ).fetchone()
            )
            received_header, received_bytes, _owned_files = raw_deck_receipts.read_owned(
                conn, incoming
            )
        assert received_header["evidence"] == retained.retention.evidence
        received_deck = json.loads(received_header["raw"]["deck"])
        expected_deck = retained.retention.deck.to_dict()
        assert received_deck["paper_id"] == mapped["local_id"]
        assert received_deck["deck_id"] != expected_deck["deck_id"]
        assert {k: v for k, v in received_deck.items() if k not in {"paper_id", "deck_id"}} == {
            k: v for k, v in expected_deck.items() if k not in {"paper_id", "deck_id"}
        }
        assert all(
            received_bytes[hashlib.sha256(value).hexdigest()] == value
            for value in case["images"].values()
        )
    finally:
        review.close()
    assert all(
        hashlib.sha256(value).hexdigest() in archive_hashes for value in case["images"].values()
    )
    assert digest_a in archive_hashes
    info = receiver.journal.path.stat()
    local_target = rescue_deck_import.capture(
        receiver.journal.path,
        mapped["local_id"],
        "guide",
        expected_native=(info.st_dev, info.st_ino),
        request_id="verify-imported-original",
    )
    verified_source = rescue_deck_import.prepare(
        local_target, rescue_deck_import.inspect_file(source)
    )
    assert verified_source.summary["source_status"] == "owned"
    assert file_id(mapped["portable_id"], "deck", "guide") != retained.candidate_id
