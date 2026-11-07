"""Typed human claim edits rechecked against a process-owned original snapshot.

This produces scientific content, never a write capability. Receiver observation,
source ownership, private persistence and transactional publication belong to the
typed recovery adapter. Generic text review must keep refusing claim sets.
"""

from __future__ import annotations

import json

from paper_daily import annotation_content, claim_content
from paper_daily import research_evidence as evidence

FORMAT = "paperfact.claim-review-draft.v1"
MAX_BYTES = annotation_content.MAX_BYTES


def _load(raw):
    if not isinstance(raw, (str, bytes)):
        raise ValueError("A bounded encoded claim draft is required")
    try:
        data = raw.encode("utf-8") if isinstance(raw, str) else raw
        if len(data) > MAX_BYTES:
            raise ValueError("Claim draft exceeds its byte budget")

        def pairs(items):
            value = {}
            for key, item in items:
                if key in value:
                    raise ValueError("Duplicate claim draft field")
                value[key] = item
            return value

        return json.loads(data, object_pairs_hook=pairs, parse_constant=lambda _: _nonfinite())
    except (UnicodeError, TypeError, RecursionError) as exc:
        raise ValueError("Invalid claim draft JSON") from exc


def _nonfinite():
    raise ValueError("Nonfinite claim draft value")


def editable(baseline):
    """Return only editable proposals, with no inherited verification authority."""
    body = annotation_content.decode("claims", baseline)
    claims = []
    for claim in body["report"]["claims"]:
        passages = []
        for passage in claim["passages"]:
            location = passage["location"]
            value = dict(quote=passage["quote"], page=location["page"], anchor=location["anchor"])
            citation = passage["citation_identity"]["proposed"]
            if citation is not None:
                value["citation"] = citation
            passages.append(value)
        claims.append(
            dict(
                text=claim["text"],
                judgment={name: claim["judgment"][name] for name in ("status", "reason")},
                passages=passages,
            )
        )
    result = dict(
        format=FORMAT,
        baseline_digest=claim_content.hashed(body),
        source=body["report"]["source"],
        claims=claims,
    )
    return _checked(body, result)


def _checked(body, draft):
    claim_content.closed(draft, {"format", "baseline_digest", "source", "claims"})
    if draft["format"] != FORMAT:
        raise ValueError("Unsupported claim draft format")
    claim_content.digest(draft["baseline_digest"])
    if draft["baseline_digest"] != claim_content.hashed(body):
        raise ValueError("Claim draft belongs to another saved baseline")
    if draft["source"] != body["report"]["source"]:
        raise ValueError("Claim draft cannot change the original source")
    claims = draft["claims"]
    if not isinstance(claims, list) or not 1 <= len(claims) <= claim_content.MAX_CLAIMS:
        raise ValueError("Claim draft needs a bounded nonempty claim group")
    total = 0
    for claim in claims:
        if not isinstance(claim, dict) or not isinstance(claim.get("passages"), list):
            raise ValueError("Invalid claim draft passages")
        total += len(claim["passages"])
        if total > claim_content.MAX_PASSAGES:
            raise ValueError("Claim draft exceeds its passage budget")
    # This existing closed codec also copies the proposals before verification.
    payload = evidence._validate(
        dict(format=evidence.FORMAT, source=draft["source"], claims=claims)
    )
    return {**draft, "source": payload["source"], "claims": payload["claims"]}


def parse(baseline, raw):
    """Validate exact original identity and bounded proposed edits, without I/O."""
    return _checked(annotation_content.decode("claims", baseline), _load(raw))


def revise(snapshot, baseline, raw, *, cancelled=None):
    """Worker-only deterministic revision; no AI, database writes or publication.

    All positions/identities are rebuilt from the captured original. A missing
    quote stays missing, caller support remains a proposal, and external citation
    identity remains unresolved. A caller must separately revalidate ownership
    and its displayed target immediately before publishing this result.
    """
    body = annotation_content.decode("claims", baseline)
    draft = _checked(body, _load(raw))
    report = evidence.verify_snapshot(
        snapshot,
        dict(format=evidence.FORMAT, source=draft["source"], claims=draft["claims"]),
        cancelled=cancelled,
    )
    return _result(body, draft, report)


def revise_for_receiver(snapshot, baseline, raw, *, cancelled=None):
    """Explicit receiver mapping from an actual snapshot; PDF bytes stay exact.

    Original input digests remain provenance. The result is still content only;
    the typed operation must own the receiver, source and displayed write base.
    """
    body = annotation_content.decode("claims", baseline)
    draft = _checked(body, _load(raw))
    source, _data = evidence._checked_snapshot(snapshot)
    if source["document_hash"] != draft["source"]["document_hash"]:
        raise ValueError("Receiver snapshot is not the draft's exact original")
    report = evidence.verify_snapshot(
        snapshot,
        dict(format=evidence.FORMAT, source=source, claims=draft["claims"]),
        cancelled=cancelled,
    )
    return _result(body, draft, report)


def _result(body, draft, report):
    revised = annotation_content.validate(
        "claims",
        dict(
            format=claim_content.FORMAT,
            recipe=claim_content.RECIPE,
            inputs=body["inputs"],
            generation=dict(
                task="claims", backend="manual", requested_model=None, returned_model=None
            ),
            report=report,
        ),
    )
    return dict(
        body=revised,
        baseline_digest=draft["baseline_digest"],
        draft_digest=claim_content.hashed(draft),
    )
