"""A recipient continues imported research with a separately signed-in fixture account."""

import json
import os
import zipfile

import pytest
from test_bundle import _workspace
from test_bundle import sharer as _sharer

from paper_daily import (
    ai_accounts,
    ai_usage,
    brief,
    bundle,
    config,
    dive,
    feedback,
    llm,
    research_service,
    store,
)
from paper_daily.ai_types import Completion

sharer = _sharer


def test_recipient_import_read_own_ai_analyze_and_reexport(sharer, monkeypatch):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QCoreApplication, QEvent
    from PySide6.QtWidgets import QApplication

    from paper_daily.desktop.ai_picker import AIPickerDialog
    from paper_daily.desktop.ask import AskRunner
    from paper_daily.desktop.main import Data

    original, tmp = sharer
    sender_root = bundle.DATA_DIR
    sender_pdf = b"%PDF recipient keeps these original bytes"
    bundle.PDF_DIR.mkdir()
    (bundle.PDF_DIR / "ref_a.pdf").write_bytes(sender_pdf)
    (sender_root / "llm.json").write_text('{"api_key":"sender-secret"}')
    original = research_service.export_bundle("cat", tmp / "with-pdf.zip")

    root = tmp / "recipient"
    root.mkdir()
    recipient_db = _workspace(root, monkeypatch)
    monkeypatch.setattr(config, "TEXT_DIR", root / "text")
    monkeypatch.setattr(llm, "SETTINGS_PATH", root / "llm.json")
    monkeypatch.setattr(llm, "ACCESS_CHECK", None)
    for key in list(os.environ):
        if key.startswith(("PAPERFACT_", "PAPER_DAILY_")):
            monkeypatch.delenv(key)
    monkeypatch.setattr(
        bundle, "fetch", lambda *a, **k: pytest.fail("bundle transfer contacted a service")
    )
    assert research_service.list_collections() == []
    assert not llm.SETTINGS_PATH.exists()
    research_service.import_bundle(original["out"])
    assert not llm.SETTINGS_PATH.exists() and feedback.consent() is None
    data = Data()
    assert data.full_text("ref:a") == "full text"
    assert data.dive("ref:a") == "sharer dive"
    assert (root / "pdf/ref_a.pdf").read_bytes() == sender_pdf

    # Only vendor auth/transport and model discovery are simulated. The picker,
    # persisted routes, generation facade, analysis saving and bundles are real.
    app = QApplication.instance() or QApplication([])
    identities = set()
    monkeypatch.setattr(ai_accounts, "command", lambda backend: [backend])

    def auth(cfg, action):
        if action == "login":
            identities.add(cfg.account_id)
        return (
            ("已登入：recipient@example.org", "ok")
            if cfg.account_id in identities else (None, "尚未登入")
        )

    monkeypatch.setattr(ai_accounts, "auth", auth)
    monkeypatch.setattr(ai_accounts, "models", lambda cfg: ["recipient-model"])
    monkeypatch.setattr(ai_usage, "subscription", lambda cfg: {"windows": [], "message": "fixture"})
    monkeypatch.setattr(ai_usage, "local_summary", lambda cfg: {
        "calls": 0, "failed": 0, "input": 0, "output": 0, "unknown": 0,
    })

    def start(self, prompt, done, failed, call, **_kwargs):
        result, reason = call(prompt)
        (done if result is not None else failed)(result if result is not None else reason)

    monkeypatch.setattr(AskRunner, "start", start)
    llm.save_settings(backend="none")
    picker = AIPickerDialog()
    picker.providers["codex"].click()
    picker.login_button.click()
    picker.model.setEditText("recipient-model")
    picker.use_button.click()
    chosen = llm.settings(task="dive")
    assert chosen.backend == "codex" and chosen.account_id in identities
    assert chosen.model == "recipient-model"
    assert "sender-secret" not in llm.SETTINGS_PATH.read_text()
    picker.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    app.processEvents()

    calls = []
    body = (
        "# Recipient analysis\n" + "A verified synthetic explanation of the imported paper. " * 30
    )

    class Provider:
        def complete(self, request, cfg, post):
            calls.append((request, cfg))
            assert "full text" in request.prompt
            return Completion(body, model=cfg.model)

    monkeypatch.setitem(llm._PROVIDERS, "codex", Provider())
    monkeypatch.setattr(brief, "prepare", lambda row: (None, data.full_text(row["id"])))
    with store.connect() as db:
        store.set_kv(db, "ui.auto_highlights", "0")
    assert dive.dive_ahead(paper_id="ref:a", rewrite=True) == 1
    assert len(calls) == 1 and calls[0][1].account_id == chosen.account_id
    assert data.dive("ref:a") == body
    assert not feedback.path().exists()

    outgoing = research_service.export_bundle("cat", tmp / "recipient.paperfact.zip")
    with zipfile.ZipFile(outgoing["out"]) as archive:
        tables = json.loads(archive.read("tables.json"))
        assert tables["dives"][0]["body"] == body
        assert archive.read("files/pdf/ref_a.pdf") == sender_pdf
        assert not any(
            "llm.json" in name or "product-events" in name for name in archive.namelist()
        )
        serialized = archive.read("tables.json") + archive.read("manifest.json")
        assert b"recipient@example.org" not in serialized and b"sender-secret" not in serialized
    assert recipient_db.execute("SELECT COUNT(*) FROM list_papers").fetchone()[0] == 2
