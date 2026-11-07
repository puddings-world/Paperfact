"""Source-bound core-claim note generation for the desktop reader."""

from __future__ import annotations

import json
from contextlib import closing, contextmanager
from contextvars import ContextVar
from dataclasses import dataclass

from paper_daily import audit_inputs, claims, llm, research_generation, sync_capture
from paper_daily.research_job_lock import claim
from paper_daily.store import get_kv, now, set_kv

ACTIVE = ContextVar("paperfact_claim_notes_job", default=None)


@contextmanager
def scope(job):
    token = ACTIVE.set(job)
    try:
        yield
    finally:
        ACTIVE.reset(token)


@dataclass
class ClaimNotesJob:
    owner: object
    document: object
    connections: object
    cfg: object

    def _source(self):
        document = self.document
        if (
            self.owner is None
            or document is None
            or not audit_inputs.verify_loaded_source(
                self.owner, document, document.sha256, lambda: False
            )
        ):
            raise ValueError("請重新開啟論文，確認原文版本後再整理核心論點。")

    def _marks(self, conn):
        return [
            dict(row)
            for row in conn.execute(
                "SELECT quote,reason,anchor,'' AS kind FROM pdf_ai_highlights "
                "WHERE paper_id=? AND document_hash=? AND hidden=0 ORDER BY id",
                (self.owner.paper_id, self.document.sha256),
            )
        ]

    def _verified_marks(self, marks):
        from paper_daily import pdf_highlights

        anchors, items = [], []
        keys = ("p0", "p1", "o0", "o1")
        for mark in marks:
            anchor = json.loads(mark["anchor"])
            if not all(type(anchor.get(key)) is int for key in keys):
                raise ValueError("原文重點位置無效，請重新核對來源。")
            if anchor.get("document_hash", self.document.sha256) != self.document.sha256:
                raise ValueError("原文重點屬於另一個 PDF 版本。")
            anchors.append({key: anchor[key] for key in keys})
            items.append(dict(text=mark["quote"], page=anchor["p0"] + 1))
        digest, located, missing = pdf_highlights.locate(self.document.path, {"items": items})
        if (
            digest != self.document.sha256
            or missing
            or len(located) != len(anchors)
            or any(
                actual != expected
                for (_, actual, _), expected in zip(located, anchors, strict=True)
            )
        ):
            raise ValueError("原文重點與 PDF 不一致，請重新核對。")
        return marks

    def run(self, *, force=False):
        self._source()
        path, pid = self.owner.database, self.owner.paper_id
        with claim(path, "core-claim-notes", pid) as acquired:
            if not acquired:
                return 0, "核心論點正在整理，請稍候。"
            with closing(research_generation._connect(path)) as conn:
                conn.execute("BEGIN")
                self.owner.check(conn)
                if not force and claims.has_cards(conn, pid):
                    return 0, "已有核心論點卡"
                marks = self._marks(conn)
                if len(marks) < 3:
                    return 0, "原文重點不足三句，請先分析原文重點。"
                if len(marks) > 64 or len(json.dumps(marks).encode()) > 240000:
                    return 0, "原文重點過多，請先縮小範圍。"
                prompt = claims._prompt(conn, pid, marks)
                old = {
                    row["id"]: dict(row)
                    for row in conn.execute(
                        "SELECT * FROM notes WHERE paper_id=? AND kind=?", (pid, claims.KIND)
                    )
                }
                observations = {
                    identity: sync_capture.observe_note(conn, identity) for identity in old
                }
            self._verified_marks(marks)
            self._source()
            with llm.connection_scope(self.connections):
                answer, reason = llm.complete(
                    prompt, system=claims.SYSTEM, timeout=600, task=claims.TASK, cfg=self.cfg
                )
            if not answer:
                return 0, reason or "AI 沒有回覆；原有卡片保留。"
            picked = claims._pick(answer, marks)
            if not picked:
                return 0, "沒有可核對的論點；原有卡片保留。"
            self._source()
            with closing(research_generation._connect(path)) as conn:
                conn.execute("BEGIN IMMEDIATE")
                self.owner.check(conn)
                if marks != self._marks(conn) or prompt != claims._prompt(conn, pid, marks):
                    raise ValueError("論文內容或原文重點已變更；原有卡片保留。")
                written = get_kv(conn, claims._written_key(pid)) or {}
                remove = []
                for row in conn.execute(
                    "SELECT * FROM notes WHERE paper_id=? AND kind=?", (pid, claims.KIND)
                ):
                    if old.get(row["id"]) == dict(row) and written.get(
                        str(row["id"])
                    ) == claims._digest(row["body"]):
                        remove.append(row["id"])
                with sync_capture.expecting(conn, [observations[i] for i in remove]):
                    conn.executemany("DELETE FROM notes WHERE id=?", [(i,) for i in remove])
                    fresh = {}
                    for mark in reversed(picked):
                        body = claims.body(mark["quote"], mark["claim"], mark["explain"])
                        anchor = json.loads(mark["anchor"])
                        anchor["document_hash"] = self.document.sha256
                        row = conn.execute(
                            "INSERT INTO notes(paper_id,body,created_at,kind,page,anchor) "
                            "VALUES(?,?,?,?,?,?)",
                            (pid, body, now(), claims.KIND, anchor["p0"] + 1, json.dumps(anchor)),
                        )
                        fresh[str(row.lastrowid)] = claims._digest(body)
                    set_kv(conn, claims._written_key(pid), fresh)
                    self._source()
                    conn.commit()
            return len(picked), ""
