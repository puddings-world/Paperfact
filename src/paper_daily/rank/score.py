"""Turn raw signals into one comparable number per paper.

Every component is mapped to 0..1 before weighting. Citation counts and author
h-indices are both extremely heavy-tailed, so they are converted to percentile ranks
within the corpus rather than used directly -- otherwise one 20,000-citation paper
would flatten the entire scale and nothing else would ever differ.

Citation *velocity* (citations per year since publication) is used instead of raw
citations, because raw counts make it structurally impossible for a recent paper to
outrank an old one, which would defeat reading newest-first.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime

from paper_daily.config import ScoreWeights
from paper_daily.rank.canon import canon_index
from paper_daily.rank.classify import TYPE_WEIGHT, classify
from paper_daily.store import now

AWARD_VALUE = {"oral": 1.0, "spotlight": 0.7, "best": 1.0}


def _percentiles(values: list[float]) -> dict[float, float]:
    """Value -> percentile rank in 0..1. Ties share a rank."""
    uniq = sorted(set(values))
    if len(uniq) <= 1:
        return dict.fromkeys(uniq, 0.5)
    return {v: i / (len(uniq) - 1) for i, v in enumerate(uniq)}


def score_all(conn: sqlite3.Connection, weights: ScoreWeights) -> int:
    rows = conn.execute(
        "SELECT id, venue, year, title, abstract, topic, award, citation_count, "
        "author_strength FROM papers"
    ).fetchall()
    if not rows:
        return 0

    this_year = datetime.now(UTC).year
    years = [r["year"] for r in rows]
    y_min, y_max = min(years), max(years)
    canon = canon_index()

    velocities: list[float] = []
    strengths: list[float] = []
    for r in rows:
        age = max(this_year - r["year"], 1)
        velocities.append((r["citation_count"] or 0) / age)
        strengths.append(r["author_strength"] or 0.0)
    v_pct = _percentiles(velocities)
    s_pct = _percentiles(strengths)

    updates = []
    for r, vel, stg in zip(rows, velocities, strengths, strict=True):
        ptype, conf = classify(r["title"], r["abstract"], r["topic"])
        parts = {
            "award": AWARD_VALUE.get((r["award"] or "").lower(), 0.0),
            "citation_velocity": v_pct[vel],
            "author_strength": s_pct[stg],
            "paper_type": TYPE_WEIGHT.get(ptype, 0.5),
            "recency": (r["year"] - y_min) / max(y_max - y_min, 1),
        }
        total = (
            weights.award * parts["award"]
            + weights.citation_velocity * parts["citation_velocity"]
            + weights.author_strength * parts["author_strength"]
            + weights.paper_type * parts["paper_type"]
            + weights.recency * parts["recency"]
        )
        from paper_daily.store import title_key

        is_canon = 1 if title_key(r["title"]) in canon else 0
        updates.append(
            (
                round(total, 6),
                json.dumps(parts),
                ptype,
                conf,
                is_canon,
                now(),
                r["id"],
            )
        )

    conn.executemany(
        "UPDATE papers SET score=?, score_parts_json=?, paper_type=?, type_confidence=?, "
        "is_canon=?, scored_at=? WHERE id=?",
        updates,
    )
    return len(updates)
