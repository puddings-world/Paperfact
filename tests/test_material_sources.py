"""Actual collected materials and native source owners, with no UI/model/writes."""

import copy
import hashlib
import json
import os
import pickle
import sqlite3
from contextlib import closing
from dataclasses import asdict
from threading import Event

import pymupdf
import pytest
from test_local_deck_proposals import local as local
from test_local_deck_proposals import native, prepared
from test_portable_deck_proposal import scientific as scientific
from test_rescue_deck_import import RECEIVER, TARGET, attach
from test_rescue_deck_import import case as case
from test_rescue_deck_import import codec as codec
from test_rescue_deck_import import no_external as no_external
from test_rescue_deck_import import original as original

from paper_daily import (
    figures,
    materials,
    paper_highlights,
    research_evidence,
    research_generation,
    source_snapshots,
    store,
)
from paper_daily import local_deck_proposals as catalog
from paper_daily import material_sources as sources
from paper_daily import portable_deck_proposal as content
from paper_daily.document_reader import from_workspace, register_document_paths
from paper_daily.sync_capture import suppress_capture
from paper_daily.sync_files import file_id
from paper_daily.sync_source_files import publish


def pdf(text):
    with pymupdf.open() as document:
        document.new_page().insert_text((40, 50), text)
        return document.tobytes()


@pytest.fixture(params=["local", "managed"])
def source(request, tmp_path, monkeypatch):
    a = pdf("1 Owned A Method\nExact original material for independent review.\n2 Owned A Results")
    b = pdf("1 Current B Method\nDifferent current material.\n2 Current B Results")
    sha = hashlib.sha256(a).hexdigest()
    if request.param == "local":
        local = request.getfixturevalue("local")
        science = request.getfixturevalue("scientific")
        deck, evidence, images, _originals, _sha, _b = science
        for row in deck.sources + deck.figures + evidence["sources"] + evidence["figures"]:
            row["document_hash"] = sha
        manifest, blobs = content.encode(deck, evidence, images, {sha: a}, source_document_hash=sha)
        job = prepared((local[0], manifest, blobs, local[3], local[4]))
        proposal = catalog.retain(job)
        database, paper_id, client = local[0], "local-paper", None
        root = tmp_path / "primary"
        root.mkdir()
        alias = root / (paper_id + ".pdf")
        alias.write_bytes(a)
        resolver = from_workspace(database, legacy_root=root)

        def replace():
            alias.write_bytes(b)
            return resolver.resolve(paper_id)

        details = dict(proposal=proposal, job=job, alias=alias)
    else:
        case = request.getfixturevalue("case")
        client, blobs = case["a"], case["transfer"].store
        database, paper_id = client.journal.path, TARGET
        root = tmp_path / "legacy"
        with client.journal.transaction() as conn:
            register_document_paths(
                conn,
                workspace_id="workspace",
                blob_root=blobs.root,
                projection_root=tmp_path / "reader",
                legacy_root=root,
            )
            parent = client._optimistic_graph(conn)[0][("paper", RECEIVER)]["incarnation"]
        attach(client, blobs, RECEIVER, a, "material-a-primary")
        original = tmp_path / "selected-a.pdf"
        original.write_bytes(a)
        operation = publish(
            client,
            RECEIVER,
            original,
            document_hash=sha,
            parent_incarnation=parent,
            store=blobs,
            version_root=case["transfer"].root,
            request_id="material-a-original",
        )
        resolver = from_workspace(database)

        def replace():
            attach(client, blobs, RECEIVER, b, "material-b-primary")
            return resolver.resolve(paper_id)

        details = dict(operation=operation, blobs=blobs)
    monkeypatch.setattr(store, "DB_PATH", database)
    for name, value in (
        ("DATA_DIR", tmp_path / "material-cache"),
        ("FIG_DIR", tmp_path / "figures"),
        ("TEXT_DIR", tmp_path / "text"),
        ("PDF_DIR", root),
    ):
        monkeypatch.setattr(materials, name, value)
    monkeypatch.setattr(figures, "FIG_DIR", tmp_path / "figures")
    monkeypatch.setattr(paper_highlights, "CACHE_DIR", tmp_path / "highlights")
    document = resolver.resolve(paper_id)
    assert document.available and document.sha256 == sha and resolver.intact(document)
    found = materials.collect(paper_id, document=document)
    assert found.headings and found.headings[0]["document_hash"] == sha
    return dict(
        mode=request.param,
        database=database,
        paper=paper_id,
        document=document,
        found=found,
        a=a,
        b=b,
        sha=sha,
        replace=replace,
        client=client,
        **details,
    )


def capture(source, **kwargs):
    return sources.capture_collection(
        source["database"],
        source["paper"],
        source["document"],
        source["found"],
        expected_native=native(source["database"]),
        **kwargs,
    )


def selected(collection):
    item = collection.item("headings", 0)
    assert item is not None
    return sources.select(collection, item.key, item.payload)


def baseline(source):
    root = source["database"].parent
    with closing(sqlite3.connect(source["database"].as_uri() + "?mode=ro", uri=True)) as conn:
        sql = list(conn.iterdump())
    return sql, {
        str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in root.rglob("*")
        if p.is_file() and not p.name.endswith(("-wal", "-shm"))
    }


def test_actual_collection_a_survives_primary_b_without_read_writes_or_source_substitution(source):
    before = baseline(source)
    collection = capture(source)
    assert collection.historical_available and collection.unavailable_reason is None
    assert baseline(source) == before
    current_b = source["replace"]()
    assert current_b.available and current_b.sha256 != collection.document_hash
    after_actor = baseline(source)
    selected_a = selected(collection)
    proof = sources.prepare(selected_a)
    assert proof.database == source["database"] and proof.data == source["a"]
    assert proof.document_hash == source["sha"] and proof.pages == 1
    assert proof.source["text"] == source["found"].headings[0]["text"]
    assert proof.locator_status == "declared_geometry"
    assert current_b.path.read_bytes() == source["b"]
    assert sources.gui_status(proof) == "ready"
    assert baseline(source) == after_actor


def test_small_gui_projection_selection_and_proof_never_sql_hash_json_or_parse_pdf(
    source, monkeypatch
):
    collection = capture(source)
    proof = sources.prepare(selected(collection))
    item = collection.item("headings", 0)

    def deny(*_args, **_kwargs):
        raise AssertionError("GUI material metadata must be small/native only")

    with monkeypatch.context() as scoped:
        scoped.setattr(sqlite3, "connect", deny)
        scoped.setattr(hashlib, "sha256", deny)
        scoped.setattr(json, "loads", deny)
        scoped.setattr(pymupdf, "open", deny)
        assert sources.select(collection, item.key, item.payload).payload == item.payload
        assert proof.source["document_hash"] == source["sha"]
        assert sources.gui_status(proof) == "ready"
        assert sources.gui_status(proof, current=lambda: False) == "revoked"


def test_note_interference_rechecks_same_selection_without_recapturing_owner(source):
    proof = sources.prepare(selected(capture(source)))
    with (
        closing(research_generation._connect(source["database"])) as conn,
        conn,
        suppress_capture(conn),
    ):
        conn.execute(
            "INSERT INTO notes(paper_id,body,kind,created_at) VALUES(?,?,'note','2026-11-01')",
            (source["paper"], "Unrelated interpretation"),
        )
    after_actor = baseline(source)
    assert sources.gui_status(proof) == "recheck"
    renewed = sources.revalidate(proof)
    assert renewed.selection is proof.selection and renewed.data == proof.data
    assert sources.gui_status(renewed) == "ready"
    assert baseline(source) == after_actor


def test_selection_is_exact_and_capability_never_enters_asdict_mime_or_pickle(source):
    collection = capture(source)
    before = asdict(source["found"])
    source["found"]._source_collection = collection
    assert asdict(source["found"]) == before
    with pytest.raises(TypeError):
        asdict(collection)
    with pytest.raises(TypeError):
        pickle.dumps(collection)
    item = collection.item("headings", 0)
    forged = item.payload
    forged["document_hash"] = "0" * 64
    with pytest.raises(ValueError):
        sources.select(collection, item.key, forged)
    with pytest.raises(ValueError):
        sources.select(collection, "unknown-key", item.payload)
    source["found"].headings[0]["text"] = "Later mutable item"
    assert selected(collection).payload["text"] != "Later mutable item"


def test_retained_source_same_byte_write_with_restored_mtime_revokes(source):
    proof = sources.prepare(selected(capture(source)))
    path, stamp = proof.source_path, proof.source_path.stat()
    path.write_bytes(path.read_bytes())
    os.utime(path, ns=(stamp.st_atime_ns, stamp.st_mtime_ns))
    assert sources.gui_status(proof) == "revoked"
    with pytest.raises(ValueError):
        sources.revalidate(proof)


def test_cancelled_owned_read_closes_handles_and_accepts_no_result(source, monkeypatch):
    selection = selected(capture(source))
    proof = sources.prepare(selection)
    stop = Event()
    read = sources.reads._read

    def cancelled(path, *args):
        value = read(path, *args)
        if path == proof.source_path:
            stop.set()
        return value

    before = baseline(source)
    monkeypatch.setattr(sources.reads, "_read", cancelled)
    with pytest.raises(ValueError, match="cancelled"):
        sources.prepare(selection, current=lambda: not stop.is_set())
    assert baseline(source) == before
    replacement = proof.source_path.with_suffix(".replacement")
    replacement.write_bytes(proof.data)
    assert native(replacement) != native(proof.source_path)
    os.replace(replacement, proof.source_path)


@pytest.mark.parametrize("source", ["managed"], indirect=True)
def test_capture_accepts_actual_intact_reader_a_when_desired_is_already_b(source):
    b = source["replace"]()
    assert source["document"]._owner.intact(source["document"])
    assert not source["document"]._owner.current(source["document"])
    proof = sources.prepare(selected(capture(source)))
    assert proof.data == source["a"] and b.path.read_bytes() == source["b"]


@pytest.mark.parametrize("source", ["managed"], indirect=True)
def test_retired_original_refuses_without_fallback(source):
    proof = sources.prepare(selected(capture(source)))
    client = source["client"]
    identity = file_id(RECEIVER, "original_source", source["sha"])
    client.save(client.new_graph_operation("research_file", identity, {}, action="delete"))
    assert proof.source_path.read_bytes() == source["a"]
    after_actor = baseline(source)
    assert sources.gui_status(proof) == "recheck"
    with pytest.raises(ValueError):
        sources.revalidate(proof)
    assert baseline(source) == after_actor


@pytest.mark.parametrize("source", ["local"], indirect=True)
def test_missing_owned_original_preserves_items_and_never_adopts_later_owner(source):
    with closing(sqlite3.connect(source["database"])) as conn, conn:
        conn.execute("DELETE FROM " + catalog.TABLE)
    before = baseline(source)
    collection = capture(source)
    assert not collection.historical_available and collection.items
    assert collection.unavailable_reason == "original_not_retained"
    with pytest.raises(sources.OriginalUnavailable):
        sources.prepare(selected(collection))
    assert baseline(source) == before
    catalog.retain(source["job"])
    with pytest.raises(ValueError):
        sources.prepare(selected(collection))


@pytest.mark.parametrize("source", ["local"], indirect=True)
def test_real_source_snapshot_receipt_without_claim_or_catalog_grants_exact_owned_a(source):
    with closing(research_generation._connect(source["database"])) as conn, conn:
        context = research_generation.begin_generation(
            conn, table="close_readings", owner_id=source["paper"], input_reader="target"
        )
    context = research_generation.bind_inputs(context, document=source["document"])
    row = source_snapshots.retain(context, research_evidence.capture(source["document"]))
    with closing(sqlite3.connect(source["database"])) as conn, conn:
        conn.execute("DELETE FROM " + catalog.TABLE)
        assert conn.execute("SELECT COUNT(*) FROM paper_claim_sets").fetchone()[0] == 0
    before = baseline(source)
    collection = capture(source)
    proof = sources.prepare(selected(collection))
    assert proof.data == source["a"]
    assert proof.source_path == source_snapshots.source_path(source["database"], row)
    assert baseline(source) == before


@pytest.mark.parametrize("source", ["local"], indirect=True)
def test_external_parent_recreation_refuses_old_collection_without_writes(source):
    proof = sources.prepare(selected(capture(source)))
    with (
        closing(research_generation._connect(source["database"])) as conn,
        conn,
        suppress_capture(conn),
    ):
        row = conn.execute("SELECT * FROM papers WHERE id=?", (source["paper"],)).fetchone()
        conn.execute("DELETE FROM papers WHERE id=?", (source["paper"],))
        conn.execute("INSERT INTO papers VALUES (" + ",".join("?" for _ in row) + ")", tuple(row))
    after_actor = baseline(source)
    with pytest.raises(ValueError):
        sources.revalidate(proof)
    assert baseline(source) == after_actor


def test_projection_exact_table_heading_sentence_schema_and_defensive_small_metadata():
    value = materials.Materials(
        "paper",
        exhibits=[
            dict(
                id="figure:1",
                label="Table 1",
                caption="Exact caption",
                page=1,
                rows=[["Name", "Value"], ["Observed", "0"]],
                document_hash="a" * 64,
            )
        ],
        headings=[dict(text="1 Methods", page=1, level=1, document_hash="a" * 64)],
        sentences=[
            dict(
                text="Exact sentence",
                page=1,
                reason="Proposed importance",
                origin="manual",
                anchor={"p0": 0, "p1": 0, "o0": 0, "o1": 2},
                mark_id=7,
                document_hash="a" * 64,
            )
        ],
    )
    original = copy.deepcopy(asdict(value))
    items = sources.project_items(value)
    assert [(item.group, item.index, item.variant) for item in items] == [
        ("exhibits", 0, "main"),
        ("exhibits", 0, "table"),
        ("headings", 0, "main"),
        ("sentences", 0, "main"),
    ]
    assert items[1].payload == dict(
        kind="table",
        id="figure:1",
        label="Table 1",
        page=1,
        rect=None,
        document_hash="a" * 64,
        rows=value.exhibits[0]["rows"],
    )
    assert items[2].payload == dict(value.headings[0], kind="heading")
    assert items[3].payload["mark_id"] == 7 and items[3].payload["reason"] == "Proposed importance"
    items[1].payload["rows"][0][0] = "Changed defensive view"
    assert items[1].payload["rows"][0][0] == "Name"
    assert [item.key for item in sources.project_items(value)] == [item.key for item in items]
    assert asdict(value) == original


def test_projection_bounds_and_nonfinite_metadata_fail_without_truncation():
    with pytest.raises(ValueError, match="nothing truncated"):
        sources.project_items(
            materials.Materials(
                "paper", headings=[dict(text="1 Methods")] * (sources.MAX_ITEMS + 1)
            )
        )
    with pytest.raises(ValueError):
        sources.project_items(
            materials.Materials("paper", headings=[dict(text="1 Methods", rect=[float("nan")])])
        )
    with pytest.raises(ValueError):
        sources.project_items(materials.Materials("paper", headings=None))


@pytest.mark.parametrize("source", ["managed"], indirect=True)
@pytest.mark.parametrize("change", ["foreign-binding", "incomplete"])
def test_actual_store_binding_or_completeness_change_cannot_authorize_original(source, change):
    proof = sources.prepare(selected(capture(source)))
    with closing(sqlite3.connect(source["blobs"].root / "index.sqlite")) as conn, conn:
        if change == "foreign-binding":
            conn.execute("UPDATE transfer_binding SET device='foreign'")
        else:
            conn.execute("UPDATE blobs SET complete=0 WHERE digest=?", (source["sha"],))
    after_actor = baseline(source)
    assert sources.gui_status(proof) == "recheck"
    with pytest.raises(ValueError):
        sources.revalidate(proof)
    assert baseline(source) == after_actor


@pytest.mark.parametrize("source", ["local"], indirect=True)
def test_actual_native_database_replacement_revokes_before_sql(source, monkeypatch):
    collection = capture(source)
    selection = selected(collection)
    proof = sources.prepare(selection)
    replacement = source["database"].with_suffix(".replacement")
    with (
        closing(sqlite3.connect(source["database"])) as conn,
        closing(sqlite3.connect(replacement)) as target,
    ):
        conn.backup(target)
    assert native(replacement) != native(source["database"])
    os.replace(replacement, source["database"])

    def deny(*_args, **_kwargs):
        raise AssertionError("Changed native DB must refuse before SQL")

    monkeypatch.setattr(sources.reads, "_connect", deny)
    assert sources.gui_status(proof) == "revoked"
    with pytest.raises(ValueError):
        sources.select(collection, selection.item.key, selection.payload)
    with pytest.raises(ValueError):
        sources.prepare(selection)


@pytest.mark.parametrize("source", ["local"], indirect=True)
def test_real_same_hash_other_paper_owner_never_grants_this_collection(source):
    with closing(sqlite3.connect(source["database"])) as conn, conn:
        store.upsert_papers(
            conn,
            [
                dict(
                    id="other-paper",
                    title="A distinct paper",
                    venue="Fixture",
                    year=2026,
                    source="fixture",
                )
            ],
        )
    root = catalog._root(source["database"], native(source["database"]))
    other = catalog.prepare(
        source["database"],
        "other-paper",
        source["job"].manifest,
        lambda row: (root / "objects" / row["sha256"]).read_bytes(),
        request_id="different-actual-owner",
        expected_native=native(source["database"]),
    )
    other_id = catalog.retain(other)
    with closing(sqlite3.connect(source["database"])) as conn, conn:
        conn.execute("DELETE FROM " + catalog.TABLE + " WHERE proposal_id=?", (source["proposal"],))
        assert catalog.record(conn, other_id)["paper_id"] == "other-paper"
    before = baseline(source)
    collection = capture(source)
    assert not collection.historical_available and collection.items
    with pytest.raises(sources.OriginalUnavailable):
        sources.prepare(selected(collection))
    assert baseline(source) == before


@pytest.mark.parametrize("source", ["local"], indirect=True)
def test_receipt_version_tampering_revokes_real_private_source_read(source):
    with closing(research_generation._connect(source["database"])) as conn, conn:
        context = research_generation.begin_generation(
            conn, table="close_readings", owner_id=source["paper"], input_reader="target"
        )
    context = research_generation.bind_inputs(context, document=source["document"])
    row = source_snapshots.retain(context, research_evidence.capture(source["document"]))
    with closing(sqlite3.connect(source["database"])) as conn, conn:
        conn.execute("DELETE FROM " + catalog.TABLE)
    proof = sources.prepare(selected(capture(source)))
    receipt = source_snapshots.receipt_path(source["database"], row)
    receipt.write_bytes(receipt.read_bytes())
    before = baseline(source)
    assert sources.gui_status(proof) == "revoked"
    with pytest.raises(ValueError):
        sources.revalidate(proof)
    assert baseline(source) == before


@pytest.mark.parametrize("source", ["local"], indirect=True)
def test_unknown_item_source_is_preserved_but_never_borrows_collection_a(source):
    source["found"].headings[0]["document_hash"] = None
    collection = capture(source)
    choice = selected(collection)
    assert choice.payload["document_hash"] is None and collection.historical_available
    with pytest.raises(sources.OriginalUnavailable):
        sources.prepare(choice)
