"""Actual enrolled package imports retain source bytes and typed research."""

import hashlib
import json
import sqlite3
import zipfile
from contextlib import closing

import pytest
from test_research_generation import pdf
from test_sync_files import LOCAL, deck, drain, paper_payload, png
from test_sync_files import codec as codec
from test_sync_files import pair as pair

from paper_daily import bundle, store
from paper_daily.document_reader import from_workspace
from paper_daily.package_import import PackageImporter
from paper_daily.sync_artifacts import applied_file
from paper_daily.sync_capture import CaptureConnection, install
from paper_daily.sync_files import file_id
from paper_daily.sync_source_files import resolved

STAMP = "2026-10-30T00:00:00+00:00"


def enroll_capture(client):
    with closing(sqlite3.connect(client.journal.path, factory=CaptureConnection)) as conn:
        conn.execute("BEGIN IMMEDIATE")
        install(conn, workspace_id=client.journal.workspace_id, device_id=client.journal.device_id)
        conn.commit()


@pytest.fixture
def package(tmp_path, monkeypatch):
    root = tmp_path / "sharer"
    root.mkdir()
    database = root / "papers.sqlite"
    monkeypatch.setattr(store, "DB_PATH", database)
    monkeypatch.setattr(bundle, "DATA_DIR", root)
    monkeypatch.setattr(bundle, "PDF_DIR", root / "pdf")
    store.init_db()
    with store.connect() as conn:
        store.upsert_papers(
            conn,
            [
                dict(
                    id="ref:example",
                    title="Original paper",
                    venue="Fixture",
                    year=2026,
                    source="fixture",
                    doi="10.0000/example",
                    page_url="https://example.org/paper",
                    pdf_url="https://example.org/original.pdf",
                )
            ],
        )
        conn.execute(
            "INSERT INTO lists(id,name,created_at) VALUES(?,?,?)", ("reading", "Reading", STAMP)
        )
        conn.execute(
            "INSERT INTO list_papers(list_id,paper_id,position,added_at) VALUES(?,?,?,?)",
            ("reading", "ref:example", 0, STAMP),
        )
        conn.execute(
            "INSERT INTO dives(paper_id,body,written_at) VALUES(?,?,?)",
            ("ref:example", "Complete original explanation", STAMP),
        )
        conn.execute(
            "INSERT INTO close_readings(paper_id,body,written_at) VALUES(?,?,?)",
            ("ref:example", "Complete close reading", STAMP),
        )
        conn.execute(
            "INSERT INTO notes(paper_id,body,kind,created_at) VALUES(?,?,?,?)",
            ("ref:example", "Personal note", "note", STAMP),
        )
    (root / "pdf").mkdir()
    pdf(root / "pdf/ref_example.pdf", "The original experiment supports a bounded result.")
    out = tmp_path / "research.zip"
    bundle.export("reading", out)
    return out, hashlib.sha256((root / "pdf/ref_example.pdf").read_bytes()).hexdigest()


def test_actual_shared_entry_imports_new_managed_paper_instead_of_filtering_its_analysis(
    package,
    pair,
    tmp_path,
    monkeypatch,
):
    archive, digest = package
    _server, a, _b, fa, _fb, _ta, _tb = pair
    enroll_capture(a)
    root = tmp_path / "destination"
    root.mkdir()
    monkeypatch.setattr(store, "DB_PATH", a.journal.path)
    monkeypatch.setattr(bundle, "DATA_DIR", root)
    monkeypatch.setattr(bundle, "PDF_DIR", root / "pdf")
    report = bundle.import_(archive, pdfs=False)
    assert report["papers"] == report["dives"] == report["notes"] == 1
    mapping = report["identity_mapping"]["ref:example"]
    reader = from_workspace(a.journal.path, legacy_root=root / "pdf")
    original = reader.resolve(mapping["local_id"])
    assert original.available and original.sha256 == digest
    with a.journal.transaction() as conn:
        assert (
            conn.execute(
                "SELECT body FROM dives WHERE paper_id=?", (mapping["local_id"],)
            ).fetchone()[0]
            == "Complete original explanation"
        )
        assert (
            conn.execute(
                "SELECT body FROM notes WHERE paper_id=?", (mapping["local_id"],)
            ).fetchone()[0]
            == "Personal note"
        )
        row = conn.execute(
            "SELECT page_url,pdf_url FROM papers WHERE id=?", (mapping["local_id"],)
        ).fetchone()
        assert tuple(row) == ("https://example.org/paper", "https://example.org/original.pdf")
        assert (
            resolved(conn, mapping["portable_id"], digest).read_bytes()
            == original.path.read_bytes()
        )
        assert applied_file(conn, file_id(mapping["portable_id"], "original_source", digest))
    before = a.journal.pending()
    again = bundle.import_(archive, pdfs=False)
    assert again["replayed"] is True and again["identity_mapping"] == report["identity_mapping"]
    assert a.journal.pending() == before


def test_prepared_import_rolls_back_roots_research_outbox_and_file_ownership(
    package, pair, tmp_path, monkeypatch
):
    archive, _digest = package
    _server, a, _b, _fa, _fb, _ta, _tb = pair
    enroll_capture(a)
    root = tmp_path / "rollback"
    root.mkdir()
    importer = PackageImporter(a.journal.path, root)
    prepared = importer.prepare(archive)
    before = a.journal.pending()
    original = a.journal.apply_in
    calls = []

    def fail(conn, operation, writer):
        result = original(conn, operation, writer)
        calls.append(operation)
        if len(calls) == 3:
            raise OSError("fixture disk failure")
        return result

    monkeypatch.setattr(a.journal, "apply_in", fail)
    # The service captures its own client, so patch that exact transaction owner.
    monkeypatch.setattr(importer.client.journal, "apply_in", fail)
    with pytest.raises(OSError):
        importer.apply(prepared)
    assert a.journal.pending() == before
    with a.journal.transaction() as conn:
        assert conn.execute("SELECT COUNT(*) FROM lists").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM dives").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM research_document_applied").fetchone()[0] == 0


@pytest.fixture
def rich_package(package, tmp_path):
    from paper_daily import claim_content, research_evidence

    archive, original_hash = package
    source_root = tmp_path / "sharer"
    document = from_workspace(
        source_root / "papers.sqlite", legacy_root=source_root / "pdf"
    ).resolve("ref:example")
    snapshot = research_evidence.capture(document)
    proposals = {
        "format": research_evidence.FORMAT,
        "source": {"paper_id": "ref:example", "document_hash": original_hash},
        "claims": [
            {
                "text": "The experiment supports a bounded result.",
                "judgment": {"status": "unresolved", "reason": "Check design assumptions."},
                "passages": [
                    {
                        "quote": "The original experiment supports a bounded result.",
                        "page": 1,
                        "anchor": None,
                    }
                ],
            }
        ],
    }
    body = {
        "format": claim_content.FORMAT,
        "recipe": claim_content.RECIPE,
        "inputs": {"dive": "1" * 64, "close_reading": "2" * 64},
        "generation": {
            "task": "claims",
            "backend": "fixture",
            "requested_model": None,
            "returned_model": None,
        },
        "report": research_evidence.verify_snapshot(snapshot, proposals),
    }
    with zipfile.ZipFile(archive) as z:
        values = {name: z.read(name) for name in z.namelist()}
    manifest = json.loads(values["manifest.json"])
    tables = json.loads(values["tables.json"])
    tables["paper_claim_sets"] = [
        {
            "paper_id": "ref:example",
            "body_json": json.dumps(body),
            "source_hash": claim_content.source_digest(body["inputs"], original_hash),
            "document_hash": original_hash,
            "written_at": STAMP,
        }
    ]
    tables["paper_annotation_known"] = [{"feature": "claims", "paper_id": "ref:example"}]
    claim_path = bundle._claim_source_relative("ref:example", original_hash).as_posix()
    values["files/" + claim_path] = document.path.read_bytes()
    manifest["claim_sources"] = {"ref:example": {"sha256": original_hash, "path": claim_path}}
    manifest["format"] = 2
    manifest["capabilities"] = bundle._required_capabilities(tables)
    value = deck()
    value.paper_id = "ref:example"
    value.sources[0]["document_hash"] = original_hash
    folder = "presentations/" + bundle._digest("ref:example")[:24]
    values["files/" + folder + "/guide.json"] = json.dumps(value.to_dict()).encode()
    values["files/figures/ref_example/a.png"] = png("red")
    values["files/figures/ref_example/b.png"] = png("blue")
    newer = tmp_path / "newer.pdf"
    pdf(newer, "A revised original introduces a different experiment.")
    current = newer.read_bytes()
    values["files/pdf/ref_example.pdf"] = current
    current_hash = hashlib.sha256(current).hexdigest()
    manifest["pdfs"]["ref:example"] = {"sha256": current_hash, "bytes": len(current), "url": None}
    manifest["file_hashes"] = {
        name.removeprefix("files/"): hashlib.sha256(data).hexdigest()
        for name, data in values.items()
        if name.startswith("files/")
    }
    manifest["counts"] = {key: len(rows) for key, rows in tables.items()} | {
        "files": len(manifest["file_hashes"])
    }
    values["manifest.json"] = json.dumps(manifest).encode()
    values["tables.json"] = json.dumps(tables).encode()
    result = tmp_path / "rich-research.zip"
    with zipfile.ZipFile(result, "w") as z:
        for name, data in values.items():
            z.writestr(name, data)
    return result, current_hash, original_hash, body


def test_actual_two_device_closure_and_missing_receipt_retry_preserve_newer_note(
    rich_package,
    pair,
    tmp_path,
    monkeypatch,
):
    from paper_daily import presentations
    from paper_daily.sync_deck_publication import load_managed_deck
    from paper_daily.sync_transfers import DocumentTransfers

    archive, current_hash, claim_hash, claim_body = rich_package
    server, a, b, fa, fb, ta, tb = pair
    enroll_capture(a)
    root_a = tmp_path / "import-a"
    root_b = tmp_path / "import-b"
    root_a.mkdir()
    root_b.mkdir()
    figure_reader = presentations.figure_bytes
    monkeypatch.setattr(
        presentations,
        "figure_bytes",
        lambda value, key: (
            value._revision_figures[key]
            if getattr(value, "_revision_figures", None) is not None
            else figure_reader(value, key)
        ),
    )
    importer = PackageImporter(a.journal.path, root_a)
    prepared = importer.prepare(archive)
    report = importer.apply(prepared)
    identity = report["identity_mapping"]["ref:example"]
    assert report["decks"] == report["paper_claim_sets"] == 1
    da = DocumentTransfers(
        a,
        fa.store,
        server,
        origin="https://fixture.invalid",
        token=ta,
        reader_root=root_a / ".package-reader",
        legacy_root=root_a / "pdf",
    )
    db = DocumentTransfers(
        b,
        fb.store,
        server,
        origin="https://fixture.invalid",
        token=tb,
        reader_root=root_b / ".package-reader",
        legacy_root=root_b / "pdf",
    )
    with a.journal.transaction() as conn:
        file_operations = [
            json.loads(row[0])
            for row in conn.execute("SELECT operation FROM research_file_desired WHERE active=1")
        ]

    def prepare_push(operation):
        if operation["entity_type"] == "paper_document":
            drain(lambda: da.upload(operation), "uploaded")
        elif operation["entity_type"] == "research_file":
            drain(lambda: fa.upload(operation), "uploaded")
        return True

    a.sync_once(server, ta, prepare_push=prepare_push)
    b.sync_once(server, tb)
    drain(lambda: db.download(identity["portable_id"]), "bound")
    for operation in file_operations:
        drain(lambda operation=operation: fb.download(operation["entity_id"]), "bound")
    with b.journal.transaction() as conn:
        local = conn.execute(
            "SELECT local_id FROM research_paper_identity WHERE sync_id=?",
            (identity["portable_id"],),
        ).fetchone()[0]
        assert (
            conn.execute("SELECT body FROM dives WHERE paper_id=?", (local,)).fetchone()[0]
            == "Complete original explanation"
        )
        actual = json.loads(
            conn.execute(
                "SELECT body_json FROM paper_claim_sets WHERE paper_id=?", (local,)
            ).fetchone()[0]
        )
        assert actual == claim_body
        assert (
            hashlib.sha256(
                resolved(conn, identity["portable_id"], claim_hash).read_bytes()
            ).hexdigest()
            == claim_hash
        )
        assert (
            hashlib.sha256(
                resolved(conn, identity["portable_id"], current_hash).read_bytes()
            ).hexdigest()
            == current_hash
        )
        assert tuple(
            conn.execute("SELECT page_url,pdf_url FROM papers WHERE id=?", (local,)).fetchone()
        ) == ("https://example.org/paper", "https://example.org/original.pdf")
        note_id = conn.execute(
            "SELECT sync_id FROM research_note_identity WHERE local_id="
            "(SELECT id FROM notes WHERE paper_id=?)",
            (local,),
        ).fetchone()[0]
        note = json.loads(
            conn.execute(
                "SELECT operation FROM paperfact_sync_heads "
                "WHERE entity_type='note' AND entity_id=?",
                (note_id,),
            ).fetchone()[0]
        )
        assert not conn.execute(
            "SELECT 1 FROM sqlite_master WHERE name='package_import_receipts'"
        ).fetchone()
    reader = from_workspace(b.journal.path, legacy_root=root_b / "pdf")
    assert reader.resolve(local).sha256 == current_hash
    monkeypatch.setattr(store, "DB_PATH", b.journal.path)
    managed, restored_deck = load_managed_deck(local, "guide")
    assert managed and restored_deck.slides[0].speaker_notes == "Speaker explanation"
    assert len(restored_deck.slides[0].elements) == 3
    assert presentations.figure_bytes(restored_deck, "figure:1") == png("red")
    assert presentations.figure_bytes(restored_deck, "figure:2") == png("blue")
    edited = b.new_graph_operation("note", note_id, {**note["payload"], "body": "Newer peer note"})
    b.save(edited)
    enroll_capture(b)
    pending = b.journal.pending()
    second = PackageImporter(b.journal.path, root_b)
    replay = second.apply(second.prepare(archive))
    assert replay["notes"] == 0
    assert b.journal.pending() == pending
    with b.journal.transaction() as conn:
        assert (
            conn.execute("SELECT body FROM notes WHERE paper_id=?", (local,)).fetchone()[0]
            == "Newer peer note"
        )
        assert conn.execute("SELECT COUNT(*) FROM lists").fetchone()[0] == 1


def rewrite_package(archive, destination, *, transform=None, extra_files=None):
    """Fixture archive edit keeps the ordinary archive integrity checks active."""
    with zipfile.ZipFile(archive) as z:
        values = {name: z.read(name) for name in z.namelist()}
    manifest = json.loads(values["manifest.json"])
    tables = json.loads(values["tables.json"])
    if transform:
        transform(manifest, tables, values)
    for name, value in (extra_files or {}).items():
        values["files/" + name] = value
    manifest["file_hashes"] = {
        name.removeprefix("files/"): hashlib.sha256(value).hexdigest()
        for name, value in values.items()
        if name.startswith("files/")
    }
    required = bundle._required_capabilities(tables)
    manifest["format"] = 2 if required else bundle.FORMAT
    manifest["capabilities"] = required
    manifest["counts"] = {name: len(rows) for name, rows in tables.items()}
    values["manifest.json"] = json.dumps(manifest).encode()
    values["tables.json"] = json.dumps(tables).encode()
    with zipfile.ZipFile(destination, "w") as z:
        for name, value in values.items():
            z.writestr(name, value)
    return destination


def empty_research(client):
    with client.journal.transaction() as conn:
        assert conn.execute("SELECT COUNT(*) FROM lists").fetchone()[0] == 0
        assert [row[0] for row in conn.execute("SELECT id FROM papers")] == [LOCAL]
        for name in (
            "research_document_applied",
            "research_file_applied",
            "package_import_receipts",
        ):
            if conn.execute("SELECT 1 FROM sqlite_master WHERE name=?", (name,)).fetchone():
                assert conn.execute("SELECT COUNT(*) FROM " + name).fetchone()[0] == 0
    assert client.journal.pending() == []


@pytest.fixture
def importer(pair, tmp_path):
    _server, a, _b, _fa, _fb, _ta, _tb = pair
    enroll_capture(a)
    root = tmp_path / "importer"
    root.mkdir()
    return PackageImporter(a.journal.path, root), a


def test_failure_then_same_request_retry_publishes_once(package, importer, monkeypatch):
    service, client = importer
    original = service.client.journal.apply_in
    count = 0

    def fail(conn, operation, writer):
        nonlocal count
        value = original(conn, operation, writer)
        count += 1
        if count == 4:
            raise OSError("fixture disk full")
        return value

    monkeypatch.setattr(service.client.journal, "apply_in", fail)
    with pytest.raises(OSError, match="disk full"):
        service.apply(service.prepare(package[0], request_id="retry-action"))
    empty_research(client)
    monkeypatch.setattr(service.client.journal, "apply_in", original)
    applied = service.apply(service.prepare(package[0], request_id="retry-action"))
    pending = client.journal.pending()
    replay = service.apply(service.prepare(package[0], request_id="retry-action"))
    assert applied["papers"] == 1 and replay["replayed"]
    assert client.journal.pending() == pending
    assert not list(service.root.glob(".package-import-*"))


@pytest.mark.parametrize("when", ["prepare", "before_apply", "during_apply", "before_commit"])
def test_cancel_never_publishes_partial_import(package, importer, monkeypatch, when):
    from paper_daily.workspace_service import Cancelled, Ticket

    service, client = importer
    ticket = Ticket()
    if when == "prepare":
        ticket.cancel()
        with pytest.raises(Cancelled):
            service.prepare(package[0], ticket=ticket)
    else:
        prepared = service.prepare(package[0], ticket=ticket)
        if when == "before_apply":
            ticket.cancel()
        elif when == "before_commit":
            publish = ticket.publish

            def cancel_before_publish(action):
                ticket.cancel()
                publish(action)

            monkeypatch.setattr(ticket, "publish", cancel_before_publish)
        else:
            original = service.client.journal.apply_in

            def cancel_after_write(conn, operation, writer):
                result = original(conn, operation, writer)
                ticket.cancel()
                return result

            monkeypatch.setattr(service.client.journal, "apply_in", cancel_after_write)
        with pytest.raises(Cancelled):
            service.apply(prepared, ticket=ticket)
    assert not ticket.published
    empty_research(client)
    assert not list(service.root.glob(".package-import-*"))


@pytest.mark.parametrize(
    "change", ["archive", "source", "workspace", "binding", "target", "namespace"]
)
def test_prepared_import_rejects_changed_scope_without_overwriting(
    package, importer, monkeypatch, change
):
    from uuid import uuid4

    def new_uuid():
        return str(uuid4())

    service, client = importer
    prepared = service.prepare(package[0])
    if change == "archive":
        with package[0].open("ab") as out:
            out.write(b"changed")
    elif change == "source":
        staged = prepared.originals[0][0]
        selected, _identity = staged.proof.files[package[1]]
        selected.write_bytes(b"corrupt fixture bytes")
    elif change == "workspace":
        monkeypatch.setattr(
            service, "current_path", lambda: service.database.with_name("other.sqlite")
        )
    elif change == "binding":
        with client.journal.transaction() as conn:
            conn.execute("UPDATE research_capture_binding SET device=?", (new_uuid(),))
    elif change == "target":
        planned = json.loads(prepared.operations)[0]
        client.save(
            client.new_graph_operation(
                "paper",
                planned["entity_id"],
                {**planned["payload"], "title": "Newer independent research"},
            )
        )
    else:
        client.save(
            client.new_graph_operation("list", new_uuid(), {"name": "Other list", "note": ""})
        )
    pending = client.journal.pending()
    with pytest.raises((ValueError, OSError)):
        service.apply(prepared)
    assert client.journal.pending() == pending
    with client.journal.transaction() as conn:
        assert conn.execute("SELECT COUNT(*) FROM dives").fetchone()[0] == 0
        assert not conn.execute(
            "SELECT 1 FROM sqlite_master WHERE name='package_import_receipts'"
        ).fetchone()


@pytest.mark.parametrize(
    "scope",
    [
        "kv",
        "unknown_table",
        "unknown_field",
        "legacy_module",
        "cache",
        "positions",
        "link_only",
        "annotation_deletion",
    ],
)
def test_unsupported_scope_is_explicit_and_preserves_workspace(package, importer, tmp_path, scope):
    from paper_daily.package_import import UnsupportedPackage

    service, client = importer
    extra = {}

    def transform(manifest, tables, values):
        if scope == "kv":
            tables["kv"] = [{"key": "resources:ref:example", "value": "research"}]
        elif scope == "unknown_table":
            tables["future_research"] = [{"body": "must not be lost"}]
        elif scope == "unknown_field":
            tables["dives"][0]["future_evidence"] = "must not be lost"
        elif scope == "legacy_module":
            tables["papers"][0]["award"] = "best paper"
        elif scope == "link_only":
            manifest["pdfs_included"] = False
            values.pop("files/pdf/ref_example.pdf")
        elif scope == "annotation_deletion":
            tables["paper_annotation_known"] = [
                {"feature": "research_questions", "paper_id": "ref:example"}
            ]

    if scope in {"cache", "positions"}:
        folder = "research-questions" if scope == "cache" else "material-positions"
        extra[folder + "/" + bundle._digest("ref:example") + ".json"] = (
            b'{"content":"must not be lost"}'
        )
    archive = rewrite_package(
        package[0], tmp_path / "unsupported.zip", transform=transform, extra_files=extra
    )
    with pytest.raises(UnsupportedPackage):
        service.prepare(archive)
    empty_research(client)


def test_empty_list_is_valid_and_has_no_pdf_or_ai_jobs(package, importer, tmp_path):
    service, client = importer

    def empty(manifest, tables, values):
        for name in tables:
            tables[name] = []
        manifest["members"] = []
        manifest["pdfs"] = {}
        for name in list(values):
            if name.startswith("files/"):
                del values[name]

    archive = rewrite_package(package[0], tmp_path / "empty.zip", transform=empty)
    report = service.apply(service.prepare(archive))
    assert report["papers"] == report["files"] == report["notes"] == 0
    with client.journal.transaction() as conn:
        assert conn.execute("SELECT name FROM lists").fetchone()[0] == "Reading"
        assert [row[0] for row in conn.execute("SELECT id FROM papers")] == [LOCAL]
    assert {op["entity_type"] for op in client.journal.pending()} <= {"list", "list_order"}


def test_duplicate_entry_is_rejected_and_request_reuse_requires_same_action(package, importer):
    from paper_daily.package_import import import_package
    from paper_daily.research_job_lock import claim

    service, client = importer
    owner = hashlib.sha256(str(package[0].resolve()).encode()).hexdigest()
    with claim(service.database, "package-import", owner) as acquired:
        assert acquired
        with pytest.raises(ValueError, match="already in progress"):
            import_package(service.database, service.root, package[0])
    report = service.apply(service.prepare(package[0], request_id="same-action"))
    pending = client.journal.pending()
    with pytest.raises(ValueError, match="reused"):
        service.prepare(package[0], request_id="same-action", replace=True)
    assert report["papers"] == 1 and client.journal.pending() == pending


def test_confirmed_mapping_preserves_existing_wrong_pdf_and_its_research(
    package, importer, tmp_path
):
    service, client = importer
    report = service.apply(service.prepare(package[0]))
    identity = report["identity_mapping"]["ref:example"]
    original = from_workspace(client.journal.path).resolve(identity["local_id"])
    original_bytes = original.path.read_bytes()
    revised = tmp_path / "revision.pdf"
    pdf(revised, "This revised PDF must not overwrite the managed original.")

    def changed(manifest, tables, values):
        values["files/pdf/ref_example.pdf"] = revised.read_bytes()
        manifest["pdfs"]["ref:example"]["sha256"] = hashlib.sha256(revised.read_bytes()).hexdigest()
        manifest["pdfs"]["ref:example"]["bytes"] = revised.stat().st_size
        tables["dives"][0]["body"] = "Wrong-source replacement explanation"
        tables["notes"][0]["body"] = "Wrong-source replacement note"

    archive = rewrite_package(package[0], tmp_path / "revised.zip", transform=changed)
    with pytest.raises(ValueError, match="reviewed destination"):
        service.prepare(archive)
    options = dict(
        target_list_id=report["list"], paper_mapping={"ref:example": identity["local_id"]}
    )
    with pytest.raises(ValueError, match="confirmed mapping"):
        service.prepare(archive, **options)
    applied = service.apply(
        service.prepare(archive, replace=True, confirmed_mapping=True, **options)
    )
    assert applied["pdf_conflicts"] == ["ref:example"]
    assert applied["dives"] == applied["notes"] == applied.get("documents", 0) == 0
    assert original.path.read_bytes() == original_bytes
    assert from_workspace(client.journal.path).resolve(identity["local_id"]).sha256 == package[1]
    with client.journal.transaction() as conn:
        assert (
            conn.execute(
                "SELECT body FROM dives WHERE paper_id=?", (identity["local_id"],)
            ).fetchone()[0]
            == "Complete original explanation"
        )
        assert (
            conn.execute(
                "SELECT body FROM notes WHERE paper_id=?", (identity["local_id"],)
            ).fetchone()[0]
            == "Personal note"
        )
        assert conn.execute("SELECT COUNT(*) FROM lists").fetchone()[0] == 1


def test_replace_or_exact_retry_never_revives_deleted_research(package, importer):
    service, client = importer
    report = service.apply(service.prepare(package[0]))
    with client.journal.transaction() as conn:
        note_id = conn.execute("SELECT sync_id FROM research_note_identity").fetchone()[0]
    client.save(client.new_graph_operation("note", note_id, {}, action="delete"))
    before = client.journal.pending()
    replay = service.apply(service.prepare(package[0]))
    assert replay["replayed"] and client.journal.pending() == before
    with pytest.raises(ValueError, match="explicit restoration"):
        service.prepare(package[0], replace=True)
    with client.journal.transaction() as conn:
        assert conn.execute("SELECT COUNT(*) FROM notes").fetchone()[0] == 0
        assert conn.execute("SELECT id FROM lists").fetchone()[0] == report["list"]
    assert client.journal.pending() == before


def test_unrelated_paper_edit_while_pending_survives_success(package, importer):
    from test_sync_files import PAPER

    service, client = importer
    prepared = service.prepare(package[0])
    client.save(
        client.new_graph_operation(
            "paper", PAPER, {**paper_payload(), "title": "Unrelated newer title"}
        )
    )
    report = service.apply(prepared)
    with client.journal.transaction() as conn:
        assert (
            conn.execute("SELECT title FROM papers WHERE id=?", (LOCAL,)).fetchone()[0]
            == "Unrelated newer title"
        )
        assert conn.execute("SELECT COUNT(*) FROM lists").fetchone()[0] == 1
    assert report["papers"] == 1


def test_late_transaction_failure_rolls_back_receipt_and_all_activation(
    package, importer, monkeypatch
):
    from contextlib import contextmanager

    service, client = importer
    prepared = service.prepare(package[0])
    transaction = service.client.journal.transaction

    @contextmanager
    def fail_commit():
        with transaction() as conn:
            yield conn
            raise OSError("fixture commit failed")

    monkeypatch.setattr(service.client.journal, "transaction", fail_commit)
    with pytest.raises(OSError, match="commit failed"):
        service.apply(prepared)
    empty_research(client)
    monkeypatch.setattr(service.client.journal, "transaction", transaction)
    report = service.apply(service.prepare(package[0]))
    assert report["papers"] == 1


def test_broken_capture_marker_never_falls_through_to_legacy_import(package, importer, monkeypatch):
    service, client = importer
    monkeypatch.setattr(store, "DB_PATH", service.database)
    monkeypatch.setattr(bundle, "DATA_DIR", service.root)
    with client.journal.transaction() as conn:
        conn.execute("DELETE FROM research_capture_binding")
    with pytest.raises(ValueError):
        bundle.import_(package[0], pdfs=False)
    empty_research(client)


@pytest.mark.parametrize("phase", ["prepared", "applied"])
def test_service_releases_owned_database_handles_without_gc(package, tmp_path, phase):
    import os
    import shutil

    from paper_daily.sync_client import SyncClient
    from paper_daily.sync_journal import Journal
    from paper_daily.sync_research import prepare, research_order_writer, research_writer

    # Unlike the shared pair fixture, this fixture explicitly closes every
    # schema/setup connection. No gc call may mask service-owned handle leaks.
    database = tmp_path / "handle-test.sqlite"
    with closing(sqlite3.connect(database)) as conn:
        conn.executescript(store.SCHEMA)
        conn.commit()
    prepare(database, workspace_id="handle-workspace", device_id="handle-device")
    client = SyncClient(
        Journal(database, workspace_id="handle-workspace", device_id="handle-device"),
        research_writer,
        order_writer=research_order_writer,
    )
    enroll_capture(client)
    root = tmp_path / "handle-import"
    root.mkdir()
    service = PackageImporter(database, root)
    prepared = service.prepare(package[0])
    if phase == "applied":
        assert service.apply(prepared)["papers"] == 1
    replacement = database.with_suffix(".replacement")
    shutil.copy2(database, replacement)
    os.replace(replacement, database)
    with pytest.raises(ValueError, match="replaced"):
        service.apply(prepared)
    with closing(sqlite3.connect(database)) as conn:
        assert conn.execute("SELECT COUNT(*) FROM lists").fetchone()[0] == (phase == "applied")


def test_actual_second_device_receives_package_member_order(package, pair, tmp_path):
    archive, _digest = package
    server, a, b, _fa, _fb, ta, tb = pair
    enroll_capture(a)

    def more_members(manifest, tables, _values):
        first = dict(tables["papers"][0], id="ref:second", title="Second paper")
        second = dict(tables["papers"][0], id="ref:third", title="Third paper")
        tables["papers"] += [first, second]
        tables["cited_papers"] = [dict(first, id="ref:far", title="Cited far-end original")]
        tables["refs"] = [{"paper_id": "ref:third", "ref_paper_id": "ref:far", "influential": 1}]
        tables["pins"] = [{"paper_id": "ref:third", "pinned_at": STAMP}]
        tables["list_reading_goals"] = [
            {"list_id": "reading", "body": "Understand the original evidence", "written_at": STAMP}
        ]
        manifest["members"] = [
            dict(manifest["members"][0], paper_id=pid, position=i)
            for i, pid in enumerate(("ref:third", "ref:example", "ref:second"))
        ]
        manifest["pdfs"] = {"ref:example": None, "ref:second": None, "ref:third": None}
        _values.pop("files/pdf/ref_example.pdf")

    incoming = rewrite_package(archive, tmp_path / "ordered.zip", transform=more_members)
    root = tmp_path / "order-import"
    root.mkdir()
    service = PackageImporter(a.journal.path, root)
    report = service.apply(service.prepare(incoming))
    a.sync_once(server, ta)
    b.sync_once(server, tb)
    expected = [
        report["identity_mapping"][pid]["portable_id"]
        for pid in ("ref:third", "ref:example", "ref:second")
    ]
    with b.journal.transaction() as conn:
        actual = [
            row[0]
            for row in conn.execute(
                "SELECT i.sync_id FROM list_papers p JOIN research_paper_identity i "
                "ON i.local_id=p.paper_id WHERE p.list_id=? ORDER BY p.position,p.paper_id",
                (report["list"],),
            )
        ]
        edge = conn.execute(
            "SELECT left_i.sync_id,right_i.sync_id,r.influential FROM refs r "
            "JOIN research_paper_identity left_i ON left_i.local_id=r.paper_id "
            "JOIN research_paper_identity right_i ON right_i.local_id=r.ref_paper_id"
        ).fetchone()
        assert tuple(edge) == (expected[0], report["identity_mapping"]["ref:far"]["portable_id"], 1)
        pin = conn.execute(
            "SELECT p.scope,i.sync_id,p.pinned_at FROM pins p "
            "JOIN research_paper_identity i ON i.local_id=p.paper_id"
        ).fetchone()
        assert tuple(pin) == (report["list"], expected[0], STAMP)
        assert (
            conn.execute(
                "SELECT body FROM list_reading_goals WHERE list_id=?", (report["list"],)
            ).fetchone()[0]
            == "Understand the original evidence"
        )
    assert actual == expected


@pytest.mark.parametrize("mutated", [False, True])
def test_archive_native_revision_survives_prepared_json_round_trip(
    package, importer, monkeypatch, mutated
):
    from paper_daily import package_import

    service, _client = importer
    current = [123456, 789012]

    def observed(_path):
        return (1, 2, 3, 4, 5, tuple(current))

    monkeypatch.setattr(package_import, "version", observed)
    with service.client.journal.transaction() as conn:
        before = [tuple(row) for row in conn.execute("SELECT * FROM papers ORDER BY id")]
    pending = service.client.journal.pending()
    prepared = service.prepare(package[0])
    if mutated:
        current[1] += 1
        with pytest.raises(ValueError, match="archive changed"):
            service.apply(prepared)
        with service.client.journal.transaction() as conn:
            assert [
                tuple(row) for row in conn.execute("SELECT * FROM papers ORDER BY id")
            ] == before
        assert service.client.journal.pending() == pending
    else:
        result = service.apply(prepared)
        assert result["papers"] == 1
        with service.client.journal.transaction() as conn:
            assert conn.execute("SELECT body FROM dives").fetchone()[0] == (
                "Complete original explanation"
            )
