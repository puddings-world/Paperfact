"""Malformed upstream objects are unknown, never genuinely queried-empty."""

from contextlib import closing, suppress

import pytest
from test_deep_analysis import db as db

from paper_daily import config, followups, store
from paper_daily import research_generation as generation


@pytest.mark.parametrize("provider", ["openalex", "semantic_scholar"])
def test_actual_malformed_upstream_shape_never_accepts_empty_completion(db, monkeypatch, provider):
    monkeypatch.setattr(config, "PDF_DIR", db)
    if provider == "openalex":
        monkeypatch.setattr(followups, "work_id", lambda _: "W1")
        monkeypatch.setattr(followups, "_get", lambda _: {})
        monkeypatch.setattr(followups, "_citing_s2", lambda _: None)
    else:
        with store.connect() as conn:
            conn.execute("UPDATE papers SET s2_id='fixture-s2' WHERE id='a'")
        monkeypatch.setattr(followups, "work_id", lambda _: None)
        monkeypatch.setattr(followups, "fetch_text", lambda *a, **kw: "{}")
    with suppress(ValueError):  # Malformed responses may fail, but never publish success.
        followups.fetch("a", database=store.DB_PATH)
    with closing(generation._connect(store.DB_PATH)) as conn:
        assert conn.execute("SELECT COUNT(*) FROM paper_later_outcomes").fetchone()[0] == 0
