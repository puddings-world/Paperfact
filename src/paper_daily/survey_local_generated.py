"""Observed publication of generated surveys in an unbound local workspace.

This derives storage directly from a sealed real generation proposal. It never
fabricates a package import, sync identity or replacement generation context.
"""

from __future__ import annotations

import hmac
import secrets
from contextlib import closing
from dataclasses import dataclass, field

from paper_daily import research_evidence as evidence
from paper_daily import research_generation as generation
from paper_daily import survey_local as local
from paper_daily import survey_sources

_KEY = secrets.token_bytes(32)


def _seal(proposal, staged, replace):
    return hmac.new(
        _KEY, local._json([proposal._seal, staged._seal, replace]).encode(), "sha256"
    ).hexdigest()


def observe_in(conn, context, sources):
    papers = sorted(s["paper_id"] for s in sources if s["state"] == "captured")
    return local._snapshot(conn, context.owner_id, papers)


def observe(context, sources):
    with closing(generation._connect(context.db_path)) as conn:
        conn.execute("BEGIN")
        if generation._stale(conn, context) is not None:
            raise ValueError("Survey inputs changed before local report observation")
        return observe_in(conn, context, sources)


def current_in(conn, proposal):
    report = survey_sources.checked_proposal(proposal)
    context = proposal._capture._context
    data = survey_sources._checked(proposal._capture)
    if (
        data.get("native") is not None
        or data.get("local") is None
        or generation._path(conn) != str(context.db_path)
        or generation._stale(conn, context) is not None
        or observe_in(conn, context, report["sources"]) != data["local"]
        or not survey_sources.current(proposal._capture)
    ):
        raise ValueError("Survey inputs, originals or local report changed")
    return report, context, data["local"]


@dataclass(frozen=True)
class PreparedLocalSurvey:
    proposal: survey_sources.SurveyProposal = field(repr=False)
    staged: local.StagedLocalSurvey = field(repr=False)
    replace: bool
    _seal: str = field(repr=False)


def prepare(proposal, *, replace=False, cancelled=lambda: False):
    if type(replace) is not bool:
        raise ValueError("Local report replacement intent must be explicit")
    report = survey_sources.checked_proposal(proposal)
    context = proposal._capture._context
    survey_sources._cancel(cancelled)
    with closing(generation._connect(context.db_path)) as conn:
        conn.execute("BEGIN")
        _report, _context, observed = current_in(conn, proposal)
    selected = []
    mapping = {}
    bindings = []
    for source, snapshot in zip(report["sources"], proposal._capture._snapshots, strict=True):
        survey_sources._cancel(cancelled)
        if source["state"] != "captured":
            continue
        _original, raw = evidence._checked_snapshot(snapshot)
        paper = source["paper_id"]
        selected.append(
            local._stage_file(
                context.db_path,
                paper,
                dict(sha256=source["document_hash"], size=len(raw)),
                raw,
                cancelled,
            )
        )
        mapping[paper] = paper
        bindings.append(dict(source_id=source["id"], paper_id=paper))
    data = dict(
        database=str(context.db_path),
        native=generation._identity(context.db_path),
        list_id=context.owner_id,
        paper_map=mapping,
        portable=dict(report=report, bindings=bindings),
        observed=observed,
    )
    encoded, files = local._json(data), tuple(selected)
    staged = local.StagedLocalSurvey(encoded, files, local._seal(encoded, files))
    local.checked(staged)
    with closing(generation._connect(context.db_path)) as conn:
        conn.execute("BEGIN")
        current_in(conn, proposal)
        local.check_targets_in(conn, staged)
    survey_sources._cancel(cancelled)
    return PreparedLocalSurvey(proposal, staged, replace, _seal(proposal, staged, replace))


def publish(prepared, *, cancelled=lambda: False):
    if (
        not isinstance(prepared, PreparedLocalSurvey)
        or not isinstance(prepared.proposal, survey_sources.SurveyProposal)
        or not isinstance(prepared.staged, local.StagedLocalSurvey)
        or type(prepared.replace) is not bool
        or not isinstance(prepared._seal, str)
        or not hmac.compare_digest(
            prepared._seal, _seal(prepared.proposal, prepared.staged, prepared.replace)
        )
    ):
        raise ValueError("Local generated survey needs its prepared publication proof")
    report = survey_sources.checked_proposal(prepared.proposal)
    context = prepared.proposal._capture._context
    local.checked(prepared.staged)
    survey_sources._cancel(cancelled)
    with closing(generation._connect(context.db_path)) as conn, conn:
        conn.execute("BEGIN IMMEDIATE")
        saved = local.current_in(conn, context.owner_id)
        if saved:
            body = local._current_sources(conn, saved, generation._identity(context.db_path))
            if body["report"] == report:
                # Idempotent acknowledgement only: never reactivate an older
                # version or refresh stale inputs on a retry.
                return dict(state="unchanged", reports=0, report_id=report["id"])
        current_in(conn, prepared.proposal)
        local.check_targets_in(conn, prepared.staged)
        result = local.publish_in(
            conn,
            prepared.staged,
            replace=prepared.replace,
            cancelled=cancelled,
        )
        if not survey_sources.current(prepared.proposal._capture):
            raise ValueError("Survey inputs or originals changed before local commit")
        survey_sources._cancel(cancelled)
        if result["reports"]:
            result = {**result, "state": "generated"}
        return result
