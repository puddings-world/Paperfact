"""Inactive lineage report validation preserves explicit proposal/source boundaries."""

import copy
import json
import sqlite3

import pytest

GOLDEN = (
    '{"format":"paperfact.lineage-set.v1","corpus_id":"22222222'
    '-2222-4222-8222-222222222222","inputs":{"dive":null,"close'
    '_reading":null},"generation":{"task":"lineage","backend":"'
    'fixture","requested_model":null,"returned_model":null},"re'
    'port":{"format":"paperfact.lineage-report.v1","recipe":"bo'
    'unded-lineage.v1","verification_scope":"original_snapshots'
    '","normalization":"nfkc-whitespace-soft-hyphen-wrap.v1","f'
    'ocal":"e50e9f09ec04008825eadba356676b18c98d7ec015b7ccaa9eb'
    'bab131a66be48","sources":[{"availability":"available","doc'
    'ument_hash":"1dc558e219338a0db9fdbf04576978d9d5c8f90eb538e'
    '921cbf1748e0cd3bb39","id":"e50e9f09ec04008825eadba356676b1'
    '8c98d7ec015b7ccaa9ebbab131a66be48","identity":{"arxiv_id":'
    'null,"doi":"10.0000/focal","s2_id":null,"title":"Focal Stu'
    'dy"},"identity_authority":"selected_workspace_record","pag'
    'e_count":1},{"availability":"available","document_hash":"3'
    "351b3aee423848b92110545eea9491ab4fb34f3dfd1a24b8f8bf65680e"
    'd2b9b","id":"b547bb1171f41df5a6e31b4232ffc8ed404a9123d4135'
    '959042bd916772ffbc5","identity":{"arxiv_id":null,"doi":"10'
    '.0000/prior","s2_id":null,"title":"Prior Study"},"identity'
    '_authority":"selected_workspace_record","page_count":1},{"'
    'availability":"available","document_hash":"f081395e85ecb6d'
    '2f18c2bf6704a0761f400ba8e7a4dfde398dda653bb1d5b5e","id":"1'
    "cb876a648d127f13cb07a9a1cf02772a8232104081fab9344ec26997d6"
    '363d7","identity":{"arxiv_id":null,"doi":"10.0000/later","'
    's2_id":null,"title":"Later Study"},"identity_authority":"s'
    'elected_workspace_record","page_count":1}],"statements":[{'
    '"id":"238c568efe458763234474b4c9a21fe8b2e2283afef1fcc0f77a'
    '3025174b2c22","function":"extends","judgment":{"reason":"P'
    'roposed interpretation only.","status":"supported","author'
    'ity":"caller_proposal"},"passages":[{"id":"c35ced977b63595'
    '3b536b884e3d57cf4fdbbd54a245f719e2d53fe70ae545838","source'
    '_id":"b547bb1171f41df5a6e31b4232ffc8ed404a9123d4135959042b'
    'd916772ffbc5","role":"own_characterization","cites":null,"'
    'quote":"The prior study excluded independent external coho'
    'rts.","location":{"state":"located","reason":null,"anchor"'
    ':{"p0":0,"o0":0,"p1":0,"o1":6},"page":1,"candidates":[],"t'
    'runcated":false}},{"id":"0866178ce42742c0090bbe78f6f2d7c56'
    '53eac4912ebeb56b234399db9d32579","source_id":"e50e9f09ec04'
    '008825eadba356676b18c98d7ec015b7ccaa9ebbab131a66be48","rol'
    'e":"citing_context","cites":"b547bb1171f41df5a6e31b4232ffc'
    '8ed404a9123d4135959042bd916772ffbc5","quote":"We extend '
    'Prior Study [1] using independent external observations.",'
    '"location":{"state":"located","reason":null,"anchor":{"p0"'
    ':0,"o0":10,"p1":0,"o1":18},"page":1,"candidates":[],"trunc'
    'ated":false}}],"stage":"prior_gap","subject":"b547bb1171f4'
    '1df5a6e31b4232ffc8ed404a9123d4135959042bd916772ffbc5","tex'
    't":"The prior work omitted external validation.","requirem'
    'ents":{"own_source_passage":"located","citing_passage":"lo'
    'cated","citation_identity":"unresolved","semantic_validati'
    'on":"not_performed"}},{"id":"84765bbe9cd3139fc32860ea76425'
    '26e600a0ab8ae33d53e06d64ec5119a6495","function":"extends",'
    '"judgment":{"reason":"Proposed interpretation only.","stat'
    'us":"supported","authority":"caller_proposal"},"passages":'
    '[{"id":"ddb8d02c314d7070048ad222af77d512afc3bc43cbd9fa1689'
    '4727ced568e249","source_id":"e50e9f09ec04008825eadba356676'
    'b18c98d7ec015b7ccaa9ebbab131a66be48","role":"change_eviden'
    'ce","cites":null,"quote":"We address the external cohort '
    'limitation using matched independent controls.","location"'
    ':{"state":"located","reason":null,"anchor":{"p0":0,"o0":0,'
    '"p1":0,"o1":9},"page":1,"candidates":[],"truncated":false}'
    '}],"stage":"current_change","subject":"e50e9f09ec04008825e'
    'adba356676b18c98d7ec015b7ccaa9ebbab131a66be48","text":"The'
    ' focal work added independent controls.","requirements":{"'
    'own_source_passage":"located","citing_passage":"not_requir'
    'ed","citation_identity":"not_required","semantic_validatio'
    'n":"not_performed"}},{"id":"95700eee37b0d0aef112517ba14478'
    '1299b27d8df56b17c8a2c4230591686b75","function":"extends","'
    'judgment":{"reason":"Proposed interpretation only.","statu'
    's":"supported","authority":"caller_proposal"},"passages":['
    '{"id":"0c927ca7cb2a56fe7d23d1e697960e8eb735bc24d67b36f92ef'
    '29b66d8aa38c5","source_id":"1cb876a648d127f13cb07a9a1cf027'
    '72a8232104081fab9344ec26997d6363d7","role":"own_characteri'
    'zation","cites":null,"quote":"The later study evaluated '
    'three institutions independently.","location":{"state":"lo'
    'cated","reason":null,"anchor":{"p0":0,"o0":9,"p1":0,"o1":1'
    '5},"page":1,"candidates":[],"truncated":false}},{"id":"77f'
    "672592a4bd0117f910f2dd8101ce6b0d124dc7f0bd1c82dc40e2abaa7c"
    '9e9","source_id":"1cb876a648d127f13cb07a9a1cf02772a8232104'
    '081fab9344ec26997d6363d7","role":"citing_context","cites":'
    '"e50e9f09ec04008825eadba356676b18c98d7ec015b7ccaa9ebbab131'
    'a66be48","quote":"We extend Focal Study [2] by validating '
    'across institutions.","location":{"state":"located","reaso'
    'n":null,"anchor":{"p0":0,"o0":0,"p1":0,"o1":8},"page":1,"c'
    'andidates":[],"truncated":false}}],"stage":"later_developm'
    'ent","subject":"1cb876a648d127f13cb07a9a1cf02772a823210408'
    '1fab9344ec26997d6363d7","text":"The later work tested '
    'institutional generalization.","requirements":{"own_source'
    '_passage":"located","citing_passage":"located","citation_i'
    'dentity":"unresolved","semantic_validation":"not_performed'
    '"}}],"coverage":{"current_change":"proposed","later_develo'
    'pment":"proposed","prior_gap":"proposed"},"id":"5d4b5031e1'
    'dd6c0d30510ef79e72f6651c9406c622b9f27a9415d7aaf45206b9"},"'
    'bindings":[{"source_id":"e50e9f09ec04008825eadba356676b18c'
    '98d7ec015b7ccaa9ebbab131a66be48","paper_id":"d8a9f60c-489c'
    '-543a-ac52-39f59286cbcb"},{"source_id":"b547bb1171f41df5a6'
    'e31b4232ffc8ed404a9123d4135959042bd916772ffbc5","paper_id"'
    ':"d354d698-69d0-5f82-915a-a8e276b1d6c9"},{"source_id":"1cb'
    "876a648d127f13cb07a9a1cf02772a8232104081fab9344ec26997d636"
    '3d7","paper_id":"56f1daa5-7947-5cd7-8ac0-90525bfaf4ef"}]}'
)


@pytest.fixture
def valid_set():
    return json.loads(GOLDEN)


def test_valid_report_is_read_only_and_never_certifies_semantics(valid_set, monkeypatch):
    from paper_daily import lineage_content, llm

    original = copy.deepcopy(valid_set)
    monkeypatch.setattr(llm, "complete_result", lambda *a, **kw: pytest.fail("model on validation"))
    monkeypatch.setattr(llm, "capture_connections", lambda: pytest.fail("route on validation"))
    monkeypatch.setattr(sqlite3, "connect", lambda *a, **kw: pytest.fail("SQL on pure validation"))
    report = lineage_content.validate(valid_set["report"])
    assert valid_set == original and report == original["report"]
    assert all(s["judgment"]["authority"] == "caller_proposal" for s in report["statements"])
    assert all(
        s["requirements"]["semantic_validation"] == "not_performed" for s in report["statements"]
    )
    relations = [s for s in report["statements"] if s["stage"] != "current_change"]
    assert all(s["requirements"]["citation_identity"] == "unresolved" for s in relations)


@pytest.mark.parametrize(
    "change",
    [
        "extra-field",
        "wrong-format",
        "focal-unknown",
        "source-extra",
        "untrusted-identity",
        "source-hash",
        "duplicate-source",
        "too-many-sources",
        "too-many-pages",
        "bool-pages",
        "too-many-statements",
        "duplicate-statement",
        "wrong-stage",
        "unselected-subject",
        "certified-authority",
        "unknown-function",
        "too-many-passages",
        "unselected-passage",
        "unselected-citation",
        "wrong-role-cites",
        "quote-limit",
        "forged-requirements",
        "forged-coverage",
        "changed-report-hash",
    ],
)
def test_invalid_report_fails_whole_boundary_without_mutating_input(valid_set, change):
    from paper_daily import lineage_content

    report = valid_set["report"]
    first = report["statements"][0]
    if change == "extra-field":
        report["quality_score"] = 100
    elif change == "wrong-format":
        report["format"] = "unknown"
    elif change == "focal-unknown":
        report["focal"] = "0" * 64
    elif change == "source-extra":
        report["sources"][0]["path"] = "not-authority"
    elif change == "untrusted-identity":
        report["sources"][0]["identity_authority"] = "title_match"
    elif change == "source-hash":
        report["sources"][0]["document_hash"] = "b" * 64
    elif change == "duplicate-source":
        report["sources"][1] = copy.deepcopy(report["sources"][0])
    elif change == "too-many-sources":
        report["sources"] *= 2
    elif change == "too-many-pages":
        report["sources"][0]["page_count"] = 96
    elif change == "bool-pages":
        report["sources"][0]["page_count"] = True
    elif change == "too-many-statements":
        report["statements"] *= 5
    elif change == "duplicate-statement":
        report["statements"].append(copy.deepcopy(first))
    elif change == "wrong-stage":
        first["stage"] = "quality_verdict"
    elif change == "unselected-subject":
        first["subject"] = "0" * 64
    elif change == "certified-authority":
        first["judgment"]["authority"] = "validator"
    elif change == "unknown-function":
        first["function"] = "influenced"
    elif change == "too-many-passages":
        first["passages"] *= 25
    elif change == "unselected-passage":
        first["passages"][0]["source_id"] = "0" * 64
    elif change == "unselected-citation":
        first["passages"][1]["cites"] = "0" * 64
    elif change == "wrong-role-cites":
        first["passages"][0]["cites"] = report["focal"]
    elif change == "quote-limit":
        first["passages"][0]["quote"] = "x" * 4001
    elif change == "forged-requirements":
        first["requirements"]["semantic_validation"] = "verified"
    elif change == "forged-coverage":
        report["coverage"]["prior_gap"] = "passed"
    else:
        report["id"] = "0" * 64
    before = copy.deepcopy(report)
    with pytest.raises(ValueError):
        lineage_content.validate(report)
    assert report == before


@pytest.mark.parametrize("stage", ["prior_gap", "later_development"])
def test_related_characterization_and_citing_context_need_the_correct_sources(valid_set, stage):
    from paper_daily import lineage_content

    report = valid_set["report"]
    item = next(s for s in report["statements"] if s["stage"] == stage)
    own = copy.deepcopy(item)
    own["passages"] = [p for p in own["passages"] if p["role"] == "citing_context"]
    result = lineage_content.requirements(report["focal"], own)
    assert result["own_source_passage"] == "missing"
    assert (
        result["citing_passage"] == "located" and result["semantic_validation"] == "not_performed"
    )
    citing = copy.deepcopy(item)
    for passage in citing["passages"]:
        if passage["role"] == "citing_context":
            passage["source_id"] = item["subject"] if stage == "prior_gap" else report["focal"]
    result = lineage_content.requirements(report["focal"], citing)
    assert result["own_source_passage"] == "located" and result["citing_passage"] == "missing"
    assert result["citation_identity"] == "unresolved"


@pytest.mark.parametrize("state", ["missing", "ambiguous", "source_unavailable", "invalid_anchor"])
def test_nonlocated_quotes_cannot_satisfy_own_source_or_citing_requirements(valid_set, state):
    from paper_daily import lineage_content

    report = valid_set["report"]
    item = report["statements"][0]
    for passage in item["passages"]:
        passage["location"]["state"] = state
    result = lineage_content.requirements(report["focal"], item)
    assert result["own_source_passage"] == result["citing_passage"] == "missing"
    assert result["semantic_validation"] == "not_performed"


def test_source_ids_are_content_plus_bibliography_not_paper_or_corpus_identity(valid_set):
    from paper_daily import lineage_content

    source = valid_set["report"]["sources"][0]
    identity = copy.deepcopy(source["identity"])
    assert lineage_content.source_id(identity, source["document_hash"]) == source["id"]
    identity["title"] = "Different recorded bibliography"
    assert lineage_content.source_id(identity, source["document_hash"]) != source["id"]
    assert lineage_content.source_id(source["identity"], "b" * 64) != source["id"]


def test_empty_coverage_and_unavailable_related_source_stay_explicit(valid_set):
    from paper_daily import claim_content, lineage_content

    report = valid_set["report"]
    report["statements"] = []
    report["coverage"] = dict(
        prior_gap="no_statement", current_change="no_statement", later_development="no_statement"
    )
    prior = report["sources"][1]
    prior.update(document_hash=None, page_count=None, availability="unavailable")
    prior["id"] = lineage_content.source_id(prior["identity"], None)
    report["id"] = claim_content.hashed({k: v for k, v in report.items() if k != "id"})
    assert lineage_content.validate(report)["statements"] == []
    assert report["sources"][1]["availability"] == "unavailable"
    assert set(report["coverage"].values()) == {"no_statement"}


def test_report_encoded_budget_refuses_complete_valid_shape_without_truncation(valid_set):
    from paper_daily import claim_content, lineage_content

    report = valid_set["report"]
    template = next(s for s in report["statements"] if s["stage"] == "current_change")
    items = []
    for number in range(12):
        item = copy.deepcopy(template)
        item["text"] = str(number) + "x" * 1997
        item["judgment"]["reason"] = "y" * 2000
        item["passages"] = []
        for index in range(4):
            passage = copy.deepcopy(template["passages"][0])
            passage["quote"] = str(index) + "z" * 3999
            passage["id"] = lineage_content.passage_id(passage)
            item["passages"].append(passage)
        item["requirements"] = lineage_content.requirements(report["focal"], item)
        item["id"] = lineage_content.statement_id(report["focal"], item)
        items.append(item)
    report["statements"] = items
    report["coverage"] = dict(
        prior_gap="no_statement", current_change="proposed", later_development="no_statement"
    )
    report["id"] = claim_content.hashed({k: v for k, v in report.items() if k != "id"})
    before = copy.deepcopy(report)
    with pytest.raises(ValueError, match="bounded inline budget"):
        lineage_content.validate(report)
    assert report == before
