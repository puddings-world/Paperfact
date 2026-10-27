"""Actual multi-row producers preserve all outputs, their bases, and original workspace."""

import json
import sqlite3
from contextlib import closing

import pytest
from test_research_generation import rows
from test_research_generation import workspace as workspace

from paper_daily import cites, config, followups, llm, resources, store
from paper_daily import research_compound as compound
from paper_daily import research_generation as generation
from paper_daily.enrich import s2
from paper_daily.sources import crossref
from paper_daily.sync_capture import StaleCaptureError


def begin(path, phase, key=None):
    with closing(generation._connect(path)) as conn:
        return compound.begin(conn, phase=phase, owner_id="paper", key=key)


def seed(path, phase, key="old", edited=0):
    context = begin(path, phase)
    if phase == "resources":
        key = "https://github.com/example/" + key
        value = compound.row(context, key, kind="code", source="pdf", own=1)
        completion = "text"
    elif phase == "citations":
        value = compound.row(context, key, title="Original", basis="context", edited=edited)
        completion = None
    else:
        value = compound.row(context, key, title="Original", edited=edited, citations=9)
        completion = None
    assert compound.publish(context, puts=[value], completion=completion).status == "accepted"
    return key


@pytest.fixture
def driver(workspace, monkeypatch):
    path, client, document = workspace
    root = document.path.parent
    monkeypatch.setattr(config, "PDF_DIR", root)
    monkeypatch.setattr(config, "TEXT_DIR", root)
    monkeypatch.setattr(resources, "PDF_DIR", root)
    monkeypatch.setattr(resources, "TEXT_DIR", root)
    monkeypatch.setattr(
        crossref,
        "reference_list",
        lambda _: {"1": {"title": "First", "year": 2025}, "2": {"title": "Second", "year": 2024}},
    )
    monkeypatch.setattr(s2, "references", lambda _: [])
    monkeypatch.setattr(s2, "papers_by_doi", lambda _: {})
    monkeypatch.setattr(followups, "work_id", lambda _: "W0")
    monkeypatch.setattr(followups, "_citing_s2", lambda _: [])
    monkeypatch.setattr(resources, "_hugging_face", lambda *_: [])
    monkeypatch.setattr(
        resources,
        "_search",
        lambda *_: [
            {"url": "https://github.com/example/one", "own": True},
            {"url": "https://github.com/example/two", "own": True},
        ],
    )
    calls = []

    def install(phase, hook=lambda: None):
        calls.clear()
        if phase == "judge":
            seed(path, "fetch", "one")
            seed(path, "fetch", "two")
        once = False

        def run_hook():
            nonlocal once
            calls.append(phase)
            if not once:
                once = True
                hook()

        if phase == "fetch":

            def external(_):
                run_hook()
                return [
                    {"id": "one", "title": "First", "citations": 5},
                    {"id": "two", "title": "Second", "citations": 2},
                ]

            monkeypatch.setattr(followups, "_citing_openalex", external)
        elif phase == "resources":

            def repo(url):
                run_hook()
                return {"url": url, "alive": True, "stars": 3}

            monkeypatch.setattr(resources, "_repo", repo)
        else:

            def complete(*args, **kwargs):
                run_hook()
                if phase == "citations":
                    answer = [
                        {
                            "key": str(i),
                            "title": title,
                            "purpose": "Evidence",
                            "gist": "Method",
                            "verdict": followups.VERDICTS[0],
                            "why": "Core",
                        }
                        for i, title in [(1, "First"), (2, "Second")]
                    ]
                else:
                    answer = [
                        {
                            "id": i,
                            "relation": "Extension",
                            "verdict": followups.VERDICTS[0],
                            "why": "Core",
                        }
                        for i in range(2)
                    ]
                return json.dumps(answer), "ok"

            monkeypatch.setattr(llm, "complete", complete)

    def invoke(phase):
        if phase == "citations":
            return cites.analyse("paper")
        if phase == "fetch":
            return followups.fetch("paper")
        if phase == "judge":
            return followups.judge("paper")[0]
        with store.connect() as conn:
            return resources.find(conn, "paper")

    return path, client, document, calls, install, invoke


@pytest.mark.parametrize("phase", ["citations", "fetch", "judge", "resources"])
def test_real_phase_accepts_complete_group_and_receipt(driver, phase):
    path, client, document, calls, install, invoke = driver
    install(phase)
    before = len(client.journal.pending()) if client else 0
    assert invoke(phase) == 2
    table = compound.PHASES[phase]
    saved = rows(path, f"SELECT * FROM {table}")
    assert len(saved) == 2
    receipts = rows(path, "SELECT * FROM research_compound_requests")
    latest = receipts[-1]
    compound.validate_request_record(latest)
    context = compound.Context(latest["context_json"])
    assert compound.retry_publication(context).status == "accepted"
    assert len(rows(path, "SELECT * FROM research_compound_requests")) == len(receipts)
    assert calls
    if client:
        delta = client.journal.pending()[before:]
        assert len(delta) == 2
        assert all(op["entity_type"] == "research_content" for op in delta)
        expected_hash = document.sha256 if phase in ("citations", "resources") else None
        assert all(op["payload"]["source_document_hash"] == expected_hash for op in delta)
    if phase == "fetch":
        assert rows(path, "SELECT value FROM kv WHERE key='followups.checked.paper'")


@pytest.mark.parametrize("phase", ["citations", "fetch", "judge", "resources"])
def test_changed_inventory_retains_whole_group_without_partial_or_flag(driver, phase):
    path, client, _doc, _calls, install, invoke = driver

    def concurrent():
        seed(path, "fetch" if phase == "judge" else phase, "concurrent")

    install(phase, concurrent)
    if phase == "resources":
        with pytest.raises(StaleCaptureError):
            invoke(phase)
    else:
        assert invoke(phase) == 0
    record = rows(path, "SELECT * FROM research_compound_requests WHERE status='candidate'")[0]
    assert len(json.loads(record["mutations_json"])["puts"]) == 2
    table = compound.PHASES[phase]
    current = rows(path, f"SELECT * FROM {table}")
    assert len(current) == (3 if phase == "judge" else 1)
    if phase == "judge":
        assert all(row["relation"] is None for row in current)
    if phase == "fetch":
        assert rows(path, "SELECT * FROM kv WHERE key='followups.checked.paper'") == []
    if client:
        assert not any(
            op["payload"].get("data", {}).get("relation") == "Extension"
            for op in client.journal.pending()
        )


@pytest.mark.parametrize("phase", ["citations", "fetch", "judge", "resources"])
def test_actual_storage_failure_rolls_back_group_outbox_and_completion(driver, phase):
    path, client, _doc, calls, install, invoke = driver
    install(phase)
    table = compound.PHASES[phase]
    key = compound.TABLES[table][1]
    failure_key = {"citations": "2", "resources": "https://github.com/example/two"}.get(
        phase, "two"
    )
    before = rows(path, f"SELECT * FROM {table}")
    pending = client.journal.pending() if client else None
    with closing(sqlite3.connect(path)) as conn, conn:
        conn.execute(
            f"CREATE TRIGGER reject_second BEFORE INSERT ON {table} "
            f"WHEN NEW.{key}='{failure_key}' BEGIN SELECT RAISE(ABORT,'fixture disk'); END"
        )
    if phase == "resources":
        with pytest.raises(StaleCaptureError):
            invoke(phase)
    else:
        assert invoke(phase) == 0
    assert rows(path, f"SELECT * FROM {table}") == before
    if client:
        assert client.journal.pending() == pending
    records = compound.list_recovery_requests(path)
    assert len(records) == 1
    context = compound.Context(records[0]["context_json"])
    call_count = len(calls)
    for _ in range(2):
        assert compound.retry_publication(context).candidate_id == records[0]["candidate_id"]
    assert len(calls) == call_count
    assert len(json.loads(records[0]["mutations_json"])["puts"]) == 2


@pytest.mark.parametrize("phase", ["citations", "fetch", "judge", "resources"])
def test_workspace_and_provider_switch_do_not_redirect_work(driver, monkeypatch, phase):
    path, _client, _doc, _calls, install, invoke = driver
    other = path.with_name("other.sqlite")
    with closing(sqlite3.connect(other)) as conn:
        conn.executescript(store.SCHEMA)
    monkeypatch.setattr(llm, "SETTINGS_PATH", path.with_name("ai.json"))
    llm.save_settings(backend="codex", model="first", account_id="1" * 32)

    def switch():
        monkeypatch.setattr(store, "DB_PATH", other)
        llm.save_settings(backend="codex", model="second", account_id="2" * 32)
        if phase != "resources":
            assert (llm.settings().model, llm.settings().account_id) == ("first", "1" * 32)

    install(phase, switch)
    assert invoke(phase) == 2
    assert len(rows(path, f"SELECT * FROM {compound.PHASES[phase]}")) == 2
    assert rows(other, f"SELECT * FROM {compound.PHASES[phase]}") == []


@pytest.mark.parametrize("phase", ["citations", "fetch", "judge", "resources"])
def test_duplicate_activation_does_not_start_another_external_job(driver, phase):
    _path, _client, _doc, calls, install, invoke = driver
    nested = []
    install(phase, lambda: nested.append(invoke(phase)))
    assert invoke(phase) == 2
    assert nested == [0]
    assert len(calls) == (2 if phase == "resources" else 1)


@pytest.mark.parametrize("phase", ["citations", "resources"])
def test_pdf_replacement_retains_original_source_provenance(driver, phase):
    from test_research_generation import pdf

    path, _client, document, _calls, install, invoke = driver
    install(phase, lambda: pdf(document.path, "Replacement document"))
    if phase == "resources":
        with pytest.raises(StaleCaptureError):
            invoke(phase)
    else:
        assert invoke(phase) == 0
    record = rows(path, "SELECT * FROM research_compound_requests WHERE status='candidate'")[0]
    assert json.loads(record["context_json"])["document"]["sha256"] == document.sha256
    assert rows(path, f"SELECT * FROM {compound.PHASES[phase]}") == []


@pytest.mark.parametrize("phase,kind", [("citations", "ref"), ("fetch", "followup")])
def test_manual_items_keep_loaded_base_and_each_changed_stale_draft(driver, phase, kind):
    path, _client, _doc, _calls, install, invoke = driver
    install(phase)
    assert invoke(phase) == 2
    key = "1" if kind == "ref" else "one"
    with store.connect() as conn:
        expected = followups.item_edit_snapshot(conn, "paper", kind, key)
    writer = followups.edit_reference if kind == "ref" else followups.edit_followup
    writer("paper", key, why="Newer manual edit")
    identifiers = {}
    for body in ["Draft A", "Draft B", "Draft A", "Draft B"]:
        with pytest.raises(StaleCaptureError) as error:
            writer("paper", key, expected=expected, why=body)
        assert identifiers.setdefault(body, error.value.candidate_id) == error.value.candidate_id
    assert len(set(identifiers.values())) == 2
    assert rows(
        path,
        f"SELECT why FROM {compound.PHASES[phase]} "
        f"WHERE {compound.TABLES[compound.PHASES[phase]][1]}='{key}'",
    ) == [{"why": "Newer manual edit"}]


def test_resources_do_not_commit_callers_pending_work(workspace, monkeypatch):
    path, _client, _doc = workspace
    monkeypatch.setattr(resources, "_search", lambda *_: pytest.fail("no external work"))
    with store.connect() as conn:
        conn.execute("UPDATE papers SET title='Unsaved' WHERE id='paper'")
        with pytest.raises(ValueError, match="Commit pending"):
            resources.find(conn, "paper")
        conn.rollback()
    assert rows(path, "SELECT title FROM papers") == [{"title": "Paper"}]


def test_unbound_identical_delete_recreate_invalidates_observation(tmp_path, monkeypatch):
    path = tmp_path / "research.sqlite"
    monkeypatch.setattr(store, "DB_PATH", path)
    monkeypatch.setattr(store, "ensure_dirs", lambda: None)
    with closing(sqlite3.connect(path)) as conn, conn:
        conn.executescript(store.SCHEMA)
        conn.execute(
            "INSERT INTO papers(id,title,title_key,venue,year,source) "
            "VALUES('paper','Paper','paper','X',2026,'test')"
        )
    context = begin(path, "fetch")
    original = rows(path, "SELECT * FROM papers")[0]
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
    result = compound.publish(
        context, puts=[compound.row(context, "new", title="New")], completion=context.started_at
    )
    assert result.status == "candidate" and "lifecycle" in result.reason
    assert rows(path, "SELECT * FROM followups") == []
