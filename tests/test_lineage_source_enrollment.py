"""Archive-only corpus originals cannot become other features' active sources."""

import sqlite3
from contextlib import closing
from uuid import uuid4

import pytest
from test_imported_source_enrollment import imported as imported
from test_lineage_jobs import work
from test_local_source_owners import receiver as receiver
from test_package_import import package as package
from test_package_import import rich_package as rich_package

from paper_daily import (
    enrollment_chat_history,
    lineage_source_snapshots,
    local_source_owners,
    research_lineage,
    source_snapshots,
)
from paper_daily.workspace_enrollment import EnrollmentService


def test_first_enrollment_does_not_promote_lineage_observation_into_claim_owner(imported, tmp_path):
    database, root, _current, _original, _body = imported
    previous = local_source_owners.list_owned(database)[0]
    original = source_snapshots.source_path(database, previous)
    selected = tmp_path / "selected"
    selected.mkdir()
    alias = selected / "ref_example.pdf"
    alias.write_bytes(original.read_bytes())
    corpus = research_lineage.capture(database, "ref:example", legacy_root=selected)
    retained = work(lineage_source_snapshots.retain, corpus,
                    corpus_id=str(uuid4()), request_id=str(uuid4()))
    assert len(retained) == 1
    with closing(sqlite3.connect(database)) as conn, conn:
        conn.execute("DELETE FROM research_local_source_owners")
    original.unlink()
    primary = root / "pdf/ref_example.pdf"
    service = EnrollmentService(database)
    plan = service.plan(pdfs={"ref:example": primary})
    assert not plan["supported"]
    assert any("claim source requires its exact selected original PDF" in b
               for b in plan["blockers"])
    # The ordinary inventory also requires unselected primary aliases to be classified.
    previous_bytes = primary.read_bytes()
    outside = tmp_path / "unselected-primary.pdf"
    primary.rename(outside)
    # Selecting the actual original as a primary remains an explicit valid choice.
    explicit = service.plan(pdfs={"ref:example": alias})
    assert explicit["supported"], explicit["blockers"]
    assert explicit["archived_source_receipts"] == 1
    assert outside.read_bytes() == previous_bytes
    assert source_snapshots.list_owned(database) == retained


def test_live_qa_source_selection_refuses_archive_only_observation_but_allows_explicit_primary():
    live = {"sources": [{"paper_id": "paper", "sha256": "a" * 64}]}
    archived = dict(path="private-original.pdf", sha256="a" * 64, size=100, archive_only=True)
    inventory = {}
    with pytest.raises(ValueError, match="exact original"):
        enrollment_chat_history.add_live_sources(inventory, live, {}, [archived], {"paper"})
    assert inventory == {}
    primary = {key: value for key, value in archived.items() if key != "archive_only"}
    enrollment_chat_history.add_live_sources(inventory, live, {"paper": primary},
                                            [archived], {"paper"})
    assert inventory == {("paper", "a" * 64): primary}
