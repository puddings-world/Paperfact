"""One immutable QA target; model and durable publication both stay off the UI thread."""

import json

from paper_daily import llm, research_chat


class ChatJob:
    def __init__(self, request, connections, cfg, *, resume=False):
        self.request = request
        self.connections = connections
        self.cfg = cfg
        self.answer = research_chat.answer_record(request)
        self.result = None
        self.resume = resume

    def __call__(self, _prompt):
        from paper_daily.research_job_lock import claim
        from paper_daily.work_progress import report

        with claim(self.request.db_path, "ask", self.request.data["paper_id"]) as accepted:
            if not accepted:
                return None, "這篇論文的問答正在執行，請稍候。"
            if self.resume and self.answer is None:
                self.request = research_chat.load_request(
                    self.request.db_path, self.request.request_id
                )
                self.answer = research_chat.answer_record(self.request)
                self.resume = False
            if self.answer is None and llm.ACCESS_CHECK is not None:
                with llm.connection_scope(self.connections):
                    reason = llm.ACCESS_CHECK(self.cfg, "ask")
                if reason:
                    return None, reason
            if self.answer is None:
                report("正在核對原始論文與問答紀錄")
                self.request, prompt = research_chat.prepare_chat(self.request)
                self.answer = research_chat.answer_record(self.request)
                if self.answer is None:
                    with llm.connection_scope(self.connections):
                        self.answer, reason = llm.complete(
                            prompt, cfg=self.cfg, timeout=300, task="ask"
                        )
                    if not self.answer:
                        return None, reason or "AI 暫時無法回覆，問題已保留，可重試。"
            report("正在儲存原論文的回答")
            try:
                self.result = research_chat.publish_answer(self.request, self.answer)
            except Exception:
                # Keep the completed output across process restart, even when an
                # unexpected writer error bypasses the normal publication path.
                # Retention errors still propagate; never claim an unsaved answer.
                self.result = research_chat.retain_failed_answer(self.request, self.answer)
            return json.dumps(
                {"status": self.result.status, "request_id": self.request.request_id}
            ), "ok"
