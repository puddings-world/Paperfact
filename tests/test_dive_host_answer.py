"""An agent host writes a deep dive with its own account; Paperfact stores it."""

import pytest
from test_dive import conn as conn

from paper_daily import brief, dive, llm, local_operations, store

DIVE = "## 一句話結論\n" + "這篇的主張有實驗支持。" * 100


@pytest.fixture
def host(conn, monkeypatch):
    monkeypatch.setattr(llm, "complete", lambda *a, **k: pytest.fail("Paperfact called a model"))
    monkeypatch.setattr(brief, "pack_text", lambda c, row: (f"pack for {row['title']}", None))
    return conn


def stored(conn, paper_id):
    return conn.execute("SELECT body, spec FROM dives WHERE paper_id=?", (paper_id,)).fetchone()


def test_the_task_carries_the_specification_and_the_pack(host):
    task = dive.task("p1")
    assert task["instructions"] == dive.DIVE_INSTRUCTIONS
    assert task["spec"] == dive.DIVE_SPEC
    assert task["material"] == "pack for Front of the queue"
    assert task["full_text"] is False
    assert stored(host, "p1") is None


def test_a_saved_answer_is_published_like_a_generated_dive(host):
    body, reason = dive.save_answer("p1", "\n" + DIVE + "\n")
    assert (body, reason) == (DIVE, "ok")
    row = stored(host, "p1")
    assert (row["body"], row["spec"]) == (DIVE, dive.DIVE_SPEC)


def test_a_short_reply_or_non_text_is_not_stored(host):
    body, reason = dive.save_answer("p1", "I cannot help with that.")
    assert body is None and "too short" in reason
    assert dive.save_answer("p1", ["not", "text"])[0] is None
    assert stored(host, "p1") is None


def test_a_saved_answer_lets_a_given_up_paper_be_read_ahead_again(host):
    store.set_kv(host, "dive.gave_up.p1", "1")
    store.set_kv(host, "dive.failures.p1", "3")
    host.commit()
    dive.save_answer("p1", DIVE)
    assert store.get_kv(host, "dive.gave_up.p1") is None
    assert store.get_kv(host, "dive.failures.p1") is None


def test_an_unknown_paper_has_no_task(host):
    with pytest.raises(ValueError):
        dive.task("absent")


def test_operations_share_the_envelope_and_reject_bad_input(host):
    task = local_operations.dispatch("research.dive.task", {"paper_id": "p2"})
    assert task["ok"] and task["result"]["material"] == "pack for Second"
    saved = local_operations.dispatch("research.dive.save", {"paper_id": "p2", "body": DIVE})
    assert saved == {
        "ok": True,
        "result": {"saved": True, "chars": len(DIVE), "spec": dive.DIVE_SPEC},
    }
    for operation, args in [
        ("research.dive.task", {"paper_id": "../etc"}),
        ("research.dive.save", {"paper_id": "p2", "body": 5}),
        ("research.dive.save", {"paper_id": "p2", "body": "x" * 200_001}),
    ]:
        assert local_operations.dispatch(operation, args)["error"]["code"] == "invalid_input"
    short = local_operations.dispatch("research.dive.save", {"paper_id": "p2", "body": "no"})
    assert short["error"]["code"] == "dive_answer_rejected"
    missing = local_operations.dispatch("research.dive.task", {"paper_id": "absent"})
    assert missing["error"]["code"] == "dive_task_unavailable"
