"""Phase-one saved-reader contracts; no UI activation or real providers."""

import dataclasses
import hashlib
import json
import os
import shutil
import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from copy import deepcopy
from types import SimpleNamespace
from uuid import uuid4

import pytest
from test_annotation_content import EXAMPLES
from test_research_generation import BODY, STAMP
from test_research_generation import workspace as _workspace

from paper_daily import (
    annotation_content,
    closeread,
    file_change,
    llm,
    manual_highlight_ops,
    research_chat,
    store,
    sync_capture,
)
from paper_daily import reader_saved_inputs as saved
from paper_daily import research_generation as generation
from paper_daily.desktop import main
from paper_daily.desktop import reader_saved_render as render

workspace = _workspace


def work(call, *args, **kwargs):
    with ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(call, *args, **kwargs).result(timeout=10)


def test_empty_saved_snapshot_is_explicit_and_read_only(workspace):
    from paper_daily import reader_saved_inputs as saved

    database, _client, document = workspace
    owner = manual_highlight_ops.capture_owner(database, "paper")
    request = saved.capture(
        owner, document=document, native_source_version=file_change.version(document.path)
    )
    snapshot = work(saved.read, request, document=document)
    assert snapshot.chat_snapshot["rows"] == []
    assert snapshot.data["annotations"]["highlight_analysis"]["known"] is False
    assert snapshot.data["source"]["document_hash"] == document.sha256
    assert work(saved.current, snapshot, document=document)


def test_read_and_markdown_preparation_refuse_gui_thread(workspace):
    from paper_daily import reader_saved_inputs as saved
    from paper_daily.desktop import reader_saved_render as render

    database, _client, document = workspace
    owner = manual_highlight_ops.capture_owner(database, "paper")
    request = saved.capture(owner)
    with pytest.raises(RuntimeError, match="worker"):
        saved.read(request)
    snapshot = work(saved.read, request)
    with pytest.raises(RuntimeError, match="worker"):
        render.render(snapshot, {})


def owner_request(workspace, source=True):
    database, _client, document = workspace
    owner = manual_highlight_ops.capture_owner(database, "paper")
    return saved.capture(
        owner,
        document=document if source else None,
        native_source_version=file_change.version(document.path) if source else None,
    ), document if source else None


def snapshot(workspace, source=True):
    request, document = owner_request(workspace, source)
    return work(saved.read, request, document=document)


def turn(workspace, question="Question <unsafe>", answer="**Answer**"):
    with closing(generation._connect(workspace[0])) as conn:
        request = research_chat.begin_chat(
            conn,
            paper_id="paper",
            question=question,
            request_id=str(uuid4()),
            document=workspace[2],
        )
    request, _prompt = research_chat.prepare_chat(request)
    if answer is not None:
        assert research_chat.publish_answer(request, answer).status == "accepted"
    return request


def modify(database, sql, args=()):
    with closing(generation._connect(database)) as conn, sync_capture.suppress_capture(conn):
        conn.execute(sql, args)
        conn.commit()


def add_annotation(workspace, feature, body=None, digest=None, source_hash="a" * 64):
    body = deepcopy(EXAMPLES[feature]) if body is None else body
    modify(
        workspace[0],
        f"INSERT INTO {annotation_content.FEATURES[feature]} VALUES(?,?,?,?,?)",
        ("paper", json.dumps(body), source_hash, digest or workspace[2].sha256, STAMP),
    )


def disk_hashes(root):
    return {
        p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in root.rglob("*")
        if p.is_file() and not p.name.endswith(("-wal", "-shm"))
    }


def test_actual_saved_producers_render_with_stable_delete_observations(workspace):
    assert closeread.write("paper")[0] == BODY
    turn(workspace)
    pending = turn(workspace, question="Pending", answer=None)
    actual = main.Data().chat_snapshot("paper")
    value = snapshot(workspace)
    assert value.chat_snapshot == actual
    assert value.data["pending"][0]["request_id"] == pending.request_id
    prepared = work(render.render, value, main.LIGHT, rich=False)
    assert "<b>Answer</b>" in prepared.chat_html
    assert "Question &lt;unsafe&gt;" in prepared.chat_html
    assert "Pending" in prepared.chat_html and pending.request_id in prepared.chat_html
    assert "resumeqa:" in prepared.chat_html and "delq:" in prepared.chat_html
    assert "Methods" in prepared.dive_html
    assert prepared.snapshot is value
    ids = [item["row"]["id"] for item in actual["rows"][:2]]
    expected = {**value.chat_snapshot, "rows": value.chat_snapshot["rows"][:2]}
    main.Data().delete_chat(ids, expected=expected)
    with closing(generation._connect(workspace[0])) as conn:
        assert [row["body"] for row in research_chat.history(conn, "paper")] == ["Pending"]
    assert not work(saved.current, value, document=workspace[2])


def test_reads_and_render_do_not_write_or_consult_global_workspace_or_accounts(
    workspace,
    tmp_path,
    monkeypatch,
):
    turn(workspace)
    assert closeread.write("paper")[0]
    request, document = owner_request(workspace)
    cache = tmp_path / "legacy-cache"
    cache.mkdir()
    (cache / "unknown.json").write_text('{"unverified":true}')
    before = disk_hashes(tmp_path)
    with closing(sqlite3.connect(workspace[0])) as conn:
        before_dump = "\n".join(conn.iterdump())
    other = tmp_path / "must-not-create.sqlite"
    monkeypatch.setattr(store, "DB_PATH", other)

    def forbidden(*args, **kwargs):
        pytest.fail("Saved preparation invoked a global reader, writer or provider")

    monkeypatch.setattr(main.Data, "chat_snapshot", forbidden)
    monkeypatch.setattr(llm, "complete", forbidden)
    monkeypatch.setattr(llm, "complete_result", forbidden)
    monkeypatch.setattr(llm, "capture_connections", forbidden)
    monkeypatch.setattr(manual_highlight_ops, "capture_owner", forbidden)
    from paper_daily import paper_highlights, reading_links, research_lifecycle

    monkeypatch.setattr(research_lifecycle, "ensure_lifecycle", forbidden)
    monkeypatch.setattr(paper_highlights, "cached", forbidden)
    monkeypatch.setattr(reading_links, "cached", forbidden)
    value = work(saved.read, request, document=document)
    work(render.render, value, main.LIGHT, rich=True)
    assert work(saved.current, value, document=document)
    assert not other.exists()
    with closing(sqlite3.connect(workspace[0])) as conn:
        assert "\n".join(conn.iterdump()) == before_dump
    assert disk_hashes(tmp_path) == before


def test_capture_is_metadata_only_and_payloads_are_detached_primitives(workspace, monkeypatch):
    owner = manual_highlight_ops.capture_owner(workspace[0], "paper")

    def forbidden(*args, **kwargs):
        pytest.fail("Capture accessed SQL or PDF hashing")

    with monkeypatch.context() as patch:
        patch.setattr(saved, "_connect", forbidden)
        patch.setattr(hashlib, "file_digest", forbidden)
        request = saved.capture(
            owner,
            document=workspace[2],
            native_source_version=file_change.version(workspace[2].path),
        )
    value = work(saved.read, request, document=workspace[2])
    for dto in (request, value):
        with pytest.raises(dataclasses.FrozenInstanceError):
            dto.paper_id = "other"
    body = value.data
    body["chat"]["rows"].append({"invented": True})
    assert value.chat_snapshot["rows"] == []

    def primitive(value):
        if isinstance(value, (tuple, list)):
            return all(primitive(item) for item in value)
        if isinstance(value, dict):
            return all(isinstance(k, str) and primitive(v) for k, v in value.items())
        return value is None or type(value) in (str, int, bool, float)

    assert primitive(dataclasses.asdict(value))


@pytest.mark.parametrize("change", ["missing", "recreated", "replacement", "binding", "source"])
def test_first_worker_rejects_owner_or_source_changes_without_rebinding(workspace, change):
    request, document = owner_request(workspace)
    database = workspace[0]
    if change == "source":
        data = bytearray(document.path.read_bytes())
        data[-12] ^= 1
        document.path.write_bytes(data)
    elif change == "replacement":
        with closing(sqlite3.connect(database)) as conn:
            conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        replacement = database.with_suffix(".new")
        shutil.copyfile(database, replacement)
        os.replace(replacement, database)
    elif change == "binding":
        if workspace[1] is None:
            with closing(sqlite3.connect(database)) as conn, conn:
                conn.execute(
                    "CREATE TABLE research_capture_binding(id INTEGER PRIMARY KEY "
                    "CHECK(id=1),workspace TEXT NOT NULL,device TEXT NOT NULL)"
                )
                conn.execute("INSERT INTO research_capture_binding VALUES(1,'other','device')")
        else:
            modify(database, "UPDATE research_capture_binding SET device='other'")
    else:
        with closing(generation._connect(database)) as conn, sync_capture.suppress_capture(conn):
            row = dict(conn.execute("SELECT * FROM papers WHERE id='paper'").fetchone())
            conn.execute("DELETE FROM papers WHERE id='paper'")
            if change == "recreated":
                conn.execute(
                    f"INSERT INTO papers({','.join(row)}) VALUES({','.join('?' for _ in row)})",
                    tuple(row.values()),
                )
            conn.commit()
    with pytest.raises((ValueError, OSError, sqlite3.Error)):
        work(saved.read, request, document=document)


@pytest.mark.parametrize("change", ["chat", "close_reading", "annotation", "marks", "pending"])
def test_exact_saved_changes_invalidate_snapshot(workspace, change):
    turn(workspace)
    value = snapshot(workspace)
    if change == "chat":
        modify(workspace[0], "UPDATE chat SET body='Changed' WHERE role='user'")
    elif change == "close_reading":
        assert closeread.write("paper")[0]
    elif change == "annotation":
        add_annotation(workspace, "highlight_analysis")
    elif change == "marks":
        owner = manual_highlight_ops.capture_owner(workspace[0], "paper")
        view = manual_highlight_ops.load(
            owner, workspace[2].path, workspace[2].sha256, document=workspace[2]
        )
        manual_highlight_ops.add(view, dict(p0=0, o0=0, p1=0, o1=1), "Original experiment")
    else:
        turn(workspace, "Pending", answer=None)
    assert not work(saved.current, value, document=workspace[2])


def test_actual_checkpoint_is_not_a_research_change(workspace):
    turn(workspace)
    value = snapshot(workspace)
    with closing(sqlite3.connect(workspace[0])) as conn:
        assert conn.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()[0] == 0
    assert work(saved.current, value, document=workspace[2])


def test_checkpoint_between_snapshot_reads_is_accepted(workspace, monkeypatch):
    turn(workspace)
    request, document = owner_request(workspace)
    original = saved._read
    calls = []

    def observed(*args):
        value = original(*args)
        calls.append(1)
        if len(calls) == 1:
            with closing(sqlite3.connect(workspace[0])) as conn:
                assert conn.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()[0] == 0
        return value

    monkeypatch.setattr(saved, "_read", observed)
    assert work(saved.read, request, document=document).chat_snapshot["rows"]
    assert len(calls) == 2


def test_unknown_and_known_empty_do_not_resurrect_old_caches(workspace):
    value = snapshot(workspace, source=False)
    assert value.data["source"] == {"known": False, "document_hash": None}
    assert value.data["marks"] == []
    for feature in ("highlight_analysis", "reading_links"):
        assert value.data["annotations"][feature] == {"known": False, "row": None, "body": None}
    add_annotation(workspace, "highlight_analysis")
    modify(workspace[0], "DELETE FROM paper_highlight_analysis WHERE paper_id='paper'")
    value = snapshot(workspace, source=False)
    assert value.data["annotations"]["highlight_analysis"] == {
        "known": True,
        "row": None,
        "body": None,
    }


@pytest.mark.parametrize("problem", ["malformed", "oversized", "scalar"])
def test_bad_saved_annotation_fails_without_truncation_or_write(workspace, problem):
    body = (
        "{"
        if problem == "malformed"
        else (
            '{"items":[],"padding":"' + "x" * annotation_content.MAX_BYTES + '"}'
            if problem == "oversized"
            else "null"
        )
    )
    modify(
        workspace[0],
        "INSERT INTO paper_highlight_analysis VALUES(?,?,?,?,?)",
        ("paper", body, "a" * 64, workspace[2].sha256, STAMP),
    )
    request, document = owner_request(workspace)
    before = disk_hashes(workspace[0].parent)
    with pytest.raises(ValueError):
        work(saved.read, request, document=document)
    assert disk_hashes(workspace[0].parent) == before


def test_oversized_chat_fails_before_history_materialization(workspace, monkeypatch):
    turn(workspace)
    request, document = owner_request(workspace)
    modify(workspace[0], "UPDATE chat SET body=?", ("x" * (saved.MAX_BYTES + 1),))

    def forbidden(*args):
        pytest.fail("Fetched oversized history")

    monkeypatch.setattr(research_chat, "history", forbidden)
    with pytest.raises(ValueError, match="budget"):
        work(saved.read, request, document=document)


def test_sql_hash_and_markdown_only_execute_on_worker(workspace, monkeypatch):
    turn(workspace)
    request, document = owner_request(workspace)
    calls = []
    for module, name in ((saved, "_connect"), (hashlib, "file_digest"), (render, "_markdown")):
        original = getattr(module, name)

        def track(*args, _original=original, _name=name, **kwargs):
            assert threading.current_thread() is not threading.main_thread()
            calls.append(_name)
            return _original(*args, **kwargs)

        monkeypatch.setattr(module, name, track)
    value = work(saved.read, request, document=document)
    work(render.render, value, main.LIGHT, rich=False)
    assert {"_connect", "file_digest", "_markdown"} <= set(calls)


@pytest.mark.parametrize("rich", [False, True])
def test_chat_pairing_and_html_exactly_match_current_reader_contract(workspace, rich):
    turn(workspace)
    turn(workspace, "Pending", answer=None)
    value = snapshot(workspace)
    rows = [item["row"] for item in value.chat_snapshot["rows"]]
    assert render.pair_exchanges(rows) == main._exchanges(rows)
    pending = {item["user_key"]: item for item in value.data["pending"]}
    shell = SimpleNamespace(
        win=SimpleNamespace(pal=main.LIGHT),
        _qa_pending=pending,
        chat_view=SimpleNamespace(markdown=lambda text: render._markdown(text, main.LIGHT, rich)),
    )
    expected = "<h3>問答紀錄</h3>" + "".join(
        main.ReaderPage._exchange(shell, q, a) for q, a in main._exchanges(rows)
    )
    assert work(render.render, value, main.LIGHT, rich=rich).chat_html == expected


def test_mixed_portable_legacy_orphan_pairing_preserves_every_id():
    def row(identity, role, **extra):
        return dict(id=identity, role=role, body=str(identity), paper_id="p", **extra)

    rows = [
        row(1, "user"),
        row(2, "assistant"),
        row(3, "assistant"),
        row(4, "user", message_id="q", exchange_id="e"),
        row(5, "assistant", reply_to="q", exchange_id="wrong"),
        row(6, "assistant", reply_to="q", exchange_id="e"),
        row(7, "assistant", reply_to="q", exchange_id="e"),
        row(8, "user", message_id="pending", exchange_id="f"),
    ]
    assert render.pair_exchanges(rows) == main._exchanges(rows)
    assert rows[3]["message_id"] == "q"
    assert {r["id"] for pair in render.pair_exchanges(rows) for r in pair if r} == set(range(1, 9))


@pytest.mark.parametrize("source", ["exact", "wrong", "unknown"])
def test_saved_highlights_are_never_relabelled_to_current_pdf(workspace, source):
    modify(
        workspace[0],
        "INSERT INTO dives(paper_id,body,spec,written_at) VALUES(?,?,?,?)",
        ("paper", "## Result\nA saved explanation.", "fixture", STAMP),
    )
    add_annotation(
        workspace,
        "highlight_analysis",
        digest="b" * 64 if source == "wrong" else workspace[2].sha256,
    )
    value = snapshot(workspace, source=source != "unknown")
    page = work(render.render, value, main.LIGHT).dive_html
    quote = EXAMPLES["highlight_analysis"]["items"][0]["text"]
    assert (quote in page) is (source == "exact")
    assert value.data["annotations"]["highlight_analysis"]["row"]["document_hash"] == (
        "b" * 64 if source == "wrong" else workspace[2].sha256
    )


def test_missing_owner_and_native_witness_never_invent_authority(workspace):
    with pytest.raises(ValueError, match="existing"):
        saved.capture(None)
    owner = manual_highlight_ops.capture_owner(workspace[0], "paper")
    with pytest.raises(ValueError, match="identity"):
        saved.capture(owner, document=workspace[2])
    with pytest.raises(ValueError, match="invent"):
        saved.capture(owner, native_source_version=(1, 2))


def test_retained_loaded_A_remains_exact_when_desired_B_changes(tmp_path):
    from test_document_reader import LOCAL, prepared
    from test_sync_document_research import document as operation
    from test_sync_document_research import pdf_bytes
    from test_sync_reading_state_research import save

    database, journal, _blobs, resolver, _alias, _data = prepared(tmp_path)
    from paper_daily.sync_client import SyncClient
    from paper_daily.sync_research import research_writer

    SyncClient(journal, research_writer)
    with closing(generation._connect(database)) as conn:
        conn.execute("BEGIN IMMEDIATE")
        sync_capture.install(conn, workspace_id="workspace", device_id="device")
        conn.commit()
    loaded_a = resolver.resolve(LOCAL)
    owner = manual_highlight_ops.capture_owner(database, LOCAL)
    request = saved.capture(
        owner, document=loaded_a, native_source_version=file_change.version(loaded_a.path)
    )
    save(journal, operation(pdf_bytes("Desired newer B"), op_id="new-b"))
    assert not resolver.current(loaded_a)
    assert resolver.intact(loaded_a)
    value = work(saved.read, request, document=loaded_a)
    assert value.data["source"]["document_hash"] == loaded_a.sha256
    assert work(saved.current, value, document=loaded_a)
    assert value.request == request


def test_same_bytes_new_resolver_cannot_satisfy_captured_document(workspace):
    from paper_daily.document_reader import DocumentReader

    request, document = owner_request(workspace)
    other = DocumentReader(
        workspace[0], projection_root=None, legacy_root=document.path.parent
    ).resolve("paper")
    assert other.sha256 == document.sha256 and other._owner is not document._owner
    with pytest.raises(ValueError, match="identity"):
        work(saved.read, request, document=other)


@pytest.mark.parametrize("mismatch", ["none", "key", "analysis", "source"])
def test_reading_links_require_all_three_actual_job_bindings(workspace, mismatch):
    from paper_daily import reading_links

    dive = "## Result\nA saved explanation."
    modify(
        workspace[0],
        "INSERT INTO dives(paper_id,body,spec,written_at) VALUES(?,?,?,?)",
        ("paper", dive, "fixture", STAMP),
    )
    add_annotation(workspace, "highlight_analysis")
    analysis = {**EXAMPLES["highlight_analysis"], "source_hash": "a" * 64}
    key = reading_links._key(reading_links.sections(dive, None), analysis)
    body = deepcopy(EXAMPLES["reading_links"])
    body["links"][0]["explanation"] = "EXACT_LINK_EXPLANATION"
    if mismatch == "analysis":
        body["analysis_hash"] = "c" * 64
    add_annotation(
        workspace,
        "reading_links",
        body=body,
        source_hash="d" * 64 if mismatch == "key" else key,
        digest="b" * 64 if mismatch == "source" else workspace[2].sha256,
    )
    value = snapshot(workspace)
    page = work(render.render, value, main.LIGHT).dive_html
    assert ("EXACT_LINK_EXPLANATION" in page) is (mismatch == "none")


def test_saved_change_during_capture_is_not_silently_rebased(workspace, monkeypatch):
    turn(workspace)
    request, document = owner_request(workspace)
    original = saved._read
    calls = []

    def observed(*args):
        result = original(*args)
        calls.append(1)
        if len(calls) == 1:
            modify(workspace[0], "UPDATE chat SET body='New saved text' WHERE role='user'")
        return result

    monkeypatch.setattr(saved, "_read", observed)
    with pytest.raises(ValueError, match="changed"):
        work(saved.read, request, document=document)


def test_missing_database_is_not_created_by_request(workspace):
    request, _document = owner_request(workspace, source=False)
    missing = workspace[0].with_name("missing.sqlite")
    stale = dataclasses.replace(request, database=str(missing))
    with pytest.raises(FileNotFoundError):
        work(saved.read, stale)
    assert not missing.exists()


def test_hidden_ai_marks_preserve_observations_and_never_reappear(workspace):
    from test_research_generation import pdf

    previous = workspace[2]
    quote = "Original experiment establishes a useful result"
    previous.path.unlink()
    pdf(previous.path, quote)
    document = previous._owner.resolve("paper")
    assert document.available and document.sha256 != previous.sha256
    workspace = (workspace[0], workspace[1], document)
    key = hashlib.sha256(f"1:{quote}".encode()).hexdigest()
    body = deepcopy(EXAMPLES["highlight_analysis"])
    body["items"][0].update(text=quote, page=1, source="page:1")
    add_annotation(workspace, "highlight_analysis", body=body)
    modify(
        workspace[0],
        "INSERT INTO pdf_ai_highlights(paper_id,document_hash,source_key,analysis_hash,"
        "anchor,quote,reason) VALUES(?,?,?,?,?,?,?)",
        (
            "paper",
            document.sha256,
            key,
            "a" * 64,
            json.dumps(dict(p0=0, o0=0, p1=0, o1=6)),
            quote,
            "Evidence",
        ),
    )
    value = snapshot(workspace)
    assert len(value.data["marks"]) == 1
    assert value.data["highlight_records"][0]["row"]["quote"] == quote
    modify(workspace[0], "UPDATE pdf_ai_highlights SET hidden=1 WHERE paper_id='paper'")
    assert not work(saved.current, value, document=document)
    hidden = snapshot(workspace)
    assert hidden.data["marks"] == []
    assert hidden.data["highlight_records"][0]["row"]["hidden"] == 1


def test_observed_output_edits_are_distinct_from_identical_final_text(workspace):
    assert closeread.write("paper")[0]
    before = snapshot(workspace)
    original = before.data["close_readings"][0]
    for body in ("Temporarily edited content", original["body"]):
        with closing(generation._connect(workspace[0])) as conn:
            context = generation.begin_generation(
                conn,
                table="close_readings",
                owner_id="paper",
                input_reader="target",
            )
        assert (
            generation.publish_generation(context, row={**original, "body": body}).status
            == "accepted"
        )
    after = snapshot(workspace)
    assert after.data["close_readings"] == before.data["close_readings"]
    if workspace[1] is not None:
        assert (
            after.data["saved_observations"]["close_readings"]
            != before.data["saved_observations"]["close_readings"]
        )
        assert not work(saved.current, before, document=workspace[2])
    else:
        assert after.data["saved_observations"]["close_readings"] is None
        assert work(saved.current, before, document=workspace[2])
