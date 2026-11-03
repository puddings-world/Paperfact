import json
import sqlite3
from contextlib import closing
from uuid import uuid4

import pytest
from test_sync_capture import bound as _bound_fixture
from test_sync_capture import seed

from paper_daily import research_chat as chat
from paper_daily import research_generation, store
from paper_daily.desktop.main import _exchanges

bound = _bound_fixture


@pytest.fixture
def legacy(tmp_path, monkeypatch):
    path = tmp_path / "papers.db"
    monkeypatch.setattr(store, "DB_PATH", path)
    monkeypatch.setattr(store, "ensure_dirs", lambda: None)
    store.init_db()
    seed()
    return path


def start(question="Question", **kwargs):
    with store.connect() as conn:
        return chat.begin_chat(
            conn, paper_id="local-paper", question=question, request_id=str(uuid4()), **kwargs
        )


def messages(path=None):
    with closing(research_generation._connect(path or store.DB_PATH)) as conn:
        return chat.history(conn, "local-paper")


def test_question_is_durable_before_answer_and_exact_answer_retry_is_idempotent(legacy):
    request, prompt = chat.prepare_chat(start())
    assert "Question" in prompt
    assert [(r["role"], r["body"]) for r in messages()] == [("user", "Question")]
    result = chat.publish_answer(request, "Answer")
    assert result.status == "accepted"
    assert chat.publish_answer(request, "Answer") == result
    assert len(messages()) == 2
    with pytest.raises(ValueError):
        chat.publish_answer(request, "Different")


def test_bound_turns_are_journaled_and_source_request_not_provider_data(bound):
    seed()
    request, _ = chat.prepare_chat(start())
    assert chat.publish_answer(request, "Answer").status == "accepted"
    ops = [o for o in bound.journal.pending() if o["entity_type"] == "research_content"]
    assert [o["payload"]["data"]["role"] for o in ops] == ["user", "assistant"]
    assert ops[1]["payload"]["data"]["reply_to"] == ops[0]["payload"]["key"]
    assert ops[0]["payload"]["data"]["exchange_id"] == request.request_id
    assert "db_path" not in json.dumps(ops)


@pytest.mark.parametrize("mutation", ["delete", "recreate", "edit", "history"])
def test_changed_input_retains_answer_without_overwriting_current_data(legacy, mutation):
    request, _ = chat.prepare_chat(start())
    with store.connect() as conn:
        if mutation == "history":
            conn.execute("UPDATE chat SET body='New question' WHERE role='user'")
        elif mutation == "edit":
            conn.execute("UPDATE papers SET title='Changed' WHERE id='local-paper'")
        else:
            paper = dict(conn.execute("SELECT * FROM papers WHERE id='local-paper'").fetchone())
            conn.execute("DELETE FROM papers WHERE id='local-paper'")
            if mutation == "recreate":
                conn.execute(
                    "INSERT INTO papers("
                    + ",".join(paper)
                    + ") VALUES("
                    + ",".join("?" for _ in paper)
                    + ")",
                    tuple(paper.values()),
                )
    result = chat.publish_answer(request, "Preserved answer")
    assert result.status == "candidate"
    assert not any(r["role"] == "assistant" for r in messages())
    assert chat.publish_answer(request, "Preserved answer") == result
    with store.connect() as conn:
        row = dict(conn.execute("SELECT * FROM research_chat_requests").fetchone())
    assert (
        json.loads(chat.validate_request_record(row)["answer_json"])["body"] == "Preserved answer"
    )


def test_workspace_switch_writes_only_original_database(legacy, tmp_path, monkeypatch):
    request, _ = chat.prepare_chat(start())
    other = tmp_path / "other.db"
    monkeypatch.setattr(store, "DB_PATH", other)
    store.init_db()
    seed()
    assert chat.publish_answer(request, "Original answer").status == "accepted"
    assert messages(other) == []
    assert messages(legacy)[-1]["body"] == "Original answer"


def test_replaced_database_retains_outside_replacement(legacy):
    request, _ = chat.prepare_chat(start())
    saved = legacy.with_suffix(".saved")
    legacy.rename(saved)
    store.init_db()
    result = chat.publish_answer(request, "Recoverable answer")
    assert result.status == "candidate"
    with sqlite3.connect(legacy) as conn:
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM sqlite_master WHERE name='research_chat_requests'"
            ).fetchone()[0]
            == 0
        )
    files = list(legacy.parent.glob(".paperfact-chat/*/*.json"))
    assert len(files) == 1
    assert chat.validate_request_record(json.loads(files[0].read_text()))["answer_json"]
    assert chat.publish_answer(request, "Recoverable answer") == result


def test_prepare_retry_keeps_one_question_and_stable_prompt(legacy):
    request, prompt = chat.prepare_chat(start())
    again, prompt2 = chat.prepare_chat(request)
    assert prompt2 == prompt and again.encoded == request.encoded
    assert len(messages()) == 1


def test_pairing_uses_portable_refs_and_unknown_reference_never_mispairs():
    rows = [
        dict(id=1, role="user", message_id="u1", exchange_id="e1", reply_to=None, paper_id="p"),
        dict(id=2, role="user", message_id="u2", exchange_id="e2", reply_to=None, paper_id="p"),
        dict(
            id=3, role="assistant", message_id="a1", exchange_id="e1", reply_to="u1", paper_id="p"
        ),
        dict(
            id=4,
            role="assistant",
            message_id="a2",
            exchange_id="e2",
            reply_to="missing",
            paper_id="p",
        ),
    ]
    paired = _exchanges(rows)
    assert [(q["id"] if q else None, a["id"] if a else None) for q, a in paired] == [
        (1, 3),
        (2, None),
        (None, 4),
    ]


@pytest.mark.parametrize("question", ["", "  ", None])
def test_empty_question_makes_no_receipt_or_chat(legacy, question):
    with pytest.raises(ValueError):
        start(question)
    assert messages() == []


def test_restart_reuses_prepared_question_and_completed_delivery_without_ai(legacy, monkeypatch):
    from paper_daily import llm
    from paper_daily.desktop.qa_job import ChatJob

    request, _ = chat.prepare_chat(start())
    resumed = chat.load_request(legacy, request.request_id)
    resumed, _ = chat.prepare_chat(resumed)
    assert len(messages()) == 1
    result = chat.publish_answer(resumed, "Answer")
    complete = chat.load_request(legacy, request.request_id)
    monkeypatch.setattr(llm, "complete", lambda *a, **k: pytest.fail("Retry must not call AI"))
    monkeypatch.setattr(llm, "ACCESS_CHECK", lambda *a: pytest.fail("Stored output needs no login"))
    job = ChatJob(complete, {}, None)
    response, _ = job("")
    assert json.loads(response)["status"] == "accepted" and job.result == result
    assert len(messages()) == 2


def test_failed_question_commit_rolls_back_turn_receipt_and_outbox(bound, monkeypatch):
    seed()
    before = bound.journal.pending()
    request = start()
    monkeypatch.setattr(
        chat,
        "_commit",
        lambda conn: (_ for _ in ()).throw(sqlite3.OperationalError("fixture failure")),
    )
    with pytest.raises(sqlite3.OperationalError):
        chat.prepare_chat(request)
    assert messages() == [] and bound.journal.pending() == before
    with store.connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM research_chat_requests").fetchone()[0] == 0


def test_failed_answer_commit_retains_output_without_partial_assistant(bound, monkeypatch):
    seed()
    request, _ = chat.prepare_chat(start())
    before = bound.journal.pending()
    monkeypatch.setattr(
        chat,
        "_commit",
        lambda conn: (_ for _ in ()).throw(sqlite3.OperationalError("fixture failure")),
    )
    result = chat.publish_answer(request, "Preserved output")
    assert result.status == "candidate" and len(messages()) == 1
    assert bound.journal.pending() == before
    records = chat.list_recovery_requests(store.DB_PATH)
    assert len(records) == 1 and json.loads(records[0]["answer_json"])["body"] == "Preserved output"


@pytest.mark.parametrize(
    "change",
    [
        lambda row: row.update(status="accepted"),
        lambda row: row.update(extra="invalid"),
        lambda row: row.update(request_id="bad"),
        lambda row: row.update(candidate_id="fake"),
    ],
)
def test_malformed_qa_receipts_are_rejected(legacy, change):
    request, _ = chat.prepare_chat(start())
    with store.connect() as conn:
        row = dict(conn.execute("SELECT * FROM research_chat_requests").fetchone())
    change(row)
    with pytest.raises(ValueError):
        chat.validate_request_record(row)


def _answered(question, **kwargs):
    request, prompt = chat.prepare_chat(start(question, **kwargs))
    assert chat.publish_answer(request, f"Answer to {question}").status == "accepted"
    return request, prompt


def test_a_concise_question_is_answered_on_its_own_with_cited_support(legacy):
    _answered("First")
    _answered("Second")
    request, prompt = chat.prepare_chat(start("Third", style={"answer": "concise", "turns": 0}))
    assert "回答格式(精要)" in prompt and "(p.3)" in prompt
    # Earlier turns stay out, so the answer cannot drift toward them.
    assert "First" not in prompt and "Second" not in prompt
    assert request.data["version"] == 2 and request.data["history"] == []
    # A retry reads the stored version 2 receipt back and asks the same way.
    again, retried = chat.prepare_chat(request)
    assert retried == prompt and again.data["style"] == {"answer": "concise", "turns": 0}
    assert chat.publish_answer(again, "Short answer").status == "accepted"


def test_following_up_keeps_only_the_last_exchange(legacy):
    _answered("First")
    _answered("Second")
    request, prompt = chat.prepare_chat(start("Third", style={"answer": "concise", "turns": 2}))
    assert "Second" in prompt and "Answer to Second" in prompt and "First" not in prompt
    assert [r["body"] for r in request.data["history"]] == ["Second", "Answer to Second"]


def test_a_full_answer_keeps_the_version_1_receipt_and_six_turns(legacy):
    for n in range(4):
        _answered(f"Q{n}")
    request, prompt = chat.prepare_chat(start("Last"))
    assert request.data["version"] == 1 and "style" not in request.data
    assert "回答格式(精要)" not in prompt and len(request.data["history"]) == 6


@pytest.mark.parametrize("style", [{"answer": "short", "turns": 0},
                                   {"answer": "concise", "turns": 3},
                                   {"answer": "concise", "turns": 0, "tone": "x"}])
def test_an_unknown_answer_style_is_refused(legacy, style):
    with pytest.raises((ValueError, TypeError)):
        start(style=style)
