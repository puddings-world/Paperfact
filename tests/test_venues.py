"""Where a paper was published, said the way the field says it."""

from __future__ import annotations

from paper_daily import venues


def test_long_venue_names_are_said_briefly():
    assert venues.label(
        "International Conference on Medical Image Computing and Computer-Assisted Intervention",
        2025,
    ) == "MICCAI 2025"
    assert venues.label("Medical Image Computing and Computer Assisted Intervention – MICCAI 2023",
                        2023) == "MICCAI 2023"
    assert venues.label("MICCAI 2026", 2026) == "MICCAI 2026"
    assert venues.label("Scientific Data", 2024) == "Sci Data 2024"


def test_a_preprint_says_so():
    assert venues.label("arXiv (Cornell University)", 2026) == "arXiv 2026 · 預印本"
    assert venues.is_preprint("arXiv.org")
    assert not venues.is_preprint("IEEE Transactions on Medical Imaging")


def test_publisher_latex_is_stripped_before_matching():
    assert venues._plain("$$\\textsf{GLSFormer}$$: Gated") == "GLSFormer: Gated"


def test_refresh_replaces_a_stale_preprint_venue(monkeypatch):
    import sqlite3

    from paper_daily import store

    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(store.SCHEMA)
    store._migrate(conn)
    store.upsert_papers(conn, [
        {"id": "ref:sasvi", "title": "SASVi - Segment Any Surgical Video", "venue": "arXiv.org",
         "year": 2025, "source": "test", "doi": "10.48550/arXiv.2502.09653"},
        {"id": "ref:tmi", "title": "Multi-View TTA", "year": 2025, "source": "test",
         "venue": "IEEE Transactions on Medical Imaging"},
    ])
    asked = []

    def published(title):
        asked.append(title)
        return {"venue": "International Journal of Computer Assisted Radiology and Surgery",
                "year": 2025, "doi": "10.1007/s11548-025-03408-y"}

    monkeypatch.setattr(venues, "published", published)
    assert venues.refresh(conn, ["ref:sasvi", "ref:tmi"], log=lambda _m: None) == 1
    row = conn.execute("SELECT venue, doi FROM papers WHERE id='ref:sasvi'").fetchone()
    assert venues.short(row["venue"]) == "IJCARS"
    assert row["doi"] == "10.1007/s11548-025-03408-y"
    assert asked == ["SASVi - Segment Any Surgical Video"]
