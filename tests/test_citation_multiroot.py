"""Unrelated pin/reference parents never become citation output observations."""

import json
from contextlib import closing

import pytest
from test_list_pins import pins as pins
from test_list_pins import toggle
from test_reference_edges import pair as pair
from test_reference_edges import query, write
from test_research_generation import pdf

from paper_daily import cites, config, llm, store
from paper_daily import research_compound as compound
from paper_daily import research_generation as generation
from paper_daily.enrich import s2
from paper_daily.sources import crossref
from paper_daily.sync_capture import expecting, observe_target


@pytest.mark.parametrize("extra", ["pin", "reference", "both"])
def test_actual_citation_publication_with_multi_parent_research_targets(
    pins,
    tmp_path,
    monkeypatch,
    extra,
):
    a, _b, _service, _ta, _tb = pins
    if extra in ("pin", "both"):
        toggle(a)
    if extra in ("reference", "both"):
        write(
            a,
            "INSERT INTO refs(paper_id,ref_paper_id,influential) VALUES(?,?,?)",
            ("a-source", "a-target", 1),
        )
    before = a.journal.pending()
    root = tmp_path / "pdf"
    root.mkdir()
    pdf(root / "a-source.pdf", "The method uses an earlier approach [1].")
    monkeypatch.setattr(store, "DB_PATH", a.journal.path)
    monkeypatch.setattr(store, "ensure_dirs", lambda: None)
    monkeypatch.setattr(config, "PDF_DIR", root)
    monkeypatch.setattr(config, "TEXT_DIR", root)
    monkeypatch.setattr(crossref, "reference_list", lambda _: {"1": {"title": "Earlier method"}})
    monkeypatch.setattr(s2, "references", lambda _: [])
    monkeypatch.setattr(s2, "papers_by_doi", lambda _: {})
    calls = []

    def answer(*args, **kwargs):
        calls.append(args[0])
        return json.dumps(
            [
                {
                    "key": "1",
                    "title": "Earlier method",
                    "purpose": "Baseline",
                    "gist": "An earlier approach",
                    "verdict": "值得",
                    "why": "Explains the method",
                }
            ]
        ), "ok"

    monkeypatch.setattr(llm, "complete", answer)
    assert cites.analyse("a-source") == 1 and len(calls) == 1
    assert query(a, "SELECT ref_key FROM cites") == [("1",)]
    assert a.journal.pending()[: len(before)] == before
    with closing(generation._connect(a.journal.path)) as conn:
        receipt = dict(conn.execute("SELECT * FROM research_compound_requests").fetchone())
        compound.validate_request_record(receipt)
        assert cites.coverage(conn, "a-source", verify_source=True)["state"] == "complete"
        original = json.loads(receipt["context_json"])
        assert original["tokens"] == {}

    # An explicit user deletion remains a tombstone, even on a manual retry.
    with store.connect(path=a.journal.path) as conn:
        observed = observe_target(conn, "paper", "a-source", "citation", "1")
        with expecting(conn, [observed]):
            conn.execute("DELETE FROM cites WHERE paper_id='a-source' AND ref_key='1'")
    deleted_pending = a.journal.pending()
    assert cites.analyse("a-source") == 0 and len(calls) == 2
    assert query(a, "SELECT * FROM cites") == []
    assert a.journal.pending() == deleted_pending
    with closing(generation._connect(a.journal.path)) as conn:
        retained = conn.execute(
            "SELECT * FROM research_compound_requests WHERE status='candidate'"
        ).fetchone()
        compound.validate_request_record(dict(retained))
        context = json.loads(retained["context_json"])
        assert len(context["tokens"]) == 1
        assert next(iter(context["tokens"].values()))["active"] is False
