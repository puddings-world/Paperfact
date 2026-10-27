"""Compound boundaries preserve unrelated data and reject malformed/rebound work."""

import json
import sqlite3
from contextlib import closing

import pytest
from test_research_compound import begin, seed
from test_research_compound import driver as driver
from test_research_generation import rows
from test_research_generation import workspace as workspace

from paper_daily import cites, followups, llm, resources, store
from paper_daily import research_compound as compound
from paper_daily.sync_capture import StaleCaptureError


def test_reanalysis_prunes_generated_noise_but_preserves_manual_reference(driver):
    path, _client, _doc, _calls, install, invoke = driver
    seed(path, "citations", "noise")
    seed(path, "citations", "curated", edited=1)
    install("citations")
    assert invoke("citations") == 2
    assert {r["ref_key"] for r in rows(path, "SELECT * FROM cites")} == {"1", "2", "curated"}
    assert rows(path, "SELECT edited,title FROM cites WHERE ref_key='curated'") == [
        {"edited": 1, "title": "Original"}
    ]


def test_manual_reference_does_not_conflict_with_unrelated_reference(driver):
    path, _client, _doc, _calls, install, invoke = driver
    install("citations")
    invoke("citations")
    with store.connect() as conn:
        expected = followups.item_edit_snapshot(conn, "paper", "ref", "1")
    followups.edit_reference("paper", "2", why="Unrelated edit")
    followups.edit_reference("paper", "1", expected=expected, why="My edit")
    assert rows(path, "SELECT why FROM cites ORDER BY ref_key") == [
        {"why": "My edit"},
        {"why": "Unrelated edit"},
    ]


def test_full_phase_does_not_conflict_with_another_feature(driver):
    path, _client, _doc, _calls, install, invoke = driver
    install("citations", lambda: seed(path, "fetch", "new-followup"))
    assert invoke("citations") == 2
    assert len(rows(path, "SELECT * FROM followups")) == 1


def test_replaced_database_receives_no_old_candidate_tables(driver):
    path, _client, _doc, _calls, install, invoke = driver
    replacement = path.with_name("replacement.sqlite")
    with closing(sqlite3.connect(replacement)) as conn:
        conn.executescript(store.SCHEMA)

    def replace():
        path.replace(path.with_name("previous.sqlite"))
        replacement.replace(path)

    install("citations", replace)
    assert invoke("citations") == 0
    assert rows(path, "SELECT * FROM cites") == []
    assert rows(path, "SELECT name FROM sqlite_master WHERE name LIKE 'research_%'") == []
    # The retained result belongs to the original inode/binding, not the replacement.
    candidates = list(path.parent.glob(".paperfact-compound/*/*.json"))
    assert len(candidates) == 1
    record = compound.validate_request_record(json.loads(candidates[0].read_text(encoding="utf-8")))
    assert record["status"] == "candidate"


@pytest.mark.parametrize("phase", ["citations", "fetch", "judge", "resources"])
def test_cancelled_external_work_does_not_publish_partial_research(driver, phase):
    path, _client, _doc, _calls, install, invoke = driver

    def cancel():
        raise RuntimeError("cancelled fixture job")

    install(phase, cancel)
    before = rows(path, f"SELECT * FROM {compound.PHASES[phase]}")
    with pytest.raises(RuntimeError, match="cancelled fixture job"):
        invoke(phase)
    assert rows(path, f"SELECT * FROM {compound.PHASES[phase]}") == before


def test_legacy_text_replacement_is_not_applied_to_new_document(driver, monkeypatch):
    path, _client, document, _calls, install, invoke = driver
    document.path.unlink()
    text = document.path.with_suffix(".txt")
    text.write_text("Original source", encoding="utf-8")
    install("citations", lambda: text.write_text("Changed source", encoding="utf-8"))
    assert invoke("citations") == 0
    assert rows(path, "SELECT * FROM cites") == []
    record = rows(path, "SELECT * FROM research_compound_requests WHERE status='candidate'")[0]
    assert json.loads(record["context_json"])["document"] is None
    assert json.loads(record["context_json"])["text_source"]["sha256"]


def test_missing_managed_document_never_reads_old_pdf_alias(tmp_path, monkeypatch):
    from test_document_reader import LOCAL, prepared, register

    path, journal, blob_store, reader, alias, _data = prepared(tmp_path)
    register(path, journal, blob_store, reader)
    from paper_daily.sync_documents import desired_document

    with journal.transaction() as conn:
        target = desired_document(conn, reader.inspect(LOCAL).paper_id)
    for item in (blob_store.root / "objects").rglob(target["sha256"]):
        item.unlink()
    # Removing applied binding guarantees unavailable even while the legacy alias exists.
    with journal.transaction() as conn:
        conn.execute("DELETE FROM research_document_applied")
    monkeypatch.setattr(store, "DB_PATH", path)
    monkeypatch.setattr(llm, "complete", lambda *_a, **_k: pytest.fail("no AI without managed PDF"))
    assert alias.exists()
    with pytest.raises(ValueError, match="PDF is unavailable"):
        cites.analyse(LOCAL)


def test_followup_pipeline_keeps_original_workspace(driver, monkeypatch):
    from paper_daily import citegraph

    path, _client, _doc, _calls, install, _invoke = driver
    other = path.with_name("other.sqlite")
    with closing(sqlite3.connect(other)) as conn:
        conn.executescript(store.SCHEMA)
    install("fetch", lambda: monkeypatch.setattr(store, "DB_PATH", other))

    def complete(_prompt, *, task, **_kwargs):
        if task == "overview":
            return json.dumps({"summary": "Context", "reading": []}), "ok"
        return json.dumps(
            [{"id": 0, "relation": "Extension", "verdict": followups.VERDICTS[0], "why": "Useful"}]
        ), "ok"

    monkeypatch.setattr(llm, "complete", complete)
    monkeypatch.setattr(
        citegraph, "links", lambda *_: pytest.fail("legacy graph writer cannot redirect")
    )
    assert followups.analyse("paper") == 1
    assert rows(other, "SELECT * FROM followups") == []
    assert rows(path, "SELECT summary FROM paper_context") == [{"summary": "Context"}]


def test_request_validator_rejects_arbitrary_mutation_fields_and_owner(driver):
    path, _client, _doc, _calls, install, invoke = driver
    install("fetch")
    invoke("fetch")
    record = rows(path, "SELECT * FROM research_compound_requests")[-1]
    for change in ("sql", "owner", "path"):
        malformed = dict(record)
        if change == "path":
            context = json.loads(record["context_json"])
            context["db_path"] = "../unrelated.sqlite"
            malformed["context_json"] = json.dumps(context)
        else:
            mutation = json.loads(record["mutations_json"])
            if change == "sql":
                mutation["sql"] = "DELETE FROM papers"
            else:
                mutation["puts"][0]["paper_id"] = "other"
            malformed["mutations_json"] = json.dumps(mutation)
        with pytest.raises(ValueError):
            compound.validate_request_record(malformed)


@pytest.mark.parametrize("phase", ["citations", "resources"])
def test_failure_after_pruning_restores_old_rows_and_outbox(driver, phase):
    path, client, _doc, _calls, install, invoke = driver
    seed(path, phase, "old-generated")
    install(phase)
    table, column = compound.PHASES[phase], compound.TABLES[compound.PHASES[phase]][1]
    before = rows(path, f"SELECT * FROM {table}")
    pending = client.journal.pending() if client else None
    key = "2" if phase == "citations" else "https://github.com/example/two"
    with closing(sqlite3.connect(path)) as conn, conn:
        conn.execute(
            f"CREATE TRIGGER stop_second BEFORE INSERT ON {table} "
            f"WHEN NEW.{column}='{key}' BEGIN SELECT RAISE(ABORT,'fixture disk'); END"
        )
    if phase == "resources":
        with pytest.raises(StaleCaptureError):
            invoke(phase)
    else:
        assert invoke(phase) == 0
    assert rows(path, f"SELECT * FROM {table}") == before
    if client:
        assert client.journal.pending() == pending
    retained = compound.list_recovery_requests(path)
    assert len(json.loads(retained[0]["mutations_json"])["deletes"]) == 1


def test_resource_discovery_keeps_explicitly_curated_links(driver):
    path, _client, _doc, _calls, install, invoke = driver
    context = begin(path, "resources")
    url = "https://github.com/example/manual"
    output = compound.row(context, url, kind="code", source="manual", own=1, note="My note")
    assert compound.publish(context, puts=[output], completion="notext").status == "accepted"
    install("resources")
    assert invoke("resources") == 2
    assert rows(path, "SELECT note,source FROM resources WHERE source='manual'") == [
        {"note": "My note", "source": "manual"}
    ]
    assert len(rows(path, "SELECT * FROM resources")) == 3


def test_resource_url_case_replacement_does_not_leave_duplicate_rows(driver, monkeypatch):
    path, _client, _doc, _calls, install, invoke = driver
    seed(path, "resources", "one")
    install("resources")
    previous = resources._repo

    def repo(url):
        result = previous(url)
        result["url"] = url.replace("/one", "/One")
        return result

    monkeypatch.setattr(resources, "_repo", repo)
    assert invoke("resources") == 2
    assert {r["url"] for r in rows(path, "SELECT url FROM resources")} == {
        "https://github.com/example/One",
        "https://github.com/example/two",
    }


def test_in_memory_resource_work_stays_inside_callers_transaction(tmp_path, monkeypatch):
    from test_resources import _db

    monkeypatch.setattr(resources, "PDF_DIR", tmp_path)
    monkeypatch.setattr(resources, "TEXT_DIR", tmp_path)
    monkeypatch.setattr(
        resources, "_search", lambda *_: [{"url": "https://github.com/example/repo", "own": True}]
    )
    monkeypatch.setattr(resources, "_repo", lambda url: {"url": url, "alive": True})
    conn = _db()
    try:
        assert conn.in_transaction
        assert resources.find(conn, "ref:brain") == 1
        assert conn.in_transaction
        conn.rollback()
        assert conn.execute("SELECT COUNT(*) FROM resources").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM papers").fetchone()[0] == 0
    finally:
        conn.close()


@pytest.mark.parametrize("workspace", [False], indirect=True)
@pytest.mark.parametrize("phase", ["fetch", "judge"])
def test_followup_pipeline_does_not_continue_into_recreated_parent(driver, monkeypatch, phase):
    path, _client, _doc, _calls, install, _invoke = driver
    original = rows(path, "SELECT * FROM papers")[0]

    def recreate():
        with store.connect() as conn:
            conn.execute("DELETE FROM papers WHERE id='paper'")
            conn.execute(
                "INSERT INTO papers("
                + ",".join(original)
                + ") VALUES("
                + ",".join("?" for _ in original)
                + ")",
                tuple(original.values()),
            )

    install("fetch", recreate if phase == "fetch" else lambda: None)

    def complete(_prompt, *, task, **_kwargs):
        assert phase == "judge" and task == "followups", "No later stage may target recreated owner"
        recreate()
        return json.dumps(
            [{"id": 0, "relation": "Extension", "verdict": followups.VERDICTS[0], "why": "Useful"}]
        ), "ok"

    monkeypatch.setattr(llm, "complete", complete)
    messages = []
    assert followups.analyse("paper", messages.append) == 0
    assert any("remaining phases skipped" in message for message in messages)
    assert rows(path, "SELECT * FROM paper_context") == []
    assert all(row["relation"] is None for row in rows(path, "SELECT * FROM followups"))


@pytest.mark.parametrize("workspace", [True], indirect=True)
def test_large_feature_refresh_retains_every_row_and_has_retry_safe_outbox(workspace, monkeypatch):
    path, client, _document = workspace
    works = [{"id": f"W{i}", "title": f"Work {i}", "citations": i} for i in range(200)]
    monkeypatch.setattr(followups, "work_id", lambda _: "root")
    monkeypatch.setattr(followups, "_citing_openalex", lambda _: works)
    monkeypatch.setattr(followups, "_citing_s2", lambda _: [])
    assert followups.fetch("paper") == 200
    for work in works:
        work["citations"] += 1
    assert followups.fetch("paper") == 200
    assert len(rows(path, "SELECT * FROM followups")) == 200
    records = rows(path, "SELECT * FROM research_compound_requests")
    assert len(records) == 2 and all(r["status"] == "accepted" for r in records)
    pending = client.journal.pending(limit=1000)
    assert len([op for op in pending if op["entity_type"] == "research_content"]) == 400
    assert (
        compound.retry_publication(compound.Context(records[-1]["context_json"])).status
        == "accepted"
    )
    assert client.journal.pending(limit=1000) == pending
