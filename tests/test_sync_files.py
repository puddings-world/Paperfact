"""Closed artifact wire formats and actual cross-device editable-deck publication."""

import copy
import hashlib
import json
import sqlite3
from uuid import uuid4

import pytest

from paper_daily import presentations, store
from paper_daily.sync_artifacts import applied_file, desired_file, materialize, paths
from paper_daily.sync_blobs import BlobStore
from paper_daily.sync_client import SyncClient
from paper_daily.sync_deck_files import encode_deck
from paper_daily.sync_deck_publication import StaleDeckError, observe_deck
from paper_daily.sync_file_transfers import FileTransfers
from paper_daily.sync_files import (
    canonical_json,
    file_id,
    referenced_blobs,
    validate_closure,
    validate_payload,
)
from paper_daily.sync_journal import Journal
from paper_daily.sync_research import prepare, research_writer
from paper_daily.sync_service import ReferenceService

PAPER = "11111111-1111-4111-8111-111111111111"
LOCAL = "sync:" + PAPER
INPUTS = {
    "schema_version": 1,
    "complete": False,
    "entities": [],
    "documents": [],
    "inputs_sha256": None,
}


def png(color):
    import pymupdf

    rgb = b"\xff\x00\x00" if color == "red" else b"\x00\x00\xff"
    return pymupdf.Pixmap(pymupdf.csRGB, 32, 24, rgb * (32 * 24), False).tobytes("png")


def deck():
    return presentations.Deck(
        PAPER,
        "Paper",
        "Guide",
        "guide",
        "Colleagues",
        10,
        [
            presentations.Slide(
                "Method",
                "Background",
                "Important",
                ["A result"],
                "Speaker explanation",
                ["figure:1", "figure:2", "cite:1"],
                "figure:1",
                [
                    {"kind": "figure", "figure": "figure:1", "x": 20, "y": 20, "w": 200, "h": 200},
                    {"kind": "figure", "figure": "figure:2", "x": 250, "y": 20, "w": 200, "h": 200},
                    {"kind": "text", "text": "Editable", "x": 20, "y": 250, "w": 500, "h": 50},
                ],
            )
        ],
        [
            {"id": "figure:1", "label": "First", "kind": "figure", "page": 1},
            {"id": "figure:2", "label": "Second", "kind": "figure", "page": 2},
            {
                "id": "cite:1",
                "label": "Reference",
                "kind": "citations",
                "url": "https://example.org/paper",
            },
        ],
        [
            {"id": "figure:1", "label": "First", "caption": "Caption one", "file": "a.png"},
            {"id": "figure:2", "label": "Second", "caption": "Caption two", "file": "b.png"},
        ],
        [],
        "2026-10-26T00:00:00Z",
        generation={"model": "fixture", "profile": "private-account", "request_id": "secret"},
    )


@pytest.fixture
def codec(monkeypatch):
    images = {"figure:1": png("red"), "figure:2": png("blue")}
    original = presentations.figure_bytes
    monkeypatch.setattr(
        presentations,
        "figure_bytes",
        lambda d, key: original(d, key) if getattr(d, "_file_operation", None) else images[key],
    )
    value = deck()
    payload, blobs = encode_deck(value, PAPER, input_versions=INPUTS)
    return value, payload, blobs


def test_codec_preserves_editable_layout_citations_and_only_used_images(codec):
    value, payload, blobs = codec
    assert value.generation["profile"] == "private-account"
    assert "asset" not in value.figures[0]
    body = validate_closure(payload, lambda row: blobs[row["sha256"]])
    assert body["deck"]["slides"][0]["speaker_notes"] == "Speaker explanation"
    assert len(body["deck"]["slides"][0]["elements"]) == 3
    assert body["deck"]["generation"] == {"model": "fixture"}
    assert body["deck"]["sources"][2]["url"] == "https://example.org/paper"


@pytest.mark.parametrize(
    "mutation", ["unknown", "duplicate", "size", "role", "feature", "nan", "bool", "input_extra"]
)
def test_manifest_rejects_unsupported_or_malformed_claims(codec, mutation):
    _, payload, _ = codec
    bad = copy.deepcopy(payload)
    if mutation == "unknown":
        bad["path"] = "../private"
    elif mutation == "duplicate":
        bad["assets"].append(bad["assets"][0])
    elif mutation == "size":
        bad["body"]["size"] = 8 * 1024**2 + 1
    elif mutation == "role":
        bad["assets"][0]["role"] = "executable"
    elif mutation == "feature":
        bad["feature"] = "arbitrary_json"
    elif mutation == "nan":
        bad["assets"][0]["size"] = float("nan")
    elif mutation == "bool":
        bad["format_version"] = True
    else:
        bad["input_versions"]["token"] = "private"
    with pytest.raises(ValueError):
        validate_payload(bad)


@pytest.mark.parametrize(
    "mutation", ["traversal", "extra_layout", "bad_png", "missing", "bad_hash", "duplicate_json"]
)
def test_closure_fails_closed(codec, mutation):
    _, payload, blobs = codec
    payload, blobs = copy.deepcopy(payload), dict(blobs)
    if mutation in {"traversal", "extra_layout"}:
        body = json.loads(blobs[payload["body"]["sha256"]])
        if mutation == "traversal":
            body["deck"]["figures"][0]["file"] = "../../secret.png"
        else:
            body["deck"]["slides"][0]["elements"][0]["onclick"] = "run()"
        data = canonical_json(body)
    elif mutation == "duplicate_json":
        data = b'{"version":1,"version":1}'
    else:
        description = payload["assets"][0]
        if mutation == "missing":
            del blobs[description["sha256"]]
            with pytest.raises(KeyError):
                validate_closure(payload, lambda row: blobs[row["sha256"]])
            return
        if mutation == "bad_hash":
            blobs[description["sha256"]] = b"corrupt"
        else:
            data = b"\x89PNG\r\n\x1a\nnot-an-image"
            description.update(sha256=hashlib.sha256(data).hexdigest(), size=len(data))
            blobs[description["sha256"]] = data
        with pytest.raises(ValueError):
            validate_closure(payload, lambda row: blobs[row["sha256"]])
        return
    payload["body"].update(sha256=hashlib.sha256(data).hexdigest(), size=len(data))
    blobs[payload["body"]["sha256"]] = data
    with pytest.raises(ValueError):
        validate_closure(payload, lambda row: blobs[row["sha256"]])


def side(tmp_path, name):
    path = tmp_path / (name + ".sqlite")
    with sqlite3.connect(path) as conn:
        conn.executescript(store.SCHEMA)
    prepare(path, workspace_id="workspace", device_id=name)
    return SyncClient(Journal(path, workspace_id="workspace", device_id=name), research_writer)


def paper_payload():
    return {
        "title": "Paper",
        "authors": [],
        "year": 2026,
        **{
            key: None
            for key in (
                "venue",
                "abstract",
                "doi",
                "arxiv_id",
                "s2_id",
                "page_url",
                "pdf_url",
                "source",
            )
        },
    }


@pytest.fixture
def pair(tmp_path, monkeypatch, codec):
    server = ReferenceService(tmp_path / "authority.sqlite", blob_root=tmp_path / "authority-blobs")
    a, b = side(tmp_path, "a"), side(tmp_path, "b")
    ta, tb = server.enroll("workspace", "a"), server.enroll("workspace", "b")
    fa = FileTransfers(
        a, BlobStore(tmp_path / "a-blobs"), server, origin="https://fixture.invalid", token=ta
    )
    fb = FileTransfers(
        b, BlobStore(tmp_path / "b-blobs"), server, origin="https://fixture.invalid", token=tb
    )
    operation = a.new_graph_operation("paper", PAPER, paper_payload())
    a.save(operation)
    a.sync_once(server, ta)
    b.sync_once(server, tb)
    monkeypatch.setattr(store, "DB_PATH", a.journal.path)
    monkeypatch.setattr(presentations, "DECK_DIR", tmp_path / "legacy-decks")
    return server, a, b, fa, fb, ta, tb


def drain(fn, final):
    for _ in range(40):
        result = fn()
        if result["state"] == final:
            return result
    raise AssertionError(result)


def save_current(pair, value):
    _, a, _, _, _, _, _ = pair
    value.paper_id = LOCAL
    observation = observe_deck(LOCAL, "guide")
    path = presentations.save_deck(value, observation=observation)
    assert path.is_file()
    with a.journal.transaction() as conn:
        return desired_file(conn, file_id(PAPER, "deck", "guide"))


def test_actual_save_transfer_receive_reopen_export_keeps_editable_deck(
    pair, codec, monkeypatch, tmp_path
):
    server, a, b, fa, fb, ta, tb = pair
    value, _, _ = codec
    operation = save_current(pair, value)
    assert not fa.ready_to_push(operation)
    drain(lambda: fa.upload(operation), "uploaded")
    a.sync_once(server, ta, prepare_push=fa.ready_to_push)
    b.sync_once(server, tb)
    with b.journal.transaction() as conn:
        assert desired_file(conn, operation["entity_id"]) == operation
        assert applied_file(conn, operation["entity_id"]) is None
    drain(lambda: fb.download(operation["entity_id"]), "bound")
    monkeypatch.setattr(store, "DB_PATH", b.journal.path)
    reopened = presentations.load_deck(LOCAL, "guide")
    assert reopened.slides[0].speaker_notes == "Speaker explanation"
    assert reopened.slides[0].elements[2]["text"] == "Editable"
    assert presentations.figure_bytes(reopened, "figure:1") == png("red")
    from paper_daily.presentation_export import export_html

    destination = tmp_path / "deck.html"
    export_html(reopened, destination)
    assert destination.is_file()


def test_stale_loaded_candidate_does_not_overwrite_and_survives_restart(pair, codec):
    _, a, _, _, _, _, _ = pair
    value, _, _ = codec
    save_current(pair, value)
    first, stale = presentations.load_deck(LOCAL, "guide"), presentations.load_deck(LOCAL, "guide")
    first.title = "First edit"
    presentations.save_deck(first)
    stale.title = "Recover this draft"
    with pytest.raises(StaleDeckError) as raised:
        presentations.save_deck(stale)
    assert presentations.load_deck(LOCAL, "guide").title == "First edit"
    with a.journal.transaction() as conn:
        assert conn.execute(
            "SELECT payload FROM research_file_candidates WHERE candidate_id=?",
            (raised.value.candidate_id,),
        ).fetchone()
        assert conn.execute("SELECT count(*) FROM research_file_versions").fetchone()[0] == 2


def test_exact_save_request_retry_does_not_duplicate_revision(pair, codec):
    _, a, _, _, _, _, _ = pair
    value, _, _ = codec
    value.paper_id = LOCAL
    observed = observe_deck(LOCAL, "guide")
    request = str(uuid4())
    first = presentations.save_deck(value, observation=observed, request_id=request)
    assert presentations.save_deck(value, observation=observed, request_id=request) == first
    with a.journal.transaction() as conn:
        assert conn.execute("SELECT count(*) FROM research_file_versions").fetchone()[0] == 1


def test_committed_intent_recovers_after_materialization_failure(pair, codec, monkeypatch):
    from paper_daily import sync_deck_publication as publication

    _, a, _, _, _, _, _ = pair
    value, _, _ = codec
    real = publication.materialize
    monkeypatch.setattr(
        publication, "materialize", lambda *_: (_ for _ in ()).throw(OSError("fixture"))
    )
    with pytest.raises(OSError):
        save_current(pair, value)
    with a.journal.transaction() as conn:
        operation = desired_file(conn, file_id(PAPER, "deck", "guide"))
        assert operation is not None
        assert applied_file(conn, operation["entity_id"]) is None
        blob_store, root = paths(conn)
    monkeypatch.setattr(publication, "materialize", real)
    directory = materialize(blob_store, root, operation)
    from paper_daily.sync_artifacts import activate

    with a.journal.transaction() as conn:
        assert activate(conn, operation, directory)
    assert presentations.load_deck(LOCAL, "guide").title == value.title


def test_bad_raw_parent_does_not_mutate_research_or_outbox(pair, codec):
    _, a, _, _, _, _, _ = pair
    _, payload, _ = codec
    operation = a.new_graph_operation("research_file", file_id(PAPER, "deck", "guide"), payload)
    operation["parents"][0]["incarnation"] = "wrong"
    with pytest.raises(ValueError):
        a.save(operation)
    with a.journal.transaction() as conn:
        assert desired_file(conn, operation["entity_id"]) is None


def test_referenced_blob_closure_is_deduplicated(pair, codec):
    _, a, _, _, _, _, _ = pair
    _, payload, _ = codec
    operation = a.new_graph_operation("research_file", file_id(PAPER, "deck", "guide"), payload)
    assert len(referenced_blobs(operation)) == 3
    assert all(set(row) == {"sha256", "size", "media_type"} for row in referenced_blobs(operation))


def test_workspace_switch_rejects_before_staging_or_candidate_write(pair, codec, monkeypatch):
    _, a, b, _, fb, _, _ = pair
    value = codec[0]
    value.paper_id = LOCAL
    observed = observe_deck(LOCAL, "guide")
    monkeypatch.setattr(store, "DB_PATH", b.journal.path)
    with pytest.raises(ValueError, match="workspace/device"):
        presentations.save_deck(value, observation=observed)
    with b.journal.transaction() as conn:
        assert conn.execute("SELECT count(*) FROM research_file_versions").fetchone()[0] == 0
        assert conn.execute("SELECT count(*) FROM research_file_candidates").fetchone()[0] == 0
    with fb.store._transaction() as conn:
        assert conn.execute("SELECT count(*) FROM blobs").fetchone()[0] == 0
    assert a.journal.device_id != b.journal.device_id


def test_old_applied_deck_stays_readable_but_cannot_overwrite_new_missing_closure(
    pair, codec, monkeypatch
):
    server, a, b, fa, fb, ta, tb = pair
    operation = save_current(pair, codec[0])
    drain(lambda: fa.upload(operation), "uploaded")
    a.sync_once(server, ta)
    b.sync_once(server, tb)
    drain(lambda: fb.download(operation["entity_id"]), "bound")
    edited = presentations.load_deck(LOCAL, "guide")
    edited.title = "New complete revision"
    presentations.save_deck(edited)
    with a.journal.transaction() as conn:
        second = desired_file(conn, operation["entity_id"])
    drain(lambda: fa.upload(second), "uploaded")
    a.sync_once(server, ta)
    b.sync_once(server, tb)
    monkeypatch.setattr(store, "DB_PATH", b.journal.path)
    old = presentations.load_deck(LOCAL, "guide")
    assert old.title == "Guide"
    old.title = "Stale draft is recoverable"
    with pytest.raises(StaleDeckError):
        presentations.save_deck(old)
    with b.journal.transaction() as conn:
        assert desired_file(conn, operation["entity_id"]) == second
        assert applied_file(conn, operation["entity_id"]) == operation
    drain(lambda: fb.download(operation["entity_id"]), "bound")
    assert presentations.load_deck(LOCAL, "guide").title == "New complete revision"


@pytest.mark.parametrize("filename", ["deck.json", "asset"])
def test_changed_installed_closure_never_activates(pair, codec, filename):
    from paper_daily.sync_artifacts import activate

    _, a, _, _, _, _, _ = pair
    operation = save_current(pair, codec[0])
    with a.journal.transaction() as conn:
        blob_store, root = paths(conn)
    directory = materialize(blob_store, root, operation)
    path = directory / (
        filename
        if filename == "deck.json"
        else operation["payload"]["assets"][0]["sha256"] + ".png"
    )
    path.write_bytes(b"tampered")
    with a.journal.transaction() as conn:
        with pytest.raises(ValueError, match="changed"):
            activate(conn, operation, directory)
        assert applied_file(conn, operation["entity_id"]) == operation


def test_cancel_and_session_switch_during_blob_read_cannot_activate(pair, codec, monkeypatch):
    server, a, b, fa, fb, ta, tb = pair
    operation = save_current(pair, codec[0])
    drain(lambda: fa.upload(operation), "uploaded")
    a.sync_once(server, ta)
    b.sync_once(server, tb)
    original = server.blob_read

    def cancel(*args, **kwargs):
        data = original(*args, **kwargs)
        fb.cancel(operation["entity_id"])
        return data

    monkeypatch.setattr(server, "blob_read", cancel)
    assert fb.download(operation["entity_id"])["state"] == "interrupted"
    assert fb.download(operation["entity_id"])["state"] == "cancelled"
    with b.journal.transaction() as conn:
        assert applied_file(conn, operation["entity_id"]) is None
    monkeypatch.setattr(server, "blob_read", original)
    assert fb.download(operation["entity_id"], retry=True)["state"] in {"downloading", "bound"}
    fb.close()
    assert fb.download(operation["entity_id"])["state"] == "signed_out"


def test_corrupt_download_partial_is_repaired_on_retry(pair, codec, monkeypatch):
    server, a, b, fa, fb, ta, tb = pair
    operation = save_current(pair, codec[0])
    drain(lambda: fa.upload(operation), "uploaded")
    a.sync_once(server, ta)
    b.sync_once(server, tb)
    original = server.blob_read

    def corrupt(*args, **kwargs):
        data = original(*args, **kwargs)
        return bytes([data[0] ^ 1]) + data[1:]

    monkeypatch.setattr(server, "blob_read", corrupt)
    with pytest.raises(ValueError):
        fb.download(operation["entity_id"])
    monkeypatch.setattr(server, "blob_read", original)
    drain(lambda: fb.download(operation["entity_id"], retry=True), "bound")
    with b.journal.transaction() as conn:
        assert applied_file(conn, operation["entity_id"]) == operation


def test_managed_history_restore_publishes_a_new_revision(pair, codec):
    _, a, _, _, _, _, _ = pair
    original = save_current(pair, codec[0])
    current = presentations.load_deck(LOCAL, "guide")
    current.title = "Changed title"
    presentations.save_deck(current)
    versions = presentations.list_versions(LOCAL, "guide")
    choice = next(row for row in versions if original["operation_id"] in row["file"])
    restored = presentations.restore_version(LOCAL, "guide", choice["file"])
    assert restored.title == "Guide"
    assert presentations.figure_bytes(restored, "figure:2") == png("blue")
    with a.journal.transaction() as conn:
        assert conn.execute("SELECT count(*) FROM research_file_versions").fetchone()[0] == 3


def test_input_snapshot_bounds_do_not_truncate_or_save(pair, codec):
    _, a, _, _, _, _, _ = pair
    with a.journal.transaction() as conn:
        conn.executemany(
            "INSERT INTO chat(paper_id,role,body,created_at) VALUES(?,?,?,?)",
            [(LOCAL, "user", "x", "2026-10-26T00:00:00Z")] * 1001,
        )
    with pytest.raises(ValueError, match="bound"):
        observe_deck(LOCAL, "guide")
    with a.journal.transaction() as conn:
        assert conn.execute("SELECT count(*) FROM chat").fetchone()[0] == 1001
        assert conn.execute("SELECT count(*) FROM research_file_versions").fetchone()[0] == 0


def test_upload_full_closure_validation_is_once_per_unchanged_session(pair, codec, monkeypatch):
    from paper_daily import sync_file_transfers

    _, _, _, fa, _, _, _ = pair
    operation = save_current(pair, codec[0])
    original = sync_file_transfers.verify_closure
    reads = []

    def counted(*args):
        reads.append(1)
        return original(*args)

    monkeypatch.setattr(sync_file_transfers, "verify_closure", counted)
    drain(lambda: fa.upload(operation), "uploaded")
    assert len(reads) == 1
    assert fa.upload(operation)["state"] == "uploaded"
    assert len(reads) == 1


def test_switch_to_unbound_workspace_retains_draft_in_original_only(
    pair, codec, monkeypatch, tmp_path
):
    _, a, _, _, _, _, _ = pair
    value = codec[0]
    value.paper_id = LOCAL
    observation = observe_deck(LOCAL, "guide")
    destination = tmp_path / "unbound.sqlite"
    with sqlite3.connect(destination) as conn:
        conn.executescript(store.SCHEMA)
    monkeypatch.setattr(store, "DB_PATH", destination)
    with pytest.raises(StaleDeckError) as raised:
        presentations.save_deck(value, observation=observation)
    with a.journal.transaction() as conn:
        assert conn.execute(
            "SELECT deck FROM research_file_drafts WHERE candidate_id=?",
            (raised.value.candidate_id,),
        ).fetchone()
    with sqlite3.connect(destination) as conn:
        assert not conn.execute(
            "SELECT name FROM sqlite_master WHERE name LIKE 'research_file_%'"
        ).fetchone()
    assert not presentations._path(LOCAL, "guide").exists()


def test_manual_edit_preserves_loaded_pdf_and_evidence_provenance(pair, codec):
    from paper_daily.sync_artifacts import activate, stage_bytes

    _, a, _, _, _, _, _ = pair
    value = codec[0]
    evidence = {
        "sources": [dict(row, text="Research evidence") for row in value.sources],
        "coverage": [],
        "source_hash": "original-evidence",
    }
    value.source_hash = "original-evidence"
    payload, blobs = encode_deck(
        value, PAPER, input_versions=INPUTS, source_document_hash="a" * 64, evidence=evidence
    )
    operation = a.new_graph_operation("research_file", file_id(PAPER, "deck", "guide"), payload)
    with a.journal.transaction() as conn:
        storage, root = paths(conn)
    stage_bytes(storage, blobs)
    a.save(operation)
    version = materialize(storage, root, operation)
    with a.journal.transaction() as conn:
        assert activate(conn, operation, version)
    loaded = presentations.load_deck(LOCAL, "guide")
    loaded.title = "Manual edit retains historical PDF A"
    presentations.save_deck(loaded)
    with a.journal.transaction() as conn:
        latest = desired_file(conn, operation["entity_id"])
    assert latest["payload"]["source_document_hash"] == "a" * 64
    assert latest["payload"]["input_versions"] == INPUTS
    assert next(row for row in latest["payload"]["assets"] if row["role"] == "evidence") == next(
        row for row in payload["assets"] if row["role"] == "evidence"
    )


def test_enrolled_capture_and_actual_save_do_not_echo_or_duplicate(pair, codec, monkeypatch):
    from paper_daily.sync_capture import install

    _, a, _, _, _, _, _ = pair
    monkeypatch.setattr(store, "ensure_dirs", lambda: None)
    with store.connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        install(conn, workspace_id="workspace", device_id="a")
    operation = save_current(pair, codec[0])
    assert operation["entity_type"] == "research_file"
    with a.journal.transaction() as conn:
        assert conn.execute("SELECT count(*) FROM research_file_versions").fetchone()[0] == 1


def test_observation_before_generation_rejects_changed_research_inputs(pair, codec, monkeypatch):
    from paper_daily.ai_types import Completion

    _, a, _, _, _, _, _ = pair
    original = save_current(pair, codec[0])
    value = presentations.load_deck(LOCAL, "guide")
    evidence = {
        "paper": {"id": LOCAL, "title": "Paper"},
        "sources": [dict(row, text="Evidence") for row in value.sources],
        "figures": value.figures,
        "coverage": [],
        "source_hash": "generated-evidence",
    }
    monkeypatch.setattr(presentations, "collect_evidence", lambda *_: evidence)

    def complete(*args, **kwargs):
        with a.journal.transaction() as conn:
            conn.execute(
                "INSERT INTO notes(paper_id,body,kind,created_at) VALUES(?,?,?,?)",
                (LOCAL, "Changed while model was running", "note", "2026-10-26T00:00:00Z"),
            )
        return Completion(
            json.dumps({"title": "Candidate generation", "slides": [value.slides[0].__dict__] * 4})
        )

    monkeypatch.setattr(presentations.llm, "complete_result", complete)
    generated, reason = presentations.generate(
        LOCAL, mode="guide", audience="Researchers", minutes=10, slide_count=4, inputs={"original"}
    )
    assert generated is None and "retained" in reason
    with a.journal.transaction() as conn:
        assert desired_file(conn, original["entity_id"]) == original
        assert conn.execute("SELECT count(*) FROM research_file_candidates").fetchone()[0] == 1


def test_overlap_acknowledgment_and_lost_reply_retry_are_idempotent(pair, codec, monkeypatch):
    server, _, _, fa, _, ta, _ = pair
    value = codec[0]
    # Large but valid evidence forces several bounded body/asset chunks.
    value.paper_id = LOCAL
    value.source_hash = "large-evidence"
    evidence = {
        "sources": [dict(value.sources[0], text="x" * (190 * 1024)) for _ in range(4)],
        "coverage": [],
        "source_hash": value.source_hash,
    }
    observation = observe_deck(LOCAL, "guide")
    presentations.save_deck(value, observation=observation, evidence=evidence)
    with pair[1].journal.transaction() as conn:
        operation = desired_file(conn, file_id(PAPER, "deck", "guide"))
    original = server.blob_append
    failed = []

    def lost_reply(token, upload, offset, data):
        response = original(token, upload, offset, data)
        if not failed:
            failed.append(True)
            raise ConnectionError("fixture dropped reply")
        return response

    monkeypatch.setattr(server, "blob_append", lost_reply)
    with pytest.raises(ConnectionError):
        fa.upload(operation)
    monkeypatch.setattr(server, "blob_append", original)
    drain(lambda: fa.upload(operation), "uploaded")
    assert fa.ready_to_push(operation)
    assert server.session_info(ta)["device_id"] == "a"


def test_acknowledging_loaded_local_revision_does_not_make_its_edit_stale(pair, codec):
    server, a, _, fa, _, ta, _ = pair
    operation = save_current(pair, codec[0])
    opened = presentations.load_deck(LOCAL, "guide")
    drain(lambda: fa.upload(operation), "uploaded")
    a.sync_once(server, ta)
    opened.title = "Edit after own acknowledgment"
    presentations.save_deck(opened)
    assert presentations.load_deck(LOCAL, "guide").title == opened.title


def test_server_advanced_overlap_offset_resumes_unaligned_verified_range(pair, codec, monkeypatch):
    server, a, _, fa, _, _, _ = pair
    value = codec[0]
    value.paper_id = LOCAL
    value.source_hash = "overlap-evidence"
    evidence = {
        "sources": [dict(value.sources[0], text="x" * (190 * 1024)) for _ in range(4)],
        "coverage": [],
        "source_hash": value.source_hash,
    }
    presentations.save_deck(value, observation=observe_deck(LOCAL, "guide"), evidence=evidence)
    with a.journal.transaction() as conn:
        operation = desired_file(conn, file_id(PAPER, "deck", "guide"))
    from paper_daily.sync_blobs import BlobManifest
    from paper_daily.sync_transfers import CHUNK_BYTES

    original = server.blob_append
    advanced = []

    def racing(token, upload, offset, data):
        response = original(token, upload, offset, data)
        if len(data) == CHUNK_BYTES and not advanced:
            for row in referenced_blobs(operation):
                raw = fa.store.verified_path(BlobManifest(row["sha256"], row["size"])).read_bytes()
                if raw[offset : offset + len(data)] == data and len(raw) > offset + len(data) + 7:
                    response = original(
                        token,
                        upload,
                        offset + len(data),
                        raw[offset + len(data) : offset + len(data) + 7],
                    )
                    advanced.append(True)
                    break
        return response

    monkeypatch.setattr(server, "blob_append", racing)
    drain(lambda: fa.upload(operation), "uploaded")
    assert advanced


def test_corrupt_local_staging_partial_can_be_retried(pair):
    from paper_daily.sync_artifacts import stage_bytes
    from paper_daily.sync_blobs import BlobManifest

    storage = pair[3].store
    content = b"fixture immutable bytes"
    sha = hashlib.sha256(content).hexdigest()
    manifest = BlobManifest(sha, len(content))
    storage.begin(manifest)
    storage.append(manifest, 0, b"X" * len(content))
    with pytest.raises(ValueError):
        stage_bytes(storage, {sha: content})
    stage_bytes(storage, {sha: content})
    assert storage.verified_path(manifest).read_bytes() == content


def test_new_deck_records_input_workspace_and_keeps_it_through_edit_and_copy(pair, codec):
    from paper_daily.sync_files import scope_input_versions

    value = codec[0]
    operation = save_current(pair, value)
    versions = copy.deepcopy(operation["payload"]["input_versions"])
    assert versions["schema_version"] == 2 and versions["workspace_id"] == "workspace"
    assert versions["complete"] is False
    loaded = presentations.load_deck(LOCAL, "guide")
    loaded.title = "Later manual edit"
    presentations.save_deck(loaded)
    with pair[1].journal.transaction() as conn:
        current = desired_file(conn, operation["entity_id"])
    assert current["payload"]["input_versions"] == versions
    assert scope_input_versions(versions, "restored-workspace") == versions
    assert versions == operation["payload"]["input_versions"]
    for damage in (lambda v: v.pop("workspace_id"),
                   lambda v: v.update(workspace_id="https://untrusted.invalid"),
                   lambda v: v.update(schema_version=True),
                   lambda v: v.update(token="not-a-permitted-field")):
        bad = copy.deepcopy(current["payload"])
        damage(bad["input_versions"])
        with pytest.raises(ValueError):
            validate_payload(bad)
