from test_research_chat import legacy as legacy_fixture
from test_research_chat import messages, start

from paper_daily import research_chat as chat
from paper_daily import store

legacy = legacy_fixture


def test_legacy_turns_are_in_prompt_and_mutation_retains_answer(legacy):
    with store.connect() as conn:
        conn.execute(
            "INSERT INTO chat(paper_id,role,body,created_at) VALUES(?,?,?,?)",
            ("local-paper", "user", "Legacy context", "2026-10-27T00:00:00Z"),
        )
    request, prompt = chat.prepare_chat(start())
    assert "Legacy context" in prompt
    assert request.data["history"][0]["message_id"] is None
    with store.connect() as conn:
        conn.execute("UPDATE chat SET body='Changed legacy context' WHERE id=1")
    assert chat.publish_answer(request, "Answer").status == "candidate"
    assert len(messages()) == 2
