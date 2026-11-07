"""Reject-only native delivery fence; caller retains owner/source/view guards."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from paper_daily import file_change


def fence(database):
    database = Path(database)
    main = file_change.version(database)
    try:
        wal = file_change.version(Path(str(database) + "-wal"))
    except FileNotFoundError:
        wal = None
    return main, wal


@dataclass(frozen=True)
class PreparedEmptyStatus:
    database: Path
    observed: tuple
    state: str = "queried_no_judged_inputs"
    query_label: str = ""

    def unchanged(self):
        """Metadata interference can reject; it never proves research/source truth."""
        try:
            return fence(self.database) == self.observed
        except OSError:
            return False


def prepared(outcome, database, before, after):
    if outcome.get("state") != "queried_no_judged_inputs" or before != after:
        return None
    labels = {
        "queried_empty": "queried, no results / \u5df2\u67e5\u8a62\uff0c\u7121\u7d50\u679c",
        "unknown": "not established / \u5c1a\u672a\u78ba\u8a8d",
    }
    query = outcome.get("query")
    label = ""
    if query:
        label = (
            "Recorded query at "
            + query["queried_at"]
            + "; OpenAlex: "
            + labels[query["providers"]["openalex"]]
            + "; Semantic Scholar: "
            + labels[query["providers"]["semantic_scholar"]]
        )
    return PreparedEmptyStatus(Path(database), after, query_label=label)
