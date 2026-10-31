"""Closed lineage evidence report; located text never certifies influence or support."""

from paper_daily.claim_content import closed, digest, hashed, location, normalize, number, text

FORMAT = "paperfact.lineage-report.v1"
RECIPE = "bounded-lineage.v1"
MAX_SOURCES = 4
MAX_STATEMENTS = 12
MAX_PASSAGES = 48
STAGES = {"prior_gap", "current_change", "later_development"}
FUNCTIONS = {
    "uses-method",
    "uses-data",
    "extends",
    "compares",
    "supports",
    "contrasts",
    "background",
    "unresolved",
}
ROLES = {"own_characterization", "citing_context", "change_evidence"}
IDENTITY_FIELDS = {"title", "doi", "arxiv_id", "s2_id"}


def source_id(identity, document_hash):
    return hashed(["lineage-source.v1", identity, document_hash])


def statement_id(focal, item):
    return hashed([RECIPE, focal, item["stage"], item["subject"], normalize(item["text"])])


def passage_id(item):
    return hashed(
        [
            RECIPE,
            item["source_id"],
            item["role"],
            item["cites"],
            normalize(item["quote"]),
            item["location"],
        ]
    )


def requirements(focal, item):
    """Report quote requirements, not semantic proof or citation-identity authority."""
    own = any(
        p["source_id"] == item["subject"]
        and p["role"] in {"own_characterization", "change_evidence"}
        and p["location"]["state"] == "located"
        for p in item["passages"]
    )
    citing, cited = (
        (focal, item["subject"]) if item["stage"] == "prior_gap" else (item["subject"], focal)
    )
    relation = item["stage"] != "current_change"
    context = any(
        p["source_id"] == citing
        and p["role"] == "citing_context"
        and p["cites"] == cited
        and p["location"]["state"] == "located"
        for p in item["passages"]
    )
    return {
        "own_source_passage": "located" if own else "missing",
        "citing_passage": ("located" if context else "missing") if relation else "not_required",
        "citation_identity": "unresolved" if relation else "not_required",
        "semantic_validation": "not_performed",
    }


def validate(report):
    closed(
        report,
        {
            "format",
            "recipe",
            "verification_scope",
            "normalization",
            "focal",
            "sources",
            "statements",
            "coverage",
            "id",
        },
    )
    if (
        report["format"] != FORMAT
        or report["recipe"] != RECIPE
        or not isinstance(report["verification_scope"], str)
        or report["verification_scope"] not in {"original_snapshots", "current_sources"}
        or report["normalization"] != "nfkc-whitespace-soft-hyphen-wrap.v1"
    ):
        raise ValueError("Unsupported lineage report")
    sources = report["sources"]
    if not isinstance(sources, list) or not 1 <= len(sources) <= MAX_SOURCES:
        raise ValueError("Invalid lineage corpus")
    by_id = {}
    for source in sources:
        closed(
            source,
            {"id", "identity", "identity_authority", "document_hash", "availability", "page_count"},
        )
        closed(source["identity"], IDENTITY_FIELDS)
        text(source["identity"]["title"], 2000)
        for field in IDENTITY_FIELDS - {"title"}:
            text(source["identity"][field], 1000, nullable=True)
        if source["identity_authority"] != "selected_workspace_record":
            raise ValueError("Lineage paper identity needs a selected source")
        if source["availability"] == "available":
            digest(source["document_hash"])
            number(source["page_count"], 96, 1)
        elif source["availability"] == "unavailable":
            if source["document_hash"] is not None or source["page_count"] is not None:
                raise ValueError("Unavailable lineage source has an active version")
        else:
            raise ValueError("Invalid lineage source availability")
        if (
            source["id"] != source_id(source["identity"], source["document_hash"])
            or source["id"] in by_id
        ):
            raise ValueError("Invalid or duplicate lineage source")
        by_id[source["id"]] = source
    if (
        not isinstance(report["focal"], str)
        or report["focal"] not in by_id
        or by_id[report["focal"]]["availability"] != "available"
    ):
        raise ValueError("The focal lineage source is unavailable")
    if sum(row["page_count"] or 0 for row in sources) > 96:
        raise ValueError("Lineage corpus exceeds its page budget")
    items = report["statements"]
    if not isinstance(items, list) or len(items) > MAX_STATEMENTS:
        raise ValueError("Lineage statement budget exceeded")
    ids, count = set(), 0
    for item in items:
        closed(
            item,
            {"id", "stage", "subject", "text", "function", "judgment", "passages", "requirements"},
        )
        if (
            not isinstance(item["stage"], str)
            or item["stage"] not in STAGES
            or not isinstance(item["subject"], str)
            or item["subject"] not in by_id
        ):
            raise ValueError("Lineage statement names an unselected paper")
        if (item["stage"] == "current_change") != (item["subject"] == report["focal"]):
            raise ValueError("Lineage stage belongs to another source")
        text(item["text"], 2000)
        if not isinstance(item["function"], str) or item["function"] not in FUNCTIONS:
            raise ValueError("Invalid proposed citation function")
        closed(item["judgment"], {"status", "reason", "authority"})
        if (
            not isinstance(item["judgment"]["status"], str)
            or item["judgment"]["status"] not in {"supported", "inferred", "unresolved"}
            or item["judgment"]["authority"] != "caller_proposal"
        ):
            raise ValueError("Lineage judgment is not a certified verdict")
        text(item["judgment"]["reason"], 2000)
        if item["id"] != statement_id(report["focal"], item) or item["id"] in ids:
            raise ValueError("Invalid or duplicate lineage statement")
        ids.add(item["id"])
        if not isinstance(item["passages"], list):
            raise ValueError("Invalid lineage passages")
        count += len(item["passages"])
        if count > MAX_PASSAGES:
            raise ValueError("Lineage passage budget exceeded")
        passage_ids = set()
        for p in item["passages"]:
            closed(p, {"id", "source_id", "role", "cites", "quote", "location"})
            if (
                not isinstance(p["source_id"], str)
                or p["source_id"] not in by_id
                or not isinstance(p["role"], str)
                or p["role"] not in ROLES
            ):
                raise ValueError("Unselected lineage passage source")
            if p["cites"] is not None and (
                not isinstance(p["cites"], str) or p["cites"] not in by_id
            ):
                raise ValueError("Unselected lineage citation identity")
            if (p["role"] == "citing_context") != (p["cites"] is not None):
                raise ValueError("Lineage citation context needs explicit proposed identity")
            text(p["quote"], 4000)
            source = by_id[p["source_id"]]
            if source["availability"] == "available":
                location(p["location"], source["page_count"])
            elif p["location"] != {
                "state": "source_unavailable",
                "reason": "original_unavailable",
                "anchor": None,
                "page": None,
                "candidates": [],
                "truncated": False,
            }:
                raise ValueError("Unavailable lineage source has a located passage")
            if (
                source["availability"] == "unavailable"
                and type(p["location"]["truncated"]) is not bool
            ):
                raise ValueError("Invalid unavailable lineage location flag")
            if p["id"] != passage_id(p) or p["id"] in passage_ids:
                raise ValueError("Invalid or duplicate lineage passage")
            passage_ids.add(p["id"])
        if item["requirements"] != requirements(report["focal"], item):
            raise ValueError("Lineage requirements have an unsupported verdict")
    coverage = {
        stage: ("proposed" if any(x["stage"] == stage for x in items) else "no_statement")
        for stage in sorted(STAGES)
    }
    if report["coverage"] != coverage or report["id"] != hashed(
        {k: v for k, v in report.items() if k != "id"}
    ):
        raise ValueError("Lineage report identity or coverage changed")
    from paper_daily.sync_files import canonical_json

    if len(canonical_json(report)) > 220 * 1024:
        raise ValueError("Lineage report exceeds its bounded inline budget")
    return report
