"""Closed archive-only input/query observations for later outcomes; no replay."""

from __future__ import annotations

import json

from paper_daily import later_outcomes as outcomes
from paper_daily import research_generation as generation
from paper_daily.sync_files import closed, digest


def generation_inputs(value):
    from paper_daily.sync_content import _text

    closed(value, {"paper", "lookup_policy", "cites", "followups", "dive", "overview"})
    if value["paper"] is None:
        raise ValueError("Later history requires its captured paper")
    closed(value["paper"], set(outcomes.PAPER_FIELDS))
    for key, text in value["paper"].items():
        if key == "year":
            if text is not None and type(text) is not int:
                raise ValueError("Invalid archived paper year")
        else:
            _text(text, generation.MAX_BYTES)
    policy = value["lookup_policy"]
    closed(policy, {"version", "most_cited", "newest"})
    if policy["version"] != outcomes.POLICY:
        raise ValueError("Unknown archived later lookup policy")
    if any(
        type(policy[k]) is not int or not 0 <= policy[k] <= generation.MAX_ROWS
        for k in ("most_cited", "newest")
    ):
        raise ValueError("Invalid archived later query budget")
    # This finite protocol deliberately supports only the genuinely empty query path.
    if value["cites"] != [] or value["followups"] != [] or value["overview"] is not None:
        raise ValueError("Nonempty later research requires a separately supported history adapter")
    if value["dive"] is not None:
        digest(value["dive"])


def query_sources(record):
    from paper_daily import research_compound as compound

    compound.validate_request_record(record)
    context = json.loads(record["context_json"])
    mutations = json.loads(record["mutations_json"])
    if (
        context["phase"] != "fetch"
        or context["key"] is not None
        or context["rows"]
        or mutations["puts"]
        or mutations["deletes"]
        or mutations["completion"] != context["started_at"]
        or context["document"] is not None
        or context["text_source"] is not None
        or context["prompts"]
    ):
        raise ValueError("Only captured empty-fetch history is supported by later outcomes")
    return set()


def redundant_hint(conn, row):
    """Exclude only duplicate legacy hints; typed rows remain the sole outcome data."""
    from paper_daily.later_outcome_packages import read

    key = row["key"]
    for prefix in ("followups.checked.", "analyze.failed.later."):
        if not key.startswith(prefix):
            continue
        paper = key[len(prefix) :]
        if not outcomes._exists(conn):
            return False
        selected = read(conn, paper)
        if selected is None:
            return False
        body = outcomes.decode(selected["body_json"])
        try:
            value = json.loads(row["value"])
        except (ValueError, TypeError):
            return False
        if prefix == "analyze.failed.later.":
            return value is None and row["value"].strip() == "null"
        return value == body["query"]["queried_at"] and isinstance(value, str)
    return False
