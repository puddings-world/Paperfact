"""Filesystem layout and tunable knobs.

Everything the pipeline writes lives under DATA_DIR so the repo stays clean and the
whole corpus can be rebuilt by deleting one directory.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

from paper_daily import __version__, runtime

ROOT = runtime.bundle_root()
runtime.load_env_file()
DATA_DIR = runtime.data_dir()

DB_PATH = DATA_DIR / "papers.db"
HTTP_CACHE = DATA_DIR / "httpcache"
PDF_DIR = DATA_DIR / "pdf"
TEXT_DIR = DATA_DIR / "text"
BRIEF_DIR = DATA_DIR / "briefs"

VENUES = ("ICLR", "ICML", "NeurIPS")

# Semantic Scholar allows ~1 req/s unauthenticated. A free key lifts this a lot;
# set S2_API_KEY and the client picks it up automatically.
S2_API_KEY = os.environ.get("S2_API_KEY", "").strip()
# Sent with every request so an API operator can reach whoever runs this copy. Each
# user sets their own; a default address would be one person's, sent by everyone.
CONTACT_EMAIL = (
    os.environ.get("PAPERFACT_EMAIL") or os.environ.get("PAPER_DAILY_EMAIL") or ""
).strip()


def user_agent(contact: str) -> str:
    reach = f"mailto:{contact}" if contact else "https://github.com/puddings-world/Paperfact"
    return f"Paperfact/{__version__} (+{reach})"


USER_AGENT = user_agent(CONTACT_EMAIL)


@dataclass(frozen=True)
class ScoreWeights:
    """Relative pull of each ranking signal. Tuned so no single signal dominates.

    Every component is normalised to roughly 0..1 before weighting, so these read as
    percentages of total influence.
    """

    award: float = 0.30  # oral / spotlight / best-paper labels
    citation_velocity: float = 0.25
    author_strength: float = 0.15
    paper_type: float = 0.20  # principle-type papers over application/benchmark
    recency: float = 0.10

    # Canon papers bypass scoring entirely and are injected at fixed intervals.
    canon_every_n: int = 14


@dataclass(frozen=True)
class Settings:
    years: tuple[int, ...] = field(default=tuple(range(2016, 2027)))
    weights: ScoreWeights = field(default_factory=ScoreWeights)
    queue_target: int = 5000
    # Companion papers surfaced alongside each main paper (lineage / contrast).
    companions_per_day: int = 2


SETTINGS = Settings()


def ensure_dirs() -> None:
    for d in (DATA_DIR, HTTP_CACHE, PDF_DIR, TEXT_DIR, BRIEF_DIR):
        d.mkdir(parents=True, exist_ok=True)
