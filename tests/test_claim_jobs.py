"""Captured source/account claims publish once, preserving completed stale work."""

import copy
import json
import sqlite3
from contextlib import closing
from dataclasses import replace

import pytest
from test_highlight_generation import QUOTES
from test_highlight_generation import ready as _ready
from test_highlight_generation import workspace as _workspace
from test_research_generation import rows

from paper_daily import (
    annotation_reader,
    claim_content,
    claim_jobs,
    llm,
    research_evidence,
    store,
    sync_capture,
)
from paper_daily import research_generation as generation
from paper_daily.ai_types import Completion, Settings
from paper_daily.claim_jobs import ClaimJob

workspace = _workspace
ready = _ready


@pytest.fixture
def claims(ready, monkeypatch):
    with closing(generation._connect(ready[0])) as conn, conn, sync_capture.suppress_capture(conn):
        conn.execute(
            "INSERT INTO dives(paper_id,body,spec,written_at) VALUES "
            "('paper','Original deep explanation','fixture','2026-01-01T00:00:00+00:00')"
        )
        conn.execute(
            "INSERT INTO close_readings(paper_id,body,spec,written_at) VALUES "
            "('paper','Original close reading','fixture','2026-01-01T00:00:00+00:00')"
        )
    calls = []
    output = {
        "claims": [
            {
                "text": "Independent observations isolate the comparison.",
                "judgment": {"status": "unresolved", "reason": "Check study assumptions."},
                "passages": [{"quote": QUOTES[0], "page": 1, "anchor": None}],
            }
        ]
    }
    monkeypatch.setattr(llm, "settings", lambda **kw: Settings("fixture", model="requested"))

    def complete(prompt, **kwargs):
        calls.append((json.loads(prompt), kwargs))
        return Completion(json.dumps(output), model="returned")

    monkeypatch.setattr(llm, "complete_result", complete)
    return ready, output, calls


def job(claims):
    ready = claims[0]
    return ClaimJob.capture(ready[0], "paper", legacy_root=ready[2].path.parent)


def saved(claims):
    return annotation_reader.saved(claims[0][0], "paper", "claims")


def test_actual_one_call_publication_cached_reuse_and_retry_preserve_source_and_account(claims):
    current = job(claims)
    claims[0][3].update(account="changed", model="changed")
    outcome = current.run()
    assert outcome.status == "accepted" and current.run() == outcome
    assert len(claims[2]) == 1
    assert claims[0][4] == [{"account": "original", "model": "original-model"}]
    body = saved(claims)
    assert body["report"]["verification_scope"] == "original_snapshot"
    assert body["report"]["source"]["document_hash"] == claims[0][2].sha256
    assert body["generation"] == {
        "task": "claims",
        "backend": "fixture",
        "requested_model": "requested",
        "returned_model": "returned",
    }
    assert body["report"]["claims"][0]["semantic_validation"] == "not_performed"
    assert body["report"]["claims"][0]["passages"][0]["location"]["state"] == "located"
    cached, reason = claim_jobs.ensure(claims[0][0], "paper", legacy_root=claims[0][2].path.parent)
    assert cached == body and reason == "cached" and len(claims[2]) == 1
    assert generation.retry_publication(current.context) == outcome
    if claims[0][1]:
        operations = [
            op
            for op in claims[0][1].journal.pending()
            if op.get("payload", {}).get("feature") == "claims"
        ]
        assert len(operations) == 1
        assert operations[0]["payload"]["data"]["body_json"]["report"] == body["report"]


def test_unlocatable_and_ambiguous_quotes_remain_honest_without_semantic_badge(claims):
    claims[1]["claims"][0]["passages"][0]["quote"] = "Unreported statistical superiority."
    claims[1]["claims"][0]["judgment"]["status"] = "supported"
    assert job(claims).run().status == "accepted"
    claim = saved(claims)["report"]["claims"][0]
    assert claim["judgment"]["authority"] == "caller"
    assert claim["semantic_validation"] == "not_performed"
    assert claim["passages"][0]["location"]["state"] == "missing"
    assert claim["passages"][0]["location"]["anchor"] is None


@pytest.mark.parametrize("mutation", ["pdf", "inputs", "target", "parent"])
def test_changed_inputs_source_target_or_parent_retain_complete_original_work(
    claims, monkeypatch, mutation
):
    current = job(claims)
    complete = llm.complete_result

    def changed(*args, **kwargs):
        result = complete(*args, **kwargs)
        if mutation == "pdf":
            claims[0][2].path.write_bytes(b"different source after AI")
        else:
            with (
                closing(generation._connect(claims[0][0])) as conn,
                conn,
                sync_capture.suppress_capture(conn),
            ):
                if mutation == "inputs":
                    conn.execute("UPDATE dives SET body='Later user edit' WHERE paper_id='paper'")
                elif mutation == "target":
                    conn.execute("INSERT INTO paper_annotation_known VALUES('claims','paper')")
                else:
                    conn.execute("DELETE FROM papers WHERE id='paper'")
                    store.upsert_papers(
                        conn,
                        [
                            dict(
                                id="paper",
                                title="Recreated",
                                venue="Fixture",
                                year=2026,
                                source="fixture",
                            )
                        ],
                    )
        return result

    monkeypatch.setattr(llm, "complete_result", changed)
    result = current.run()
    assert result.status == "candidate" and len(claims[2]) == 1
    assert rows(claims[0][0], "SELECT * FROM paper_claim_sets") == []
    assert current.result is not None
    retained = json.loads(current.result["body_json"])
    assert retained["report"]["claims"][0]["passages"][0]["location"]["state"] == "located"
    assert current.run() == result and len(claims[2]) == 1


def test_duplicate_activation_failure_and_known_deletion_do_not_spend_extra_ai(claims, monkeypatch):
    first, second = job(claims), job(claims)
    complete = llm.complete_result

    def nested(*args, **kwargs):
        with pytest.raises(ValueError, match="already running"):
            second.run()
        return complete(*args, **kwargs)

    monkeypatch.setattr(llm, "complete_result", nested)
    assert first.run().status == "accepted"
    with closing(generation._connect(claims[0][0])) as conn:
        token = sync_capture.observe_target(conn, "paper", "paper", "claims", "main")
        with sync_capture.expecting(conn, [token]):
            conn.execute("DELETE FROM paper_claim_sets")
            conn.commit()
    result, reason = claim_jobs.ensure(claims[0][0], "paper", legacy_root=claims[0][2].path.parent)
    assert result == {"claims": [], "known": True} and "deleted" in reason
    assert len(claims[2]) == 1


@pytest.mark.parametrize("invalid", ["duplicate", "id", "malformed", "unavailable"])
def test_invalid_or_failed_completion_preserves_existing_claims(claims, monkeypatch, invalid):
    assert job(claims).run().status == "accepted"
    before = rows(claims[0][0], "SELECT * FROM paper_claim_sets")
    if invalid == "duplicate":
        claims[1]["claims"] *= 2
    elif invalid == "id":
        claims[1]["claims"][0]["id"] = "invented"
    elif invalid == "malformed":
        monkeypatch.setattr(llm, "complete_result", lambda *a, **kw: Completion("broken JSON"))
    else:
        monkeypatch.setattr(
            llm, "complete_result", lambda *a, **kw: Completion(None, "Unavailable")
        )
    with pytest.raises(ValueError):
        job(claims).run()
    assert rows(claims[0][0], "SELECT * FROM paper_claim_sets") == before


def test_cancel_before_ai_and_after_completion_preserves_completed_work(claims):
    current = job(claims)
    with pytest.raises(ValueError, match="cancelled"):
        current.run(cancelled=lambda: True)
    assert claims[2] == []
    completed = job(claims)
    outcome = completed.run(cancelled=lambda: bool(claims[2]))
    assert outcome.status == "candidate" and "cancelled" in outcome.reason
    assert rows(claims[0][0], "SELECT * FROM paper_claim_sets") == []
    assert generation.list_recovery_requests(claims[0][0])
    assert completed.run() == outcome and len(claims[2]) == 1


def test_storage_abort_rolls_back_claim_outbox_and_receipt_but_retains_result(claims):
    with closing(sqlite3.connect(claims[0][0])) as conn, conn:
        conn.execute(
            "CREATE TRIGGER broken_claim BEFORE INSERT ON paper_claim_sets "
            "BEGIN SELECT RAISE(ABORT,'fixture failure'); END"
        )
    current = job(claims)
    assert current.run().status == "candidate"
    assert rows(claims[0][0], "SELECT * FROM paper_claim_sets") == []
    assert rows(claims[0][0], "SELECT * FROM paper_annotation_known WHERE feature='claims'") == []
    assert generation.list_recovery_requests(claims[0][0])
    if claims[0][1]:
        assert not [
            op
            for op in claims[0][1].journal.pending()
            if op.get("payload", {}).get("feature") == "claims"
        ]


def test_snapshot_authority_cannot_be_deserialized_or_modified(claims):
    current = job(claims)
    proposals = {"format": research_evidence.FORMAT, "source": current.snapshot.source, **claims[1]}
    for fake in (
        {"source": current.snapshot.source},
        replace(current.snapshot, _bytes=b"forged source"),
        replace(current.snapshot, _source_json="malformed"),
        replace(current.snapshot, _seal="f" * 64),
    ):
        with pytest.raises(research_evidence.EvidenceError, match="invalid_snapshot"):
            research_evidence.verify_snapshot(fake, proposals)
    assert (
        research_evidence.verify_snapshot(current.snapshot, proposals)["verification_scope"]
        == "original_snapshot"
    )


def test_shared_claim_schema_rejects_semantic_and_identity_changes(claims):
    assert job(claims).run().status == "accepted"
    body = json.loads(rows(claims[0][0], "SELECT body_json FROM paper_claim_sets")[0]["body_json"])
    claim_content.validate(body)
    for field, value in [("semantic_validation", "verified"), ("id", "f" * 64)]:
        changed = copy.deepcopy(body)
        changed["report"]["claims"][0][field] = value
        with pytest.raises(ValueError):
            claim_content.validate(changed)


def test_global_workspace_switch_during_completion_never_redirects_claim_publication(
    claims, monkeypatch, tmp_path
):
    original = claims[0][0]
    other = tmp_path / "other.sqlite"
    with sqlite3.connect(other) as conn:
        conn.executescript(store.SCHEMA)
    complete = llm.complete_result
    current = job(claims)

    def switched(*args, **kwargs):
        output = complete(*args, **kwargs)
        monkeypatch.setattr(store, "DB_PATH", other)
        return output

    monkeypatch.setattr(llm, "complete_result", switched)
    assert current.run().status == "accepted"
    assert len(rows(original, "SELECT * FROM paper_claim_sets")) == 1
    assert rows(other, "SELECT * FROM paper_claim_sets") == []


def test_replaced_database_receives_no_candidate_or_business_write(claims, monkeypatch):
    database = claims[0][0]
    archived = database.with_suffix(".old")
    complete = llm.complete_result
    current = job(claims)
    replacement = []

    def switched(*args, **kwargs):
        output = complete(*args, **kwargs)
        database.rename(archived)
        with sqlite3.connect(database) as conn:
            conn.executescript(store.SCHEMA)
            replacement.extend(conn.iterdump())
        return output

    monkeypatch.setattr(llm, "complete_result", switched)
    assert current.run().status == "candidate"
    with sqlite3.connect(database) as conn:
        assert list(conn.iterdump()) == replacement
    sidecar = generation._recovery_path(current.context)
    assert sidecar.is_file()
    retained = generation.validate_request_record(json.loads(sidecar.read_text(encoding="utf-8")))
    assert retained["context_json"] == current.context._json
    assert retained["row_json"] == generation._json(current.result)


def test_read_only_claim_body_fixtures_are_closed_and_hash_checked():
    from pathlib import Path

    fixtures = json.loads(
        (Path(__file__).parent / "fixtures/claim-sets.json").read_text(encoding="utf-8")
    )
    for item in fixtures:
        if item["valid"]:
            assert claim_content.validate(item["body"]) == item["body"]
        else:
            with pytest.raises(ValueError):
                claim_content.validate(item["body"])


def test_claim_route_inherits_global_and_supports_explicit_override_reset():
    from paper_daily import ai_profiles
    from paper_daily.desktop.ai_dialog import TASK_LABELS

    data = {
        "active_profile": "global",
        "prefer_saved_profiles": True,
        "profiles": {
            "global": {"backend": "openai", "model": "global-model", "requires_key": False},
            "reviewer": {"backend": "anthropic", "model": "review-model", "api_key": "fixture"},
        },
    }

    def resolve():
        return ai_profiles.resolve(
            data, "claims", backends=("openai", "anthropic", "none"), environ={}
        )

    assert "claims" in ai_profiles.TASKS and TASK_LABELS["claims"]
    assert resolve().model == "global-model" and resolve().profile == "global"
    data["routes"] = {"claims": "reviewer"}
    assert resolve().model == "review-model" and resolve().profile == "reviewer"
    data["routes"] = {}
    assert resolve().model == "global-model"
    data["routes"] = {"claims": "missing"}
    with pytest.raises(ValueError, match="Unknown AI profile"):
        resolve()


def test_claim_generation_preserves_edited_legacy_claim_notes(claims):
    with (
        closing(generation._connect(claims[0][0])) as conn,
        conn,
        sync_capture.suppress_capture(conn),
    ):
        conn.execute(
            "INSERT INTO notes(paper_id,body,created_at,kind) VALUES "
            "('paper','My edited legacy claim card','2026-01-01T00:00:00+00:00','claim')"
        )
    before = rows(claims[0][0], "SELECT * FROM notes")
    assert job(claims).run().status == "accepted"
    assert rows(claims[0][0], "SELECT * FROM notes") == before


def test_actual_ambiguous_quote_has_no_jump_anchor(claims):
    import pymupdf

    path = claims[0][2].path
    with pymupdf.open(path) as pdf:
        pdf.new_page().insert_text((40, 50), QUOTES[0])
        value = pdf.tobytes()
    path.write_bytes(value)
    claims[1]["claims"][0]["passages"][0]["page"] = None
    assert job(claims).run().status == "accepted"
    location = saved(claims)["report"]["claims"][0]["passages"][0]["location"]
    assert location["state"] == "ambiguous" and location["anchor"] is None
    assert len(location["candidates"]) == 2


def test_claim_input_budget_stops_before_ai_or_source_cache_write(claims, monkeypatch):
    monkeypatch.setattr(claim_jobs, "MAX_INPUT_BYTES", 10)
    with pytest.raises(ValueError, match="input exceeds"):
        job(claims).run()
    assert claims[2] == []
    assert not (claims[0][0].parent / "pdf/.claim-evidence").exists()


def test_loaded_owner_is_rechecked_inside_capture_before_lifecycle_or_ai_writes(claims):
    from paper_daily.manual_highlight_ops import capture_owner

    database = claims[0][0]
    owner = capture_owner(database, "paper")
    with closing(generation._connect(database)) as conn, conn, sync_capture.suppress_capture(conn):
        conn.execute("DELETE FROM papers WHERE id='paper'")
        store.upsert_papers(
            conn,
            [dict(id="paper", title="Recreated", year=2026, venue="Fixture", source="fixture")],
        )
    before = rows(database, "SELECT * FROM research_parent_lifecycle")
    with pytest.raises(ValueError, match="Loaded paper or workspace changed"):
        ClaimJob.capture(database, "paper", legacy_root=claims[0][2].path.parent, owner=owner)
    with pytest.raises(ValueError, match="Loaded paper or workspace changed"):
        claim_jobs.ensure(database, "paper", legacy_root=claims[0][2].path.parent, owner=owner)
    assert rows(database, "SELECT * FROM research_parent_lifecycle") == before
    assert claims[2] == []


def test_ensure_passes_loaded_owner_into_atomic_capture_even_for_cached_content(
    claims, monkeypatch
):
    from paper_daily.manual_highlight_ops import capture_owner

    assert job(claims).run().status == "accepted"
    owner = capture_owner(claims[0][0], "paper")
    capture = ClaimJob.capture
    seen = []

    def checked(*args, **kwargs):
        assert kwargs["owner"] is owner
        seen.append(True)
        return capture(*args, **kwargs)

    monkeypatch.setattr(ClaimJob, "capture", checked)
    value, reason = claim_jobs.ensure(
        claims[0][0], "paper", legacy_root=claims[0][2].path.parent, owner=owner
    )
    assert value["report"]["claims"] and reason == "cached" and seen == [True]
    assert len(claims[2]) == 1


def test_textless_pdf_never_uses_saved_analysis_as_a_substitute_original(claims):
    import pymupdf

    with pymupdf.open() as pdf:
        pdf.new_page()
        data = pdf.tobytes()
    claims[0][2].path.write_bytes(data)
    with pytest.raises(ValueError, match="no readable text"):
        job(claims).run()
    assert claims[2] == []
    assert not (claims[0][0].parent / "pdf/.claim-evidence").exists()


def test_claim_receipt_does_not_turn_requested_fallback_into_reported_model(claims, monkeypatch):
    monkeypatch.setattr(llm, "complete_result", lambda *a, **kw: Completion(
        json.dumps(claims[1]), model="requested", model_reported=False))
    assert job(claims).run().status == "accepted"
    body = saved(claims)
    assert body["generation"]["requested_model"] == "requested"
    assert body["generation"]["returned_model"] is None
