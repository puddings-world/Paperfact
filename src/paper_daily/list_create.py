"""Create independent lists from a topic, a bibliography, or no papers yet."""

import json
from urllib.parse import urlencode
from uuid import uuid4

from paper_daily import lists, llm
from paper_daily.enrich import s2
from paper_daily.http import fetch
from paper_daily.store import connect, now, upsert_papers


def _json(text):
    try:
        return llm.reply_json(text, dict)
    except ValueError as exc:
        raise ValueError("AI 回傳的格式無法讀取；請重試。") from exc


def topic_papers(topic, log=lambda _m: None):
    text, reason = llm.complete(
        topic,
        task="list_parse",
        timeout=120,
        system='將研究需求轉成 1–3 個精簡英文學術搜尋字串。只輸出 JSON {"queries":["..."]}。',
    )
    if not text:
        raise ValueError(reason)
    queries = _json(text).get("queries")
    if (
        not isinstance(queries, list)
        or not 1 <= len(queries) <= 3
        or any(not isinstance(q, str) or not q.strip() or len(q) > 300 for q in queries)
    ):
        raise ValueError("AI 未提供有效搜尋條件")
    candidates = {}
    for query in queries:
        log("搜尋學術文獻：" + query)
        params = urlencode(dict(query=query, fields=s2.MATCH_FIELDS, limit=30))
        payload = json.loads(fetch(f"{s2.API}/paper/search?{params}", retries=2))
        for paper in payload.get("data") or []:
            if paper.get("paperId") and paper.get("title"):
                candidates[paper["paperId"]] = paper
    if not candidates:
        raise ValueError("找不到可核對的論文，請調整主題範圍或貼上參考文獻。")
    log("AI 正在根據搜尋結果挑選與安排閱讀順序…")
    text, reason = llm.complete(
        json.dumps(dict(topic=topic, papers=list(candidates.values())), ensure_ascii=False),
        task="list_parse",
        timeout=180,
        system=(
            "僅從提供的真實搜尋結果中挑選最多 12 篇符合研究需求的論文，按建議閱讀順序排列。"
            '不得新增文獻或改寫 ID。只輸出 JSON {"ids":["paperId", ...]}。'
        ),
    )
    if not text:
        raise ValueError(reason)
    ids = _json(text).get("ids")
    if (
        not isinstance(ids, list)
        or not 1 <= len(ids) <= 12
        or any(not isinstance(pid, str) or pid not in candidates for pid in ids)
    ):
        raise ValueError("AI 選擇了搜尋結果以外的論文，清單尚未建立，請重試。")
    return [candidates[pid] for pid in dict.fromkeys(ids)]


def create(name, raw="", mode="references", log=lambda _m: None):
    name = name.strip()
    if not name or len(name) > 200:
        raise ValueError("請輸入 1–200 字的清單名稱")
    list_id = "list-" + uuid4().hex[:16]
    if mode == "references":
        entries = lists.parse_bibliography(raw, log, strict=True)
        if not entries:
            raise ValueError("沒有找到可匯入的參考文獻")
        return lists.import_list(name, raw, list_id, log, entries=entries)
    if mode not in ("topic", "empty"):
        raise ValueError("未知清單建立方式")
    if mode == "topic" and not raw.strip():
        raise ValueError("請描述研究主題")
    papers = topic_papers(raw, log) if mode == "topic" else []
    with connect() as conn:
        conn.execute(
            "INSERT INTO lists(id,name,note,created_at) VALUES (?,?,?,?)",
            (list_id, name, raw if mode == "topic" else None, now()),
        )
        for position, paper in enumerate(papers):
            row = lists._paper_from_match(dict(title=paper["title"]), paper)
            existing = conn.execute(
                "SELECT id FROM papers WHERE title_key=? LIMIT 1", (row["title_key"],)
            ).fetchone()
            if existing:
                row["id"] = existing[0]
            else:
                upsert_papers(conn, [row])
            conn.execute(
                "INSERT OR IGNORE INTO list_papers(list_id,paper_id,position,citation,added_at) "
                "VALUES (?,?,?,?,?)",
                (list_id, row["id"], position, row["title"], now()),
            )
        conn.commit()
    return dict(id=list_id, added=len(papers), parsed=len(papers))
