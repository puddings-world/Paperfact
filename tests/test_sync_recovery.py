"""Independent recovery keeps complete research/history without active credentials."""

import hashlib
import json
import sqlite3
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest
from test_sync_operations import client, paper

from paper_daily import sync_recovery as recovery
from paper_daily.store import SCHEMA
from paper_daily.sync_blobs import BlobManifest, BlobStore
from paper_daily.sync_operations import ResearchOperations
from paper_daily.sync_service import ReferenceService


@pytest.fixture
def research(tmp_path):
    source = tmp_path / "source" / "papers.db"
    source.parent.mkdir()
    current = client(source, "origin-device")
    result = ResearchOperations(current).create_list(
        "Recovery route",
        [{"paper": paper(), "notes": ["Saved research"]}],
        request_id="original-intake",
    )
    with sqlite3.connect(source) as conn:
        paper_id = conn.execute("SELECT sync_id FROM research_paper_identity").fetchone()[0]
    return source, current, result, paper_id


def archive_rows(package, name):
    with zipfile.ZipFile(package) as archive:
        return [json.loads(line) for line in archive.read("tables/" + name + ".jsonl").splitlines()]


def blob(store, data):
    manifest = BlobManifest(hashlib.sha256(data).hexdigest(), len(data))
    store.begin(manifest)
    store.append(manifest, 0, data)
    store.finalize(manifest)
    return manifest


def rewrite(package, destination, mutate):
    with zipfile.ZipFile(package) as archive:
        files = {name: archive.read(name) for name in archive.namelist()}
    manifest = json.loads(files["manifest.json"])
    mutate(manifest, files)
    files["manifest.json"] = json.dumps(manifest).encode()
    with zipfile.ZipFile(destination, "w") as archive:
        for name, data in files.items():
            archive.writestr(name, data)
    return destination


def test_pending_research_round_trip_is_detached_and_source_is_untouched(research, tmp_path):
    source, current, result, _paper_id = research
    before = current.journal.pending()
    package = tmp_path / "backup.zip"
    manifest = recovery.create(source, package)
    assert recovery.inspect(package) == manifest
    restored = recovery.restore_detached(package, tmp_path / "restored")
    assert restored["detached"]
    assert current.journal.pending() == before
    assert archive_rows(package, "paperfact_sync_operations")[0][
        "envelope"
    ] == recovery.canonical_operation(before[0])
    with sqlite3.connect(tmp_path / "restored" / "papers.db") as conn:
        assert conn.execute("SELECT name FROM lists").fetchall() == [("Recovery route",)]
        assert conn.execute("SELECT body FROM notes").fetchall() == [("Saved research",)]
        assert conn.execute("SELECT id FROM lists").fetchone()[0] == result["list_id"]
        names = {row[0] for row in conn.execute("SELECT name FROM sqlite_master")}
        assert "paperfact_sync_identity" not in names
        assert "research_capture_binding" not in names
        assert "document_reader_paths" not in names
        origin, fresh = conn.execute(
            "SELECT origin_device,recovery_device FROM recovery_identity"
        ).fetchone()
        assert origin == "origin-device" and fresh != origin
        archived = conn.execute(
            "SELECT data FROM recovery_records WHERE table_name='paperfact_sync_operations' "
            "ORDER BY row_number"
        ).fetchall()
        assert len(archived) == len(before)


def test_excludes_credentials_unknown_kv_and_deleted_free_pages(research, tmp_path):
    source, _current, _result, _paper_id = research
    secret = "PRIVATE-CREDENTIAL-FIXTURE-" + "s" * 20000
    with sqlite3.connect(source) as conn:
        conn.execute("PRAGMA secure_delete=OFF")
        conn.execute("CREATE TABLE private_credentials(secret TEXT)")
        conn.execute("INSERT INTO private_credentials VALUES(?)", (secret,))
        conn.execute("INSERT INTO kv VALUES('api.secret',?)", (secret,))
        conn.execute("INSERT INTO kv VALUES('ui.private_location',?)", (secret,))
        conn.execute("INSERT INTO kv VALUES('lists.order','[]')")
        conn.commit()
        conn.execute("DELETE FROM private_credentials")
    package = tmp_path / "private.zip"
    recovery.create(source, package)
    with zipfile.ZipFile(package) as archive:
        contents = b"".join(archive.read(name) for name in archive.namelist())
        assert secret.encode() not in contents
        assert b"private_credentials" not in contents
    assert archive_rows(package, "kv") == [{"key": "lists.order", "value": "[]"}]


def test_retains_accepted_history_ack_gap_and_local_candidates(research, tmp_path):
    source, current, result, _paper_id = research
    service = ReferenceService(tmp_path / "server.db")
    token = service.enroll("workspace", "origin-device")
    current.sync_once(service, token)
    operation = current.new_graph_operation(
        "list", result["list_id"], {"name": "Not yet received", "note": ""}
    )
    current.save(operation)
    event = service.push(token, operation)
    current.journal.acknowledge(operation["operation_id"], event["sequence"])
    candidate = {"observations": [], "mutations": [{"after_json": "retained unsent content"}]}
    with sqlite3.connect(source) as conn:
        conn.execute(
            "CREATE TABLE research_capture_candidates(id TEXT PRIMARY KEY,content TEXT NOT NULL)"
        )
        conn.execute(
            "INSERT INTO research_capture_candidates VALUES('candidate',?)",
            (json.dumps(candidate),),
        )
    package = tmp_path / "history.zip"
    manifest = recovery.create(source, package)
    assert manifest["cursor"] < event["sequence"]
    rows = archive_rows(package, "paperfact_sync_operations")
    assert rows[-1]["server_revision"] == event["sequence"]
    assert archive_rows(package, "research_capture_candidates")[0]["content"] == json.dumps(
        candidate
    )
    assert len(archive_rows(package, "paperfact_sync_graph_receipts")) == manifest["cursor"]


def test_pdf_closure_contains_old_accepted_and_new_pending_bytes(research, tmp_path):
    source, current, _result, paper_id = research
    store = BlobStore(tmp_path / "owned")
    service = ReferenceService(tmp_path / "server.db", blob_root=tmp_path / "remote")
    token = service.enroll("workspace", "origin-device")
    current.sync_once(service, token)
    manifests = []
    for index in range(2):
        data = b"%PDF-1.7 fixture revision " + str(index).encode()
        declared = blob(store, data)
        manifests.append(declared)
        operation = current.new_graph_operation(
            "paper_document",
            paper_id,
            {
                "paper_id": paper_id,
                "sha256": declared.sha256,
                "size": declared.size,
                "media_type": "application/pdf",
            },
        )
        current.save(operation)
        if index == 0:
            upload = service.blob_begin(token, {"sha256": declared.sha256, "size": declared.size})
            service.blob_append(token, upload["upload_id"], 0, data)
            service.blob_commit(token, upload["upload_id"])
            current.sync_once(service, token)
    package = tmp_path / "with-files.zip"
    manifest = recovery.create(source, package, blob_store=store)
    assert {item["sha256"] for item in manifest["blobs"]} == {m.sha256 for m in manifests}
    recovery.restore_detached(package, tmp_path / "restored")
    for item in manifests:
        assert (
            hashlib.sha256(
                (tmp_path / "restored" / "objects" / item.sha256).read_bytes()
            ).hexdigest()
            == item.sha256
        )


def test_missing_pending_bytes_cannot_produce_complete_backup(research, tmp_path):
    source, current, _result, paper_id = research
    current.save(
        current.new_graph_operation(
            "paper_document",
            paper_id,
            {
                "paper_id": paper_id,
                "sha256": "a" * 64,
                "size": 123,
                "media_type": "application/pdf",
            },
        )
    )
    output = tmp_path / "missing.zip"
    with pytest.raises(recovery.RecoveryError, match="bytes require"):
        recovery.create(source, output)
    assert not output.exists()


@pytest.mark.parametrize(
    "folder", ["pdf", "presentations", "paper-highlights", "figures", "material-positions"]
)
def test_unclassified_legacy_research_fails_instead_of_silently_omitting(
    research, tmp_path, folder
):
    source, *_ = research
    path = source.parent / folder / "legacy.bin"
    path.parent.mkdir()
    path.write_bytes(b"legacy research must survive")
    with pytest.raises(recovery.RecoveryError, match="Legacy research files"):
        recovery.create(source, tmp_path / "incomplete.zip")
    assert path.read_bytes() == b"legacy research must survive"


def test_missing_historical_graph_receipt_is_rejected(research, tmp_path):
    source, current, *_ = research
    service = ReferenceService(tmp_path / "server.db")
    current.sync_once(service, service.enroll("workspace", "origin-device"))
    with sqlite3.connect(source) as conn:
        conn.execute(
            "DELETE FROM paperfact_sync_graph_receipts WHERE operation_id="
            "(SELECT operation_id FROM paperfact_sync_graph_receipts LIMIT 1)"
        )
    with pytest.raises(recovery.RecoveryError, match="receipt closure"):
        recovery.create(source, tmp_path / "bad.zip")


def test_unknown_research_schema_and_unflushed_capture_rejected(research, tmp_path):
    source, *_ = research
    with sqlite3.connect(source) as conn:
        conn.execute("CREATE TABLE research_unhandled(body TEXT)")
    with pytest.raises(recovery.RecoveryError, match="Unsupported research schema"):
        recovery.create(source, tmp_path / "unknown.zip")


@pytest.mark.parametrize(
    "change",
    [
        "traversal",
        "extra",
        "bad_hash",
        "missing_table",
        "cursor_gap",
        "duplicate_json",
        "wrong_columns",
    ],
)
def test_malformed_archive_never_activates_partial_directory(research, tmp_path, change):
    source, *_ = research
    package = tmp_path / "good.zip"
    recovery.create(source, package)

    def mutate(manifest, files):
        if change == "traversal":
            files["../escaped"] = b"unsafe"
        elif change == "extra":
            files["unknown.txt"] = b"unknown"
        elif change == "bad_hash":
            manifest["tables"][0]["sha256"] = "0" * 64
        elif change == "missing_table":
            table = next(item for item in manifest["tables"] if item["name"] == "notes")
            manifest["tables"].remove(table)
            del files["tables/notes.jsonl"]
        elif change == "cursor_gap":
            manifest["cursor"] = 100
        elif change == "duplicate_json":
            files["tables/notes.jsonl"] = b'{"id":1,"id":2}\n'
        else:
            manifest["tables"][0]["columns"].append("credential")

    damaged = rewrite(package, tmp_path / "damaged.zip", mutate)
    destination = tmp_path / "restore"
    with pytest.raises((ValueError, zipfile.BadZipFile)):
        recovery.restore_detached(damaged, destination)
    assert not destination.exists()
    assert not (tmp_path / "escaped").exists()


def test_existing_output_destination_and_source_sidecar_never_overwritten(research, tmp_path):
    source, *_ = research
    output = tmp_path / "existing.zip"
    output.write_bytes(b"preserve existing backup")
    with pytest.raises(recovery.RecoveryError):
        recovery.create(source, output)
    assert output.read_bytes() == b"preserve existing backup"
    with pytest.raises(recovery.RecoveryError):
        recovery.create(source, Path(str(source) + "-journal"))
    package = tmp_path / "good.zip"
    recovery.create(source, package)
    destination = tmp_path / "existing"
    destination.mkdir()
    (destination / "keep").write_text("original")
    with pytest.raises(recovery.RecoveryError):
        recovery.restore_detached(package, destination)
    assert (destination / "keep").read_text() == "original"


def test_sqlite_backup_includes_committed_wal_rows_without_source_mutation(tmp_path):
    source = tmp_path / "papers.db"
    with sqlite3.connect(source) as conn:
        conn.executescript(SCHEMA)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("INSERT INTO lists VALUES('wal','Only in WAL','','2026-10-26')")
        conn.commit()
        package = tmp_path / "wal.zip"
        recovery.create(source, package)
        assert archive_rows(package, "lists")[0]["name"] == "Only in WAL"
        assert conn.execute("SELECT name FROM lists").fetchone()[0] == "Only in WAL"


def test_module_cli_runs_create_inspect_restore_without_network(research, tmp_path):
    source, *_ = research
    package = tmp_path / "cli.zip"
    for args in (
        ["create", str(source), str(package)],
        ["inspect", str(package)],
        ["restore-detached", str(package), str(tmp_path / "cli-restored")],
    ):
        completed = subprocess.run(
            [sys.executable, "-m", "paper_daily.sync_recovery", *args],
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert completed.returncode == 0, completed.stderr
        assert isinstance(json.loads(completed.stdout), dict)
    assert (tmp_path / "cli-restored" / "papers.db").is_file()


def test_actual_initialized_schema_round_trip(tmp_path, monkeypatch):
    from paper_daily import store

    source = tmp_path / "papers.db"
    monkeypatch.setattr(store, "DB_PATH", source)
    monkeypatch.setattr(store, "ensure_dirs", lambda: None)
    store.init_db()
    with store.connect() as conn:
        conn.execute("INSERT INTO lists VALUES('live','Actual init','','2026-10-26')")
    package = tmp_path / "actual.zip"
    recovery.create(source, package)
    recovery.restore_detached(package, tmp_path / "restored")
    with sqlite3.connect(tmp_path / "restored" / "papers.db") as conn:
        assert conn.execute("SELECT name FROM lists").fetchone()[0] == "Actual init"
        assert {r[1] for r in conn.execute("PRAGMA table_info(notes)")} >= {
            "anchor",
            "page",
            "kind",
        }


def test_package_swapped_after_inspection_cannot_restore_changed_rows(
    research, tmp_path, monkeypatch
):
    source, *_ = research
    package = tmp_path / "backup.zip"
    recovery.create(source, package)
    original = recovery.inspect

    def swap(path):
        manifest = original(path)

        def change(_manifest, files):
            files["tables/notes.jsonl"] = files["tables/notes.jsonl"].replace(
                b"Saved research", b"Wrong research"
            )

        rewritten = rewrite(path, tmp_path / "replacement.zip", change)
        path.write_bytes(rewritten.read_bytes())
        return manifest

    monkeypatch.setattr(recovery, "inspect", swap)
    with pytest.raises(recovery.RecoveryError, match="integrity"):
        recovery.restore_detached(package, tmp_path / "restored")
    assert not (tmp_path / "restored").exists()


def test_applied_pdf_restore_remains_readable_when_new_desired_is_pending(research, tmp_path):
    from paper_daily.document_reader import from_workspace

    source, current, _result, portable = research
    owned = BlobStore(tmp_path / "owned")
    import pymupdf

    with pymupdf.open() as document:
        document.new_page().insert_text((40, 50), "Original viewed version")
        old_bytes = document.tobytes()
    with pymupdf.open() as document:
        document.new_page().insert_text((40, 50), "Incoming replacement")
        new_bytes = document.tobytes()
    old = blob(owned, old_bytes)
    new = blob(owned, new_bytes)
    for index, item in enumerate((old, new)):
        current.save(
            current.new_graph_operation(
                "paper_document",
                portable,
                {
                    "paper_id": portable,
                    "sha256": item.sha256,
                    "size": item.size,
                    "media_type": "application/pdf",
                },
            )
        )
        if index == 0:
            with sqlite3.connect(source) as conn:
                target = conn.execute("SELECT target FROM research_document_desired").fetchone()[0]
                conn.execute(
                    "INSERT INTO research_document_applied VALUES(?,?)", (portable, target)
                )
                local = conn.execute("SELECT local_id FROM research_paper_identity").fetchone()[0]
    package = tmp_path / "pdf.zip"
    recovery.create(source, package, blob_store=owned)
    destination = tmp_path / "readable"
    recovery.restore_detached(package, destination)
    document = from_workspace(destination / "papers.db", legacy_root=destination / "pdf").resolve(
        local
    )
    assert document.available
    assert document.sha256 == old.sha256
    assert document.path.read_bytes() == old_bytes
    assert (destination / "objects" / new.sha256).is_file()
    current.save(current.new_graph_operation("paper_document", portable, {}, action="delete"))
    deleted_package = tmp_path / "retired.zip"
    recovery.create(source, deleted_package, blob_store=owned)
    recovery.restore_detached(deleted_package, tmp_path / "retired")
    assert not (tmp_path / "retired" / "pdf").exists()
    assert (tmp_path / "retired" / "objects" / old.sha256).is_file()


def test_generation_database_and_sidecar_candidates_are_archived_as_provenance(research, tmp_path):
    from contextlib import closing

    from paper_daily import research_generation as generation

    source, _current, _result, _portable = research
    with closing(generation._connect(source)) as conn:
        local = conn.execute("SELECT id FROM papers").fetchone()[0]
        context = generation.begin_generation(
            conn,
            table="close_readings",
            owner_id=local,
            input_reader="target",
            request_id="generation",
        )
    output = {
        "paper_id": local,
        "body": "Preserved output",
        "spec": "fixture",
        "written_at": "2026-10-26T00:00:00+00:00",
    }
    generation._retain_outside_database(context, output, "Original database replaced")
    package = tmp_path / "candidate.zip"
    recovery.create(source, package)
    rows = archive_rows(package, "research_generation_recovery")
    assert len(rows) == 1
    assert json.loads(rows[0]["row_json"])["body"] == "Preserved output"
    recovery.restore_detached(package, tmp_path / "restored")
    with sqlite3.connect(tmp_path / "restored" / "papers.db") as conn:
        archived = conn.execute(
            "SELECT data FROM recovery_records WHERE table_name=?",
            ("research_generation_recovery",),
        ).fetchone()[0]
        assert json.loads(archived)["request_id"] == "generation"
    assert not (tmp_path / "restored" / ".paperfact-generation").exists()


def test_research_file_history_candidates_and_applied_editable_deck(
    research, tmp_path, monkeypatch
):
    from test_sync_files import INPUTS, deck, png

    from paper_daily import presentations
    from paper_daily.sync_deck_files import encode_deck
    from paper_daily.sync_files import file_id

    source, current, _result, portable = research
    monkeypatch.setattr(
        presentations,
        "figure_bytes",
        lambda _deck, key: png("red" if key == "figure:1" else "blue"),
    )
    value = presentations.deck_from_dict(deck().to_dict())
    payload, objects = encode_deck(value, portable, input_versions=INPUTS)
    owned = BlobStore(tmp_path / "owned")
    for data in objects.values():
        blob(owned, data)
    identity = file_id(portable, "deck", "guide")
    operation = current.new_graph_operation("research_file", identity, payload)
    current.save(operation)
    with sqlite3.connect(source) as conn:
        conn.execute(
            "INSERT INTO research_file_applied VALUES(?,?)",
            (identity, recovery.canonical_operation(operation)),
        )
        local = conn.execute("SELECT local_id FROM research_paper_identity").fetchone()[0]
        draft = value.to_dict()
        assets = {asset["id"]: asset for asset in payload["assets"]}
        for figure, asset in zip(draft["figures"], assets.values(), strict=True):
            figure["asset"] = asset["sha256"] + ".png"
        draft["slides"][0]["speaker_notes"] = "Unsent edited draft"
        observation = {"workspace_id": "workspace", "entity_id": identity, "artifact": operation}
        conn.execute(
            "INSERT INTO research_file_drafts VALUES(?,?,?,?)",
            ("draft", identity, json.dumps(draft), json.dumps(observation)),
        )
        conn.execute(
            "INSERT INTO research_file_candidates VALUES(?,?,?,?)",
            ("candidate", identity, json.dumps(payload), json.dumps(observation)),
        )
    package = tmp_path / "deck.zip"
    manifest = recovery.create(source, package, blob_store=owned)
    assert {r["sha256"] for r in manifest["blobs"]} == set(objects)
    assert (
        json.loads(archive_rows(package, "research_file_drafts")[0]["deck"])["slides"][0][
            "speaker_notes"
        ]
        == "Unsent edited draft"
    )
    assert len(archive_rows(package, "research_file_candidates")) == 1
    destination = tmp_path / "restored"
    recovery.restore_detached(package, destination)
    folder = destination / "presentations" / hashlib.sha256(local.encode()).hexdigest()[:24]
    restored = presentations.deck_from_dict(
        json.loads((folder / "guide.json").read_text(encoding="utf-8"))
    )
    assert restored.paper_id == local
    assert restored.slides[0].speaker_notes == value.slides[0].speaker_notes
    assert restored.slides[0].elements == value.slides[0].elements
    monkeypatch.setattr(presentations, "DECK_DIR", destination / "presentations")
    assert (folder / "assets" / restored.figures[0]["asset"]).read_bytes() == png("red")


def test_detached_reexport_cannot_silently_drop_archived_pending_work(research, tmp_path):
    source, *_ = research
    package = tmp_path / "original.zip"
    recovery.create(source, package)
    recovery.restore_detached(package, tmp_path / "restored")
    with pytest.raises(recovery.RecoveryError, match="detached re-export"):
        recovery.create(tmp_path / "restored" / "papers.db", tmp_path / "lossy.zip")
    assert not (tmp_path / "lossy.zip").exists()


def test_unpinned_deck_draft_assets_block_complete_backup(research, tmp_path):
    from test_sync_files import deck

    from paper_daily.sync_files import file_id

    source, _current, _result, portable = research
    identity = file_id(portable, "deck", "guide")
    observation = {"workspace_id": "workspace", "entity_id": identity, "artifact": None}
    with sqlite3.connect(source) as conn:
        conn.execute(
            "INSERT INTO research_file_drafts VALUES(?,?,?,?)",
            ("draft", identity, json.dumps(deck().to_dict()), json.dumps(observation)),
        )
    with pytest.raises(recovery.RecoveryError, match="unpinned"):
        recovery.create(source, tmp_path / "incomplete.zip")
    assert not (tmp_path / "incomplete.zip").exists()


def test_corrupt_historical_bytes_leave_requested_backup_absent(research, tmp_path):
    source, current, _result, paper_id = research
    owned = BlobStore(tmp_path / "owned")
    item = blob(owned, b"immutable owned bytes")
    current.save(
        current.new_graph_operation(
            "paper_document",
            paper_id,
            {
                "paper_id": paper_id,
                "sha256": item.sha256,
                "size": item.size,
                "media_type": "application/pdf",
            },
        )
    )
    owned._path(item).write_bytes(b"X" * item.size)
    with pytest.raises(ValueError):
        recovery.create(source, tmp_path / "corrupt.zip", blob_store=owned)
    assert not (tmp_path / "corrupt.zip").exists()


def test_restore_destination_created_at_publication_is_preserved(research, tmp_path, monkeypatch):
    source, *_ = research
    package = tmp_path / "backup.zip"
    recovery.create(source, package)
    original = recovery.publish_directory
    destination = tmp_path / "restored"

    def race(stage, target):
        target.mkdir()
        return original(stage, target)

    monkeypatch.setattr(recovery, "publish_directory", race)
    with pytest.raises(FileExistsError):
        recovery.restore_detached(package, destination)
    assert destination.is_dir() and list(destination.iterdir()) == []
    assert package.is_file()
    assert not list(tmp_path.glob(".paperfact-restore-*"))
