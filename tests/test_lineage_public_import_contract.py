"""Public native import accepts complete originals and rejects invalid closure atomically."""

import json
import zipfile
from contextlib import closing

import pytest
from test_lineage_bundle_journey import dump, select
from test_lineage_bundle_journey import shared as shared
from test_package_import import enroll_capture
from test_research_lineage import corpus as corpus
from test_sync_files import codec as codec
from test_sync_files import pair as pair

from paper_daily import bundle, lineage_sets, llm
from paper_daily.sync_source_files import resolved

STAMP = "2026-11-01T00:00:00+00:00"


def corrected(source, output, *, damage=None):
    with zipfile.ZipFile(source) as original:
        manifest = json.loads(original.read("manifest.json"))
        manifest["list"]["created_at"] = STAMP
        for member in manifest["members"]:
            member["added_at"] = STAMP
        target = "files/" + manifest["lineage_sources"][0]["path"]
        with zipfile.ZipFile(output, "w") as archive:
            for name in original.namelist():
                if name == target and damage == "missing":
                    continue
                data = original.read(name)
                if name == "manifest.json":
                    data = json.dumps(manifest).encode("utf-8")
                elif name == target and damage == "corrupt":
                    data = b"wrong exact original"
                archive.writestr(name, data)
    return output


def test_complete_public_native_import_preserves_science_model_and_all_originals_without_download(
    shared, pair, tmp_path, monkeypatch
):
    path, _source, originals, rows = shared
    client = pair[1]
    enroll_capture(client)
    select(monkeypatch, client.journal.path)
    monkeypatch.setattr(llm, "complete_result", lambda *_a, **_k: pytest.fail("No AI call"))
    archive = corrected(path, tmp_path / "realistic-timestamps.zip")
    result = bundle.import_(archive, pdfs=False)
    assert result["state"] == "applied_locally" and result["lineage_reports"] == 1
    mapping = result["identity_mapping"]
    focal = mapping["focal"]["local_id"]
    row = lineage_sets.saved(client.journal.path, focal)[0]
    actual, expected = (
        lineage_sets.decode(row["body_json"]),
        lineage_sets.decode(rows[0]["body_json"]),
    )
    assert actual["report"] == expected["report"] and actual["generation"] == expected["generation"]
    assert row["written_at"] == rows[0]["written_at"]
    expected_bytes = {
        source["document_hash"]: originals[binding["paper_id"]]
        for binding, source in zip(expected["bindings"], expected["report"]["sources"], strict=True)
    }
    with closing(client.journal._connect()) as conn:
        for binding, source in zip(actual["bindings"], actual["report"]["sources"], strict=True):
            old = next(
                key for key, item in mapping.items() if item["local_id"] == binding["paper_id"]
            )
            selected = resolved(conn, mapping[old]["portable_id"], source["document_hash"])
            assert selected.read_bytes() == expected_bytes[source["document_hash"]]
    science = [op for op in client.journal.pending() if op["payload"].get("feature") == "lineage"]
    assert len(science) == 1 and len(science[0]["source_dependencies"]) == 3
    before, pending = dump(client.journal.path), client.journal.pending()
    assert bundle.import_(archive, pdfs=False)["state"] == "previously_applied"
    assert dump(client.journal.path) == before and client.journal.pending() == pending


@pytest.mark.parametrize("damage", ["missing", "corrupt"])
def test_public_native_import_rejects_bad_originals_before_research_or_outbox_changes(
    shared, pair, tmp_path, monkeypatch, damage
):
    path, _source, _originals, _rows = shared
    client = pair[1]
    enroll_capture(client)
    select(monkeypatch, client.journal.path)
    archive = corrected(path, tmp_path / (damage + ".zip"), damage=damage)
    before, pending = dump(client.journal.path), client.journal.pending()
    with pytest.raises(ValueError):
        bundle.import_(archive, pdfs=False)
    assert dump(client.journal.path) == before and client.journal.pending() == pending
