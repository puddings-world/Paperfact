"""Saved Lineage originals bind exact corpus/source/owner and GUI delivery state."""

import shutil
import sqlite3
from contextlib import closing
from dataclasses import replace
from uuid import uuid4

import pytest
from test_lineage_jobs import work
from test_lineage_recovery import published
from test_research_lineage import corpus as corpus

from paper_daily import lineage_originals as originals
from paper_daily import lineage_sets, llm, research_generation
from paper_daily.manual_highlight_ops import observe_owner


def loaded(corpus, monkeypatch):
    job = published(corpus, monkeypatch)
    owner = observe_owner(
        corpus[0], "focal", expected_native=research_generation._identity(corpus[0])
    )
    row = lineage_sets.saved(corpus[0], "focal", corpus_id=job.corpus_id)[0]
    monkeypatch.setattr(
        llm, "complete_result", lambda *_a, **_k: pytest.fail("Saved-only source read")
    )
    return owner, row


@pytest.mark.parametrize("index", [0, 1, 2])
def test_exact_source_bytes_and_peer_identity_read_without_any_database_write(
    corpus, monkeypatch, index
):
    owner, row = loaded(corpus, monkeypatch)
    before = corpus[0].read_bytes()
    source = corpus[2].sources[index]
    snapshot = work(originals.prepare, owner, row, source["id"])
    assert snapshot.paper_id == ["focal", "prior", "later"][index]
    assert snapshot.document_hash == source["document_hash"]
    assert originals.metadata_current(snapshot)
    assert (
        originals.for_delivery(snapshot, owner, row, source["id"])
        == corpus[2]._documents[index].path.read_bytes()
    )
    assert corpus[0].read_bytes() == before


@pytest.mark.parametrize(
    "field,value",
    [
        ("document_hash", "0" * 64),
        ("paper_id", "unrelated-paper"),
        ("source_id", "0" * 64),
        ("_data", b"different bytes"),
    ],
)
def test_public_identity_or_byte_forgery_cannot_deliver(corpus, monkeypatch, field, value):
    owner, row = loaded(corpus, monkeypatch)
    source = corpus[2].sources[1]["id"]
    snapshot = work(originals.prepare, owner, row, source)
    forged = replace(snapshot, **{field: value})
    assert not originals.metadata_current(forged)
    with pytest.raises(ValueError, match="native verified snapshot"):
        originals.for_delivery(forged, owner, row, source)


@pytest.mark.parametrize(
    "changed", ["target", "candidate", "publication", "association", "parent", "database"]
)
def test_pending_snapshot_cannot_deliver_after_native_or_sql_state_changes(
    corpus, monkeypatch, changed
):
    owner, row = loaded(corpus, monkeypatch)
    source = corpus[2].sources[1]["id"]
    snapshot = work(originals.prepare, owner, row, source)
    if changed == "database":
        copy = corpus[0].with_name("replacement.sqlite")
        shutil.copy2(corpus[0], copy)
        copy.replace(corpus[0])
    else:
        with closing(sqlite3.connect(corpus[0])) as conn, conn:
            if changed == "target":
                conn.execute("UPDATE paper_lineage_sets SET written_at='2026-11-01T00:00:00+00:00'")
            elif changed == "candidate":
                conn.execute("DELETE FROM research_generation_requests")
            elif changed == "publication":
                conn.execute("DELETE FROM research_lineage_publications")
            elif changed == "association":
                conn.execute("DELETE FROM research_local_source_owners")
            else:
                conn.execute(
                    "UPDATE research_parent_lifecycle SET token=? WHERE entity_id='later'",
                    ("0" * 32,),
                )
    assert not originals.metadata_current(snapshot)
    with pytest.raises(ValueError, match="view changed"):
        originals.for_delivery(snapshot, owner, row, source)


@pytest.mark.parametrize("changed", ["owner", "row", "source", "closed"])
def test_gui_delivery_requires_actual_current_loaded_view(corpus, monkeypatch, changed):
    owner, row = loaded(corpus, monkeypatch)
    source = corpus[2].sources[1]["id"]
    snapshot = work(originals.prepare, owner, row, source)
    if changed == "owner":
        owner = observe_owner(
            corpus[0], "focal", expected_native=research_generation._identity(corpus[0])
        )
    elif changed == "row":
        row = dict(row, corpus_key=str(uuid4()))
    elif changed == "source":
        source = corpus[2].sources[2]["id"]
    else:
        owner = None
    with pytest.raises(ValueError, match="view changed"):
        originals.for_delivery(snapshot, owner, row, source)


def test_selected_original_A_is_returned_while_current_primary_B_remains_untouched(
    corpus, monkeypatch
):
    owner, row = loaded(corpus, monkeypatch)
    source = corpus[2].sources[0]["id"]
    before = (corpus[1] / "focal.pdf").read_bytes()
    from test_research_evidence import pdf

    pdf(corpus[1] / "focal.pdf", [["A different current primary original B."]])
    primary = (corpus[1] / "focal.pdf").read_bytes()
    snapshot = work(originals.prepare, owner, row, source)
    assert originals.for_delivery(snapshot, owner, row, source) == before
    assert (corpus[1] / "focal.pdf").read_bytes() == primary and primary != before


def test_damaged_retained_original_never_falls_back_to_an_available_primary(corpus, monkeypatch):
    owner, row = loaded(corpus, monkeypatch)
    source = corpus[2].sources[0]["id"]
    snapshot = work(originals.prepare, owner, row, source)
    snapshot._source.write_bytes(b"corrupted retained original")
    assert (corpus[1] / "focal.pdf").is_file()
    assert not originals.metadata_current(snapshot)
    with pytest.raises(ValueError):
        work(originals.prepare, owner, row, source)


def test_delivery_guard_never_hashes_or_parses_pdf_and_cancel_creates_nothing(corpus, monkeypatch):
    owner, row = loaded(corpus, monkeypatch)
    source = corpus[2].sources[1]["id"]
    snapshot = work(originals.prepare, owner, row, source)
    before = corpus[0].read_bytes()

    def forbidden(*_a, **_k):
        pytest.fail("Delivery guard must only check bounded native/SQL metadata")

    monkeypatch.setattr(originals.atomic_sources, "verify", forbidden)
    monkeypatch.setattr(originals.local_source_owners, "_read_pdf", forbidden)
    assert originals.metadata_current(snapshot)
    assert originals.for_delivery(snapshot, owner, row, source).startswith(b"%PDF")
    assert work(originals.prepare, owner, row, source, cancelled=lambda: True) is None
    assert corpus[0].read_bytes() == before


def test_last_worker_guard_refuses_a_target_change_during_pdf_verification(corpus, monkeypatch):
    owner, row = loaded(corpus, monkeypatch)
    source = corpus[2].sources[1]["id"]
    read = originals.local_source_owners._read_pdf

    def changed(*args, **kwargs):
        result = read(*args, **kwargs)
        with closing(sqlite3.connect(corpus[0])) as conn, conn:
            conn.execute("UPDATE paper_lineage_sets SET written_at='2026-11-01T00:00:00+00:00'")
        return result

    monkeypatch.setattr(originals.local_source_owners, "_read_pdf", changed)
    with pytest.raises(ValueError, match="ownership changed"):
        work(originals.prepare, owner, row, source)


def test_wrong_source_and_main_thread_are_refused_without_new_rows(corpus, monkeypatch):
    owner, row = loaded(corpus, monkeypatch)
    before = corpus[0].read_bytes()
    with pytest.raises(ValueError, match="not selected"):
        work(originals.prepare, owner, row, "0" * 64)
    with pytest.raises(ValueError, match="worker_required"):
        originals.prepare(owner, row, corpus[2].sources[0]["id"])
    assert corpus[0].read_bytes() == before
