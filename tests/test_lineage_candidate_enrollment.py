"""First sync enrollment preserves old-identity proposals without promoting sources."""

import json
import os
import shutil
import sqlite3
from contextlib import closing
from uuid import uuid4

from test_lineage_candidates import completed
from test_research_evidence import pdf
from test_research_lineage import corpus as corpus

from paper_daily import enrollment_history, lineage_candidates, source_provenance, store
from paper_daily.sync_source_files import resolved
from paper_daily.workspace_enrollment import EnrollmentService


def test_replaced_database_candidate_enrolls_all_exact_originals_as_private_history(
    corpus, monkeypatch
):
    # The low-level capture fixture uses short title keys; enrollment requires
    # the normal writer's canonical derived value for lossless round trips.
    with closing(sqlite3.connect(corpus[0])) as conn, conn:
        for paper, title in conn.execute("SELECT id,title FROM papers").fetchall():
            conn.execute(
                "UPDATE papers SET title_key=? WHERE id=?", (store.title_key(title), paper)
            )
    replacement = corpus[0].with_suffix(".replacement")

    def replace():
        shutil.copyfile(corpus[0], replacement)
        os.replace(replacement, corpus[0])
        pdf(corpus[1] / "focal.pdf", [["Current B contains new independent observations."]])

    job, result, _calls = completed(corpus, monkeypatch, replace)
    record = job._state.candidate.record
    old_hash = json.loads(record["row_json"])["document_hash"]
    current = (corpus[1] / "focal.pdf").read_bytes()
    selected = {name: corpus[1] / (name + ".pdf") for name in ("focal", "prior", "later")}
    service = EnrollmentService(corpus[0])
    plan = service.plan(pdfs=selected)
    assert plan["supported"], plan["blockers"]
    assert plan["archived_source_receipts"] == 3
    output = corpus[0].parent.parent / ("lineage-enrolled-" + str(uuid4()))
    backup = corpus[0].parent.parent / ("lineage-enrollment-" + str(uuid4()) + ".zip")
    prepared = service.prepare(output, backup_output=backup, request_id=str(uuid4()), pdfs=selected)
    with closing(sqlite3.connect(prepared["database"])) as conn:
        records = enrollment_history.archived(conn)
        candidates = [
            json.loads(r["body_json"])
            for r in records
            if r["protocol"] == "research_generation_recovery"
        ]
        assert candidates == [record]
        assert len(source_provenance.archived(conn)) == 3
        portable = conn.execute(
            "SELECT sync_id FROM research_paper_identity WHERE local_id='focal'"
        ).fetchone()[0]
        assert resolved(conn, portable, old_hash) is None
        assert not conn.execute(
            "SELECT 1 FROM sqlite_master WHERE name='paper_lineage_sets'"
        ).fetchone()
    assert result.execution["persistence"] == "candidate"
    assert (corpus[1] / "focal.pdf").read_bytes() == current
    assert lineage_candidates.validate(record) == record
