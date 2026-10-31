"""Deterministic quoted-source checks never establish a claim's semantic truth."""

import copy
import json
import sqlite3
from contextlib import closing
from dataclasses import replace

import pymupdf
import pytest

from paper_daily import research_evidence as evidence
from paper_daily import store
from paper_daily.document_reader import DocumentReader, ResolvedDocument

UNIQUE = "Replication used a held-out cohort of 50 participants."
REPEATED = "The intervention improved accuracy by 10% under the matched budget."
CONTROL = "Controls were assigned independently."


def pdf(path, pages):
    with pymupdf.open() as document:
        for lines in pages:
            page = document.new_page()
            for number, line in enumerate(lines):
                page.insert_text((40, 50 + number * 20), line)
        document.save(path)


@pytest.fixture
def source(tmp_path):
    database = tmp_path / "research.sqlite"
    with closing(sqlite3.connect(database)) as conn, conn:
        conn.executescript(store.SCHEMA)
        conn.execute(
            "INSERT INTO papers(id,title,title_key,year,venue,source) "
            "VALUES('paper','Study','study',2026,'Fixture','fixture')"
        )
    root = tmp_path / "pdf"
    root.mkdir()
    path = root / "paper.pdf"
    pdf(
        path,
        [
            [
                REPEATED,
                REPEATED,
                CONTROL,
                "inter-",
                "vention was blinded.",
                "pretreatment was excluded.",
            ],
            [UNIQUE, CONTROL],
        ],
    )
    reader = DocumentReader(database, projection_root=None, legacy_root=root)
    document = reader.resolve("paper")
    assert document.available
    return document


def proposal(source, quote=UNIQUE, *, page=None, anchor=None, judgment="unresolved"):
    return {
        "format": evidence.FORMAT,
        "source": {"paper_id": source.paper_id or source.local_id, "document_hash": source.sha256},
        "claims": [
            {
                "text": "The study establishes general clinical benefit.",
                "judgment": {"status": judgment, "reason": "Needs independent appraisal."},
                "passages": [{"quote": quote, "page": page, "anchor": anchor}],
            }
        ],
    }


def first(report):
    return report["claims"][0]["passages"][0]


def test_located_quote_returns_reader_anchor_without_upgrading_caller_judgment(source, monkeypatch):
    monkeypatch.setattr(store, "DB_PATH", source.path.parent / "unrelated.sqlite")
    request = proposal(source)
    original = copy.deepcopy(request)
    report = evidence.verify(source, request)
    item = first(report)
    assert item["location"]["state"] == "located"
    anchor = item["location"]["anchor"]
    assert anchor["p0"] == anchor["p1"] == 1 and item["location"]["page"] == 2
    with pymupdf.open(source.path) as document:
        words = document[1].get_text("words")
    assert " ".join(word[4] for word in words[anchor["o0"] : anchor["o1"] + 1]) == UNIQUE
    assert report["claims"][0]["judgment"] == {
        "status": "unresolved",
        "reason": "Needs independent appraisal.",
        "authority": "caller",
    }
    assert report["claims"][0]["semantic_validation"] == "not_performed"
    assert request == original and evidence.verify(source, request) == report
    assert str(source.path) not in json.dumps(report)
    assert not store.DB_PATH.exists()


def test_proposed_supported_with_missing_quote_remains_unverified(source):
    report = evidence.verify(
        source, proposal(source, "No such result was reported.", judgment="supported")
    )
    claim = report["claims"][0]
    assert claim["judgment"]["status"] == "supported"
    assert claim["judgment"]["authority"] == "caller"
    assert claim["semantic_validation"] == "not_performed"
    assert first(report)["location"]["state"] == "missing"
    assert "verdict" not in report and "confidence" not in report and "score" not in report


def test_inference_stays_inference_when_quoted_passage_is_found(source):
    report = evidence.verify(source, proposal(source, judgment="inferred"))
    assert first(report)["location"]["state"] == "located"
    assert report["claims"][0]["judgment"]["status"] == "inferred"


def test_external_citation_identity_is_unresolved_even_when_quote_contains_a_title_or_number(
    source,
):
    request = proposal(source)
    citation = {"paper_id": "different-paper", "doi": "10.9999/not-verified", "title": UNIQUE}
    request["claims"][0]["passages"][0]["citation"] = citation
    result = first(evidence.verify(source, request))
    assert result["location"]["state"] == "located"
    assert result["citation_identity"] == {
        "state": "unresolved",
        "reason": "no_trusted_citation_mapping",
        "proposed": citation,
    }


@pytest.mark.parametrize(
    "key,value,code",
    [
        ("paper_id", "forged-paper", "source_identity_mismatch"),
        ("document_hash", "f" * 64, "source_hash_mismatch"),
    ],
)
def test_wrong_source_identity_or_hash_is_rejected_before_pdf_parsing(
    source, monkeypatch, key, value, code
):
    request = proposal(source)
    request["source"][key] = value
    monkeypatch.setattr(evidence, "_page_words", lambda *a: pytest.fail("No parsing wrong source"))
    with pytest.raises(evidence.EvidenceError) as caught:
        evidence.verify(source, request)
    assert caught.value.code == code
    assert value not in str(caught.value) and str(source.path) not in str(caught.value)


def test_same_hash_cannot_prove_document_owner_without_a_trusted_reader(source):
    forged = ResolvedDocument(
        "legacy", "available", "paper", path=source.path, sha256=source.sha256
    )
    with pytest.raises(evidence.EvidenceError, match="source_unavailable"):
        evidence.verify(forged, proposal(source))


def test_ambiguous_same_page_or_multiple_pages_never_picks_first_match(source):
    report = evidence.verify(source, proposal(source, REPEATED, page=1))
    location = first(report)["location"]
    assert location["state"] == "ambiguous" and location["anchor"] is None
    assert len(location["candidates"]) == 2
    assert all(anchor["p0"] == 0 for anchor in location["candidates"])
    report = evidence.verify(source, proposal(source, CONTROL))
    assert first(report)["location"]["state"] == "ambiguous"
    assert (
        first(evidence.verify(source, proposal(source, CONTROL, page=2)))["location"]["state"]
        == "located"
    )


def test_explicit_anchor_disambiguates_only_the_exact_bounding_quote(source):
    ambiguous = evidence.verify(source, proposal(source, REPEATED, page=1))
    anchor = first(ambiguous)["location"]["candidates"][1]
    located = first(evidence.verify(source, proposal(source, REPEATED, page=1, anchor=anchor)))
    assert located["location"]["state"] == "located" and located["location"]["anchor"] == anchor
    wrong = dict(anchor, o0=anchor["o0"] + 1)
    assert (
        first(evidence.verify(source, proposal(source, REPEATED, anchor=wrong)))["location"][
            "state"
        ]
        == "invalid_anchor"
    )
    assert (
        first(evidence.verify(source, proposal(source, UNIQUE, anchor=anchor)))["location"]["state"]
        == "invalid_anchor"
    )


@pytest.mark.parametrize("page", [-1, 0, 3, 999999999])
def test_invalid_page_never_falls_back_to_a_different_page(source, page):
    location = first(evidence.verify(source, proposal(source, page=page)))["location"]
    assert location["state"] == "invalid_page" and location["anchor"] is None


@pytest.mark.parametrize(
    "anchor",
    [
        {"p0": -1, "o0": 0, "p1": 0, "o1": 1},
        {"p0": 0, "o0": 999, "p1": 0, "o1": 1000},
        {"p0": 1, "o0": 0, "p1": 0, "o1": 1},
        {"p0": 0, "o0": 2, "p1": 0, "o1": 1},
    ],
)
def test_invalid_anchor_bounds_stay_invalid(source, anchor):
    location = first(evidence.verify(source, proposal(source, anchor=anchor)))["location"]
    assert location["state"] == "invalid_anchor" and location["anchor"] is None


def test_explicit_anchor_page_mismatch_is_not_reinterpreted(source):
    anchor = first(evidence.verify(source, proposal(source)))["location"]["anchor"]
    assert (
        first(evidence.verify(source, proposal(source, page=1, anchor=anchor)))["location"]["state"]
        == "invalid_anchor"
    )


def test_normalizes_whitespace_and_line_wrapping_but_not_word_substrings(source):
    result = evidence.verify(source, proposal(source, "intervention was blinded."))
    assert first(result)["location"]["state"] == "located"
    assert first(result)["location"]["anchor"]["o1"] > first(result)["location"]["anchor"]["o0"]
    spaced = evidence.verify(
        source, proposal(source, "Replication  used\n a held-out cohort of 50 participants.")
    )
    assert first(spaced)["location"]["state"] == "located"
    partial = evidence.verify(source, proposal(source, "treatment was excluded."))
    assert first(partial)["location"]["state"] == "missing"


def test_source_change_during_verification_returns_no_partial_report(source, monkeypatch):
    original = evidence._page_words
    changed = []

    def mutate(page, number):
        value = original(page, number)
        if not changed:
            changed.append(True)
            source.path.write_bytes(b"replacement source during verification")
        return value

    monkeypatch.setattr(evidence, "_page_words", mutate)
    with pytest.raises(evidence.EvidenceError, match="source_changed"):
        evidence.verify(source, proposal(source))


def test_changed_or_missing_source_after_resolution_is_not_relocated(source):
    source.path.unlink()
    with pytest.raises(evidence.EvidenceError, match="source_changed"):
        evidence.verify(source, proposal(source))


def test_reader_closed_or_parent_deleted_cannot_authorize_evidence(source):
    source._owner.close()
    with pytest.raises(evidence.EvidenceError, match="source_changed"):
        evidence.verify(source, proposal(source))


def test_stable_ids_are_source_scoped_and_judgment_revision_changes_only_report(source):
    request = proposal(source)
    first_report = evidence.verify(source, request)
    request["claims"][0]["judgment"] = {
        "status": "supported",
        "reason": "Caller revised appraisal.",
    }
    second_report = evidence.verify(source, request)
    assert first_report["id"] != second_report["id"]
    assert first_report["claims"][0]["id"] == second_report["claims"][0]["id"]
    assert first(first_report)["id"] == first(second_report)["id"]
    for value in (first_report["id"], first_report["claims"][0]["id"], first(first_report)["id"]):
        assert len(value) == 64 and all(char in "0123456789abcdef" for char in value)
    # Another trusted paper can own identical bytes; source identity still scopes IDs.
    with sqlite3.connect(source._owner.db_path) as conn:
        conn.execute(
            "INSERT INTO papers(id,title,title_key,year,venue,source) "
            "VALUES('other','Other','other',2026,'Fixture','fixture')"
        )
    (source.path.parent / "other.pdf").write_bytes(source.path.read_bytes())
    other = source._owner.resolve("other")
    assert other.sha256 == source.sha256
    assert (
        evidence.verify(other, proposal(other))["claims"][0]["id"]
        != first_report["claims"][0]["id"]
    )


def test_duplicate_claims_and_passages_are_rejected_but_shared_evidence_is_allowed(source):
    request = proposal(source)
    request["claims"].append(copy.deepcopy(request["claims"][0]))
    with pytest.raises(evidence.EvidenceError, match="duplicate_claim"):
        evidence.verify(source, request)
    request["claims"][1]["text"] = "A separate proposed claim."
    report = evidence.verify(source, request)
    assert first(report)["id"] == report["claims"][1]["passages"][0]["id"]
    request["claims"].pop()
    request["claims"][0]["passages"] *= 2
    with pytest.raises(evidence.EvidenceError, match="duplicate_passage"):
        evidence.verify(source, request)


def test_empty_claim_list_and_unresolved_claim_without_quotes_are_valid(source):
    request = proposal(source)
    request["claims"] = []
    assert evidence.verify(source, request)["claims"] == []
    request = proposal(source)
    request["claims"][0]["passages"] = []
    assert evidence.verify(source, request)["claims"][0]["semantic_validation"] == "not_performed"


@pytest.mark.parametrize(
    "change",
    [
        lambda data: data.update(extra="unexpected"),
        lambda data: data["source"].update(path="forbidden"),
        lambda data: data["claims"][0].update(score=0.99),
        lambda data: data["claims"][0]["judgment"].update(status=[]),
        lambda data: data["claims"][0]["judgment"].update(confidence=99),
        lambda data: data["claims"][0]["passages"][0].update(page=True),
        lambda data: data["claims"][0]["passages"][0].update(quote=""),
        lambda data: data["claims"][0]["passages"][0].update(anchor={"p0": 0}),
        lambda data: data["claims"][0]["passages"][0].update(citation={"title": "Guess"}),
    ],
)
def test_closed_schema_and_types_fail_without_echoing_untrusted_content(source, change):
    request = proposal(source)
    change(request)
    with pytest.raises(evidence.EvidenceError) as caught:
        evidence.verify(source, request)
    assert caught.value.code == "invalid_schema"
    assert str(caught.value) == "Claim evidence verification: invalid_schema"


@pytest.mark.parametrize(
    "limit,value,code",
    [
        ("MAX_REQUEST_BYTES", 10, "request_limit"),
        ("MAX_CLAIMS", 0, "claim_limit"),
        ("MAX_PASSAGES", 0, "passage_limit"),
        ("MAX_PDF_BYTES", 10, "pdf_limit"),
        ("MAX_PAGES", 1, "page_limit"),
        ("MAX_WORDS", 1, "text_limit"),
        ("MAX_WORDS_PER_PAGE", 1, "text_limit"),
        ("MAX_TEXT_CHARS", 1, "text_limit"),
    ],
)
def test_all_budgets_fail_observably_without_partial_report(
    source, monkeypatch, limit, value, code
):
    monkeypatch.setattr(evidence, limit, value)
    with pytest.raises(evidence.EvidenceError) as caught:
        evidence.verify(source, proposal(source))
    assert caught.value.code == code


def test_ambiguity_candidates_are_bounded_without_hiding_truncation(source, monkeypatch):
    monkeypatch.setattr(evidence, "MAX_MATCHES", 1)
    location = first(evidence.verify(source, proposal(source, REPEATED)))["location"]
    assert location["state"] == "ambiguous" and len(location["candidates"]) == 1
    assert location["truncated"] and location["anchor"] is None


def test_cancelled_before_or_during_verification_does_not_return_a_report(source):
    with pytest.raises(evidence.EvidenceError, match="cancelled"):
        evidence.verify(source, proposal(source), cancelled=lambda: True)
    calls = []

    def cancelled():
        calls.append(True)
        return len(calls) == 3

    with pytest.raises(evidence.EvidenceError, match="cancelled"):
        evidence.verify(source, proposal(source), cancelled=cancelled)
    assert len(calls) == 3


def test_invalid_pdf_is_not_treated_as_a_missing_quote(source):
    source.path.write_bytes(b"%PDF-1.4\nnot a valid PDF object")
    document = source._owner.resolve("paper")
    assert document.status == "invalid" and not document.available
    assert document.path is None
    with pytest.raises(evidence.EvidenceError, match="source_unavailable"):
        evidence.verify(document, proposal(document))


def test_parser_failure_has_no_partial_report_or_raw_error_content(source, monkeypatch):
    def fail(*a, **kw):
        raise RuntimeError("Private parser details " + str(source.path))

    monkeypatch.setattr(pymupdf, "open", fail)
    with pytest.raises(evidence.EvidenceError) as caught:
        evidence.verify(source, proposal(source))
    assert caught.value.code == "invalid_document"
    assert str(caught.value) == "Claim evidence verification: invalid_document"


def test_cross_page_quote_uses_explicit_verified_word_coordinates(source):
    quote = "pretreatment was excluded. Replication used a held-out"
    result = evidence.verify(source, proposal(source, quote))
    anchor = first(result)["location"]["anchor"]
    assert first(result)["location"]["state"] == "located"
    assert anchor["p0"] == 0 and anchor["p1"] == 1
    explicit = evidence.verify(source, proposal(source, quote, anchor=anchor))
    assert first(explicit)["location"]["anchor"] == anchor


def test_proposal_mutation_during_pdf_io_does_not_change_the_verified_claim(source, monkeypatch):
    request = proposal(source)
    original = evidence._page_words

    def mutate(page, number):
        request["source"]["paper_id"] = "different-owner"
        request["claims"][0]["text"] = "Malicious changed proposal"
        return original(page, number)

    monkeypatch.setattr(evidence, "_page_words", mutate)
    report = evidence.verify(source, request)
    assert report["source"]["paper_id"] == "paper"
    assert report["claims"][0]["text"] == "The study establishes general clinical benefit."
    assert first(report)["location"]["state"] == "located"


def test_encrypted_document_has_its_own_observable_failure(source, tmp_path):
    encrypted = tmp_path / "encrypted.pdf"
    with pymupdf.open(source.path) as document:
        document.save(
            encrypted,
            encryption=pymupdf.PDF_ENCRYPT_AES_256,
            owner_pw="fixture-owner",
            user_pw="fixture-reader",
        )
    source.path.write_bytes(encrypted.read_bytes())
    document = source._owner.resolve("paper")
    assert document.status == "invalid" and not document.available
    with pytest.raises(evidence.EvidenceError, match="source_unavailable"):
        evidence.verify(document, proposal(document))


def test_local_id_relabel_cannot_borrow_another_papers_verified_path(source):
    with sqlite3.connect(source._owner.db_path) as conn:
        conn.execute(
            "INSERT INTO papers(id,title,title_key,year,venue,source) "
            "VALUES('other','Other','other',2026,'Fixture','fixture')"
        )
    other_path = source.path.parent / "other.pdf"
    pdf(other_path, [["A different paper with different source bytes."]])
    forged = replace(source, local_id="other")
    with pytest.raises(evidence.EvidenceError) as caught:
        evidence.verify(forged, proposal(forged))
    assert caught.value.code == "source_identity_mismatch"


def test_managed_source_requires_its_trusted_portable_identity(tmp_path):
    from test_document_reader import prepared

    _database, _journal, _store, reader, _alias, _data = prepared(tmp_path)
    from test_document_reader import LOCAL

    document = reader.resolve(LOCAL)
    assert document.available and document.paper_id and document.paper_id != document.local_id
    request = proposal(document)
    request["claims"] = []
    report = evidence.verify(document, request)
    assert report["source"]["paper_id"] == document.paper_id
    request["source"]["paper_id"] = document.local_id
    with pytest.raises(evidence.EvidenceError, match="source_identity_mismatch"):
        evidence.verify(document, request)


def test_located_passage_id_survives_adding_page_and_exact_anchor_hints(source):
    automatic = first(evidence.verify(source, proposal(source)))
    explicit = first(
        evidence.verify(source, proposal(source, page=2, anchor=automatic["location"]["anchor"]))
    )
    assert automatic["id"] == explicit["id"]
    assert automatic["proposal_id"] != explicit["proposal_id"]
