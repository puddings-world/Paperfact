"""The quick translation: Google's pieces joined, and every failure a reason, not a raise."""

from __future__ import annotations

import httpx

from paper_daily import translate


class _Reply:
    def __init__(self, status, body):
        self.status_code, self._body = status, body

    def json(self):
        if isinstance(self._body, Exception):
            raise self._body
        return self._body


def test_sentences_come_back_joined(monkeypatch):
    body = [[["我們驗證品質。", "We validate the quality.", None], ["其次。", "Next.", None]]]
    monkeypatch.setattr(translate.httpx, "post", lambda *a, **k: _Reply(200, body))
    assert translate.machine("We validate the quality. Next.") == ("我們驗證品質。其次。", "ok")


def test_a_closed_endpoint_is_a_reason_for_the_caller_to_fall_back(monkeypatch):
    monkeypatch.setattr(translate.httpx, "post", lambda *a, **k: _Reply(429, None))
    assert translate.machine("x")[0] is None

    def offline(*a, **k):
        raise httpx.ConnectError("no route")

    monkeypatch.setattr(translate.httpx, "post", offline)
    assert translate.machine("x")[0] is None
    monkeypatch.setattr(translate.httpx, "post", lambda *a, **k: _Reply(200, ValueError()))
    assert translate.machine("x")[0] is None
