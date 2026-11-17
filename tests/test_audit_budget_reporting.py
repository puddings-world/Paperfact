"""AI disclosures distinguish configured intent from provider-reported facts."""

from pathlib import Path

import pytest

from paper_daily import llm
from paper_daily.desktop.source_fact_dialog import TEXT


@pytest.fixture(autouse=True)
def actual_candidate_source():
    expected = Path(__file__).resolve().parents[1] / "src/paper_daily"
    assert Path(llm.__file__).resolve() == expected / "llm.py"


@pytest.mark.parametrize("language", ["en", "zh-TW"])
def test_audit_output_budget_copy_is_a_setting_with_service_controlled_limits(language):
    text = TEXT[language]["budget"].format(tokens=4000)
    assert "4000" in text
    if language == "en":
        assert "budget setting" in text.lower() and "AI service" in text
        assert "output cap" not in text.lower()
    else:
        assert "\u9810\u7b97\u8a2d\u5b9a" in text and "\u5be6\u969b" in text
