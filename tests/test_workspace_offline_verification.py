"""Resumable verification uses actual fixtures and sealed in-process proofs."""

import pytest
from test_sync_files import codec as codec_fixture
from test_sync_transfers import attach
from test_sync_transfers import setup as transfer_setup_fixture
from test_workspace_offline import add_deck
from test_workspace_offline import prepared as prepared_fixture

from paper_daily import workspace_offline as offline
from paper_daily.sync_blobs import BlobManifest
from paper_daily.workspace_offline_verification import MAX_PASS_BYTES, OfflineVerification
from paper_daily.workspace_service import Cancelled, SnapshotChanged, Ticket, WorkspaceChanged

codec = codec_fixture
transfer_setup = transfer_setup_fixture
prepared = prepared_fixture


def test_native_proofs_resume_pdf_then_deck_without_rehashing_current_pdf(
    prepared, codec, monkeypatch
):
    service, _client, local, *_ = prepared
    add_deck(prepared, codec)
    plan = service.plan([local])
    pdf_bytes = plan["papers"][0]["pdf"]["target"]["size"]
    budget = plan["required_bytes"] - pdf_bytes
    assert budget > pdf_bytes
    calls = []
    original = offline.verify_document

    def counted(*args):
        calls.append(1)
        return original(*args)

    monkeypatch.setattr(offline, "verify_document", counted)
    session = OfflineVerification(service, [local])
    first = session.advance(max_bytes=budget)
    assert first["partial"] and not first["ready"]
    assert first["papers"][0]["pdf"]["state"] == "verified"
    assert first["verified_assets"] == 1
    second = session.advance(max_bytes=budget)
    assert second["ready"] and second["verification_pass"] == 2
    assert second["verified_bytes"] == plan["required_bytes"]
    assert second["reused_assets"] == 1 and second["verified_assets"] == 4
    third = session.advance(max_bytes=budget)
    assert third["ready"] and third["verification_bytes"] == 0 and calls == [1]
    assert not third["whole_workspace_offline_verified"]


def test_an_item_larger_than_one_pass_requires_explicit_larger_budget(prepared):
    service, _client, local, *_ = prepared
    session = OfflineVerification(service, [local])
    first = session.advance(max_bytes=1)
    assert first["partial"] and not first["ready"]
    assert first["verification_bytes"] == 0
    assert session.advance()["ready"]


def test_new_pass_limit_can_verify_beyond_the_old_stateless_budget(prepared, monkeypatch):
    service, _client, local, *_ = prepared
    # Lower only the old API's policy bound; native PDF/file verification stays real.
    monkeypatch.setattr(offline, "MAX_BYTES", 1)
    assert OfflineVerification(service, [local]).advance()["ready"]


def test_cached_proof_is_invalidated_by_actual_corruption_and_retry_repairs(prepared, monkeypatch):
    service, _client, local, _portable, blob_store, manifest, data = prepared
    session = OfflineVerification(service, [local])
    assert session.advance()["ready"]
    target = blob_store.verified_path(manifest)
    target.write_bytes(data[:-1] + bytes([data[-1] ^ 1]))
    damaged = session.advance()
    assert not damaged["ready"] and damaged["papers"][0]["pdf"]["state"] == "unavailable"
    assert damaged["verified_bytes"] == 0
    target.write_bytes(data)
    assert session.advance()["ready"]


def test_corruption_after_reused_proof_but_before_return_prevents_ready(prepared):
    service, _client, local, _portable, blob_store, manifest, data = prepared
    session = OfflineVerification(service, [local])
    assert session.advance()["ready"]
    target = blob_store.verified_path(manifest)

    def corrupt(_event):
        target.write_bytes(data[:-1] + bytes([data[-1] ^ 1]))

    result = session.advance(progress=corrupt)
    assert not result["ready"] and result["papers"][0]["pdf"]["state"] == "invalid"


def test_missing_cached_deck_asset_cannot_reuse_a_ready_flag(prepared, codec):
    service, _client, local, _portable, blob_store, *_ = prepared
    operation = add_deck(prepared, codec)
    session = OfflineVerification(service, [local])
    assert session.advance()["ready"]
    asset = operation["payload"]["assets"][0]
    path = blob_store.verified_path(BlobManifest(asset["sha256"], asset["size"]))
    value = path.read_bytes()
    path.unlink()
    assert not session.advance()["ready"]
    path.write_bytes(value)
    assert session.advance()["ready"]


@pytest.mark.parametrize("when", ["before", "during", "between"])
def test_source_replacement_requires_a_new_selection_not_a_stale_ready_report(
    prepared,
    transfer_setup,
    tmp_path,
    monkeypatch,
    when,
):
    service, _client, local, *_ = prepared
    session = OfflineVerification(service, [local])
    if when == "between":
        assert session.advance()["ready"]
    if when == "during":
        original = offline.verify_document

        def replace(*args):
            proof = original(*args)
            attach(transfer_setup, tmp_path, request_id="changed-source", text="Different source")
            return proof

        monkeypatch.setattr(offline, "verify_document", replace)
    else:
        attach(transfer_setup, tmp_path, request_id="changed-source", text="Different source")
    with pytest.raises(SnapshotChanged):
        session.advance()


@pytest.mark.parametrize("when", ["before", "during"])
def test_cancel_never_returns_ready_and_explicit_new_ticket_can_resume(prepared, when):
    service, _client, local, *_ = prepared
    session = OfflineVerification(service, [local])
    ticket = Ticket()
    if when == "before":
        ticket.cancel()

    def stop(_event):
        ticket.cancel()

    with pytest.raises(Cancelled):
        session.advance(ticket=ticket, progress=stop if when == "during" else lambda _event: None)
    assert session.advance()["ready"]


def test_switching_workspace_during_verification_discards_result(prepared, tmp_path):
    _service, client, local, *_ = prepared
    active = [client.journal.path]
    service = offline.OfflineService(client.journal.path, current_path=lambda: active[0])
    session = OfflineVerification(service, [local])

    def switch(_event):
        active[0] = tmp_path / "other.db"

    with pytest.raises(WorkspaceChanged):
        session.advance(progress=switch)


def test_rapid_repeated_activation_cannot_create_concurrent_verification(prepared):
    service, _client, local, *_ = prepared
    session = OfflineVerification(service, [local])
    nested = []

    def repeat(_event):
        with pytest.raises(RuntimeError, match="already running"):
            session.advance()
        nested.append(1)

    assert session.advance(progress=repeat)["ready"]
    assert nested == [1]


def test_reports_and_callers_cannot_mutate_selection_or_proof_authority(prepared):
    service, _client, local, *_ = prepared
    selection = [local]
    session = OfflineVerification(service, selection)
    selection.append("not selected")
    first = session.advance()
    first["papers"][0]["pdf"]["target"]["sha256"] = "0" * 64
    first["papers"][0]["ready"] = False
    second = session.advance()
    assert second["ready"] and len(second["papers"]) == 1
    assert second["papers"][0]["pdf"]["target"]["sha256"] != "0" * 64


def test_new_instance_must_reverify_instead_of_trusting_previous_report(prepared, monkeypatch):
    service, _client, local, *_ = prepared
    assert OfflineVerification(service, [local]).advance()["ready"]
    calls = []
    original = offline.verify_document

    def counted(*args):
        calls.append(1)
        return original(*args)

    monkeypatch.setattr(offline, "verify_document", counted)
    assert OfflineVerification(service, [local]).advance()["ready"]
    assert calls == [1]


@pytest.mark.parametrize("source", ["unknown", "mismatch"])
def test_reusing_verified_assets_never_upgrades_unknown_document_provenance(
    prepared, codec, source
):
    service, _client, local, *_ = prepared
    add_deck(prepared, codec, source=source)
    session = OfflineVerification(service, [local])
    assert not session.advance()["ready"]
    again = session.advance()
    assert not again["ready"] and again["reused_assets"] > 0


@pytest.mark.parametrize(
    "kwargs",
    [
        {"max_bytes": 0},
        {"max_bytes": True},
        {"max_bytes": MAX_PASS_BYTES + 1},
        {"max_assets": 0},
        {"seconds": 0},
        {"seconds": float("nan")},
        {"seconds": True},
    ],
)
def test_invalid_budget_cannot_produce_a_report(prepared, kwargs):
    service, _client, local, *_ = prepared
    session = OfflineVerification(service, [local])
    with pytest.raises(ValueError):
        session.advance(**kwargs)
    assert session.advance()["ready"]
