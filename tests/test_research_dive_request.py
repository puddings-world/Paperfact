"""Provider-visible study appraisal is field-neutral; saved work remains readable."""

from test_dive import conn as conn_fixture

from paper_daily import dive

conn = conn_fixture


def test_request_keeps_original_pack_and_route_with_study_specific_evidence_rules(monkeypatch):
    captured = []
    output = "Saved explanation. " * 60
    pack = "Qualitative interview study: sampling and coding are reported; no neural model."
    config = object()

    def complete(prompt, **kwargs):
        captured.append((prompt, kwargs))
        return output, "ok"

    monkeypatch.setattr(dive.llm, "complete", complete)
    result, reason = dive._from_pack(pack, cfg=config)
    assert (result, reason) == (output, "ok")
    sent, options = captured[0]
    assert sent == pack and options["cfg"] is config and options["task"] == "dive"
    system = options["system"]
    assert "ML 研究導讀者" not in system
    assert "質性取樣與編碼" in system and "定理條件與證明" in system
    assert "作者主張" in system and "尚無依據" in system
    assert "未報告不等於零" in system and "引用存在不等於主張受支持" in system
    assert "不可硬套神經網路或量化架構" in system
    assert "不把關聯寫成因果" in system


def test_new_recipe_does_not_rewrite_or_hide_existing_dive_in_normal_selection(conn):
    original = "Researcher-approved explanation"
    conn.execute(
        "INSERT INTO dives(paper_id,body,written_at,spec) VALUES('p1',?,?,?)",
        (original, "2026-01-01T00:00:00Z", "2026-10-front-matter"),
    )
    conn.commit()
    rows = dive._select(conn, 5, None, None, rewrite=False)
    assert "p1" not in [row["id"] for row in rows]
    assert conn.execute("SELECT body FROM dives WHERE paper_id='p1'").fetchone()[0] == original
