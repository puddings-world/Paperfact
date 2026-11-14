"""Actual saved typed decks and exact per-source ownership; audit is read-only/no model."""

import copy
import hashlib
import json
import sqlite3
from contextlib import closing
from types import SimpleNamespace

import pymupdf
import pytest
from test_sync_files import paper_payload

from paper_daily import audit_appraisal, audit_decks, llm, presentations, store, sync_source_files
from paper_daily.audit_decks import DeckAuditReader
from paper_daily.sync_artifacts import register_paths, stage_bytes
from paper_daily.sync_blobs import BlobStore
from paper_daily.sync_client import SyncClient
from paper_daily.sync_deck_publication import observe_deck, publication_scope
from paper_daily.sync_documents import bind_verified_document, desired_document, verify_document
from paper_daily.sync_files import canonical_json
from paper_daily.sync_journal import Journal
from paper_daily.sync_research import prepare, research_writer

PAPER = "11111111-1111-4111-8111-111111111111"
OTHER = "22222222-2222-4222-8222-222222222222"
LOCAL = "sync:" + PAPER
QUOTE = "The original study included 50 participants under a matched budget."


def pdf(path, text=QUOTE):
    with pymupdf.open() as doc:
        doc.new_page().insert_text((40, 50), text)
        doc.save(path)
    return path.read_bytes()


def primary(value, paper, data, request):
    digest = hashlib.sha256(data).hexdigest()
    stage_bytes(value.blobs, {digest: data})
    operation = value.client.new_graph_operation(
        "paper_document",
        paper,
        dict(paper_id=paper, sha256=digest, size=len(data), media_type="application/pdf"),
        operation_id=request,
    )
    value.client.save(operation)
    with value.client.journal.transaction() as conn:
        target = desired_document(conn, paper)
    verified = verify_document(value.blobs, target)
    with value.client.journal.transaction() as conn:
        assert bind_verified_document(conn, target, verified)
    return target


@pytest.fixture
def saved(tmp_path, monkeypatch):
    database = tmp_path / "research.sqlite"
    with closing(sqlite3.connect(database)) as conn, conn:
        conn.executescript(store.SCHEMA)
    prepare(database, workspace_id="workspace", device_id="device")
    client = SyncClient(
        Journal(database, workspace_id="workspace", device_id="device"), research_writer
    )
    paper = client.new_graph_operation(
        "paper", PAPER, paper_payload(), operation_id="paper-created"
    )
    client.save(paper)
    blobs, versions = BlobStore(tmp_path / "blobs"), tmp_path / "versions"
    with client.journal.transaction() as conn:
        register_paths(conn, "workspace", blobs, versions)
    value = SimpleNamespace(
        path=database, client=client, blobs=blobs, versions=versions, root=tmp_path
    )
    source = tmp_path / "explicit-original.pdf"
    data = pdf(source)
    value.document = primary(value, PAPER, data, "document-A")
    value.source_operation = sync_source_files.publish(
        client,
        PAPER,
        source,
        document_hash=value.document["sha256"],
        parent_incarnation=paper["incarnation"],
        store=blobs,
        version_root=versions,
        request_id="original-A",
    )
    pixmap = pymupdf.Pixmap(pymupdf.csRGB, 24, 24, b"\xff\x00\x00" * 24 * 24, False)
    image = pixmap.tobytes("png")
    monkeypatch.setattr(presentations, "figure_bytes", lambda *_: image)
    monkeypatch.setattr(store, "DB_PATH", database)
    source_rows = [
        dict(
            id="page:1",
            label="Original page",
            kind="original",
            page=1,
            text=QUOTE,
            document_hash=value.document["sha256"],
        ),
        dict(
            id="figure:1",
            label="Figure caption",
            kind="figure",
            page=1,
            text="Caption prose mentions 50 participants.",
            document_hash=value.document["sha256"],
        ),
    ]
    deck = presentations.Deck(
        LOCAL,
        "Saved paper",
        "Saved editable deck",
        "guide",
        "Researchers",
        10,
        [
            presentations.Slide(
                "Comparison",
                "Evidence",
                "Reported 50 participants",
                ["50 participants; 900 mg is an explanatory claim"],
                "Speaker notes stay complete.",
                ["page:1", "figure:1"],
                "figure:1",
                None,
            )
        ],
        source_rows,
        [
            dict(
                id="figure:1",
                label="Figure caption",
                caption="Caption",
                page=1,
                document_hash=value.document["sha256"],
                file="fixture.png",
            )
        ],
        [],
        "2026-10-30T00:00:00Z",
        source_hash="a" * 64,
        generation={"inputs": ["original"]},
    )
    evidence = dict(sources=source_rows, coverage=[], source_hash=deck.source_hash)
    with publication_scope(client):
        observation = observe_deck(LOCAL, "guide")
        presentations.save_deck(deck, observation=observation, evidence=evidence)
    value.deck, value.operation = deck, deck._file_operation
    return value


def reader(saved, **kwargs):
    return DeckAuditReader(saved.path, LOCAL, "guide", saved.operation["operation_id"], **kwargs)


def bytes_snapshot(root):
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob("*") if p.is_file()}


def revise(saved, change):
    payload = copy.deepcopy(saved.operation["payload"])
    body_path = saved.blobs._path(
        __import__("paper_daily.sync_blobs", fromlist=["BlobManifest"]).BlobManifest(
            payload["body"]["sha256"], payload["body"]["size"]
        )
    )
    body = json.loads(body_path.read_bytes())
    change(body, payload)
    from paper_daily.sync_files import descriptor

    data = canonical_json(body)
    payload["body"] = descriptor(data, "application/json")
    stage_bytes(saved.blobs, {payload["body"]["sha256"]: data})
    operation = saved.client.new_graph_operation(
        "research_file", saved.operation["entity_id"], payload
    )
    saved.client.save(operation)
    saved.operation = operation
    return operation


def test_real_saved_editable_deck_reads_exact_closure_original_and_full_text_without_writes(
    saved, monkeypatch
):
    monkeypatch.setattr(llm, "capture_connections", lambda: pytest.fail("Audit captured AI route"))
    monkeypatch.setattr(llm, "complete_result", lambda *a, **k: pytest.fail("Audit called AI"))
    monkeypatch.setattr(
        presentations, "_path", lambda *a: pytest.fail("Audit used global deck lookup")
    )
    monkeypatch.setattr(
        presentations, "figure_bytes", lambda *a: pytest.fail("Audit used mutable figure lookup")
    )
    from paper_daily import sync_artifacts, sync_deck_publication

    monkeypatch.setattr(
        sync_deck_publication,
        "load_managed_deck",
        lambda *a: pytest.fail("Audit loaded/materialized deck"),
    )
    monkeypatch.setattr(
        sync_artifacts, "materialize", lambda *a: pytest.fail("Audit wrote a projection")
    )
    before = bytes_snapshot(saved.root)
    service = reader(
        saved, selected=saved.deck.to_dict(), selected_operation=saved.deck._file_operation
    )
    prepared = service.prepare()
    report = prepared.report
    assert service.current(prepared) and bytes_snapshot(saved.root) == before
    assert report["body_hash"] == saved.operation["payload"]["body"]["sha256"]
    assert report["input_digest"] == "a" * 64 and report["input_digest"] != saved.document["sha256"]
    assert report["coverage_complete"] and report["covered_sources"] == 2
    assert report["semantics"] == "not_checked"
    original = next(row for row in report["sources"] if row["id"] == "page:1")
    assert original["owner"]["paper_id"] == PAPER
    assert original["recorded_document_hash"] == saved.document["sha256"]
    checks = original["report"]["checks"]
    assert any(row["state"] == "located" and row["quote"] == QUOTE for row in checks)
    assert any(
        row["state"] == "not_observed" and row["quantity"]["value"] == "900" for row in checks
    )
    assert "Speaker notes stay complete." in original["report"]["items"][0]["text"]
    assert not any(
        row["rule"] == "quote_location" for row in report["sources"][1]["report"]["checks"]
    )


def test_old_A_is_owned_and_audited_after_current_primary_B_without_rebinding(saved):
    source = saved.root / "explicit-B.pdf"
    primary(
        saved,
        PAPER,
        pdf(source, "Current original B contains unrelated observations."),
        "document-B",
    )
    before = bytes_snapshot(saved.root)
    report = reader(saved).prepare().report
    assert report["coverage_complete"]
    assert all(row["current_primary_matches"] is False for row in report["sources"])
    assert all(
        row["recorded_document_hash"] == saved.document["sha256"] for row in report["sources"]
    )
    assert any(
        check["state"] == "located"
        for row in report["sources"]
        for check in row["report"]["checks"]
    )
    assert bytes_snapshot(saved.root) == before


@pytest.mark.parametrize(
    "change,expected",
    [
        ("unknown", "source_unknown"),
        ("unrecorded", "source_owner_unrecorded"),
        ("missing_intent", "document_scope_unavailable"),
        ("retired", "original_unavailable"),
    ],
)
def test_missing_representable_scope_stays_explicit_without_focal_fallback(saved, change, expected):
    if change in {"unknown", "unrecorded"}:

        def update(body, _payload):
            for row in body["deck"]["sources"]:
                row["document_hash"] = None if change == "unknown" else "b" * 64
            for row in body["deck"]["figures"]:
                row["document_hash"] = None if change == "unknown" else "b" * 64

        revise(saved, update)
    elif change == "missing_intent":
        with closing(sqlite3.connect(saved.path)) as conn, conn:
            conn.execute("DELETE FROM research_document_intents WHERE operation_id='document-A'")
    else:
        operation = saved.client.new_graph_operation(
            "research_file", saved.source_operation["entity_id"], {}, action="delete"
        )
        saved.client.save(operation)
    report = reader(saved).prepare().report
    assert not report["coverage_complete"] and report["covered_sources"] == 0
    assert {row["state"] for row in report["sources"]} == {expected}
    assert not any(
        check["state"] in {"located", "observed"}
        for row in report["sources"]
        for check in row["report"]["checks"]
    )


def test_same_pdf_two_distinct_owners_is_ambiguous_not_focal_or_hash_merge(saved):
    parent = saved.client.new_graph_operation(
        "paper", OTHER, paper_payload(), operation_id="other-created"
    )
    saved.client.save(parent)
    target = primary(
        saved, OTHER, (saved.root / "explicit-original.pdf").read_bytes(), "other-document"
    )
    reference = {
        key: target[key]
        for key in ("paper_id", "operation_id", "incarnation", "parent_incarnation", "sha256")
    }
    revise(saved, lambda _body, payload: payload["input_versions"]["documents"].append(reference))
    report = reader(saved).prepare().report
    assert {row["state"] for row in report["sources"]} == {"source_owner_ambiguous"}
    assert all(row["owner"] is None for row in report["sources"])


@pytest.mark.parametrize("which", ["figure", "body", "source"])
def test_missing_declared_bytes_never_read_global_or_current_substitute(saved, which):
    payload = saved.operation["payload"]
    digest = (
        next(row["sha256"] for row in payload["assets"] if row["role"] == "figure")
        if which == "figure"
        else payload["body"]["sha256"]
        if which == "body"
        else saved.document["sha256"]
    )
    (saved.blobs.root / "objects" / digest).unlink()
    if which == "source":
        report = reader(saved).prepare().report
        assert {row["state"] for row in report["sources"]} == {"original_unavailable"}
    else:
        with pytest.raises(ValueError, match="invalid_saved_deck"):
            reader(saved).prepare()


def test_corrupt_original_fails_instead_of_relabelling_current_source(saved):
    path = saved.blobs.root / "objects" / saved.document["sha256"]
    path.write_bytes(b"x" * path.stat().st_size)
    with pytest.raises(ValueError, match="invalid_saved_deck"):
        reader(saved).prepare()


def test_current_guards_only_metadata_and_reject_changes_after_preparation(saved, monkeypatch):
    service = reader(saved)
    proof = service.prepare()
    monkeypatch.setattr(
        sqlite3, "connect", lambda *a, **k: pytest.fail("Native current opened SQL")
    )
    monkeypatch.setattr(
        hashlib, "sha256", lambda *a, **k: pytest.fail("Native current hashed data")
    )
    assert service.current(proof)
    path = saved.blobs.root / "objects" / saved.document["sha256"]
    path.write_bytes(b"x" * path.stat().st_size)
    assert not service.current(proof)


def test_new_deck_proof_cannot_expand_paid_appraisal_scope(saved, monkeypatch):
    proof = reader(saved).prepare()
    monkeypatch.setattr(llm, "capture_connections", lambda: pytest.fail("Deck captured paid route"))
    with pytest.raises(ValueError, match="saved_content_changed"):
        audit_appraisal.AppraisalJob.prepare(proof, ["slide:1"])


@pytest.mark.parametrize("field", ["incarnation", "parent_incarnation", "sha256"])
def test_recorded_document_reference_must_match_its_real_retained_target(saved, field):
    def change(_body, payload):
        payload["input_versions"]["documents"][0][field] = (
            "f" * 64 if field == "sha256" else "wrong-recorded-epoch"
        )
        if field == "sha256":
            # Keep source hashes matching the deliberately contradictory reference.
            for source in _body["deck"]["sources"]:
                source["document_hash"] = "f" * 64
            for figure in _body["deck"]["figures"]:
                figure["document_hash"] = "f" * 64

    revise(saved, change)
    with pytest.raises(ValueError, match="invalid_source_scope"):
        reader(saved).prepare()


def test_related_original_has_its_own_owner_and_parent_replacement_is_not_history(saved):
    parent = saved.client.new_graph_operation(
        "paper", OTHER, paper_payload(), operation_id="other-created"
    )
    saved.client.save(parent)
    path = saved.root / "related.pdf"
    text = "The related original recorded 75 participants under different conditions."
    target = primary(saved, OTHER, pdf(path, text), "related-document")
    sync_source_files.publish(
        saved.client,
        OTHER,
        path,
        document_hash=target["sha256"],
        parent_incarnation=parent["incarnation"],
        store=saved.blobs,
        version_root=saved.versions,
        request_id="related-original",
    )

    def change(body, payload):
        payload["input_versions"]["documents"] = [
            {
                key: target[key]
                for key in (
                    "paper_id",
                    "operation_id",
                    "incarnation",
                    "parent_incarnation",
                    "sha256",
                )
            }
        ]
        for source in body["deck"]["sources"]:
            source["document_hash"] = target["sha256"]
            if source["kind"] == "original":
                source["text"] = text
        for figure in body["deck"]["figures"]:
            figure["document_hash"] = target["sha256"]

    revise(saved, change)
    report = reader(saved).prepare().report
    assert report["coverage_complete"] and all(
        row["owner"]["paper_id"] == OTHER for row in report["sources"]
    )
    with closing(sqlite3.connect(saved.path)) as conn, conn:
        conn.execute(
            "UPDATE research_paper_projection SET incarnation='replacement' WHERE sync_id=?",
            (OTHER,),
        )
    blocked = reader(saved).prepare().report
    assert not blocked["coverage_complete"]
    assert {row["state"] for row in blocked["sources"]} == {"source_parent_replaced"}
    assert all(row["owner"] is None for row in blocked["sources"])


def test_exact_retained_deck_revision_is_not_replaced_by_newer_saved_content(saved):
    original = saved.operation
    revise(saved, lambda body, _payload: body["deck"].update(title="New saved revision"))
    selected = DeckAuditReader(saved.path, LOCAL, "guide", original["operation_id"])
    report = selected.prepare().report
    assert (
        report["title"] == "Saved editable deck"
        and report["operation_id"] == original["operation_id"]
    )
    retired = saved.client.new_graph_operation(
        "research_file", original["entity_id"], {}, action="delete"
    )
    saved.client.save(retired)
    with pytest.raises(ValueError, match="saved_deck_unavailable"):
        DeckAuditReader(saved.path, LOCAL, "guide", original["operation_id"]).prepare()
    restored = saved.client.new_graph_operation(
        "research_file", original["entity_id"], original["payload"], restore=True
    )
    saved.client.save(restored)
    with pytest.raises(ValueError, match="saved_deck_unavailable"):
        DeckAuditReader(saved.path, LOCAL, "guide", original["operation_id"]).prepare()


@pytest.mark.parametrize(
    "budget",
    [
        "MAX_BODY",
        "MAX_ASSETS",
        "MAX_SOURCE_IDS",
        "MAX_ORIGINALS",
        "MAX_PDF_BYTES",
        "MAX_PAGES",
        "MAX_WORDS",
    ],
)
def test_bounded_full_check_fails_without_truncation_or_writes(saved, monkeypatch, budget):
    monkeypatch.setattr(audit_decks, budget, 0)
    before = bytes_snapshot(saved.root)
    with pytest.raises(ValueError, match="input_limit"):
        reader(saved).prepare()
    assert bytes_snapshot(saved.root) == before


def test_declared_oversized_body_refuses_before_a_byte_read(saved, monkeypatch):
    payload = copy.deepcopy(saved.operation["payload"])
    payload["body"]["size"] = audit_decks.MAX_BODY + 1
    operation = saved.client.new_graph_operation(
        "research_file", saved.operation["entity_id"], payload
    )
    saved.client.save(operation)
    saved.operation = operation
    monkeypatch.setattr(
        audit_decks, "verify_closure", lambda *a: pytest.fail("Oversized body read")
    )
    with pytest.raises(ValueError, match="input_limit"):
        reader(saved).prepare()


@pytest.mark.parametrize("change", ["unknown_field", "duplicate_source", "contradictory_figure"])
def test_malformed_saved_closure_never_returns_partial_audit(saved, change):
    def update(body, _payload):
        if change == "unknown_field":
            body["deck"]["slides"][0]["untrusted"] = "not a slide field"
        elif change == "duplicate_source":
            body["deck"]["sources"].append(body["deck"]["sources"][0])
        else:
            body["deck"]["figures"][0]["document_hash"] = "f" * 64

    revise(saved, update)
    before = bytes_snapshot(saved.root)
    with pytest.raises(ValueError, match="invalid_saved_deck"):
        reader(saved).prepare()
    assert bytes_snapshot(saved.root) == before


def test_selected_unsaved_narrative_is_not_treated_as_the_saved_version(saved):
    selected = saved.deck.to_dict()
    selected["slides"][0]["speaker_notes"] = "Keep this unsaved edit"
    with pytest.raises(ValueError, match="selected_deck_changed"):
        reader(saved, selected=selected, selected_operation=saved.deck._file_operation).prepare()


@pytest.mark.parametrize("change", ["binding", "replace", "path"])
def test_delayed_initial_scope_change_never_follows_new_workspace(saved, change):
    selected = [saved.path]
    service = reader(saved, current_path=lambda: selected[0])
    if change == "binding":
        with closing(sqlite3.connect(saved.path)) as conn, conn:
            conn.execute("UPDATE research_sync_binding SET origin='different-device'")
    elif change == "replace":
        replacement = saved.path.with_name("replacement.sqlite")
        replacement.write_bytes(saved.path.read_bytes())
        replacement.replace(saved.path)
    else:
        other = saved.path.with_name("other.sqlite")
        other.write_bytes(saved.path.read_bytes())
        selected[0] = other
    with pytest.raises(ValueError, match="saved_content_changed"):
        service.prepare()


def test_cancelled_or_changed_source_cannot_publish_a_late_report(saved, monkeypatch):
    from paper_daily.workspace_service import Cancelled, Ticket

    ticket = Ticket()
    ticket.cancel()
    with pytest.raises(Cancelled):
        reader(saved).prepare(ticket)
    original = audit_decks.research_audit._run_checked_pages

    def changed(*args, **kwargs):
        result = original(*args, **kwargs)
        path = saved.blobs.root / "objects" / saved.document["sha256"]
        path.write_bytes(b"x" * path.stat().st_size)
        return result

    monkeypatch.setattr(audit_decks.research_audit, "_run_checked_pages", changed)
    with pytest.raises(ValueError, match="saved_content_changed"):
        reader(saved).prepare()


@pytest.mark.parametrize("change", ["retained_column", "retained_operation", "desired_workspace"])
def test_selected_retained_header_and_workspace_must_match_actual_operation(saved, change):
    with closing(sqlite3.connect(saved.path)) as conn, conn:
        if change == "retained_column":
            conn.execute(
                "UPDATE research_file_versions SET entity_id=? WHERE operation_id=?",
                (OTHER, saved.operation["operation_id"]),
            )
        else:
            op = copy.deepcopy(saved.operation)
            if change == "retained_operation":
                op["operation_id"] = "another-operation"
                conn.execute(
                    "UPDATE research_file_versions SET operation=? WHERE operation_id=?",
                    (canonical_json(op).decode(), saved.operation["operation_id"]),
                )
            else:
                op["workspace_id"] = "another-workspace"
                conn.execute(
                    "UPDATE research_file_desired SET operation=? WHERE entity_id=?",
                    (canonical_json(op).decode(), saved.operation["entity_id"]),
                )
    before = bytes_snapshot(saved.root)
    with pytest.raises(ValueError, match="invalid_saved_deck|saved_deck_unavailable"):
        reader(saved).prepare()
    assert bytes_snapshot(saved.root) == before


def test_full_saved_figure_caption_and_coverage_are_retained_as_prose_not_a_quote(saved):
    caption = "Full saved caption mentions 80% and requires human interpretation. " * 30

    def change(body, _payload):
        body["deck"]["figures"][0]["caption"] = caption
        body["deck"]["coverage"] = ["Generation used bounded captured excerpts."]

    revise(saved, change)
    report = reader(saved).prepare().report
    source = next(row for row in report["sources"] if row["id"] == "figure:1")
    item = next(row for row in source["report"]["items"] if row["id"].startswith("figure:"))
    assert item["text"] == caption and item["passages"] == []
    assert report["coverage_notes"] == ["Generation used bounded captured excerpts."]
    assert report["semantics"] == "not_checked"


def test_active_flag_cannot_turn_a_deleted_desired_header_into_a_live_saved_deck(saved):
    operation = copy.deepcopy(saved.operation)
    operation.update(action="delete", payload={})
    with closing(sqlite3.connect(saved.path)) as conn, conn:
        conn.execute(
            "UPDATE research_file_desired SET operation=? WHERE entity_id=?",
            (canonical_json(operation).decode(), operation["entity_id"]),
        )
    with pytest.raises(ValueError, match="invalid_saved_deck"):
        reader(saved).prepare()


def test_aggregate_output_input_budget_applies_across_cited_sources(saved, monkeypatch):
    from paper_daily import research_audit

    # Each source's input remains individually valid; the combined source-item corpus does not.
    service = reader(saved)
    proof = service.prepare()
    items = [row["report"]["items"] for row in proof.report["sources"]]
    sizes = [
        len(json.dumps(value, ensure_ascii=False, allow_nan=False).encode()) for value in items
    ]
    limit = max(sizes) + 1
    assert sum(len(canonical_json(value)) for value in items) > limit
    monkeypatch.setattr(research_audit, "MAX_BYTES", limit)
    for value in items:
        assert research_audit.validate(value) == value
    with pytest.raises(ValueError, match="input_limit"):
        reader(saved).prepare()


@pytest.mark.parametrize("origin", ["legacy", "workspace", "different-workspace"])
def test_recorded_input_workspace_cannot_authorize_coincident_current_references(saved, origin):
    def update(_body, payload):
        versions = payload["input_versions"]
        versions.pop("workspace_id", None)
        versions["schema_version"] = 1 if origin == "legacy" else 2
        if origin != "legacy":
            versions["workspace_id"] = origin

    revise(saved, update)
    before = bytes_snapshot(saved.root)
    report = reader(saved).prepare().report
    assert bytes_snapshot(saved.root) == before
    if origin in {"legacy", "workspace"}:
        assert report["coverage_complete"] and report["covered_sources"] == 2
    else:
        assert not report["coverage_complete"] and report["covered_sources"] == 0
        assert {row["state"] for row in report["sources"]} == {"source_owner_unrecorded"}
        assert not any(check["state"] in {"located", "observed"}
                       for row in report["sources"] for check in row["report"]["checks"])
