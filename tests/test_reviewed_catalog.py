"""Public bilingual explanations must not regress to ASCII replacement marks."""

import json
from pathlib import Path


def test_reviewed_chinese_explanations_contain_readable_chinese():
    path = Path(__file__).resolve().parents[1] / "docs/testing/catalog.json"
    catalog = json.loads(path.read_text(encoding="utf-8"))
    assert catalog["format"] == "paperfact.test-catalog.v1" and catalog["entries"]
    for entry in catalog["entries"]:
        prose = entry["zh-TW"]
        fields = [(key, prose[key]) for key in ("title", "scenario", "risk_protected")]
        for key in ("actions", "expected_outcomes", "not_proven"):
            assert prose[key], (entry["id"], key)
            fields.extend((key, text) for text in prose[key])
        for key, text in fields:
            assert any("\u3400" <= char <= "\u9fff" for char in text), (entry["id"], key, text)
