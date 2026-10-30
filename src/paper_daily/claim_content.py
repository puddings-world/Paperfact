"""Closed portable claim sets; quoted location never authorizes semantic support."""

import hashlib
import json
import re
import unicodedata

FORMAT = "paperfact.claim-set.v1"
RECIPE = "claim-extraction.v1"
HASH = re.compile(r"[0-9a-f]{64}")
MAX_CLAIMS = 16
MAX_PASSAGES = 48


def closed(value, fields):
    if not isinstance(value, dict) or set(value) != set(fields):
        raise ValueError("Unexpected claim-set fields")


def text(value, maximum, *, nullable=False):
    if nullable and value is None:
        return
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise ValueError("Invalid claim-set text")


def digest(value):
    if not isinstance(value, str) or not HASH.fullmatch(value):
        raise ValueError("Invalid claim-set digest")


def number(value, maximum, minimum=0):
    if type(value) is not int or not minimum <= value <= maximum:
        raise ValueError("Invalid claim-set number")


def hashed(value):
    encoded = json.dumps(
        value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False
    )
    return hashlib.sha256(encoded.encode()).hexdigest()


def normalize(value):
    value = unicodedata.normalize("NFKC", value).replace("\u00ad", "")
    return " ".join(re.sub(r"-\s*\n\s*(?=[a-z])", "", value).split())


def input_digest(row):
    return hashed({key: value for key, value in row.items() if key != "paper_id"})


def source_digest(inputs, document_hash):
    return hashed([RECIPE, document_hash, inputs])


def anchor(value, pages):
    closed(value, {"p0", "o0", "p1", "o1"})
    for key in ("p0", "p1"):
        number(value[key], pages - 1)
    for key in ("o0", "o1"):
        number(value[key], 19999)
    if (value["p1"], value["o1"]) < (value["p0"], value["o0"]):
        raise ValueError("Reversed claim evidence anchor")


def location(value, pages):
    closed(value, {"state", "reason", "anchor", "page", "candidates", "truncated"})
    states = {
        "located": {None},
        "missing": {"quote_not_found"},
        "ambiguous": {"multiple_quote_locations"},
        "invalid_page": {"page_out_of_range"},
        "invalid_anchor": {
            "anchor_out_of_range_or_page_mismatch",
            "anchor_does_not_bound_unique_quote",
        },
    }
    if (
        not isinstance(value["state"], str)
        or value["state"] not in states
        or (value["reason"] is not None and not isinstance(value["reason"], str))
        or value["reason"] not in states[value["state"]]
    ):
        raise ValueError("Invalid claim location state")
    if type(value["truncated"]) is not bool:
        raise ValueError("Invalid claim ambiguity flag")
    candidates = value["candidates"]
    if not isinstance(candidates, list) or len(candidates) > 8:
        raise ValueError("Invalid claim ambiguity candidates")
    for candidate in candidates:
        anchor(candidate, pages)
    if value["state"] == "located":
        anchor(value["anchor"], pages)
        if (
            type(value["page"]) is not int
            or value["page"] != value["anchor"]["p0"] + 1
            or candidates
            or value["truncated"]
        ):
            raise ValueError("Invalid located claim evidence")
    elif value["anchor"] is not None or value["page"] is not None:
        raise ValueError("Unlocated claim evidence has an active anchor")
    if value["state"] == "ambiguous":
        if len(candidates) < (1 if value["truncated"] else 2):
            raise ValueError("Ambiguous claim evidence has no alternatives")
    elif candidates or value["truncated"]:
        raise ValueError("Unexpected claim ambiguity alternatives")


def citation_identity(value):
    closed(value, {"state", "reason", "proposed"})
    proposed = value["proposed"]
    if proposed is None:
        if value["state"] != "not_requested" or value["reason"] is not None:
            raise ValueError("Invalid absent claim citation identity")
        return
    closed(proposed, {"paper_id", "doi", "title"})
    if not any(proposed.values()):
        raise ValueError("Empty proposed citation identity")
    for item in proposed.values():
        text(item, 1000, nullable=True)
    if value["state"] != "unresolved" or value["reason"] != "no_trusted_citation_mapping":
        raise ValueError("Claim citation identity has no trusted resolver")


def validate(body):
    closed(body, {"format", "recipe", "inputs", "generation", "report"})
    if body["format"] != FORMAT or body["recipe"] != RECIPE:
        raise ValueError("Unsupported claim-set format")
    closed(body["inputs"], {"dive", "close_reading"})
    for value in body["inputs"].values():
        digest(value)
    metadata = body["generation"]
    closed(metadata, {"task", "backend", "requested_model", "returned_model"})
    if metadata["task"] != "claims":
        raise ValueError("Invalid claim extraction task")
    text(metadata["backend"], 64)
    text(metadata["requested_model"], 512, nullable=True)
    text(metadata["returned_model"], 512, nullable=True)
    report = body["report"]
    closed(
        report,
        {"format", "source", "normalization", "page_count", "claims", "id", "verification_scope"},
    )
    if (
        report["format"] != "paperfact.claim-evidence.report.v1"
        or report["normalization"] != "nfkc-whitespace-soft-hyphen-wrap.v1"
        or report["verification_scope"] != "original_snapshot"
    ):
        raise ValueError("Unsupported claim evidence verification scope")
    closed(report["source"], {"paper_id", "document_hash"})
    text(report["source"]["paper_id"], 512)
    digest(report["source"]["document_hash"])
    number(report["page_count"], 500, 1)
    if not isinstance(report["claims"], list) or len(report["claims"]) > MAX_CLAIMS:
        raise ValueError("Claim set exceeds its claim budget")
    claims, count = set(), 0
    for claim in report["claims"]:
        closed(claim, {"id", "text", "atomicity", "judgment", "semantic_validation", "passages"})
        text(claim["text"], 2000)
        digest(claim["id"])
        if claim["id"] in claims or claim["id"] != hashed(
            ["claim", report["source"], normalize(claim["text"])]
        ):
            raise ValueError("Duplicate or inconsistent claim identity")
        claims.add(claim["id"])
        if (
            claim["atomicity"] != "caller_supplied"
            or claim["semantic_validation"] != "not_performed"
        ):
            raise ValueError("Claim semantics cannot be automatically certified")
        judgment = claim["judgment"]
        closed(judgment, {"status", "reason", "authority"})
        if (
            not isinstance(judgment["status"], str)
            or judgment["status"] not in {"supported", "inferred", "unresolved"}
            or judgment["authority"] != "caller"
        ):
            raise ValueError("Claim judgment requires explicit proposed authority")
        text(judgment["reason"], 2000)
        if not isinstance(claim["passages"], list):
            raise ValueError("Invalid claim passage collection")
        count += len(claim["passages"])
        if count > MAX_PASSAGES:
            raise ValueError("Claim set exceeds its passage budget")
        passages, anchors = set(), set()
        for passage in claim["passages"]:
            closed(passage, {"id", "proposal_id", "quote", "location", "citation_identity"})
            digest(passage["id"])
            digest(passage["proposal_id"])
            text(passage["quote"], 4000)
            if passage["id"] in passages:
                raise ValueError("Repeated claim source identity")
            passages.add(passage["id"])
            location(passage["location"], report["page_count"])
            citation_identity(passage["citation_identity"])
            if passage["location"]["state"] == "located":
                point = passage["location"]["anchor"]
                expected = hashed(
                    ["located-passage", report["source"], normalize(passage["quote"]), point]
                )
                if passage["id"] != expected or hashed(point) in anchors:
                    raise ValueError("Duplicate or inconsistent claim source location")
                anchors.add(hashed(point))
            elif passage["id"] != passage["proposal_id"]:
                raise ValueError("Unlocated evidence cannot gain a located identity")
    digest(report["id"])
    if report["id"] != hashed({key: value for key, value in report.items() if key != "id"}):
        raise ValueError("Claim evidence report digest differs")
    return body
