"""Explicit local rescue import: verified bytes, original sources, no activation/AI."""

import copy
import hashlib
import os
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from threading import Event

import pymupdf
import pytest
from test_raw_deck_receipts import codec as _codec
from test_raw_deck_receipts import no_external as _no_external
from test_raw_deck_receipts import original as _original
from test_sync_files import LOCAL, PAPER, paper_payload

from paper_daily import llm, presentations, raw_deck_closure, raw_deck_receipts, sync_capture
from paper_daily import rescue_deck_import as rescue
from paper_daily import research_generation as generation
from paper_daily import sync_deck_publication as publication
from paper_daily.pending_deck_result import PendingDeckResults
from paper_daily.research_lifecycle import parent_lifecycle
from paper_daily.research_review import ResearchReview
from paper_daily.sync_artifacts import stage_bytes
from paper_daily.sync_blobs import BlobStore
from paper_daily.sync_documents import (
    applied_document,
    bind_verified_document,
    desired_document,
    verify_document,
)
from paper_daily.sync_files import file_id
from paper_daily.sync_source_files import publish as publish_source

codec = _codec
no_external = _no_external
original = _original
RECEIVER = "22222222-2222-4222-8222-222222222222"
TARGET = "sync:" + RECEIVER


def native(path):
    value = path.stat()
    return value.st_dev, value.st_ino


def pdf_bytes(text):
    with pymupdf.open() as doc:
        doc.new_page().insert_text((40, 40), text)
        return doc.tobytes()


def attach(client, blobs, portable, data, request):
    sha = hashlib.sha256(data).hexdigest()
    stage_bytes(blobs, {sha: data})
    op = client.new_graph_operation(
        "paper_document",
        portable,
        {"paper_id": portable, "sha256": sha, "size": len(data), "media_type": "application/pdf"},
        operation_id=request,
    )
    client.save(op)
    with client.journal.transaction() as conn:
        wanted = desired_document(conn, portable)
    proof = verify_document(blobs, wanted)
    with client.journal.transaction() as conn:
        assert bind_verified_document(conn, wanted, proof)
    return wanted


@pytest.fixture
def case(original, monkeypatch, tmp_path):
    a, b, fa, sender, images, evidence, _observation = original
    payload = paper_payload()
    payload["title"] = "Explicit chosen receiver, never guessed from the rescue title"
    a.save(a.new_graph_operation("paper", RECEIVER, payload))
    current = copy.deepcopy(sender)
    current.paper_id = TARGET
    current.paper_title = payload["title"]
    current.title = "Previously saved receiver deck"
    presentations.save_deck(current, observation=publication.observe_deck(TARGET, "guide"))
    return dict(
        a=a,
        b=b,
        transfer=fa,
        sender=sender,
        images=images,
        evidence=evidence,
        root=tmp_path,
        before=presentations.load_deck(TARGET, "guide").to_dict(),
    )


def export_file(case, monkeypatch, *, source_hash=None, envelope_only=False, name="rescue.json"):
    value = copy.deepcopy(case["sender"])
    evidence = copy.deepcopy(case["evidence"])
    if source_hash is not None:
        for row in [*value.sources, *value.figures, *evidence["sources"]]:
            row["document_hash"] = source_hash
            row["page"] = 1
    value.version = 1
    value.figures[-1]["caption"] = "Complete unused scientific caption"
    evidence["paper"] = {"id": LOCAL, "title": "Original scientific study", "year": 2026}
    evidence["figures"] = copy.deepcopy(value.figures)
    observed = publication.observe_deck(LOCAL, "guide")

    def fail(*_args, **_kwargs):
        raise OSError("Synthetic sender storage outage")

    with monkeypatch.context() as m:
        m.setattr(BlobStore, "begin", fail)
        m.setattr(raw_deck_receipts, "write_owned", fail)
        result = raw_deck_closure.retain_outcome(
            observed, value, evidence=evidence, request_id="sender:" + name
        )
    assert not result.durable and result._capture is not None
    if envelope_only:
        # Make a valid sender artifact whose source hash is explicit only in the
        # validated envelope, without adding any writer observations to the file.
        import json

        from paper_daily.sync_files import canonical_json

        header, objects = raw_deck_receipts.decode(result._capture)
        for row in [*value.sources, *value.figures, *evidence["sources"], *evidence["figures"]]:
            row.pop("document_hash", None)
        with closing(sqlite3.connect(case["a"].journal.path)) as conn:
            from paper_daily.sync_deck_files import encode_deck
            from paper_daily.sync_source_files import input_versions

            payload, blobs = encode_deck(
                value,
                PAPER,
                input_versions=input_versions(),
                source_document_hash=source_hash,
                evidence=evidence,
            )
            inventory = []
            from paper_daily.sync_files import descriptor

            for key, data in case["images"].items():
                item = {"id": key, **descriptor(data, "image/png")}
                inventory.append(item)
                blobs[item["sha256"]] = data
            raw = {
                "candidate_id": "envelope:" + name,
                "entity_id": observed["entity_id"],
                "deck": canonical_json(value.to_dict()).decode(),
                "observation": canonical_json(observed).decode(),
            }
            closure = {
                "candidate_id": raw["candidate_id"],
                "source_sha256": raw_deck_closure.source_hash(raw),
                "payload": canonical_json(payload).decode(),
                "inventory": canonical_json({"version": 1, "images": inventory}).decode(),
            }
            captured = raw_deck_receipts.capture(conn, raw, closure, evidence, blobs)
        result = publication.DraftRetention(
            raw["candidate_id"],
            "incomplete",
            value,
            evidence,
            "Sender storage unavailable",
            captured,
        )
        assert json.loads(header["raw"]["deck"])["title"] == value.title and objects
    pool = PendingDeckResults()
    key = pool.hold(result)
    path = case["root"] / name
    pool.export(key, path)
    return path


def target(case, request="local-import", paper=TARGET):
    return rescue.capture(
        case["a"].journal.path,
        paper,
        "guide",
        expected_native=native(case["a"].journal.path),
        request_id=request,
    )


def imports(case):
    with closing(sqlite3.connect(case["a"].journal.path)) as conn:
        return conn.execute(
            "SELECT candidate_id FROM research_file_drafts "
            "WHERE candidate_id LIKE 'rescue:%' ORDER BY candidate_id"
        ).fetchall()


def unchanged(case, before_pending, source, before_file):
    assert source.read_bytes() == before_file
    assert case["a"].journal.pending() == before_pending
    assert presentations.load_deck(TARGET, "guide").to_dict() == case["before"]


def test_readonly_preview_needs_no_receiver_or_sql_and_defensive_content(case, monkeypatch):
    source = export_file(case, monkeypatch)

    def denied(*_args, **_kwargs):
        raise AssertionError("File preview must not read SQL or account settings")

    with monkeypatch.context() as m:
        m.setattr(sqlite3, "connect", denied)
        m.setattr(llm, "settings", denied)
        preview = rescue.inspect_file(source)
    assert preview.summary["images"] == 3 and preview.summary["slides"] == 1
    assert preview.preview_data["image_bytes"] == case["images"]
    assert not preview.preview_data["publish"] and not preview.preview_data["sync"]
    mutable = preview.preview_data
    mutable["deck"]["title"] = "Caller mutation"
    assert preview.preview_data["deck"]["title"] == case["sender"].title


def test_explicit_target_retains_complete_proposal_then_separate_review_applies(case, monkeypatch):
    source = export_file(case, monkeypatch)
    preview = rescue.inspect_file(source)
    job = rescue.prepare(target(case), preview)
    before, before_file = case["a"].journal.pending(), source.read_bytes()
    result = rescue.run(job)
    assert result.durable and result.context_current
    assert not result.publish and not result.sync and result.requires_explicit_review
    assert result.retention.deck.paper_id == TARGET
    assert result.retention.deck.deck_id != case["sender"].deck_id
    assert result.retention.deck.version == 1
    assert job.summary["target_title"] != job.summary["source_paper_title"]
    assert job.summary["target_id"] == TARGET
    unchanged(case, before, source, before_file)
    assert imports(case) == [(result.candidate_id,)]
    with closing(sqlite3.connect(case["a"].journal.path)) as conn:
        conn.row_factory = sqlite3.Row
        row = dict(
            conn.execute(
                "SELECT * FROM research_file_drafts WHERE candidate_id=?", (result.candidate_id,)
            ).fetchone()
        )
        header, objects, _files = raw_deck_receipts.read_owned(conn, row)
    import json

    payload = json.loads(header["closure"]["payload"])
    assert payload["paper_id"] == RECEIVER and row["entity_id"] == file_id(
        RECEIVER, "deck", "guide"
    )
    assert payload["input_versions"]["inputs_sha256"] is None
    assert not payload["input_versions"]["complete"]
    assert (
        payload["input_versions"]["documents"] == [] and payload["input_versions"]["entities"] == []
    )
    assert header["evidence"]["paper"]["title"] == "Original scientific study"
    assert all(
        objects[hashlib.sha256(data).hexdigest()] == data for data in case["images"].values()
    )
    assert rescue.run(job).candidate_id == result.candidate_id
    assert rescue.run(rescue.prepare(target(case), preview)).candidate_id == result.candidate_id
    assert imports(case) == [(result.candidate_id,)]
    review = ResearchReview(case["a"].journal.path)
    try:
        prepared = review.prepare_file(review.preview("file_draft", result.candidate_id))
        assert prepared.data["apply"]
        review.decide(prepared, request_id="explicit-rescue-apply", confirm_target=True)
    finally:
        review.close()
    assert presentations.load_deck(TARGET, "guide").title == case["sender"].title
    assert len(case["a"].journal.pending()) == len(before) + 1
    assert source.read_bytes() == before_file


@pytest.mark.parametrize("mode", ["primary-a", "retained-a-current-b", "missing-a", "foreign-a"])
def test_declared_sources_require_exact_receiver_ownership_and_never_substitute_primary(
    case, monkeypatch, mode
):
    data_a, data_b = pdf_bytes("Owned original A"), pdf_bytes("Current primary B")
    hash_a = hashlib.sha256(data_a).hexdigest()
    if mode == "primary-a":
        attach(case["a"], case["transfer"].store, RECEIVER, data_a, "primary-a")
    else:
        attach(case["a"], case["transfer"].store, RECEIVER, data_b, "primary-b")
        if mode in {"retained-a-current-b", "foreign-a"}:
            owner = RECEIVER if mode == "retained-a-current-b" else PAPER
            path = case["root"] / "owned-a.pdf"
            path.write_bytes(data_a)
            with case["a"].journal.transaction() as conn:
                parent = case["a"]._optimistic_graph(conn)[0][("paper", owner)]["incarnation"]
            publish_source(
                case["a"],
                owner,
                path,
                document_hash=hash_a,
                parent_incarnation=parent,
                store=case["transfer"].store,
                version_root=case["transfer"].root,
                request_id="retain-a",
            )
    source = export_file(case, monkeypatch, source_hash=hash_a)
    preview = rescue.inspect_file(source)
    before, before_file = case["a"].journal.pending(), source.read_bytes()
    if mode in {"missing-a", "foreign-a"}:
        with pytest.raises(ValueError, match="unavailable|not owned"):
            rescue.prepare(target(case), preview)
        assert imports(case) == []
    else:
        result = rescue.run(rescue.prepare(target(case), preview))
        assert result.durable
        with closing(sqlite3.connect(case["a"].journal.path)) as conn:
            import json

            payload = json.loads(
                conn.execute(
                    "SELECT payload FROM research_file_draft_closures WHERE candidate_id=?",
                    (result.candidate_id,),
                ).fetchone()[0]
            )
            current = applied_document(conn, RECEIVER)
        assert payload["source_document_hash"] == hash_a
        assert all(row["document_hash"] == hash_a for row in result.retention.deck.figures)
        assert (
            current["sha256"]
            == hashlib.sha256(data_a if mode == "primary-a" else data_b).hexdigest()
        )
    unchanged(case, before, source, before_file)


def test_explicit_envelope_hash_is_preserved_when_source_rows_are_unreported(case, monkeypatch):
    data = pdf_bytes("Original known only by explicit envelope hash")
    source_hash = hashlib.sha256(data).hexdigest()
    attach(case["a"], case["transfer"].store, RECEIVER, data, "envelope-original")
    source = export_file(case, monkeypatch, source_hash=source_hash, envelope_only=True)
    result = rescue.run(rescue.prepare(target(case), rescue.inspect_file(source)))
    assert result.durable
    import json

    with closing(sqlite3.connect(case["a"].journal.path)) as conn:
        payload = json.loads(
            conn.execute(
                "SELECT payload FROM research_file_draft_closures WHERE candidate_id=?",
                (result.candidate_id,),
            ).fetchone()[0]
        )
    assert payload["source_document_hash"] == source_hash
    assert all(row.get("document_hash") is None for row in result.retention.deck.sources)


def test_unknown_source_stays_unknown_despite_current_primary_b(case, monkeypatch):
    attach(
        case["a"], case["transfer"].store, RECEIVER, pdf_bytes("Primary is unrelated B"), "b-only"
    )
    source = export_file(case, monkeypatch)
    result = rescue.run(rescue.prepare(target(case), rescue.inspect_file(source)))
    import json

    with closing(sqlite3.connect(case["a"].journal.path)) as conn:
        payload = json.loads(
            conn.execute(
                "SELECT payload FROM research_file_draft_closures WHERE candidate_id=?",
                (result.candidate_id,),
            ).fetchone()[0]
        )
    assert payload["source_document_hash"] is None
    assert payload["input_versions"]["documents"] == []


@pytest.mark.parametrize("change", ["replace", "truncate", "corrupt"])
def test_preparation_never_silently_reopens_a_newer_displayed_file(case, monkeypatch, change):
    source = export_file(case, monkeypatch)
    preview, captured = rescue.inspect_file(source), target(case)
    if change == "replace":
        other = case["root"] / "replacement.json"
        other.write_bytes(source.read_bytes())
        os.replace(other, source)
    elif change == "truncate":
        source.write_bytes(source.read_bytes()[:80])
    else:
        source.write_bytes(b"corrupt")
    actor_bytes = source.read_bytes()
    with pytest.raises(ValueError):
        rescue.prepare(captured, preview)
    assert imports(case) == [] and source.read_bytes() == actor_bytes


@pytest.mark.parametrize("cancel", [False, True])
def test_file_change_or_cancellation_during_validation_creates_no_proposal(
    case, monkeypatch, cancel
):
    source = export_file(case, monkeypatch)
    actual, alive = rescue.read_export, [True]
    before = source.read_bytes()

    def during(data):
        value = actual(data)
        if cancel:
            alive[0] = False
        else:
            source.write_bytes(before + b"\n")
        return value

    monkeypatch.setattr(rescue, "read_export", during)
    with pytest.raises(ValueError):
        rescue.inspect_file(source, current=lambda: alive[0])
    assert imports(case) == []
    assert source.read_bytes() == (before if cancel else before + b"\n")


def external_parent_repair(case, *, recreate):
    """Controlled unsupported local repair, NOT supported protocol deletion."""
    with (
        closing(generation._connect(case["a"].journal.path)) as conn,
        conn,
        sync_capture.suppress_capture(conn),
    ):
        before = parent_lifecycle(conn, "paper", TARGET)
        parent = dict(conn.execute("SELECT * FROM papers WHERE id=?", (TARGET,)).fetchone())
        conn.execute("DELETE FROM papers WHERE id=?", (TARGET,))
        if recreate:
            columns = list(parent)
            conn.execute(
                "INSERT INTO papers ("
                + ",".join(columns)
                + ") VALUES ("
                + ",".join("?" for _ in columns)
                + ")",
                tuple(parent.values()),
            )
        after = parent_lifecycle(conn, "paper", TARGET)
    assert before and after != before
    return case["a"].journal.pending()


@pytest.mark.parametrize("actor", ["binding", "target-slot", "delete", "delete-restore"])
def test_pre_call_receiver_changes_refuse_without_retention(case, monkeypatch, actor):
    source = export_file(case, monkeypatch)
    job = rescue.prepare(target(case), rescue.inspect_file(source))
    if actor == "binding":
        with closing(sqlite3.connect(case["a"].journal.path)) as conn, conn:
            conn.execute("UPDATE research_sync_binding SET origin='changed-device'")
    elif actor == "target-slot":
        current = presentations.load_deck(TARGET, "guide")
        current.title = "Newer receiver deck"
        presentations.save_deck(current)
    else:
        external_parent_repair(case, recreate=actor == "delete-restore")
    before, before_file = case["a"].journal.pending(), source.read_bytes()
    with pytest.raises(ValueError):
        rescue.run(job)
    assert imports(case) == [] and source.read_bytes() == before_file
    assert case["a"].journal.pending() == before


def test_in_core_parent_recreation_keeps_only_history_and_review_refuses_old_parent(
    case, monkeypatch
):
    source = export_file(case, monkeypatch)
    job = rescue.prepare(target(case), rescue.inspect_file(source))
    real_begin, acted = BlobStore.begin, []

    def actor(self, manifest):
        if not acted:
            acted.append(True)
            actor_baseline.extend(external_parent_repair(case, recreate=True))
        return real_begin(self, manifest)

    actor_baseline = []
    monkeypatch.setattr(BlobStore, "begin", actor)
    result = rescue.run(job)
    assert result.durable and not result.context_current
    assert case["a"].journal.pending() == actor_baseline
    assert presentations.load_deck(TARGET, "guide").to_dict() == case["before"]
    review = ResearchReview(case["a"].journal.path)
    try:
        with pytest.raises(ValueError, match="lifecycle|original"):
            review.prepare_file(review.preview("file_draft", result.candidate_id))
    finally:
        review.close()
    assert source.exists()


@pytest.mark.parametrize("storage", ["primary", "both"])
def test_failed_storage_preserves_actual_import_and_exact_no_model_retry(
    case, monkeypatch, storage
):
    source = export_file(case, monkeypatch)
    job = rescue.prepare(target(case), rescue.inspect_file(source))
    before, before_file = case["a"].journal.pending(), source.read_bytes()

    def fail(*_args, **_kwargs):
        raise OSError("Receiver storage unavailable")

    with monkeypatch.context() as m:
        m.setattr(BlobStore, "begin", fail)
        if storage == "both":
            m.setattr(raw_deck_receipts, "write_owned", fail)
        result = rescue.run(job)
    assert result.retention.deck._revision_figures == case["images"]
    assert result.context_current
    assert result.state == ("receipt" if storage == "primary" else "incomplete")
    again = rescue.run(job)
    assert again.durable and again.candidate_id == result.candidate_id
    assert imports(case) == [(result.candidate_id,)]
    unchanged(case, before, source, before_file)


def test_rapid_repeat_is_single_flight_and_changed_target_request_reuse_refuses(case, monkeypatch):
    source = export_file(case, monkeypatch)
    preview = rescue.inspect_file(source)
    job = rescue.prepare(target(case), preview)
    original_call = raw_deck_closure.retain_outcome
    entered, release = Event(), Event()

    def held(*args, **kwargs):
        entered.set()
        assert release.wait(15)
        return original_call(*args, **kwargs)

    monkeypatch.setattr(raw_deck_closure, "retain_outcome", held)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(rescue.run, job)
        assert entered.wait(15)
        try:
            with pytest.raises(ValueError, match="in progress"):
                rescue.run(job)
        finally:
            release.set()
        result = future.result(timeout=20)
    assert result.durable and imports(case) == [(result.candidate_id,)]
    with pytest.raises(ValueError, match="request ID"):
        rescue.prepare(target(case, paper=LOCAL), preview)


def test_parser_rejects_actual_reparse_parent_and_oversize_file(case, monkeypatch):
    source = export_file(case, monkeypatch)
    link = case["root"] / "reparse-parent"
    if os.name == "nt":
        import _winapi

        _winapi.CreateJunction(str(source.parent), str(link))
    else:
        link.symlink_to(source.parent, target_is_directory=True)
    with pytest.raises(ValueError):
        rescue.inspect_file(link / source.name)
    huge = case["root"] / "too-large.json"
    with huge.open("wb") as stream:
        stream.truncate(raw_deck_receipts.MAX_RECEIPT + 1)
    with pytest.raises(ValueError, match="160 MiB"):
        rescue.inspect_file(huge)
    assert imports(case) == []


def cache_only_original(case, *, paper=TARGET):
    from paper_daily import manual_highlight_ops as highlights
    from paper_daily import reading_position_ops as positions
    from paper_daily import source_snapshots

    path = case["root"] / "loaded-original-a.pdf"
    path.write_bytes(pdf_bytes("Actually observed retained original A"))
    sha = hashlib.sha256(path.read_bytes()).hexdigest()
    from paper_daily import store

    with store.connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        sync_capture.install(conn, workspace_id="workspace", device_id="a")
    owner = highlights.capture_owner(case["a"].journal.path, paper)
    loaded = highlights.load(owner, path, sha)
    intent = positions.prepare(positions.capture(loaded), 1, method="entered")
    row = positions._decode(intent.view.receipt_json)
    cached = source_snapshots.source_path(case["a"].journal.path, row)
    receipt = source_snapshots.receipt_path(case["a"].journal.path, row)
    assert cached.read_bytes() == path.read_bytes() and receipt.is_file()
    return sha, row, cached, receipt


def test_actual_cache_only_original_a_is_usable_while_primary_b_stays_unchanged(case, monkeypatch):
    from paper_daily.sync_artifacts import desired_file

    sha, row, cached, receipt = cache_only_original(case)
    primary = attach(
        case["a"], case["transfer"].store, RECEIVER, pdf_bytes("Primary B"), "primary-b"
    )
    source = export_file(case, monkeypatch, source_hash=sha)
    before = case["a"].journal.pending()
    with closing(sqlite3.connect(case["a"].journal.path)) as conn:
        assert desired_file(conn, file_id(RECEIVER, "original_source", sha)) is None
    receipts_before = receipt.read_bytes()
    job = rescue.prepare(target(case), rescue.inspect_file(source))
    result = rescue.run(job)
    assert result.durable and result.context_current and job.summary["source_status"] == "owned"
    assert cached.read_bytes() == pdf_bytes_expected(case, cached)
    assert receipt.read_bytes() == receipts_before
    assert case["a"].journal.pending() == before
    with case["a"].journal.transaction() as conn:
        assert applied_document(conn, RECEIVER) == primary
    assert presentations.load_deck(TARGET, "guide").to_dict() == case["before"]
    assert row["sha256"] == sha


def pdf_bytes_expected(case, cached):
    return (case["root"] / "loaded-original-a.pdf").read_bytes()


@pytest.mark.parametrize("mutation", ["foreign", "old-parent", "tampered", "unbound"])
def test_cache_only_receipt_never_grants_foreign_old_or_tampered_source(
    case, monkeypatch, mutation
):
    import json

    from paper_daily import source_snapshots

    sha, row, cached, receipt = cache_only_original(
        case, paper=LOCAL if mutation == "foreign" else TARGET
    )
    if mutation == "old-parent":
        external_parent_repair(case, recreate=True)
    elif mutation == "tampered":
        cached.write_bytes(pdf_bytes("Changed original bytes"))
    elif mutation == "unbound":
        owner = json.loads(row["owner_json"])
        owner["binding"] = None
        forged = dict(row, owner_json=json.dumps(owner))
        receipt.unlink()
        new = source_snapshots.receipt_path(case["a"].journal.path, forged)
        new.parent.mkdir(parents=True, exist_ok=True)
        new.write_text(json.dumps(forged))
    source = export_file(case, monkeypatch, source_hash=sha)
    before, original_file = case["a"].journal.pending(), source.read_bytes()
    with pytest.raises(ValueError):
        rescue.prepare(target(case), rescue.inspect_file(source))
    assert imports(case) == [] and source.read_bytes() == original_file
    assert case["a"].journal.pending() == before


@pytest.mark.parametrize("mode", ["empty", "foreign-device"])
def test_present_optional_binding_is_never_ignored(case, mode):
    from paper_daily import store

    with store.connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        sync_capture.install(conn, workspace_id="workspace", device_id="a")
    with closing(sqlite3.connect(case["a"].journal.path)) as conn, conn:
        if mode == "empty":
            conn.execute("DELETE FROM research_capture_binding")
        else:
            conn.execute("UPDATE research_capture_binding SET device='another-device'")
    with pytest.raises(ValueError):
        target(case)
    assert imports(case) == []


def test_original_native_owner_and_cancelled_admission_create_no_proposal(case, monkeypatch):
    path = case["a"].journal.path
    with pytest.raises(ValueError, match="replaced"):
        rescue.capture(
            path,
            TARGET,
            "guide",
            expected_native=native(case["b"].journal.path),
            request_id="wrong-native",
        )
    with pytest.raises(ValueError, match="cancelled"):
        rescue.capture(
            path,
            TARGET,
            "guide",
            expected_native=native(path),
            request_id="cancelled",
            current=lambda: False,
        )
    source = export_file(case, monkeypatch)
    snapshot, preview = target(case), rescue.inspect_file(source)
    with pytest.raises(ValueError, match="cancelled"):
        rescue.prepare(snapshot, preview, current=lambda: False)
    job = rescue.prepare(snapshot, preview)
    with pytest.raises(ValueError, match="cancelled"):
        rescue.run(job, current=lambda: False)
    assert imports(case) == []


def test_selected_original_budget_refuses_before_pdf_verification(case, monkeypatch):
    content = pdf_bytes("Bounded retained A")
    sha = attach(case["a"], case["transfer"].store, RECEIVER, content, "budget-a")["sha256"]
    source = export_file(case, monkeypatch, source_hash=sha)
    monkeypatch.setattr(rescue, "MAX_SOURCE_BYTES", len(content) - 1)

    def no_verify(*_args, **_kwargs):
        raise AssertionError("Overbudget PDF must not be verified")

    monkeypatch.setattr("paper_daily.sync_documents.verify_document", no_verify)
    with pytest.raises(ValueError, match="512 MiB"):
        rescue.prepare(target(case), rescue.inspect_file(source))
    assert imports(case) == []


def test_initial_corrupt_or_truncated_export_refuses_without_sql(case, monkeypatch):
    source = export_file(case, monkeypatch)
    content = source.read_bytes()

    def deny(*_args, **_kwargs):
        raise AssertionError("Invalid file preview must not open a research database")

    monkeypatch.setattr(rescue, "_read", deny)
    for broken in (
        content[:-3],
        b'{"unsupported":true}',
        content.replace(b'"format"', b'"invalid"', 1),
    ):
        assert broken != content
        source.write_bytes(broken)
        with pytest.raises(ValueError):
            rescue.inspect_file(source)
    assert imports(case) == []


def test_cancellation_during_actual_final_source_check_prevents_retention(case, monkeypatch):
    content = pdf_bytes("Actual source checked before cancellation")
    sha = attach(case["a"], case["transfer"].store, RECEIVER, content, "cancel-source")["sha256"]
    source = export_file(case, monkeypatch, source_hash=sha)
    job = rescue.prepare(target(case), rescue.inspect_file(source))
    alive = [True]
    real = rescue._sources

    def checked(*args, **kwargs):
        result = real(*args, **kwargs)
        alive[0] = False
        return result

    monkeypatch.setattr(rescue, "_sources", checked)
    before = case["a"].journal.pending()
    with pytest.raises(ValueError, match="cancelled"):
        rescue.run(job, current=lambda: alive[0])
    assert imports(case) == []
    assert case["a"].journal.pending() == before
    assert presentations.load_deck(TARGET, "guide").to_dict() == case["before"]


def test_seventeen_distinct_declared_sources_refuse_without_partial_retention(case, monkeypatch):
    for index in range(17):
        case["sender"].sources.append(
            dict(
                id="audit:" + str(index),
                label="Declared original",
                kind="paper",
                document_hash=hashlib.sha256(str(index).encode()).hexdigest(),
                page=1,
            )
        )
    source = export_file(case, monkeypatch)
    preview = rescue.inspect_file(source)
    with pytest.raises(ValueError, match="at most 16"):
        rescue.prepare(target(case), preview)
    assert imports(case) == []


@pytest.mark.parametrize("change", ["pdf-bytes", "receipt-deleted"])
def test_prepared_cache_source_change_refuses_before_any_retention(case, monkeypatch, change):
    sha, _row, cached, receipt = cache_only_original(case)
    source = export_file(case, monkeypatch, source_hash=sha)
    job = rescue.prepare(target(case), rescue.inspect_file(source))
    before, original_file = case["a"].journal.pending(), source.read_bytes()
    if change == "pdf-bytes":
        cached.write_bytes(pdf_bytes("Changed A after preparation"))
    else:
        receipt.unlink()
    assert not job.current()
    with pytest.raises((ValueError, OSError)):
        rescue.run(job)
    assert imports(case) == []
    assert case["a"].journal.pending() == before and source.read_bytes() == original_file
    assert presentations.load_deck(TARGET, "guide").to_dict() == case["before"]
