"""Frozen capability gate from the pre-queue-pin real package reader."""

import json

from paper_daily import annotation_content
from paper_daily.bundle import FORMAT


def _required_capabilities(tables):
    capabilities = []
    if tables.get("paper_claim_sets") or any(
        row.get("feature") == "claims" for row in tables.get("paper_annotation_known", [])
    ):
        capabilities.append("claim_evidence")
    if tables.get("list_reading_goals"):
        capabilities.append("reading_goal")
    if any(tables.get(table) for table in annotation_content.FEATURES.values()):
        capabilities.append("reading_annotations")
    if tables.get("paper_annotation_known"):
        capabilities.append("annotation_deletions")
    return sorted(capabilities)


def _validated(z):
    names = z.namelist()
    if len(names) != len({name.casefold() for name in names}):
        raise ValueError("資料包包含重複檔名")
    try:
        manifest = json.loads(z.read("manifest.json"))
        tables = json.loads(z.read("tables.json"))
        if type(manifest.get("format")) is not int or manifest["format"] not in (FORMAT, 2):
            raise ValueError("不支援的研究資料包格式")
        listing = manifest["list"]
        if not all(
            isinstance(listing.get(k), str) and listing[k] for k in ("id", "name", "created_at")
        ):
            raise ValueError("資料包缺少清單資訊")
        required = _required_capabilities(tables)
        capabilities = manifest.get("capabilities", [])
        if manifest["format"] == 2:
            if not required or capabilities != required:
                raise ValueError("Package capabilities do not match its research content")
        elif required or capabilities:
            raise ValueError("Extended research requires the version-2 package format")
        return manifest, tables
    except (KeyError, TypeError, AttributeError, json.JSONDecodeError) as exc:
        raise ValueError("Invalid legacy package") from exc
