"""Read-only originals from real public local/enrolled Apply and displayed slots."""

import hashlib
import os
import sqlite3
from contextlib import closing
from threading import Event

import pytest
from test_enrolled_deck_proposals import prepare, save
from test_enrolled_deck_review import actual as actual
from test_enrolled_deck_review import case as case
from test_enrolled_deck_review import codec as codec
from test_enrolled_deck_review import no_external as no_external
from test_enrolled_deck_review import original as original
from test_enrolled_deck_review import package as package
from test_enrolled_deck_review import scientific as scientific
from test_local_deck_proposals import local as local
from test_local_deck_proposals import native, prepared

from paper_daily import active_deck_originals as originals
from paper_daily import local_deck_proposals, presentations, store
from paper_daily import research_generation as generation
from paper_daily.research_review import ResearchReview
from paper_daily.sync_capture import suppress_capture
from paper_daily.sync_files import canonical_json, file_id


@pytest.fixture(params=["local", "managed"])
def ready(request, monkeypatch):
    if request.param == "local":
        source = request.getfixturevalue("local")
        database, _manifest, _blobs, saved, _prior = source
        proposal = local_deck_proposals.retain(prepared(source))
        paper, origin = "local-paper", "local_deck"
        expected = request.getfixturevalue("scientific")
        document_hash = expected[4]
        pdf = expected[3][document_hash]
        service = ResearchReview(database, presentation_root=saved.parents[1])
        details = dict(local=source, presentation_root=saved.parents[1], client=None)
    else:
        source = request.getfixturevalue("actual")
        database = source["client"].journal.path
        proposal = save(source, prepare(source))
        paper, origin = source["local"], "enrolled_deck"
        document_hash = source["package"].original_a
        pdf = source["expected"]["original_bytes"][document_hash]
        service = ResearchReview(database)
        details = dict(actual=source, presentation_root=None, client=source["client"])
    monkeypatch.setattr(store, "DB_PATH", database)
    view = service.prepare_file(service.preview(origin, proposal))
    assert (
        service.decide(view, request_id="source-read-apply", confirm_target=True)["decision"]
        == "applied"
    )
    deck = presentations.load_deck(paper, "guide")
    assert deck.sources[0]["document_hash"] == document_hash
    yield dict(
        mode=request.param,
        database=database,
        paper=paper,
        deck=deck,
        document_hash=document_hash,
        pdf=pdf,
        **details,
    )
    service.close()


def capture(value, **kwargs):
    return originals.capture(
        value["database"],
        value["paper"],
        value["deck"],
        "figure:1",
        expected_native=native(value["database"]),
        presentation_root=value["presentation_root"],
        **kwargs,
    )


def baseline(value):
    root = value["database"].parent
    with closing(sqlite3.connect(value["database"])) as conn:
        sql = list(conn.iterdump())
    return sql, {
        str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in root.rglob("*")
        if p.is_file() and not p.name.endswith(("-wal", "-shm"))
    }


def test_public_applied_saved_deck_reads_exact_a_without_writes_or_current_b_substitution(ready):
    before = baseline(ready)
    proof = originals.prepare(capture(ready))
    assert proof.data == ready["pdf"] and proof.document_hash == ready["document_hash"]
    assert proof.pages == 1 and proof.source == ready["deck"].sources[0]
    assert originals.gui_status(proof) == "ready"
    proof.source["document_hash"] = "0" * 64
    assert proof.source["document_hash"] == ready["document_hash"]
    if ready["client"]:
        primary = ready["actual"]["package"].primary
        assert primary["sha256"] != proof.document_hash
        assert ready["deck"]._file_operation["operation_id"] == "source-read-apply"
    else:
        assert ready["deck"]._file_observation is None
    assert baseline(ready) == before


def test_gui_admission_has_no_sql_hash_pdf_and_retired_caller_never_admits(ready, monkeypatch):
    proof = originals.prepare(capture(ready))

    def deny(*_args, **_kwargs):
        raise AssertionError("GUI admission must use native metadata only")

    with monkeypatch.context() as scoped:
        scoped.setattr(sqlite3, "connect", deny)
        scoped.setattr(originals.json, "loads", deny)
        scoped.setattr(hashlib, "sha256", deny)
        scoped.setattr(originals.pymupdf, "open", deny)
        assert originals.gui_status(proof) == "ready"
        assert originals.gui_status(proof, current=lambda: False) == "revoked"


def test_unrelated_note_write_rechecks_same_authority_without_permanent_revocation(ready):
    proof = originals.prepare(capture(ready))
    conn = generation._connect(ready["database"])
    with closing(conn), conn, suppress_capture(conn):
        conn.execute(
            "INSERT INTO notes(paper_id,body,kind,created_at) VALUES(?,?,'note','2026-11-01')",
            (ready["paper"], "Unrelated new reading interpretation"),
        )
    after_actor = baseline(ready)
    assert originals.gui_status(proof) == "recheck"
    renewed = originals.revalidate(proof)
    assert renewed.capture is proof.capture and renewed.data == proof.data
    assert originals.gui_status(renewed) == "ready"
    assert baseline(ready) == after_actor


def test_same_byte_source_mutation_revokes_even_after_restoring_mtime(ready):
    proof = originals.prepare(capture(ready))
    path = proof.source_path
    info = path.stat()
    path.write_bytes(path.read_bytes())
    os.utime(path, ns=(info.st_atime_ns, info.st_mtime_ns))
    assert originals.gui_status(proof) == "revoked"
    with pytest.raises(ValueError):
        originals.revalidate(proof)


def test_cancel_after_source_read_closes_handles_and_accepts_no_result(ready, monkeypatch):
    captured = capture(ready)
    source = next(path for path, _v in captured._files if path.endswith(ready["document_hash"]))
    stop = Event()
    read = originals._read

    def cancelled(path, *args):
        result = read(path, *args)
        if str(path) == source:
            stop.set()
        return result

    before = baseline(ready)
    monkeypatch.setattr(originals, "_read", cancelled)
    with pytest.raises(ValueError, match="cancelled"):
        originals.prepare(captured, current=lambda: not stop.is_set())
    assert baseline(ready) == before
    replacement = ready["database"].parent / "replacement-source.pdf"
    replacement.write_bytes(ready["pdf"])
    assert native(replacement) != native(originals.Path(source))
    os.replace(replacement, source)  # Actual Windows replacement: no retained PDF/file handle.


def test_actual_db_replacement_between_admission_and_connection_is_rejected(ready, monkeypatch):
    captured = capture(ready)
    database = ready["database"]
    replacement = database.with_suffix(".replacement")
    with (
        closing(sqlite3.connect(database)) as conn,
        closing(sqlite3.connect(replacement)) as target,
    ):
        conn.backup(target)
    assert native(database) != native(replacement)
    connect = originals._connect
    once = []

    def replaced(path):
        if not once:
            once.append(True)
            os.replace(replacement, database)
        return connect(path)

    monkeypatch.setattr(originals, "_connect", replaced)
    with pytest.raises(ValueError, match="workspace|database"):
        originals.prepare(captured)
    assert once == [True]


def test_unsaved_source_and_unknown_source_never_inherit_saved_slot(ready):
    ready["deck"].sources[0]["document_hash"] = "0" * 64
    with pytest.raises(ValueError):
        capture(ready)
    ready["deck"].sources[0]["document_hash"] = None
    with pytest.raises(ValueError):
        capture(ready)


def test_local_catalog_same_hash_two_candidates_is_explicitly_ambiguous(local):
    database, _manifest, _blobs, saved, _before = local
    first = local_deck_proposals.retain(prepared(local))
    service = ResearchReview(database, presentation_root=saved.parents[1])
    try:
        service.decide(
            service.prepare_file(service.preview("local_deck", first)),
            request_id="local-first",
            confirm_target=True,
        )
        local_deck_proposals.retain(prepared(local, request="another-owner-record"))
        deck = presentations.load_deck("local-paper", "guide")
        with pytest.raises(ValueError, match="ambiguous"):
            originals.capture(
                database,
                "local-paper",
                deck,
                "figure:1",
                expected_native=native(database),
                presentation_root=saved.parents[1],
            )
    finally:
        service.close()


def test_retired_managed_original_is_not_resurrected_from_present_cas(actual):
    proposal = save(actual, prepare(actual))
    client = actual["client"]
    service = ResearchReview(client.journal.path)
    try:
        service.decide(
            service.prepare_file(service.preview("enrolled_deck", proposal)),
            request_id="managed-source",
            confirm_target=True,
        )
        deck = presentations.load_deck(actual["local"], "guide")
        captured = originals.capture(
            client.journal.path,
            actual["local"],
            deck,
            "figure:1",
            expected_native=native(client.journal.path),
        )
        proof = originals.prepare(captured)
        identity = file_id(actual["portable"], "original_source", proof.document_hash)
        client.save(client.new_graph_operation("research_file", identity, {}, action="delete"))
        assert proof.source_path.read_bytes() == proof.data
        assert originals.gui_status(proof) == "recheck"
        with pytest.raises(ValueError, match="retired|unavailable"):
            originals.revalidate(proof)
    finally:
        service.close()


@pytest.mark.parametrize("ready", ["local"], indirect=True)
def test_actual_local_saved_slot_with_other_paper_cannot_be_relabelled(ready):
    import json

    from paper_daily.local_deck_review import _slot

    slot = _slot(ready["presentation_root"], ready["paper"], "guide")
    body = json.loads(slot.read_bytes())
    body["paper_id"] = "another-real-owner"
    slot.write_bytes(canonical_json(body))
    before = baseline(ready)
    with pytest.raises(ValueError, match="owner|paper|slot"):
        capture(ready)
    assert baseline(ready) == before


@pytest.mark.parametrize("ready", ["local"], indirect=True)
def test_actual_public_manual_resave_retains_exact_owned_original_readability(ready):
    presentations.save_deck(ready["deck"])
    ready["deck"] = presentations.load_deck(ready["paper"], "guide")
    before = baseline(ready)
    proof = originals.prepare(capture(ready))
    assert proof.data == ready["pdf"] and proof.document_hash == ready["document_hash"]
    assert baseline(ready) == before


def saved_slot(ready):
    if ready["mode"] == "managed":
        return ready["deck"]._file_directory / "deck.json"
    from paper_daily.local_deck_review import _slot

    return _slot(ready["presentation_root"], ready["paper"], "guide")


def test_earliest_slot_witness_refuses_same_bytes_written_before_worker_capture(ready):
    slot = saved_slot(ready)
    witness = (slot, originals.file_change.version(slot))
    info = slot.stat()
    slot.write_bytes(slot.read_bytes())
    os.utime(slot, ns=(info.st_atime_ns, info.st_mtime_ns))
    with pytest.raises(ValueError, match="version changed"):
        capture(ready, expected_slot=witness)


def test_saved_body_same_byte_mutation_cannot_be_blessed_by_revalidation(ready):
    proof = originals.prepare(capture(ready))
    slot = saved_slot(ready)
    info = slot.stat()
    slot.write_bytes(slot.read_bytes())
    os.utime(slot, ns=(info.st_atime_ns, info.st_mtime_ns))
    assert originals.gui_status(proof) == "revoked"
    with pytest.raises(ValueError):
        originals.revalidate(proof)


@pytest.mark.parametrize("ready", ["managed"], indirect=True)
@pytest.mark.parametrize("change", ["foreign-binding", "incomplete", "corrupt"])
def test_managed_store_refusals_preserve_post_actor_state(ready, change):
    proof = originals.prepare(capture(ready))
    root = ready["actual"]["store"].root
    if change == "corrupt":
        value = proof.source_path.read_bytes()
        proof.source_path.write_bytes(value[:-1] + bytes([value[-1] ^ 1]))
    else:
        with closing(sqlite3.connect(root / "index.sqlite")) as conn, conn:
            if change == "foreign-binding":
                conn.execute("UPDATE transfer_binding SET device='foreign-device'")
            else:
                conn.execute("UPDATE blobs SET complete=0 WHERE digest=?", (proof.document_hash,))
    after_actor = baseline(ready)
    assert originals.gui_status(proof) in {"recheck", "revoked"}
    with pytest.raises(ValueError):
        originals.revalidate(proof)
    assert baseline(ready) == after_actor


@pytest.mark.parametrize("ready", ["local"], indirect=True)
def test_external_local_parent_recreation_refuses_original_catalog_authority(ready):
    proof = originals.prepare(capture(ready))
    # Controlled unreplicated external local repair, not a shared graph delete API.
    with closing(generation._connect(ready["database"])) as conn, conn, suppress_capture(conn):
        row = conn.execute("SELECT * FROM papers WHERE id=?", (ready["paper"],)).fetchone()
        conn.execute("DELETE FROM papers WHERE id=?", (ready["paper"],))
        conn.execute("INSERT INTO papers VALUES (" + ",".join("?" for _ in row) + ")", tuple(row))
    before = baseline(ready)
    with pytest.raises(ValueError):
        originals.revalidate(proof)
    with pytest.raises(ValueError, match="unavailable"):
        capture(ready)
    assert baseline(ready) == before


@pytest.mark.parametrize("ready", ["managed"], indirect=True)
def test_actual_native_index_replacement_revokes_without_gui_sql(ready, monkeypatch):
    proof = originals.prepare(capture(ready))
    index = ready["actual"]["store"].root / "index.sqlite"
    replacement = index.with_suffix(".replacement")
    with closing(sqlite3.connect(index)) as source, closing(sqlite3.connect(replacement)) as target:
        source.backup(target)
    assert native(index) != native(replacement)
    os.replace(replacement, index)

    def deny(*_args, **_kwargs):
        raise AssertionError("Replaced native index must be refused before SQL")

    monkeypatch.setattr(originals, "_connect", deny)
    assert originals.gui_status(proof) == "revoked"
    with pytest.raises(ValueError, match="native identity"):
        originals.revalidate(proof)


@pytest.mark.parametrize("ready", ["local"], indirect=True)
@pytest.mark.parametrize(
    "body",
    [b'{"paper_id":"local-paper","paper_id":"foreign"}', b'{"x":NaN}', b'{"x":1e999}'],
    ids=["duplicate", "nonfinite", "overflow"],
)
def test_malformed_saved_json_refuses_without_writes(ready, body):
    saved_slot(ready).write_bytes(body)
    before = baseline(ready)
    with pytest.raises(ValueError):
        capture(ready)
    assert baseline(ready) == before


@pytest.mark.parametrize("ready", ["local"], indirect=True)
def test_gui_caller_retirement_during_native_checks_cannot_admit(ready, monkeypatch):
    proof = originals.prepare(capture(ready))
    stop = Event()
    version = originals._version

    def retired(path):
        value = version(path)
        stop.set()
        return value

    monkeypatch.setattr(originals, "_version", retired)
    assert originals.gui_status(proof, current=lambda: not stop.is_set()) == "revoked"


@pytest.mark.parametrize("ready", ["local"], indirect=True)
def test_nonobject_saved_json_has_explicit_read_refusal(ready):
    saved_slot(ready).write_bytes(b"null")
    before = baseline(ready)
    with pytest.raises(ValueError):
        capture(ready)
    assert baseline(ready) == before


@pytest.mark.parametrize("ready", ["managed"], indirect=True)
def test_oversized_materialized_body_refuses_before_file_read(ready, monkeypatch):
    slot = saved_slot(ready)
    with slot.open("r+b") as stream:
        stream.truncate(originals.MAX_BODY + 1)
    before = baseline(ready)
    read = originals._read

    def bounded(path, size, *args):
        if path == slot:
            assert size <= originals.MAX_BODY, "Active body read must be bounded before allocation"
        return read(path, size, *args)

    monkeypatch.setattr(originals, "_read", bounded)
    with pytest.raises(ValueError):
        capture(ready)
    assert baseline(ready) == before
