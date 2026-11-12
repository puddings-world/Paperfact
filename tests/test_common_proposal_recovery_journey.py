"""Required full common proposal recovery: real services, no fabricated archive."""

import copy
import hashlib
import json
import sqlite3
from contextlib import closing
from pathlib import Path
from uuid import uuid4

import pymupdf
import pytest
from test_enrolled_deck_proposals import actual as actual
from test_enrolled_deck_proposals import case as case
from test_enrolled_deck_proposals import codec as codec
from test_enrolled_deck_proposals import native
from test_enrolled_deck_proposals import no_external as no_external
from test_enrolled_deck_proposals import original as original
from test_enrolled_deck_proposals import package as package
from test_enrolled_deck_proposals import scientific as scientific
from test_local_deck_proposals import local as local

from paper_daily import enrolled_deck_proposals as enrolled
from paper_daily import local_deck_proposals as local_catalog
from paper_daily import portable_deck_proposal as content
from paper_daily import presentations
from paper_daily.fetch import _safe_name
from paper_daily.recovery_adoption import RecoveryAdoptionService
from paper_daily.research_file_review import _storage
from paper_daily.research_review import ResearchReview
from paper_daily.sync_artifacts import desired_file, verify_closure
from paper_daily.sync_blobs import BlobManifest
from paper_daily.sync_deck_publication import observe_deck, publication_scope, runtime
from paper_daily.sync_files import file_id
from paper_daily.workspace_service import Ticket, WorkspaceService


def hash_bytes(value):
    return hashlib.sha256(value).hexdigest()


def state(database):
    with closing(sqlite3.connect(database)) as conn:
        tables = {
            row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        snapshots = {}
        for name in (
            "papers",
            "notes",
            "research_file_desired",
            "research_file_applied",
            "paperfact_sync_operations",
            local_catalog.TABLE,
            enrolled.TABLE,
        ):
            if name in tables:
                snapshots[name] = sorted(
                    [list(row) for row in conn.execute('SELECT * FROM "' + name + '"')], key=str
                )
    return snapshots


def sender(request, kind):
    if kind == "enrolled":
        from test_package_import import enroll_capture
        from test_sync_files import side

        from paper_daily.package_import import PackageImporter

        fixture = request.getfixturevalue("actual")
        clean_root = fixture["client"].journal.path.parent / "complete-enrolled-source"
        clean_root.mkdir()
        client = side(clean_root, "source")
        enroll_capture(client)
        destination = clean_root / "files"
        destination.mkdir()
        importer = PackageImporter(client.journal.path, destination)
        report = importer.apply(importer.prepare(fixture["package"].archive))
        mapped = report["identity_mapping"][fixture["local"]]
        prior = presentations.deck_from_dict(copy.deepcopy(fixture["package"].case["before"]))
        prior.paper_id = mapped["local_id"]
        prior._revision_figures = fixture["package"].case["images"]
        with publication_scope(client):
            presentations.save_deck(
                prior,
                observation=observe_deck(mapped["local_id"], "guide"),
                request_id="clean-source-prior-deck",
            )
        with client.journal.transaction() as conn:
            cache = _storage(conn)[0]
        prepared = enrolled.prepare(
            client,
            cache,
            mapped["local_id"],
            mapped["portable_id"],
            fixture["manifest"],
            lambda row: fixture["blobs"][row["sha256"]],
            request_id="union-four",
            expected_native=native(client.journal.path),
        )
        with client.journal.transaction() as conn:
            identity = enrolled.adopt_in(conn, prepared)
        database = client.journal.path
        source = enrolled.read(client, cache, identity, expected_native=native(database))
        primary = fixture["package"].primary
        path = cache.verified_path(BlobManifest(primary["sha256"], primary["size"]))

        def read():
            return enrolled.read(client, cache, identity, expected_native=native(database))

        with client.journal.transaction() as conn:
            active = desired_file(conn, file_id(mapped["portable_id"], "deck", "guide"))
        prior_title = verify_closure(cache, active)[1]["deck"]["title"]
        return database, source.content, read, path, prior_title
    fixture = request.getfixturevalue("local")
    database = fixture[0]
    with closing(sqlite3.connect(database)) as conn, conn:
        conn.execute("UPDATE notes SET created_at=?", ("2026-11-01T00:00:00+00:00",))
    deck, evidence, images, originals, original_a, primary_b = request.getfixturevalue("scientific")
    # The maintained fixture's custom `decks` root is not a Workspace FULL root.
    # Save through the real public manual action in the supported canonical root.
    # Keep dormant figure metadata exactly; only actually saved assets claim bytes.
    request.getfixturevalue("monkeypatch").setattr(
        presentations, "DECK_DIR", database.parent / "presentations"
    )
    prior = presentations.deck_from_dict(json.loads(fixture[3].read_text(encoding="utf-8")))
    prior._revision_figures = images
    canonical_saved = presentations.save_deck(prior)
    fourth = pymupdf.Pixmap(pymupdf.csRGB, 2, 2, b"\x13\x57\x9b" * 4, False).tobytes("png")
    evidence["figures"].append(
        dict(
            id="evidence:four",
            label="Evidence-only original A",
            caption="Full fourth-image scientific caption",
            page=1,
            document_hash=original_a,
        )
    )
    images["evidence:four"] = fourth
    manifest, blobs = content.encode(
        deck, evidence, images, originals, source_document_hash=original_a
    )
    prepared = local_catalog.prepare(
        database,
        "local-paper",
        manifest,
        lambda row: blobs[row["sha256"]],
        request_id="backup-four",
        expected_native=native(database),
    )
    identity = local_catalog.retain(prepared)

    def read():
        return local_catalog.read(database, identity, expected_native=native(database))

    source = read()
    folder = database.parent / "pdf"
    folder.mkdir()
    path = folder / (_safe_name("local-paper") + ".pdf")
    path.write_bytes(primary_b)
    return (
        database,
        source.content,
        read,
        path,
        json.loads(canonical_saved.read_text(encoding="utf-8"))["title"],
    )


@pytest.mark.parametrize("kind", ["local", "enrolled"])
def test_full_backup_detached_fresh_editable_review_preserves_common_proposal_union(request, kind):
    database, expected, reread, primary, prior_title = sender(request, kind)
    assert len(expected["deck"]["figures"]) == 3
    assert len(expected["evidence"]["figures"]) == 4 and len(expected["image_bytes"]) == 4
    original_a = expected["source_document_hash"]
    assert set(expected["original_bytes"]) == {original_a}
    primary_before = primary.read_bytes()
    assert hash_bytes(primary_before) != original_a
    source_before = state(database)
    database_before = database.read_bytes()
    output_root = database.parent.parent / (database.parent.name + "-full-recovery-" + kind)
    output_root.mkdir()
    archive = output_root / "full.zip"
    detached = output_root / "detached"
    editable = output_root / "editable"
    editable_backup = output_root / "editable.zip"
    service = WorkspaceService(database)
    status = service.status()
    observed = dict(
        kind=kind,
        stage="backup",
        source_native=list(native(database)),
        original_a=original_a,
        current_primary_b=hash_bytes(primary_before),
        image_hashes={key: hash_bytes(value) for key, value in expected["image_bytes"].items()},
        scientific_deck_ids=[row["id"] for row in expected["deck"]["figures"]],
        scientific_evidence_ids=[row["id"] for row in expected["evidence"]["figures"]],
        before=source_before,
        status=status,
        outputs={"archive": str(archive), "detached": str(detached), "editable": str(editable)},
    )
    try:
        made = service.backup(archive, Ticket())
        observed["stage"] = "detached restore"
        manifest = service.inspect(archive, Ticket())
        assert manifest == made["manifest"]
        restored = service.restore(archive, detached, manifest["backup_id"], Ticket())
        assert restored["detached"]
        observed["stage"] = "fresh editable adoption"
        adoption = RecoveryAdoptionService(detached / "papers.db")
        inspection = adoption.inspect()
        assert inspection.report["supported"], inspection.report["blockers"]
        result = adoption.prepare(
            inspection, editable, backup_output=editable_backup, request_id=str(uuid4())
        )
        assert result["editable_copy"] and not result["uploaded"]
        assert not result["adopted"] and result["status"] == "prepared_for_review"
        observed["stage"] = "explicit proposal preview/verify"
        receiver = Path(result["database"])
        review = ResearchReview(receiver)
        try:
            entries = [
                row for row in review.page(limit=100)["items"] if row["origin"] == "enrolled_deck"
            ]
            assert len(entries) == 1
            preview = review.preview(entries[0]["origin"], entries[0]["id"])
            verified = review.prepare_file(preview)
            assert verified.data["apply"] and verified.data["requires_confirmation"]
            assert verified.data["retained"] == expected["deck"]
            assert verified.data["retained_evidence"] == expected["evidence"]
            assert len(verified.data["image_manifest"]) == 4
            with closing(review._connect()) as conn:
                store, _root, _proof = _storage(conn)
            client = runtime(database=receiver)
            retained = enrolled.read(
                client, store, verified.data["id"], expected_native=native(receiver)
            )
            assert retained.content == expected
            owner = json.loads(retained.record["owner_json"])["target"]
            assert owner["database"] == str(receiver.resolve())
            assert owner["binding"] == [result["workspace_id"], result["device_id"]]
            assert owner["native"] != list(native(database))
            if kind == "enrolled":
                with closing(sqlite3.connect(database)) as conn:
                    old = conn.execute(
                        "SELECT workspace,device FROM paperfact_sync_identity"
                    ).fetchone()
                    assert owner["binding"][0] != old[0] and owner["binding"][1] != old[1]
            # Existing active work survives; the imported proposal is not automatically applied.
            assert verified.data["current"]["title"] == prior_title
            assert verified.data["current"]["title"] != expected["deck"]["title"]
        finally:
            review.close()
    except Exception as error:
        observed.update(
            error_type=type(error).__name__,
            error=str(error),
            after=state(database),
            source_database_bytes_unchanged=database.read_bytes() == database_before,
            source_science_unchanged=reread().content == expected,
            primary_bytes_unchanged=primary.read_bytes() == primary_before,
            archive_exists=archive.exists(),
            detached_exists=detached.exists(),
            editable_exists=editable.exists(),
            editable_backup_exists=editable_backup.exists(),
        )
        (database.parent / ("common-proposal-recovery-observed-" + kind + ".json")).write_text(
            json.dumps(observed, indent=2), encoding="utf-8"
        )
        raise
    assert state(database) == source_before and reread().content == expected
    assert primary.read_bytes() == primary_before
