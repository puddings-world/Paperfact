"""Real-PDF derivative fixtures preserve exact provenance without legacy adoption."""

import hashlib
import json
import os
import sqlite3
import threading
from types import SimpleNamespace

import pymupdf
import pytest
from test_document_reader import LOCAL, prepared, register
from test_presentation_pane import pane as _editor_fixture
from test_sync_document_research import document, local_blob, target
from test_sync_reading_state_research import save

from paper_daily import (
    config,
    document_reader,
    fetch,
    figures,
    materials,
    pdf_downloads,
    pocket,
    presentations,
    share,
    store,
)
from paper_daily.sync_documents import bind_verified_document, verify_document

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
editor = _editor_fixture


def pdf(text, *, second_page=False, caption_y=300):
    with pymupdf.open() as doc:
        if second_page:
            doc.new_page().insert_text((50, 60), "An intentionally different opening page.")
        page = doc.new_page()
        page.insert_text((40, 60), text, fontsize=12)
        page.draw_rect(
            (45, caption_y - 150, 360, caption_y - 25), color=(0.1, 0.2, 0.8), fill=(0.6, 0.8, 0.9)
        )
        page.insert_text((50, caption_y), "Figure 1: Synthetic research result", fontsize=12)
        return doc.tobytes()


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    path, journal, blobs, reader, alias, _ = prepared(tmp_path)
    register(path, journal, blobs, reader)
    monkeypatch.setattr(config, "DB_PATH", path)
    monkeypatch.setattr(config, "PDF_DIR", reader.legacy_root)
    monkeypatch.setattr(store, "DB_PATH", path)
    monkeypatch.setattr(fetch, "ensure_dirs", lambda: None)
    monkeypatch.setattr(figures, "ensure_dirs", lambda: None)
    for module in (fetch, materials, presentations, pocket, pdf_downloads):
        monkeypatch.setattr(module, "PDF_DIR", reader.legacy_root)
    for module in (fetch, materials, presentations):
        monkeypatch.setattr(module, "TEXT_DIR", tmp_path / "text")
    for module in (figures, materials, presentations, pocket, share):
        monkeypatch.setattr(module, "FIG_DIR", tmp_path / "figures")
    for module in (materials, presentations):
        monkeypatch.setattr(module, "DATA_DIR", tmp_path)
    monkeypatch.setattr(pocket, "POCKET_PDF_DIR", tmp_path / "pocket-pdf")
    monkeypatch.setattr(figures, "MIN_PNG_BYTES", 0)

    def install(data, identity):
        save(journal, document(data, op_id=identity))
        local_blob(blobs, data)
        wanted = target(path)
        verified = verify_document(blobs, wanted)
        with journal.transaction() as conn:
            assert bind_verified_document(conn, wanted, verified)
        return document_reader.resolve_document(LOCAL)

    return SimpleNamespace(
        path=path, journal=journal, blobs=blobs, alias=alias, install=install, tmp=tmp_path
    )


def row():
    return {"id": LOCAL, "pdf_url": "https://example.invalid/unwanted.pdf", "arxiv_id": "1234.5678"}


@pytest.mark.parametrize("state", ["missing", "detached", "unbound"])
def test_managed_unavailable_never_uses_alias_text_cache_or_network(workspace, monkeypatch, state):
    current = workspace.install(pdf("1 First Methods"), "first")
    legacy = workspace.alias.read_bytes()
    fetch.TEXT_DIR.mkdir()
    (fetch.TEXT_DIR / (fetch._safe_name(LOCAL) + ".txt")).write_text("Stale legacy text")
    if state == "detached":
        save(workspace.journal, document(b"", op_id="detach", action="delete"))
    elif state == "unbound":
        save(workspace.journal, document(pdf("2 Unbound Methods"), op_id="unbound"))
    else:
        (workspace.blobs.root / "objects" / current.sha256).unlink()
    monkeypatch.setattr(fetch, "fetch", lambda *a, **k: pytest.fail("managed URL fallback"))
    monkeypatch.setattr(
        pdf_downloads.pdf_sources, "discover", lambda *a, **k: pytest.fail("managed discovery")
    )
    assert fetch.ensure_pdf(row()) is None
    assert fetch.prepare(row()) == (None, None)
    assert fetch.extract_text(workspace.alias, LOCAL) is None
    assert figures.extract(LOCAL, workspace.alias) == []
    assert materials._pages(LOCAL) == []
    assert materials.figure_entries(LOCAL) == []
    assert pocket.pocket_pdf(LOCAL) is None and pocket.figures_for(LOCAL) == []
    assert pocket.locate(LOCAL, "Original text") is None
    with pytest.raises(pdf_downloads.FetchError, match="synchronization"):
        pdf_downloads.download(LOCAL, lambda *args: None, threading.Event())
    assert workspace.alias.read_bytes() == legacy


def test_text_cache_keys_include_hash_options_and_reject_old_captured_path(workspace):
    first = workspace.install(pdf("1 Alpha Methods with original scientific details"), "first")
    assert fetch.ensure_pdf(row()) == first.path
    short = fetch.extract_text(first.path, LOCAL, max_chars=12, document=first)
    full = fetch.extract_text(first.path, LOCAL, max_chars=2000, document=first)
    assert len(short) == 12 and "original scientific details" in full
    assert len(list(fetch.TEXT_DIR.rglob("body.txt"))) == 2
    second = workspace.install(
        pdf("2 Beta Methods with different scientific evidence", second_page=True), "second"
    )
    assert fetch.extract_text(first.path, LOCAL, document=first) is None
    assert fetch.extract_text(first.path, LOCAL) is None
    assert "Beta Methods" in fetch.extract_text(second.path, LOCAL)
    assert first.path.exists() and second.path.exists()
    assert len(list(fetch.TEXT_DIR.rglob("body.txt"))) == 3


def test_figure_cache_and_material_coordinates_follow_source_hash(workspace):
    first = workspace.install(pdf("1 Alpha Methods", caption_y=300), "first")
    old = figures.extract(LOCAL, first.path, document=first)
    assert old and old[0].page == 1 and old[0].meta["document_hash"] == first.sha256
    old_path = old[0].path
    second = workspace.install(pdf("2 Beta Methods", second_page=True, caption_y=520), "second")
    new = figures.extract(LOCAL, second.path, document=second)
    assert new and new[0].page == 2 and new[0].path != old_path
    assert old_path.exists()
    entries = materials.figure_entries(LOCAL)
    assert entries and all(item["document_hash"] == second.sha256 for item in entries)
    assert entries[0]["rect"] != old[0].meta["rect"]
    stale = {"caption": old[0].caption, "page": 1, **old[0].meta}
    unproven = {"caption": old[0].caption, "page": 1, "rect": [1, 2, 3, 4]}
    fresh = {"text": "2 Beta Methods", "page": 2, "document_hash": second.sha256}
    materials._locate_materials(LOCAL, [stale, unproven, fresh], document=second)
    assert "rect" not in stale and stale["document_hash"] == first.sha256
    assert not stale["navigation_available"]
    assert "rect" not in unproven and "document_hash" not in unproven
    assert fresh["rect"] and fresh["document_hash"] == second.sha256
    assert figures.image_path(LOCAL, {"file": old_path.name, **old[0].meta}) is None
    assert (
        figures.image_path(LOCAL, {"file": old_path.name, **old[0].meta}, historical=True)
        == old_path
    )


def test_managed_cached_only_figure_lookup_never_hashes_or_extracts_on_ui(workspace, monkeypatch):
    captured = workspace.install(pdf("1 Cached Methods"), "first")
    initial = figures.extract(LOCAL, captured.path, document=captured)
    assert initial
    monkeypatch.setattr(
        document_reader,
        "resolve_document",
        lambda *a, **k: pytest.fail("UI lookup attempted verification"),
    )
    monkeypatch.setattr(pymupdf, "open", lambda *a, **k: pytest.fail("UI lookup opened PDF"))
    cached = figures.extract(LOCAL, captured.path, cached_only=True)
    assert [figure.path for figure in cached] == [figure.path for figure in initial]
    assert (
        figures.image_path(LOCAL, {"file": initial[0].path.name, **initial[0].meta})
        == initial[0].path
    )


def test_figure_options_change_cache_and_unproven_index_is_not_adopted(workspace, monkeypatch):
    captured = workspace.install(pdf("1 Rendering Methods"), "first")
    first = figures.extract(LOCAL, captured.path, document=captured)
    monkeypatch.setattr(figures, "RENDER_SCALE", 1.25)
    second = figures.extract(LOCAL, captured.path, document=captured)
    assert first[0].path != second[0].path and first[0].path.exists()
    index = second[0].path.parent / "index.json"
    values = json.loads(index.read_text())
    values[0]["document_hash"] = "0" * 64
    index.write_text(json.dumps(values))
    assert figures.extract(LOCAL, captured.path, cached_only=True, document=captured) == []
    assert materials.figure_entries(LOCAL) == []


def test_managed_presentation_and_share_preserve_original_figure_assets(workspace):
    captured = workspace.install(pdf("1 Presentation Methods"), "first")
    extracted = figures.extract(LOCAL, captured.path, document=captured)
    evidence = presentations.collect_evidence(LOCAL, {"original"})
    assert evidence["figures"][0]["document_hash"] == captured.sha256
    assert all(
        source["document_hash"] == captured.sha256
        for source in evidence["sources"]
        if source["kind"] in ("original", "figure")
    )
    deck = SimpleNamespace(paper_id=LOCAL, figures=evidence["figures"])
    original = presentations.figure_bytes(deck, evidence["figures"][0]["id"])
    name = share._figure_file(
        LOCAL, extracted[0].path.name, workspace.tmp / "export", item=evidence["figures"][0]
    )
    assert (workspace.tmp / "export" / name).exists()
    workspace.install(pdf("2 Replacement", second_page=True), "second")
    assert presentations.figure_bytes(deck, evidence["figures"][0]["id"]) == original
    assert extracted[0].path.read_bytes() == original


def test_pocket_pdf_records_own_hash_and_explicit_original_link(workspace):
    captured = workspace.install(pdf("1 Portable Methods"), "first")
    derivative = pocket.pocket_pdf(LOCAL)
    metadata = json.loads(derivative.with_suffix(".json").read_text())
    assert metadata["source_hash"] == captured.sha256
    assert metadata["document_hash"] == hashlib.sha256(derivative.read_bytes()).hexdigest()
    anchor = pocket.locate(LOCAL, "1 Portable Methods")
    assert anchor["document_hash"] == captured.sha256
    stamp = derivative.stat().st_mtime_ns
    assert pocket.pocket_pdf(LOCAL).stat().st_mtime_ns == stamp
    replacement = workspace.install(pdf("2 Portable Revision", second_page=True), "second")
    newer = pocket.pocket_pdf(LOCAL)
    assert newer != derivative and derivative.exists()
    assert json.loads(newer.with_suffix(".json").read_text())["source_hash"] == replacement.sha256


def test_colliding_unmanaged_aliases_do_not_start_legacy_downloads(workspace, monkeypatch):
    ids = ["collision:a", "collision/a"]
    with sqlite3.connect(workspace.path) as conn:
        store.upsert_papers(
            conn,
            [
                {
                    "id": identity,
                    "title": identity,
                    "venue": "Fixture",
                    "year": 2026,
                    "source": "fixture",
                }
                for identity in ids
            ],
        )
    alias = fetch.PDF_DIR / "collision_a.pdf"
    alias.write_bytes(pdf("Unowned alias"))
    monkeypatch.setattr(fetch, "fetch", lambda *a, **k: pytest.fail("ambiguous alias fetch"))
    for identity in ids:
        assert fetch.ensure_pdf({"id": identity}) is None
        assert fetch.extract_text(alias, identity) is None
        with pytest.raises(pdf_downloads.FetchError):
            pdf_downloads.download(identity, lambda *args: None, threading.Event())


def test_stale_material_preview_retains_image_without_granting_current_navigation(workspace):
    from PySide6.QtWidgets import QApplication

    from paper_daily.desktop.figure_pane import FigurePane
    from paper_daily.desktop.main import LIGHT

    app = QApplication.instance() or QApplication([])
    captured = workspace.install(pdf("1 Before Replacement"), "first")
    extracted = figures.extract(LOCAL, captured.path, document=captured)
    pane = FigurePane(LIGHT)
    pane._paper_id = LOCAL
    pane._show(LOCAL, extracted)
    assert pane.loaded_document_hash == captured.sha256
    workspace.install(pdf("2 Later Version", second_page=True), "second")
    observed = []
    pane.jump.connect(lambda page, caption: observed.append((page, pane.loaded_document_hash)))
    pane._jump(extracted[0])
    # Parent reader compares this old hash with its actual rendered hash, rather
    # than silently relabeling the figure with the newly desired document.
    assert observed == [(1, captured.sha256)]
    pane._show(LOCAL, extracted)
    assert pane.loaded_document_hash is None
    pane.deleteLater()
    app.processEvents()


def test_materials_preview_and_add_to_deck_keep_managed_provenance(workspace):
    from PySide6.QtWidgets import QApplication

    from paper_daily.desktop.materials_panel import MaterialsPanel
    from paper_daily.desktop.presentation_pane import PresentationPane

    app = QApplication.instance() or QApplication([])
    captured = workspace.install(pdf("1 Material Methods"), "first")
    # Collect is the explicit deterministic worker action; it creates missing
    # managed figure derivatives without any publisher/AI request.
    found = materials.collect(LOCAL)
    assert found.exhibits and found.exhibits[0]["document_hash"] == captured.sha256
    panel = MaterialsPanel()
    panel.load(found)
    item = panel.tree.topLevelItem(0).child(0)
    panel._selected(item, None)
    assert not panel._preview_image.isNull()
    from PySide6.QtCore import Qt

    payload = item.data(0, Qt.ItemDataRole.UserRole)
    assert payload["cache_key"] == found.exhibits[0]["cache_key"]
    fake = SimpleNamespace(
        deck=SimpleNamespace(figures=[], sources=[]),
        figure=SimpleNamespace(addItem=lambda *args: None),
        _add_source_item=lambda *args: None,
    )
    PresentationPane._ensure_evidence(fake, payload)
    assert fake.deck.figures[0]["document_hash"] == captured.sha256
    assert fake.deck.figures[0]["cache_key"] == payload["cache_key"]
    assert fake.deck.sources[0]["document_hash"] == captured.sha256
    panel.deleteLater()
    app.processEvents()


def test_managed_original_evidence_does_not_adopt_legacy_cache_when_detached(workspace):
    captured = workspace.install(pdf("1 Actual Original"), "first")
    figures.extract(LOCAL, captured.path, document=captured)
    fetch.TEXT_DIR.mkdir(exist_ok=True)
    (fetch.TEXT_DIR / (fetch._safe_name(LOCAL) + ".txt")).write_text("Legacy alias contents")
    save(workspace.journal, document(b"", op_id="detach", action="delete"))
    with pytest.raises(ValueError):
        presentations.collect_evidence(LOCAL, {"original"})


def test_replacement_during_text_extraction_drops_result_without_relabeling(workspace, monkeypatch):
    captured = workspace.install(pdf("1 First Methods"), "first")
    replacement = pdf("2 Later Methods", second_page=True)
    original_open = pymupdf.open
    fired = False

    def changed(*args, **kwargs):
        nonlocal fired
        handle = original_open(*args, **kwargs)
        if not fired and args and str(args[0]) == str(captured.path):
            fired = True
            workspace.install(replacement, "second")
        return handle

    monkeypatch.setattr(pymupdf, "open", changed)
    assert fetch.extract_text(captured.path, LOCAL, document=captured) is None
    assert not list(fetch.TEXT_DIR.rglob("body.txt"))


def test_legacy_supplied_rectangle_is_never_stamped_as_current_pdf(workspace):
    legacy_id = "plain-legacy"
    with sqlite3.connect(workspace.path) as conn:
        store.upsert_papers(
            conn,
            [
                {
                    "id": legacy_id,
                    "title": "Legacy paper",
                    "venue": "Fixture",
                    "year": 2026,
                    "source": "fixture",
                }
            ],
        )
    (fetch.PDF_DIR / (legacy_id + ".pdf")).write_bytes(pdf("1 Legacy Methods"))
    old = {"caption": "Figure 1: Synthetic research result", "page": 1, "rect": [1, 2, 3, 4]}
    materials._locate_materials(legacy_id, [old])
    assert "rect" not in old and "document_hash" not in old
    assert old["navigation_available"] is False


def test_explicit_legacy_resolver_result_keeps_existing_cache_directory(workspace):
    identity = "plain-reader"
    with sqlite3.connect(workspace.path) as conn:
        store.upsert_papers(
            conn,
            [
                {
                    "id": identity,
                    "title": "Legacy",
                    "venue": "Fixture",
                    "year": 2026,
                    "source": "fixture",
                }
            ],
        )
    alias = fetch.PDF_DIR / (identity + ".pdf")
    alias.write_bytes(pdf("1 Legacy Capture"))
    captured = document_reader.resolve_document(identity)
    assert captured.available and not captured.managed
    extracted = figures.extract(identity, captured.path, document=captured)
    assert extracted and extracted[0].path.parent == figures.FIG_DIR / identity
    assert fetch.extract_text(captured.path, identity, document=captured)



def test_cancellation_during_managed_queue_verification_cannot_report_done(workspace, monkeypatch):
    captured = workspace.install(pdf("1 Cancelled Verification"), "first")
    cancel = threading.Event()

    def resolve(*args, **kwargs):
        cancel.set()
        return captured

    monkeypatch.setattr(fetch, "capture_document", resolve)
    with pytest.raises(pdf_downloads.Cancelled):
        pdf_downloads.download(LOCAL, lambda *args: None, cancel)


def test_managed_source_versions_append_without_replacing_existing_deck_assets():
    from copy import deepcopy

    from paper_daily.desktop.presentation_pane import PresentationPane

    previous = {"id": "figure:1", "asset": "assets/original.png", "document_hash": "a" * 64}
    fake = SimpleNamespace(
        deck=SimpleNamespace(figures=[deepcopy(previous)], sources=[deepcopy(previous)]),
        figure=SimpleNamespace(addItem=lambda *args: None),
        _add_source_item=lambda *args: None,
    )
    payload = dict(id="figure:1", file="figure.png", document_hash="b" * 64, page=2)
    PresentationPane._ensure_evidence(fake, payload)
    PresentationPane._ensure_evidence(fake, payload)
    assert fake.deck.figures[0] == previous and fake.deck.sources[0] == previous
    expected = "figure:1:" + "b" * 64
    assert [row["id"] for row in fake.deck.figures] == ["figure:1", expected]
    assert [row["id"] for row in fake.deck.sources] == ["figure:1", expected]
    assert fake.deck.figures[1]["document_hash"] == "b" * 64
    assert payload["id"] == "figure:1"


def test_managed_source_ids_match_evidence_and_materials_across_replacement(workspace):
    first = workspace.install(pdf("1 Earlier Methods"), "first")
    figures.extract(LOCAL, first.path, document=first)
    initial = materials.figure_entries(LOCAL)
    evidence = presentations.collect_evidence(LOCAL, {"original"})
    assert initial[0]["id"] == evidence["figures"][0]["id"]
    second = workspace.install(pdf("2 Later Methods", second_page=True), "second")
    figures.extract(LOCAL, second.path, document=second)
    later = materials.figure_entries(LOCAL)
    assert initial[0]["id"] != later[0]["id"]
    assert initial[0]["id"].endswith(first.sha256)
    assert later[0]["id"].endswith(second.sha256)


def test_managed_source_rejects_forged_existing_provenance_without_deck_mutation():
    from copy import deepcopy

    from paper_daily.desktop.presentation_pane import PresentationPane

    sid = figures.source_id("figure:1", "b" * 64)
    fake = SimpleNamespace(deck=SimpleNamespace(figures=[], sources=[dict(id=sid)]))
    before = deepcopy(fake.deck.sources)
    with pytest.raises(ValueError, match="unverified"):
        PresentationPane._ensure_evidence(
            fake, dict(id=sid, file="figure.png", document_hash="b" * 64)
        )
    assert fake.deck.sources == before and fake.deck.figures == []
    with pytest.raises(ValueError, match="another document"):
        figures.source_id(sid, "a" * 64)


def test_managed_material_intake_persists_exact_versioned_citations(editor):
    from PySide6.QtCore import QUrl

    widget, deck, _app, _tmp = editor
    payload = dict(kind="table", id="figure:1", rows=[["Method", "Score"], ["A", "1"]])
    for fingerprint in ("a" * 64, "b" * 64, "b" * 64):
        widget._insert_material(dict(payload, document_hash=fingerprint))
    assert widget.save_changes(), widget.status.text()
    saved = presentations.load_deck(deck.paper_id, "guide")
    expected = [figures.source_id("figure:1", value * 64) for value in ("a", "b")]
    assert [row["id"] for row in saved.sources if row["kind"] == "figure"] == expected
    assert set(expected).issubset(saved.slides[0].sources)
    assert len([obj for obj in saved.slides[0].elements if obj["kind"] == "table"]) == 3
    for sid in expected:
        assert QUrl("paperfact-source:" + sid).path() == sid


def test_managed_sentence_intake_preserves_page_version_and_citation_hash(editor):
    widget, deck, _app, _tmp = editor
    for fingerprint in ("a" * 64, "b" * 64):
        widget._insert_material(dict(
            kind="sentence", text="A verified passage", page=2, document_hash=fingerprint
        ))
    assert widget.save_changes(), widget.status.text()
    saved = presentations.load_deck(deck.paper_id, "guide")
    for fingerprint in ("a" * 64, "b" * 64):
        sid = figures.source_id("page:2", fingerprint)
        assert sid in saved.slides[0].sources
        source = next(row for row in saved.sources if row["id"] == sid)
        assert source["document_hash"] == fingerprint and source["page"] == 2
    assert saved.sources[0]["id"] == "original"
