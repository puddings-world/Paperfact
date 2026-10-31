"""Imported historical originals become archival observations, not copied authority."""

import hashlib
import json
import sqlite3
import zipfile
from contextlib import closing
from pathlib import Path
from uuid import uuid4

import pytest
from test_local_source_owners import receiver as receiver
from test_package_import import package as package
from test_package_import import rich_package as rich_package

from paper_daily import (
    bundle,
    local_source_owners,
    source_provenance,
    source_snapshots,
    sync_recovery,
)
from paper_daily.sync_source_files import resolved
from paper_daily.workspace_enrollment import EnrollmentBlocked, EnrollmentService


@pytest.fixture
def imported(rich_package, receiver, tmp_path):
    archive, current, original, body = rich_package
    with zipfile.ZipFile(archive) as z:
        values = {name: z.read(name) for name in z.namelist()
                  if not name.startswith(("files/presentations/", "files/figures/"))}
    manifest = json.loads(values["manifest.json"])
    manifest["list"]["note"] = "Shared exact original lineage"
    manifest["file_hashes"] = {name: digest for name, digest in manifest["file_hashes"].items()
                               if not name.startswith(("presentations/", "figures/"))}
    manifest["counts"]["files"] = len(manifest["file_hashes"])
    values["manifest.json"] = json.dumps(manifest).encode()
    selected = tmp_path / "claims-without-deck.zip"
    with zipfile.ZipFile(selected, "w") as z:
        for name, value in values.items():
            z.writestr(name, value)
    assert bundle.import_(selected, pdfs=False)["owned_originals"] == 1
    return receiver[0], receiver[1], current, original, body


def prepare(database, tmp_path, **kwargs):
    token = str(uuid4())
    return EnrollmentService(database).prepare(
        tmp_path / ("candidate-" + token), backup_output=tmp_path / (token + ".zip"),
        request_id=token, **kwargs,
    )


def test_actual_import_plan_enroll_preserves_original_and_archives_owner(imported, tmp_path):
    database, root, current, original, body = imported
    primary = root / "pdf/ref_example.pdf"
    receipts = local_source_owners.list_owned(database)
    source = source_snapshots.source_path(database, receipts[0])
    original_bytes = source.read_bytes()
    plan = EnrollmentService(database).plan(pdfs={"ref:example": primary})
    assert plan["supported"], plan["blockers"]
    assert plan["archived_source_receipts"] == 1
    assert plan["imported_source_receipts"] == 1
    result = prepare(database, tmp_path, pdfs={"ref:example": primary})
    copied = Path(result["database"])
    with closing(sqlite3.connect(copied)) as conn:
        assert not conn.execute("SELECT 1 FROM sqlite_master WHERE name=?",
                                (local_source_owners.TABLE,)).fetchone()
        archived = source_provenance.archived(conn)
        assert [source_provenance.validate(row) for row in archived] == receipts
        portable = conn.execute("SELECT sync_id FROM research_paper_identity WHERE local_id=?",
                                ("ref:example",)).fetchone()[0]
        located = resolved(conn, portable, original)
        assert located.read_bytes() == original_bytes
        raw = conn.execute("SELECT body_json FROM paper_claim_sets").fetchone()[0]
        assert json.loads(raw) == body
        wire = "\n".join(
            row[0] for row in conn.execute("SELECT envelope FROM paperfact_sync_operations")
        )
        assert str(database) not in wire and "database_identity" not in wire
        old_lifecycle = json.loads(receipts[0]["owner_json"])["parent_lifecycle"]
        assert conn.execute("SELECT token FROM research_parent_lifecycle WHERE entity_id=?",
                            ("ref:example",)).fetchone()[0] != old_lifecycle
    with zipfile.ZipFile(result["backup"]) as z:
        assert z.read("objects/" + original) == original_bytes
        assert hashlib.sha256(z.read("objects/" + current)).hexdigest() == current
        archived = json.loads(z.read("tables/research_source_archive.jsonl"))
        assert source_provenance.validate(archived) == receipts[0]
    detached = tmp_path / "detached"
    sync_recovery.restore_detached(result["backup"], detached)
    with closing(sqlite3.connect(detached / "papers.db")) as conn:
        assert not conn.execute("SELECT 1 FROM sqlite_master WHERE name=?",
                                (local_source_owners.TABLE,)).fetchone()
        assert conn.execute("SELECT count(*) FROM recovery_records WHERE table_name=?",
                            (source_provenance.TABLE,)).fetchone()[0] == 1
        assert not conn.execute(
            "SELECT 1 FROM sqlite_master WHERE name='paperfact_sync_identity'"
        ).fetchone()
    assert local_source_owners.list_owned(database) == receipts
    assert hashlib.sha256(primary.read_bytes()).hexdigest() == current


@pytest.mark.parametrize("change", ["missing", "corrupt", "unknown-file", "unknown-table", "deck"])
def test_invalid_or_unmapped_closure_still_refuses_enrollment(imported, tmp_path, change):
    database, root, _current, _original, _body = imported
    primary = root / "pdf/ref_example.pdf"
    receipt = local_source_owners.list_owned(database)[0]
    source = source_snapshots.source_path(database, receipt)
    if change == "missing":
        source.unlink()
    elif change == "corrupt":
        source.write_bytes(b"%PDF-corrupted fixture")
    elif change == "unknown-file":
        (source.parent / "unowned.pdf").write_bytes(source.read_bytes())
    elif change == "unknown-table":
        with closing(sqlite3.connect(database)) as conn, conn:
            conn.execute("CREATE TABLE unknown_history(secret TEXT)")
            conn.execute("INSERT INTO unknown_history VALUES('not-droppable')")
    else:
        folder = root / "presentations"
        folder.mkdir()
        (folder / "unregistered.json").write_text('{"slides":[]}')
    service = EnrollmentService(database)
    try:
        report = service.plan(pdfs={"ref:example": primary})
    except ValueError:
        return
    assert not report["supported"]
    with pytest.raises(EnrollmentBlocked):
        prepare(database, tmp_path, pdfs={"ref:example": primary})


def test_owner_schema_is_optional_and_plan_never_creates_it(tmp_path):
    from paper_daily import store
    database = tmp_path / "empty.db"
    with closing(sqlite3.connect(database)) as conn:
        conn.executescript(store.SCHEMA)
        store._migrate(conn)
    assert EnrollmentService(database).plan()["supported"]
    with closing(sqlite3.connect(database)) as conn:
        assert not conn.execute("SELECT 1 FROM sqlite_master WHERE name=?",
                                (local_source_owners.TABLE,)).fetchone()


def test_nullable_imported_list_note_enrolls_without_coercion(imported, tmp_path):
    database, root, _current, _original, _body = imported
    with closing(sqlite3.connect(database)) as conn, conn:
        conn.execute("UPDATE lists SET note=NULL")
    result = prepare(database, tmp_path, pdfs={"ref:example": root / "pdf/ref_example.pdf"})
    with closing(sqlite3.connect(result["database"])) as conn:
        assert conn.execute("SELECT note FROM lists").fetchone()[0] is None
    assert len(local_source_owners.list_owned(database)) == 1


@pytest.mark.parametrize("change", ["cancel", "receipt", "bytes"])
def test_imported_source_cancel_or_changed_observation_publishes_nothing(
    imported, tmp_path, change
):
    from paper_daily.workspace_service import Cancelled, SnapshotChanged, Ticket

    database, root, _current, _original, _body = imported
    receipt = local_source_owners.list_owned(database)[0]
    selected = source_snapshots.source_path(database, receipt)
    original = selected.read_bytes()
    ticket = Ticket()
    changed = False

    def progress(message):
        nonlocal changed
        if changed or not message.startswith("Creating"):
            return
        changed = True
        if change == "cancel":
            ticket.cancel()
        elif change == "bytes":
            selected.write_bytes(b"%PDF-modified fixture")
        else:
            with closing(sqlite3.connect(database)) as conn, conn:
                value = json.loads(receipt["owner_json"])
                value["parent_lifecycle"] = "f" * 32
                conn.execute("UPDATE research_local_source_owners SET owner_json=?",
                             (json.dumps(value),))

    token = str(uuid4())
    output, backup = tmp_path / ("pending-" + token), tmp_path / (token + ".zip")
    with pytest.raises((Cancelled, SnapshotChanged, ValueError)):
        EnrollmentService(database).prepare(
            output, backup_output=backup, request_id=token,
            pdfs={"ref:example": root / "pdf/ref_example.pdf"},
            ticket=ticket, progress=progress,
        )
    assert changed and not output.exists() and not backup.exists()
    assert len(local_source_owners.list_owned(database)) == 1
    if change != "bytes":
        assert selected.read_bytes() == original
