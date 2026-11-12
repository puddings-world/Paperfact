"""Public local note-review operations use durable IDs, never serialized authority."""

import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor

import pytest
from test_archived_draft_resumption import client_for, rows
from test_archived_draft_resumption import copied as copied
from test_archived_draft_resumption import decision as decision
from test_archived_draft_resumption import draft_variants as draft_variants
from test_archived_draft_resumption import source as source
from test_note_draft_resumption import recovered_note as recovered_note
from test_note_draft_resumption_edges import note_rows, stored
from test_note_source_mapping import UNKNOWN

from paper_daily import local_operations as ops
from paper_daily import note_review_operations, store


def invoke(name, **args):
    result = ops.dispatch("review.notes." + name, args)
    assert result["ok"], result
    return result["result"]


def start(value, monkeypatch):
    monkeypatch.setattr(store, "DB_PATH", value["path"])
    listing = invoke("list", limit=1)
    assert len(listing["items"]) == 1 and listing["next"]
    following = invoke("list", after=listing["next"], limit=1)
    assert following["items"][0]["origin_id"] != listing["items"][0]["origin_id"]
    origin = value["archived"].data["id"]
    targets = invoke("targets", origin_id=origin)
    target = next(item for item in targets["items"] if "Current anchored note B" in item["title"])
    request = dict(origin_id=origin, target_id=target["id"], operation_id="external-open")
    opened = invoke("open", **request)
    assert invoke("open", **request) == opened
    assert opened["revision"] == 1
    return {key: opened[key] for key in ("draft_id", "revision")}


def test_local_note_review_reads_maps_saves_applies_and_retries_without_paths(
    recovered_note, monkeypatch
):
    value = recovered_note
    before, pending = stored(value), client_for(value["path"]).journal.pending(1000)
    ref = start(value, monkeypatch)
    read = invoke("read", draft_id=ref["draft_id"])
    assert read["state"] == "verification_required" and not read["can_apply"]
    assert read["position_evidence"] == "legacy_position_unconfirmed"
    assert read["current"]["body"] == "Current anchored note B"
    assert str(value["path"].parent) not in json.dumps(read)
    options = invoke("sources", **ref)["items"]
    source = next(item["reference"] for item in options if item["reference"]["kind"] == "recorded")
    page = invoke("page", **ref, source=source, page_index=0, limit=2)
    assert [w["text"] for w in page["words"]] == ["A", "verified"] and page["next_offset"] == 2
    rest = invoke("page", **ref, source=source, page_index=0, offset=2)
    assert [w["order"] for w in rest["words"]] == [2, 3]
    mapped_args = dict(
        **ref, source=source, anchor=dict(p0=0, o0=0, p1=0, o1=3), operation_id="external-map"
    )
    mapped = invoke("map", **mapped_args)
    assert invoke("map", **mapped_args) == mapped and mapped["revision"] == 2
    saved = invoke(
        "save",
        draft_id=ref["draft_id"],
        revision=2,
        body="Human text from another local project",
        operation_id="external-save",
    )
    assert saved["revision"] == 3
    assert stored(value) == before and client_for(value["path"]).journal.pending(1000) == pending
    request = dict(draft_id=ref["draft_id"], revision=3, operation_id="external-apply")
    refused = ops.dispatch("review.notes.decide", request)
    assert refused["error"]["code"] == "confirmation_required" and stored(value) == before
    result = invoke("decide", **request, confirm=True)
    assert result["decision"] == "applied" and result["revision"] == 4
    assert invoke("decide", **request, confirm=True) == result
    read = invoke("read", draft_id=ref["draft_id"])
    assert read["state"] == "decided" and read["revision"] == 4
    assert read["position_evidence"] == "reviewed_passage"
    assert read["retained"]["anchor"]["selection"]["quote"] == "A verified source paper"
    assert note_rows(value, "body") == [("Human text from another local project",)]
    assert len(client_for(value["path"]).journal.pending(1000)) == len(pending) + 2
    assert ops.inspect_operation("external-apply")["result"] == result
    changed = ops.dispatch(
        "review.notes.save",
        dict(
            draft_id=ref["draft_id"],
            revision=2,
            body="A changed retry must not overwrite",
            operation_id="external-save",
        ),
    )
    assert changed["error"]["code"] == "conflict"
    assert str(value["original"]["path"].parent) not in json.dumps(read)
    value["review"].close()


@pytest.mark.parametrize("recovered_note", [UNKNOWN], indirect=True)
def test_unknown_source_requires_explicit_current_choice_and_clear_keep_preserves_research(
    recovered_note, monkeypatch
):
    value = recovered_note
    before, pending = stored(value), client_for(value["path"]).journal.pending(1000)
    ref = start(value, monkeypatch)
    options = invoke("sources", **ref)["items"]
    assert len(options) == 1 and options[0]["reference"]["kind"] == "current"
    source = options[0]["reference"]
    words = invoke("page", **ref, source=source, page_index=0)["words"]
    assert [word["text"] for word in words] == ["Receiver", "current", "original", "B"]
    mapped = invoke(
        "map", **ref, source=source, anchor=dict(p0=0, o0=0, p1=0, o1=3), operation_id="unknown-map"
    )
    read = invoke("read", draft_id=ref["draft_id"])
    assert read["recorded_source"] is None and read["source_document_hash"] == value["source_b"]
    cleared = invoke(
        "clear", draft_id=ref["draft_id"], revision=mapped["revision"], operation_id="unknown-clear"
    )
    kept = invoke(
        "decide",
        draft_id=ref["draft_id"],
        revision=cleared["revision"],
        decision="keep",
        operation_id="unknown-keep",
    )
    assert kept["decision"] == "kept"
    assert stored(value)["notes"] == before["notes"]
    assert client_for(value["path"]).journal.pending(1000) == pending
    assert invoke("read", draft_id=ref["draft_id"])["retained"]["anchor"] is None
    value["review"].close()


def test_private_and_canonical_receipt_failure_roll_back_then_retry_once(
    recovered_note, monkeypatch
):
    value = recovered_note
    ref = start(value, monkeypatch)
    before, pending = stored(value), client_for(value["path"]).journal.pending(1000)
    native = note_review_operations._receipt

    def fail(*args):
        raise sqlite3.OperationalError("Synthetic outer receipt failure")

    monkeypatch.setattr(note_review_operations, "_receipt", fail)
    args = dict(**ref, body="Private edit retained by caller", operation_id="atomic-private")
    failed = ops.dispatch("review.notes.save", args)
    assert failed["error"]["code"] == "storage_unavailable"
    assert invoke("read", draft_id=ref["draft_id"])["revision"] == 1
    monkeypatch.setattr(note_review_operations, "_receipt", native)
    saved = invoke("save", **args)
    assert saved["revision"] == 2
    monkeypatch.setattr(note_review_operations, "_receipt", fail)
    args = dict(draft_id=ref["draft_id"], revision=2, confirm=True, operation_id="atomic-apply")
    failed = ops.dispatch("review.notes.decide", args)
    assert failed["error"]["code"] == "storage_unavailable"
    assert stored(value) == before and client_for(value["path"]).journal.pending(1000) == pending
    assert invoke("read", draft_id=ref["draft_id"])["revision"] == 2
    monkeypatch.setattr(note_review_operations, "_receipt", native)
    outcome = invoke("decide", **args)
    assert invoke("decide", **args) == outcome
    assert note_rows(value, "body") == [("Private edit retained by caller",)]
    value["review"].close()


def test_parallel_public_retries_save_one_private_draft_and_one_revision(
    recovered_note, monkeypatch
):
    value = recovered_note
    monkeypatch.setattr(store, "DB_PATH", value["path"])
    targets = invoke("targets", origin_id=value["archived"].data["id"])["items"]
    target = next(item for item in targets if "Current anchored note B" in item["title"])
    args = dict(
        origin_id=value["archived"].data["id"], target_id=target["id"], operation_id="parallel-open"
    )
    with ThreadPoolExecutor(max_workers=4) as pool:
        outcomes = list(pool.map(lambda _: ops.dispatch("review.notes.open", args), range(8)))
    result = invoke("open", **args)
    assert all(
        r.get("result") == result or r.get("error", {}).get("code") == "storage_unavailable"
        for r in outcomes
    )
    assert rows(value["path"], "SELECT count(*) FROM research_review_drafts") == [(1,)]
    assert rows(
        value["path"], "SELECT count(*) FROM integration_operations WHERE id='parallel-open'"
    ) == [(1,)]
    value["review"].close()
