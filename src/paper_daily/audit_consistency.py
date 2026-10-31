"""Deterministic differences between explicitly comparable proposed facts.

Located quotation, supplied scope and attributed value remain researcher-review
proposals. No scientific contradiction or universal quality score is inferred.
"""

from __future__ import annotations

from decimal import Decimal, localcontext
from itertools import combinations

from paper_daily import audit_facts, claim_content

FORMAT = "paperfact.source-consistency.v1"
RULE = "explicit-scope-decimal.v1"


def _eligibility(left, right, study_type):
    if study_type == "unknown":
        return "study_type_unknown"
    for fact in (left, right):
        if fact["source_binding"] != "exact":
            return "source_" + fact["source_binding"]
        if fact["origin"] != "author_stated":
            return fact["origin"]
        if not fact["evidence"] or any(
            p["location"]["state"] != "located" for p in fact["evidence"]
        ):
            return "evidence_unverified"
    if left["category"] != right["category"]:
        return "different_category"
    if any(v is None for fact in (left, right) for v in fact["scope"].values()):
        return "scope_unknown"
    if left["scope"] != right["scope"]:
        return "different_scope"
    if left["value"]["kind"] != right["value"]["kind"]:
        return "different_value_kind"
    return None


def _interval(value):
    with localcontext() as context:
        context.prec = 64
        point = Decimal(value["decimal"])
        places = value["rounded_places"]
        half = Decimal(0) if places is None else Decimal("0.5").scaleb(-places)
        return point - half, point + half


def _compare(left, right, study_type):
    reason = _eligibility(left, right, study_type)
    if reason:
        return "not_comparable", reason
    one, two = left["value"], right["value"]
    if one["kind"] == "text":
        return ("same_text" if one["text"] == two["text"] else "text_difference"), None
    if one["derived"] or two["derived"]:
        return "derived_value", "derivation_not_verified"
    if one["rounded_places"] is not None or two["rounded_places"] is not None:
        a, b = _interval(one), _interval(two)
        overlap = max(a[0], b[0]) <= min(a[1], b[1])
        return ("rounding_compatible" if overlap else "rounding_disagreement"), None
    return (
        "same_value"
        if Decimal(one["decimal"]) == Decimal(two["decimal"])
        else "numeric_disagreement"
    ), None


def compare(sheet, *, cancelled=lambda: False, current=lambda: True):
    """Complete bounded all-pairs result, preserving both output locations.

    At most 32 facts produce 496 pairs. No synonym matching, unit conversion,
    unknown-scope equality, statistical inference or semantic adjudication occurs.
    """
    report = audit_facts._checked(sheet, cancelled, current)
    checks = []
    for left, right in combinations(report["facts"], 2):
        audit_facts._guard(sheet._capture, cancelled, current)
        state, reason = _compare(left, right, report["study_type"])
        checks.append(
            dict(
                left=dict(fact_id=left["id"], location=left["location"]),
                right=dict(fact_id=right["id"], location=right["location"]),
                state=state,
                reason=reason,
                review_required=state not in {"same_value", "same_text", "rounding_compatible"},
            )
        )
    audit_facts._guard(sheet._capture, cancelled, current)
    result = dict(
        format=FORMAT,
        rule_version=RULE,
        fact_sheet_id=report["id"],
        source=report["source"],
        owner_observation=report["owner_observation"],
        input_hash=report["input_hash"],
        study_type=report["study_type"],
        facts=report["facts"],
        comparisons=checks,
        covered_facts=len(report["facts"]),
        semantic_validation="not_performed",
        persistence="none",
    )
    return {**result, "id": claim_content.hashed(result)}
