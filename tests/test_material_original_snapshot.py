"""Distinct material snapshots retain exact A and use native-only GUI admission."""

import hashlib
import json
import sqlite3
from contextlib import closing

import pytest
from test_material_sources import capture
from test_material_sources import case as case
from test_material_sources import codec as codec
from test_material_sources import local as local
from test_material_sources import no_external as no_external
from test_material_sources import original as original
from test_material_sources import scientific as scientific
from test_material_sources import source as source

from paper_daily import material_sources as sources
from paper_daily.desktop import original_version as viewer


def snapshot(source):
    collection = capture(source)
    item = collection.item("headings", 0)
    selection = sources.select(collection, item.key, item.payload)
    current = source["replace"]()
    assert current.sha256 != source["sha"]
    proof = sources.prepare(selection)
    return viewer.prepare_material(proof)


def test_material_snapshot_is_distinct_exact_and_gui_admission_has_no_heavy_work(
    source, monkeypatch
):
    saved = snapshot(source)
    assert saved.data == source["a"] and saved.document_hash == source["sha"]
    assert saved.material_proof is not None and saved.active_proof is None
    assert saved.local_proof is None and saved.retained_proof is None and saved.claim is None

    def deny(*_args, **_kwargs):
        pytest.fail("Material GUI admission must use native metadata only")

    with monkeypatch.context() as scoped:
        scoped.setattr(sqlite3, "connect", deny)
        scoped.setattr(json, "loads", deny)
        scoped.setattr(hashlib, "sha256", deny)
        scoped.setattr(viewer.pymupdf, "open", deny)
        assert viewer.metadata_current(saved) and viewer.material_status(saved) == "ready"


def test_material_snapshot_note_recheck_retains_same_collection_selection_and_original(source):
    saved = snapshot(source)
    selection = saved.material_proof.selection
    with closing(sqlite3.connect(source["database"])) as conn, conn:
        conn.execute(
            "INSERT INTO notes(paper_id,body,kind,created_at) VALUES(?,?,'note','fixture')",
            (source["paper"], "A new unrelated interpretation"),
        )
    assert viewer.material_status(saved) == "recheck" and not viewer.metadata_current(saved)
    renewed = viewer.refresh_material(saved, lambda: False)
    assert renewed.material_proof.selection is selection
    assert renewed.material_proof.selection.collection is selection.collection
    assert renewed.data == saved.data == source["a"] and viewer.metadata_current(renewed)


def test_material_snapshot_source_mutation_and_mixed_proof_are_not_admitted(source):
    saved = snapshot(source)
    object.__setattr__(saved, "active_proof", saved.material_proof)
    assert not viewer.metadata_current(saved)
    object.__setattr__(saved, "active_proof", None)
    saved.source.write_bytes(saved.source.read_bytes())
    assert viewer.material_status(saved) == "revoked" and not viewer.metadata_current(saved)
    with pytest.raises(ValueError):
        viewer.refresh_material(saved, lambda: False)
