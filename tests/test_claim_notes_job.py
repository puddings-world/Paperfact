"""Core-claim cards use captured originals and never overwrite edits or another workspace."""

import json

import pymupdf
import pytest
from test_sync_capture import bound as _bound

from paper_daily import (
    claim_notes,
    claims,
    llm,
    manual_highlight_ops,
    pdf_highlights,
    store,
    sync_capture,
)
from paper_daily.desktop.main import Data
from paper_daily.document_reader import from_workspace
from paper_daily.fetch import _safe_name

bound = _bound

PID = "fixture:core"
QUOTES = [
    "The study compares three independent cohorts.",
    "The treatment improved accuracy under a matched budget.",
    "The conclusion is limited to the measured population.",
]


@pytest.fixture(params=["local", "enrolled"])
def source(request, tmp_path, monkeypatch):
    if request.param == "enrolled":
        request.getfixturevalue("bound")
    else:
        monkeypatch.setattr(store, "DB_PATH", tmp_path / "papers.db")
        monkeypatch.setattr(store, "ensure_dirs", lambda: None)
        store.init_db()
    path = tmp_path / (_safe_name(PID) + ".pdf")
    anchors = []
    with pymupdf.open() as pdf:
        for i, quote in enumerate(QUOTES):
            page = pdf.new_page()
            page.insert_text((40, 80), quote, fontsize=10)
            anchors.append(dict(p0=i, p1=i, o0=0, o1=len(page.get_text("words")) - 1))
        pdf.save(path)
    digest = pdf_highlights.document_hash(path)
    with store.connect() as conn:
        store.upsert_papers(
            conn, [dict(id=PID, title="Core claims", venue="Fixture", year=2026, source="fixture")]
        )
    with store.connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        observations = [
            sync_capture.observe_target(conn, "paper", PID, "ai_highlight", digest + ":" + str(i))
            for i in range(len(QUOTES))
        ]
        with sync_capture.expecting(conn, observations):
            for i, quote in enumerate(QUOTES):
                conn.execute(
                    "INSERT INTO pdf_ai_highlights(paper_id,document_hash,source_key,"
                    "analysis_hash,anchor,quote,reason) VALUES(?,?,?,?,?,?,?)",
                    (PID, digest, str(i), "a" * 64, json.dumps(anchors[i]), quote, "Evidence"),
                )
            conn.commit()
    document = from_workspace(store.DB_PATH, legacy_root=tmp_path).resolve(PID)
    assert document.available
    owner = manual_highlight_ops.capture_owner(store.DB_PATH, PID)
    job = claim_notes.ClaimNotesJob(owner, document, llm.capture_connections(), None)
    return job, path


def notes(job):
    with store.connect(path=job.owner.database) as conn:
        return [dict(row) for row in conn.execute("SELECT * FROM notes ORDER BY id")]


def reply(*args, **kwargs):
    return json.dumps(
        {"claims": [dict(id=1, claim="Main finding", explain="Bounded evidence")]}
    ), "ok"


def test_generated_cards_keep_exact_source_and_edited_cards_survive_refresh(source, monkeypatch):
    job, _ = source
    monkeypatch.setattr(llm, "complete", reply)
    with claim_notes.scope(job):
        assert claims.write(PID) == (1, "")
    row = notes(job)[0]
    assert row["kind"] == "claim" and row["page"] == 2
    assert json.loads(row["anchor"])["document_hash"] == job.document.sha256
    assert QUOTES[1] in row["body"]
    data = Data()
    expected = data.note_for_edit(PID, row["id"])
    data.update_note(row["id"], row["body"] + " my edit", expected=expected)
    assert job.run(force=True) == (1, "")
    assert any(r["body"].endswith("my edit") for r in notes(job))


@pytest.mark.parametrize("change", ["pdf", "highlights", "paper"])
def test_changed_input_during_model_never_publishes_cards(source, monkeypatch, change):
    job, path = source

    def changed(*args, **kwargs):
        if change == "pdf":
            path.write_bytes(path.read_bytes() + b"changed")
        else:
            with store.connect(path=job.owner.database) as conn:
                conn.execute("BEGIN IMMEDIATE")
                observations = [
                    sync_capture.observe_content(conn, "pdf_ai_highlights", dict(row))
                    for row in conn.execute("SELECT * FROM pdf_ai_highlights")
                ]
                with sync_capture.expecting(conn, observations):
                    conn.execute(
                        "UPDATE pdf_ai_highlights SET reason='changed'"
                        if change == "highlights"
                        else "UPDATE papers SET title='changed'"
                    )
                    conn.commit()
        return reply()

    monkeypatch.setattr(llm, "complete", changed)
    with pytest.raises(ValueError):
        job.run()
    assert notes(job) == []


def test_switching_global_workspace_during_model_still_saves_only_captured_paper(
    source, monkeypatch, tmp_path
):
    job, _ = source

    def switched(*args, **kwargs):
        monkeypatch.setattr(store, "DB_PATH", tmp_path / "other.db")
        store.init_db()
        return reply()

    monkeypatch.setattr(llm, "complete", switched)
    assert job.run() == (1, "")
    assert len(notes(job)) == 1
    with store.connect() as conn:
        assert conn.execute("SELECT count(*) FROM notes").fetchone()[0] == 0


def test_bad_source_anchor_refuses_before_model_and_failed_model_keeps_existing_cards(
    source, monkeypatch
):
    job, _ = source
    monkeypatch.setattr(llm, "complete", reply)
    assert job.run()[0] == 1
    saved = notes(job)
    monkeypatch.setattr(llm, "complete", lambda *a, **k: (None, "unavailable"))
    assert job.run(force=True) == (0, "unavailable")
    assert notes(job) == saved
    # Simulate corrupt persisted bytes from outside the admitted producer.
    with store.connect(path=job.owner.database) as conn, sync_capture.suppress_capture(conn):
        conn.execute("UPDATE pdf_ai_highlights SET anchor='{}'")
        conn.commit()
    monkeypatch.setattr(
        llm, "complete", lambda *a, **k: pytest.fail("Invalid source must not call AI")
    )
    with pytest.raises(ValueError):
        job.run(force=True)
    assert notes(job) == saved


def test_claim_source_uses_the_same_cross_line_hyphen_mapping_as_highlights(tmp_path):
    from types import SimpleNamespace

    path = tmp_path / "hyphen.pdf"
    with pymupdf.open() as pdf:
        page = pdf.new_page()
        page.insert_text((40, 80), "The method improves classifi-\ncation under a matched budget.")
        anchor = dict(p0=0, p1=0, o0=0, o1=len(page.get_text("words")) - 1)
        pdf.save(path)
    document = SimpleNamespace(path=path, sha256=pdf_highlights.document_hash(path))
    job = claim_notes.ClaimNotesJob(None, document, None, None)
    marks = [
        dict(
            quote="The method improves classification under a matched budget.",
            anchor=json.dumps(anchor),
            reason="Evidence",
            kind="",
        )
    ]
    assert job._verified_marks(marks) == marks
