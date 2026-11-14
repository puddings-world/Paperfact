"""Public bundle paths retain exact Lineage closure and reject incomplete packages."""

import json
import zipfile

import pytest
from test_lineage_recovery import published
from test_research_lineage import corpus as corpus

from paper_daily import bundle, store


def test_legacy_list_export_refuses_lineage_before_replacing_a_previous_package(
    corpus, monkeypatch, tmp_path
):
    published(corpus, monkeypatch)
    monkeypatch.setattr(store, "DB_PATH", corpus[0])
    monkeypatch.setattr(bundle, "DATA_DIR", corpus[0].parent)
    monkeypatch.setattr(bundle, "PDF_DIR", corpus[1])
    monkeypatch.setattr(bundle, "pdf_record", lambda *_a, **_k: None)
    with store.connect() as conn:
        conn.execute(
            "INSERT INTO lists(id,name,created_at) VALUES('lineage-list','Lineage','fixture')"
        )
        conn.execute(
            "INSERT INTO list_papers(list_id,paper_id,position,state,added_at) "
            "VALUES('lineage-list','focal',0,'pending','fixture')"
        )
    output = tmp_path / "existing-package.zip"
    previous = b"A previous user-owned package must remain untouched"
    output.write_bytes(previous)
    with pytest.raises(ValueError, match="Include exact originals.*Lineage"):
        bundle.export("lineage-list", output, with_pdfs=False)
    assert output.read_bytes() == previous


def test_lineage_rows_require_the_explicit_versioned_package_capability():
    assert bundle._required_capabilities({"paper_lineage_sets": [{"paper_id": "incoming"}]}) == [
        "lineage"
    ]


def test_legacy_reader_refuses_lineage_source_marker_even_if_rows_are_omitted(tmp_path):
    path = tmp_path / "undeclared.zip"
    manifest = dict(
        format=1,
        list=dict(id="fixture", name="Fixture", created_at="fixture"),
        members=[],
        lineage_sources=[],
        file_hashes={},
        pdfs={},
    )
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("manifest.json", json.dumps(manifest))
        archive.writestr("tables.json", json.dumps(dict(papers=[])))
    with (
        zipfile.ZipFile(path) as archive,
        pytest.raises(ValueError, match="Lineage.*closure"),
    ):
        bundle._validated(archive)
