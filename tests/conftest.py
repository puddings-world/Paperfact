"""Shared test setup."""

import os
import tempfile

import pytest

# The reading views fall back to Qt's own rich text: a Chromium per test would be
# slow, and the tests check what the app does, not the typesetting (rich_html has
# its own tests).
os.environ.setdefault("PAPERFACT_PLAIN_VIEWS", "1")
# Set before paper_daily is imported, so a maintainer's .env (or the checkout's own
# data/) is never the folder a test that forgets to isolate itself writes into. The
# empty PAPERFACT_DATA is present, so a .env cannot fill it in, yet falsy, so the
# legacy name decides; a fixture setting either name still wins.
os.environ["PAPERFACT_DATA"] = ""
os.environ["PAPER_DAILY_DATA"] = tempfile.mkdtemp(prefix="paperfact-tests-")


@pytest.fixture(autouse=True)
def isolated_model_catalog(monkeypatch):
    from paper_daily import model_catalog

    monkeypatch.setattr(model_catalog, "_catalogs", {})


@pytest.fixture(autouse=True)
def isolated_ui_state():
    """Queued view state belongs to the test that wrote it."""
    yield
    from paper_daily.desktop import ui_state

    with ui_state._lock:
        ui_state._pending.clear()
