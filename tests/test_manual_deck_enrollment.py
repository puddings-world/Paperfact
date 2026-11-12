"""First-enrollment real source/target boundaries, no AI or private receipt fabrication."""

import copy
import json
import os
import shutil
import sqlite3
import threading
from contextlib import closing
from pathlib import Path
from uuid import uuid4

import pymupdf
import pytest
from test_local_blob_binding import no_external as no_external
from test_manual_current_first_enrollment import rows, tree
from test_portable_deck_proposal import scientific as scientific
from test_proposal_recovery_primary import _directory_link

from paper_daily import local_deck_proposals as local
from paper_daily import manual_deck_enrollment as manual
from paper_daily import portable_deck_proposal as codec
from paper_daily import presentations, store, sync_artifacts, sync_document_actions, sync_recovery
from paper_daily import workspace_enrollment as enrollment
from paper_daily.fetch import _safe_name
from paper_daily.research_lifecycle import parent_lifecycle
from paper_daily.research_review import ResearchReview
from paper_daily.sync_deck_publication import load_managed_deck, publication_scope, runtime
from paper_daily.workspace_enrollment import EnrollmentService
from paper_daily.workspace_service import Cancelled, Ticket


def native(path):
    info = path.stat()
    return info.st_dev, info.st_ino


@pytest.fixture
def source(tmp_path, monkeypatch, scientific):
    root = tmp_path / "source"
    root.mkdir()
    database = root / "papers.sqlite"
    with closing(sqlite3.connect(database)) as conn:
        conn.executescript(store.SCHEMA)
        store._migrate(conn)
        store.upsert_papers(
            conn,
            [
                dict(
                    id="local-paper",
                    title="Manual source paper",
                    venue="Fixture",
                    year=2026,
                    source="fixture",
                )
            ],
        )
        conn.commit()
    monkeypatch.setattr(store, "DB_PATH", database)
    monkeypatch.setattr(presentations, "DECK_DIR", root / "presentations")
    deck, evidence, images, originals, sha, primary_b = scientific
    old = copy.deepcopy(deck)
    old.paper_id, old.title = "local-paper", "Prior manual current"
    old._revision_figures = copy.deepcopy(images)
    saved = presentations.save_deck(old)
    fourth = pymupdf.Pixmap(pymupdf.csRGB, 2, 2, b"\x12\x35\x71" * 4, False).tobytes("png")
    images["evidence:four"] = fourth
    evidence["figures"].append(
        dict(
            id="evidence:four",
            label="Fourth actual evidence",
            caption="Full fourth image",
            document_hash=sha,
            page=1,
        )
    )
    manifest, blobs = codec.encode(deck, evidence, images, originals, source_document_hash=sha)
    job = local.prepare(
        database,
        "local-paper",
        manifest,
        lambda row: blobs[row["sha256"]],
        request_id="source-proposal",
        expected_native=native(database),
    )
    proposal = local.retain(job)
    pdfs = root / "pdf"
    pdfs.mkdir()
    primary = pdfs / (_safe_name("local-paper") + ".pdf")
    primary.write_bytes(primary_b)
    return dict(
        root=root,
        database=database,
        saved=saved,
        primary=primary,
        proposal=proposal,
        manifest=manifest,
        blobs=blobs,
        expected=local.read(database, proposal, expected_native=native(database)).content,
        service=EnrollmentService(database),
        output=tmp_path / "editable",
        backup=tmp_path / "enrollment.zip",
        request=str(uuid4()),
    )


def prepare(source, **kwargs):
    return source["service"].prepare(
        source["output"],
        backup_output=source["backup"],
        request_id=source["request"],
        pdfs={"local-paper": source["primary"]},
        **kwargs,
    )


def baseline(source):
    return rows(source["database"]), tree(source["root"])


def no_outputs(source, before):
    assert not source["output"].exists() and not source["backup"].exists()
    assert baseline(source) == before


def archived_and_active(result):
    from paper_daily import enrollment_history
    from paper_daily import proposal_recovery_current as observed
    from paper_daily.research_file_review import _storage
    from paper_daily.sync_blobs import BlobManifest
    from paper_daily.sync_files import file_id
    from paper_daily.sync_source_files import input_versions

    database = Path(result["database"])
    client = runtime(database=database)
    with client.journal.transaction() as conn:
        wrapped = [
            row for row in enrollment_history.archived(conn) if row["protocol"] == observed.TABLE
        ]
        cache = _storage(conn)[0]
        portable = conn.execute(
            "SELECT sync_id FROM research_paper_identity WHERE local_id=?", ("local-paper",)
        ).fetchone()[0]
        operation = sync_artifacts.desired_file(conn, file_id(portable, "deck", "guide"))
    assert len(wrapped) == 1
    row = enrollment_history.validate(wrapped[0])[0]
    original = observed.read(
        row,
        lambda item: cache.verified_path(BlobManifest(item["sha256"], item["size"])).read_bytes(),
    )
    assert operation["payload"]["input_versions"] == input_versions()
    assert original["publish"] is False and original["input_provenance"] == "unknown"
    return client, original, operation


def test_public_plan_repeat_restart_and_prepare_preserve_one_manual_baseline(source):
    before = baseline(source)
    first = source["service"].plan(pdfs={"local-paper": source["primary"]})
    assert (
        first["supported"]
        and first["archived_history_by_protocol"]["research_observed_current_deck_recovery"] == 1
    )
    assert source["service"].plan(pdfs={"local-paper": source["primary"]}) == first
    assert baseline(source) == before
    result = prepare(source)
    client, original, operation = archived_and_active(result)
    assert original["raw"] == json.loads(source["saved"].read_bytes())
    assert len(original["raw"]["figures"]) == 3 and len(original["images"]) == 2
    assert operation["payload"]["source_document_hash"] is None
    with publication_scope(client):
        assert load_managed_deck("local-paper", "guide")[1].title == "Prior manual current"
    receiver_before, archive_before = tree(source["output"]), source["backup"].read_bytes()
    source["service"] = EnrollmentService(source["database"])
    with pytest.raises(ValueError):
        prepare(source)
    assert (
        tree(source["output"]) == receiver_before
        and source["backup"].read_bytes() == archive_before
    )
    assert baseline(source) == before
    review = ResearchReview(Path(result["database"]))
    try:
        items = [row for row in review.page(limit=100)["items"] if row["origin"] == "enrolled_deck"]
        assert len(items) == 1
        view = review.prepare_file(review.preview("enrolled_deck", items[0]["id"]))
        identity = view.data["id"]
        assert view.data["current"]["title"] == "Prior manual current"
    finally:
        review.close()
    reopened = ResearchReview(Path(result["database"]))
    try:
        items = [
            row for row in reopened.page(limit=100)["items"] if row["origin"] == "enrolled_deck"
        ]
        assert len(items) == 1 and items[0]["id"] == identity
    finally:
        reopened.close()


@pytest.mark.parametrize("fault", ["unknown-file", "json", "asset", "missing-asset", "lock"])
def test_tampered_or_unclassified_source_never_becomes_an_enrollment_baseline(source, fault):
    if fault == "unknown-file":
        (source["saved"].parent / "unrepresented-research.txt").write_bytes(b"Never omit this")
    elif fault == "json":
        source["saved"].write_bytes(b"invalid JSON")
    elif fault == "lock":
        (source["saved"].parent / ".deck-write.lock").write_bytes(b"x")
    else:
        asset = next((source["saved"].parent / "assets").glob("*.png"))
        asset.unlink() if fault == "missing-asset" else asset.write_bytes(b"corrupt actual asset")
    before = baseline(source)
    with pytest.raises((ValueError, OSError)):
        prepare(source)
    no_outputs(source, before)


def test_real_asset_junction_is_refused_without_touching_its_sibling_target(source, tmp_path):
    assets = source["saved"].parent / "assets"
    parked = source["saved"].parent / "parked-assets"
    assert assets.resolve().is_relative_to(source["root"].resolve())
    assets.rename(parked)
    target = tmp_path / "sibling-assets"
    shutil.copytree(parked, target)
    _directory_link(assets, target)
    target_before = tree(target)
    try:
        with pytest.raises(ValueError, match="link|reparse"):
            prepare(source)
        assert tree(target) == target_before
        assert not source["output"].exists() and not source["backup"].exists()
    finally:
        assets.rmdir() if os.name == "nt" else assets.unlink()
        parked.rename(assets)


@pytest.mark.parametrize("change", ["json", "database", "parent"])
def test_actual_source_change_during_staging_refuses_original_observation(
    source, monkeypatch, change
):
    stage_file = sync_document_actions.stage_file
    touched, after_actor = [], []

    def changed(cache, path, *args, **kwargs):
        value = stage_file(cache, path, *args, **kwargs)
        if Path(path) == source["saved"] and not touched:
            touched.append(True)
            if change == "json":
                raw = json.loads(source["saved"].read_bytes())
                raw["title"] = "Actual concurrent manual save"
                source["saved"].write_text(json.dumps(raw), encoding="utf-8")
            elif change == "database":
                replacement = source["root"].parent / "replacement.sqlite"
                with (
                    closing(sqlite3.connect(source["database"])) as old,
                    closing(sqlite3.connect(replacement)) as new,
                ):
                    old.backup(new)
                assert native(replacement) != native(source["database"])
                os.replace(replacement, source["database"])
            else:
                # Controlled external SQL repair, not a supported protocol-delete claim.
                with closing(sqlite3.connect(source["database"])) as conn, conn:
                    old = parent_lifecycle(conn, "paper", "local-paper")
                    row = conn.execute("SELECT * FROM papers WHERE id='local-paper'").fetchone()
                    conn.execute("DELETE FROM papers WHERE id='local-paper'")
                    conn.execute(
                        "INSERT INTO papers VALUES(" + ",".join("?" for _ in row) + ")", row
                    )
                    assert parent_lifecycle(conn, "paper", "local-paper") != old
            after_actor.append(baseline(source))
        return value

    monkeypatch.setattr(enrollment, "stage_file", changed)
    with pytest.raises((ValueError, OSError)):
        prepare(source)
    assert touched == [True]
    no_outputs(source, after_actor[0])


@pytest.mark.parametrize("phase", ["before", "staging", "final"])
def test_cancelled_enrollment_preserves_source_and_publishes_no_outputs(source, monkeypatch, phase):
    ticket = Ticket()
    stage_file = sync_document_actions.stage_file
    calls = []

    def staged(cache, path, *args, **kwargs):
        result = stage_file(cache, path, *args, **kwargs)
        if phase == "staging" and Path(path) == source["saved"]:
            calls.append(True)
            ticket.cancel()
        return result

    def progress(text):
        if phase == "final" and text.startswith("Verified candidate"):
            calls.append(True)
            ticket.cancel()

    if phase == "before":
        ticket.cancel()
    before = baseline(source)
    monkeypatch.setattr(enrollment, "stage_file", staged)
    with pytest.raises(Cancelled):
        prepare(source, ticket=ticket, progress=progress)
    assert phase == "before" or calls == [True]
    no_outputs(source, before)


@pytest.mark.parametrize("fault", ["cache", "sql-activation", "output"])
def test_storage_or_sql_failure_rolls_back_outputs_then_exact_request_retry(
    source, monkeypatch, fault
):
    import paper_daily.workspace_enrollment as enrollment

    stage_bytes, activate, publish_directory = (
        sync_artifacts.stage_bytes,
        sync_artifacts.activate,
        enrollment.publish_directory,
    )
    failures = []

    def staged(cache, blobs):
        if fault == "cache" and any(
            isinstance((value := json.loads(data)), dict)
            and "deck" in value
            and value["deck"]["title"] == "Prior manual current"
            for data in blobs.values()
            if data.startswith(b"{")
        ):
            failures.append(True)
            raise OSError("Synthetic primary cache write failure")
        return stage_bytes(cache, blobs)

    def activated(conn, operation, materialized):
        if fault == "sql-activation" and operation["payload"]["feature"] == "deck":
            failures.append(True)
            conn.set_authorizer(
                lambda action, name, *_: (
                    sqlite3.SQLITE_DENY
                    if action == sqlite3.SQLITE_INSERT and name == "research_file_applied"
                    else sqlite3.SQLITE_OK
                )
            )
            try:
                return activate(conn, operation, materialized)
            finally:
                conn.set_authorizer(None)
        return activate(conn, operation, materialized)

    def publish(*args):
        if fault == "output":
            failures.append(True)
            raise OSError("Synthetic final directory publication failure")
        return publish_directory(*args)

    before = baseline(source)
    monkeypatch.setattr(sync_artifacts, "stage_bytes", staged)
    monkeypatch.setattr(sync_artifacts, "activate", activated)
    monkeypatch.setattr(enrollment, "publish_directory", publish)
    with pytest.raises((OSError, sqlite3.DatabaseError)):
        prepare(source)
    assert failures == [True]
    no_outputs(source, before)
    monkeypatch.setattr(sync_artifacts, "stage_bytes", stage_bytes)
    monkeypatch.setattr(sync_artifacts, "activate", activate)
    monkeypatch.setattr(enrollment, "publish_directory", publish_directory)
    result = prepare(source)
    client, original, _operation = archived_and_active(result)
    assert original["raw"] == json.loads(source["saved"].read_bytes())
    with client.journal.transaction() as conn:
        operations = [
            json.loads(row[0])
            for row in conn.execute("SELECT operation FROM research_file_versions")
        ]
    assert sum(item["payload"]["feature"] == "deck" for item in operations) == 1
    assert baseline(source) == before


def test_repeated_active_prepare_is_single_flight_and_cancel_drains_without_outputs(
    source, monkeypatch
):
    original = manual.publish
    entered, release = threading.Event(), threading.Event()
    ticket = Ticket()
    outcomes = []

    def held(*args, **kwargs):
        entered.set()
        assert release.wait(30)
        return original(*args, **kwargs)

    def worker():
        try:
            outcomes.append(prepare(source, ticket=ticket))
        except BaseException as error:
            outcomes.append(error)

    before = baseline(source)
    monkeypatch.setattr(manual, "publish", held)
    thread = threading.Thread(target=worker)
    thread.start()
    try:
        assert entered.wait(30)
        with pytest.raises(ValueError, match="already running"):
            prepare(source)
        ticket.cancel()
    finally:
        release.set()
        thread.join(30)
    assert not thread.is_alive() and len(outcomes) == 1 and isinstance(outcomes[0], Cancelled)
    no_outputs(source, before)


def test_missing_same_paper_original_scope_refuses_even_with_identical_available_hash(source):
    import paper_daily.workspace_enrollment as enrollment

    with enrollment._read(source["database"], budget=30) as conn:
        actual = source["service"]._inventory(conn, {"local-paper": source["primary"]}, Ticket())
        known = actual["original_sources"]
        foreign = {("another-paper", sha): item for (_owner, sha), item in known.items()}
        with pytest.raises(ValueError, match="same-paper"):
            manual.inventory(conn, source["database"], foreign, Ticket())
    assert not source["output"].exists()


def test_old_receiver_unknown_history_protocol_refuses_before_detached_restore(
    source, tmp_path, monkeypatch
):
    from paper_daily import enrollment_history
    from paper_daily import proposal_recovery_current as observed

    prepare(source)
    assert sync_recovery.inspect(source["backup"])["format"] == "paperfact-recovery"
    monkeypatch.delitem(enrollment_history.FORMATS, observed.TABLE)
    target = tmp_path / "old-reader-restore"
    with pytest.raises(ValueError, match="protocol"):
        sync_recovery.restore_detached(source["backup"], target)
    assert not target.exists()


@pytest.mark.parametrize("fault", ["foreign-binding", "index-replacement", "version-junction"])
def test_actual_candidate_store_scope_refuses_before_foreign_or_replaced_root_mutation(
    source, tmp_path, monkeypatch, fault
):
    from paper_daily.local_blob_binding import SCHEMA as BINDING_SCHEMA

    original_publish, stage_bytes, materialize = (
        manual.publish,
        sync_artifacts.stage_bytes,
        sync_artifacts.materialize,
    )
    seen = []
    sibling = tmp_path / "unrelated-version-target"
    sibling.mkdir()
    (sibling / "sentinel.txt").write_bytes(b"Preserve unrelated owned fixture")
    sibling_before = tree(sibling)

    def publishing(client, cache, root, captured, **kwargs):
        if fault == "foreign-binding":
            index = cache.root / "index.sqlite"
            with closing(sqlite3.connect(index)) as conn, conn:
                conn.execute(BINDING_SCHEMA)
                conn.execute(
                    "INSERT INTO transfer_binding VALUES(1,?,?,?)",
                    (client.journal.workspace_id, "foreign-device", str(client.journal.path)),
                )
            seen.append(True)
        return original_publish(client, cache, root, captured, **kwargs)

    def staging(cache, encoded):
        if fault == "index-replacement" and isinstance(cache, manual._StageStore):
            index = cache.root / "index.sqlite"
            replacement = tmp_path / "candidate-index-copy.sqlite"
            with (
                closing(sqlite3.connect(index)) as old,
                closing(sqlite3.connect(replacement)) as new,
            ):
                old.backup(new)
            assert native(index) != native(replacement)
            os.replace(replacement, index)
            after_actor = tree(cache.root)
            seen.append(True)
            try:
                return stage_bytes(cache, encoded)
            finally:
                assert tree(cache.root) == after_actor
        return stage_bytes(cache, encoded)

    def projecting(cache, root, operation):
        if fault == "version-junction" and operation["payload"]["feature"] == "deck":
            root = Path(root)
            parked = root.with_name(root.name + "-parked")
            assert root.resolve().is_relative_to(tmp_path.resolve())
            root.rename(parked)
            _directory_link(root, sibling)
            seen.append(True)
            try:
                return materialize(cache, root, operation)
            finally:
                root.rmdir() if os.name == "nt" else root.unlink()
                parked.rename(root)
        return materialize(cache, root, operation)

    before = baseline(source)
    monkeypatch.setattr(manual, "publish", publishing)
    monkeypatch.setattr(sync_artifacts, "stage_bytes", staging)
    monkeypatch.setattr(sync_artifacts, "materialize", projecting)
    with pytest.raises((ValueError, OSError)):
        prepare(source)
    assert seen == [True] and tree(sibling) == sibling_before
    no_outputs(source, before)
