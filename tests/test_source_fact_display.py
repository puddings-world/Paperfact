"""Human report labels preserve source text and closed proposal distinctions."""

import copy
import json
from types import SimpleNamespace

import pytest
from test_audit_facts import atom, batch
from test_audit_facts import captured as captured_fixture
from test_audit_facts import source as source_fixture
from test_research_evidence import UNIQUE

from paper_daily import audit_consistency, audit_facts, research_audit
from paper_daily.desktop import source_fact_dialog as dialog

source, captured = source_fixture, captured_fixture


@pytest.fixture
def report(captured):
    facts = [
        atom("original"),
        atom("saved", location=dict(kind="output", item_id="notes:1", start=0, end=15)),
    ]
    sheet = audit_facts.prepare(captured, batch(captured, facts))
    execution = dict(
        backend="openai",
        requested_model="requested/author_stated-v1",
        reported_model="reported/sample-2026.10",
        max_tokens=4000,
        outcome="proposed",
        empty_reason=None,
    )
    return SimpleNamespace(
        sheet=sheet,
        execution=execution,
        consistency=audit_consistency.compare(sheet),
        items=json.loads(captured._items_json),
    )


@pytest.mark.parametrize("language", ["en", "zh-TW"])
def test_source_bound_report_uses_human_metadata_labels_and_full_provenance(report, language):
    before = copy.deepcopy(
        (report.sheet.report, report.execution, report.consistency, report.items)
    )
    rendered = dialog._render(report, report.items, dialog.TEXT[language], language)
    text = rendered["text"]
    expected = {
        "en": [
            "Original file SHA-256: ",
            "Category: Participants / sample",
            "Attribution: Attributed to authors (proposed)",
            "Saved output Note (notes:1)",
            "Comparison: none",
            "Population / material: held-out cohort",
            "Original version not recorded for this output",
            "Quote location: Passage located; semantic support not checked",
        ],
        "zh-TW": [
            "原始檔 SHA-256: ",
            "類別: 參與者／樣本",
            "陳述歸屬: 歸屬於作者的陳述（提案）",
            "已存內容 筆記 (notes:1)",
            "比較對象: none",
            "母群體／材料: held-out cohort",
            "此內容未記錄原文版本",
            "引文位置: 已定位引文；未檢查語意支持",
        ],
    }[language]
    assert all(value in text for value in expected)
    assert expected[0] + report.sheet.report["source"]["document_hash"] in text
    assert UNIQUE in text and "50 participants" in text and "0–15" in text
    assert "requested/author_stated-v1" in text and "reported/sample-2026.10" in text
    assert "sample / author_stated" not in text and "comparator=" not in text
    assert "source_unknown" not in text
    assert rendered["result"] is report and rendered["execution"] is report.execution
    assert len(rendered["sources"]) == 2
    assert rendered["sources"] == [
        dict(
            kind="audit",
            document_hash=report.sheet.report["source"]["document_hash"],
            anchor=fact["evidence"][0]["location"]["anchor"],
            page=fact["evidence"][0]["location"]["page"],
            text=UNIQUE,
            number=index,
        )
        for index, fact in enumerate(report.sheet.report["facts"], 1)
    ]
    assert before == (report.sheet.report, report.execution, report.consistency, report.items)


@pytest.mark.parametrize("language", ["en", "zh-TW"])
def test_closed_report_label_sets_cover_actual_metadata_contracts(language):
    labels = dialog.REPORT_LABELS[language]
    assert set(labels["categories"]) == audit_facts.CATEGORIES
    assert set(labels["origins"]) == audit_facts.ORIGINS
    assert set(labels["scope"]) == audit_facts.SCOPE
    assert set(labels["features"]) == research_audit.FEATURES
    assert set(labels["bindings"]) == {"exact", "unknown", "different_original"}
    assert set(labels["quote_states"]) == {
        "located", "missing", "ambiguous", "invalid_page", "invalid_anchor"
    }
    assert set(labels["reasons"]) == {
        "study_type_unknown", "source_unknown", "source_different_original",
        "reviewer_inferred", "not_reported", "not_applicable", "unknown",
        "evidence_unverified", "different_category", "scope_unknown", "different_scope",
        "different_value_kind", "derivation_not_verified", "page_out_of_range",
        "anchor_out_of_range_or_page_mismatch", "anchor_does_not_bound_unique_quote",
        "multiple_quote_locations", "quote_not_found",
    }


@pytest.mark.parametrize("language", ["en", "zh-TW"])
def test_freeform_values_models_quotes_and_missing_identity_are_not_translated(report, language):
    sheet = report.sheet.report
    exact = "sample / author_stated; comparator=population; 0.00 mg/L — 原文"
    sheet["facts"][0]["scope"]["unit"] = exact
    sheet["facts"][0]["value"]["decimal"] = "0.00"
    sheet["facts"][0]["value"]["rounded_places"] = 2
    sheet["facts"][0]["value"]["derived"] = True
    sheet["facts"][0]["evidence"][0]["quote"] = exact
    report.sheet = SimpleNamespace(report=sheet)
    report.execution["reported_model"] = None
    text = dialog._render(report, report.items, dialog.TEXT[language], language)["text"]
    assert exact in text
    assert dialog.TEXT[language]["value"] + ": 0.00" in text
    assert dialog.TEXT[language]["rounded"] + ": 2" in text
    assert dialog.TEXT[language]["derived"] in text
    assert dialog.TEXT[language]["unreported"] in text
    assert "requested/author_stated-v1" in text
    assert "reported/sample-2026.10" not in text


@pytest.mark.parametrize("language", ["en", "zh-TW"])
def test_reason_and_quote_status_labels_do_not_change_source_actions_or_comparison_states(
    report, language
):
    labels = dialog.REPORT_LABELS[language]
    sheet = report.sheet.report
    report.sheet = SimpleNamespace(report=sheet)
    for reason, friendly in labels["reasons"].items():
        report.consistency["comparisons"][0]["reason"] = reason
        before = copy.deepcopy(report.consistency)
        rendered = dialog._render(report, report.items, dialog.TEXT[language], language)
        assert friendly in rendered["text"]
        assert dialog.STATES[language]["not_comparable"] in rendered["text"]
        assert report.consistency == before
    for state, friendly in labels["quote_states"].items():
        for fact in sheet["facts"]:
            fact["evidence"][0]["location"]["state"] = state
        rendered = dialog._render(report, report.items, dialog.TEXT[language], language)
        assert friendly in rendered["text"]
        assert len(rendered["sources"]) == (2 if state == "located" else 0)
