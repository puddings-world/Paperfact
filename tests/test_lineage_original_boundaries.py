"""Read-only source boundaries across missing peers, restart and detached recovery."""

import hashlib
import json
import os
import sqlite3
import subprocess
import sys
from contextlib import closing
from pathlib import Path
from uuid import uuid4

import pytest
from test_lineage_jobs import work
from test_lineage_originals import loaded
from test_lineage_publication import publish
from test_lineage_target_jobs import job_for, observed
from test_research_lineage import corpus as corpus

from paper_daily import (
    lineage_originals,
    lineage_publication,
    lineage_sets,
    llm,
    research_generation,
    research_lineage,
    store,
    sync_recovery,
)
from paper_daily.ai_types import Completion
from paper_daily.manual_highlight_ops import capture_owner, observe_owner


def test_known_unavailable_peer_returns_absence_without_source_or_identity_creation(
    corpus, monkeypatch
):
    with closing(sqlite3.connect(corpus[0])) as conn, conn:
        store._migrate(conn)
    captured = research_lineage.capture(
        corpus[0],
        "focal",
        ["prior", "later", "missing"],
        legacy_root=corpus[1],
    )
    chosen = (corpus[0], corpus[1], captured)
    observation = observed(chosen)
    response = json.dumps(
        dict(format=research_lineage.PROPOSALS, focal=captured.focal, statements=[])
    )
    monkeypatch.setattr(llm, "complete_result", lambda *_a, **_k: Completion(response))
    job = job_for(chosen, observation)
    work(job.run)
    work(publish, corpus[0], work(lineage_publication.prepare, job._state.candidate))
    owner = observe_owner(
        corpus[0], "focal", expected_native=research_generation._identity(corpus[0])
    )
    row = lineage_sets.saved(corpus[0], "focal", corpus_id=job.corpus_id)[0]
    before = corpus[0].read_bytes()
    assert work(lineage_originals.prepare, owner, row, captured.sources[-1]["id"]) is None
    assert corpus[0].read_bytes() == before


def test_detached_archive_does_not_reactivate_old_original_grants(corpus, monkeypatch, tmp_path):
    _owner, expected = loaded(corpus, monkeypatch)
    package, target = tmp_path / "backup.zip", tmp_path / "detached"
    sync_recovery.create(corpus[0], package)
    sync_recovery.restore_detached(package, target)
    database = target / "papers.db"
    # Simulate the ordinary desktop load's fresh local view, not source adoption.
    owner = capture_owner(database, "focal")
    before = database.read_bytes()
    with pytest.raises(ValueError, match="no current local publication receipt"):
        work(lineage_originals.prepare, owner, expected, corpus[2].sources[1]["id"])
    assert database.read_bytes() == before
    assert (target / "objects" / corpus[2].sources[1]["document_hash"]).is_file()


def test_unrelated_invalid_history_is_not_parsed_or_selected_for_current_source(
    corpus, monkeypatch
):
    owner, row = loaded(corpus, monkeypatch)
    with closing(sqlite3.connect(corpus[0])) as conn, conn:
        conn.execute(
            "INSERT INTO research_lineage_publications VALUES(?,?,?,?)",
            (str(uuid4()), "0" * 64, "unrelated invalid JSON", "unrelated invalid JSON"),
        )
    selected = corpus[2].sources[1]
    snapshot = work(lineage_originals.prepare, owner, row, selected["id"])
    assert (
        hashlib.sha256(
            lineage_originals.for_delivery(snapshot, owner, row, selected["id"])
        ).hexdigest()
        == selected["document_hash"]
    )


def test_fresh_process_can_inspect_saved_original_without_native_job_replay(corpus, monkeypatch):
    _owner, expected = loaded(corpus, monkeypatch)
    selected = corpus[2].sources[1]
    before = corpus[0].read_bytes()
    script = """import hashlib,json,sys
from concurrent.futures import ThreadPoolExecutor
from paper_daily import lineage_originals as originals,lineage_sets,llm,research_generation as g
from paper_daily.manual_highlight_ops import observe_owner
llm.complete_result=lambda *a,**k: (_ for _ in ()).throw(AssertionError('No model call'))
database=sys.argv[1]
owner=observe_owner(database,'focal',expected_native=g._identity(database))
row=lineage_sets.saved(database,'focal',corpus_id=sys.argv[2])[0]
with ThreadPoolExecutor(max_workers=1) as pool:
    snapshot=pool.submit(originals.prepare,owner,row,sys.argv[3]).result(timeout=15)
data=originals.for_delivery(snapshot,owner,row,sys.argv[3])
print(json.dumps({'paper_id':snapshot.paper_id,'sha256':hashlib.sha256(data).hexdigest()}))
"""
    child = subprocess.run(
        [sys.executable, "-c", script, str(corpus[0]), expected["corpus_key"], selected["id"]],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=25,
        env={**os.environ, "PYTHONPATH": str(Path(__file__).parents[1] / "src")},
    )
    assert child.returncode == 0, child.stderr
    assert json.loads(child.stdout) == {"paper_id": "prior", "sha256": selected["document_hash"]}
    assert corpus[0].read_bytes() == before
