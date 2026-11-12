"""Actual observed enrolled import: typed outcome/source scope, atomic failure/retry."""

import hashlib
import json
import os
import shutil
import sqlite3
from contextlib import closing

import pytest
from test_later_outcome_bundle import source
from test_reading_positions import make
from test_research_generation import pdf
from test_research_generation import workspace as workspace

from paper_daily import bundle
from paper_daily import later_outcomes as outcomes
from paper_daily.document_reader import from_workspace
from paper_daily.package_import import PackageImporter
from paper_daily.sync_blobs import BlobStore
from paper_daily.sync_capture import CaptureConnection, install
from paper_daily.sync_file_transfers import FileTransfers
from paper_daily.sync_source_files import resolved
from paper_daily.workspace_service import Cancelled, Ticket


def receiver(root):
    root.mkdir()
    client = make(root / "papers.db", "receiver")
    with closing(sqlite3.connect(client.journal.path, factory=CaptureConnection)) as conn:
        conn.execute("BEGIN IMMEDIATE")
        install(conn, workspace_id="workspace", device_id="receiver")
        conn.commit()

    class InertTransport:
        def __getattr__(self, name):
            if name == "base_url":
                raise AttributeError(name)
            raise AssertionError("Package setup contacted a transport")

    transfer = FileTransfers(
        client,
        BlobStore(root / "blobs"),
        InertTransport(),
        origin="https://fixture.invalid",
        token=None,
    )
    transfer.close()
    return client, PackageImporter(client.journal.path, root)


@pytest.mark.parametrize("current_b", [False, True], ids=["current-A", "retained-A-current-B"])
def test_actual_enrolled_package_uses_fresh_scope_and_exact_source(
    workspace, monkeypatch, tmp_path, current_b
):
    sender, document, archive = source(workspace, monkeypatch, tmp_path)
    if current_b:
        pdf(document.path, "Sharer primary B differs from accepted query source A")
    current = hashlib.sha256(document.path.read_bytes()).hexdigest()
    bundle.export("reading", archive)
    client, importer = receiver(tmp_path / "enrolled")
    report = importer.apply(importer.prepare(archive))
    mapping = report["identity_mapping"]["paper"]
    assert mapping["local_id"] != "paper"
    document_b = from_workspace(client.journal.path).resolve(mapping["local_id"])
    assert document_b.managed and document_b.available and document_b.sha256 == current
    with client.journal.transaction() as conn:
        row = conn.execute(
            "SELECT body_json,document_hash FROM paper_later_outcomes WHERE paper_id=?",
            (mapping["local_id"],),
        ).fetchone()
        assert row["document_hash"] == document.sha256
        assert (
            hashlib.sha256(
                resolved(conn, mapping["portable_id"], document.sha256).read_bytes()
            ).hexdigest()
            == document.sha256
        )
        assert outcomes.settled(conn, mapping["local_id"]) is (not current_b)
    pending = client.journal.pending()
    wire = json.dumps(pending)
    assert (
        str(sender) not in wire
        and "database_identity" not in wire
        and "parent_lifecycle" not in wire
    )
    assert importer.apply(importer.prepare(archive))["replayed"]
    assert client.journal.pending() == pending
    assert from_workspace(client.journal.path).resolve(mapping["local_id"]).sha256 == current


@pytest.mark.parametrize("change", ["cancel", "native"])
def test_enrolled_staged_import_refuses_cancel_or_actual_native_replacement(
    workspace, monkeypatch, tmp_path, change
):
    _sender, _document, archive = source(workspace, monkeypatch, tmp_path)
    bundle.export("reading", archive)
    client, importer = receiver(tmp_path / "enrolled")
    prepared = importer.prepare(archive)
    before = client.journal.pending()
    ticket = Ticket()
    if change == "cancel":
        ticket.cancel()
    else:
        replacement = client.journal.path.with_suffix(".replacement")
        shutil.copyfile(client.journal.path, replacement)
        os.replace(replacement, client.journal.path)
    with pytest.raises((ValueError, Cancelled)):
        importer.apply(prepared, ticket=ticket)
    assert client.journal.pending() == before
    with client.journal.transaction() as conn:
        assert conn.execute("SELECT COUNT(*) FROM paper_later_outcomes").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM papers").fetchone()[0] == 0


def test_actual_enrolled_sql_failure_rolls_back_outcome_source_and_retry_is_single(
    workspace, monkeypatch, tmp_path
):
    _sender, _document, archive = source(workspace, monkeypatch, tmp_path)
    bundle.export("reading", archive)
    client, importer = receiver(tmp_path / "enrolled")
    prepared = importer.prepare(archive)
    original = importer.client.journal.apply_in

    def fail(conn, operation, writer):
        result = original(conn, operation, writer)
        if (
            operation["entity_type"] == "research_content"
            and operation["payload"].get("feature") == "later_outcome"
        ):
            raise OSError("Fixture failure after actual typed outcome SQL")
        return result

    monkeypatch.setattr(importer.client.journal, "apply_in", fail)
    with pytest.raises(OSError, match="after actual typed"):
        importer.apply(prepared)
    with client.journal.transaction() as conn:
        assert conn.execute("SELECT COUNT(*) FROM paper_later_outcomes").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM research_file_applied").fetchone()[0] == 0
    assert client.journal.pending() == []
    monkeypatch.setattr(importer.client.journal, "apply_in", original)
    report = importer.apply(importer.prepare(archive))
    assert report["paper_later_outcomes"] == 1
    pending = client.journal.pending()
    assert importer.apply(importer.prepare(archive))["replayed"]
    assert client.journal.pending() == pending
