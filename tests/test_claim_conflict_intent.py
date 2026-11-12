"""Captured conflict identity, rollback and legacy continuation are observable rules."""

import copy
import json
from uuid import uuid4

import pytest
from test_claim_draft_storage import rows
from test_claim_review_continuity import claims as claims
from test_claim_review_continuity import ready as ready
from test_claim_review_continuity import receiver as receiver
from test_claim_review_continuity import scene as scene
from test_claim_review_continuity import source_pair as source_pair
from test_claim_review_continuity import typed_edit
from test_claim_review_continuity import workspace as workspace
from test_claim_review_operations import invoke
from test_enrollment_history_peer import peer

from paper_daily import claim_draft_resume, claim_review_operations, local_operations, store
from paper_daily.archived_draft_resume import _sealed
from paper_daily.research_review import ResearchReview

pytestmark = pytest.mark.parametrize("workspace", [True], indirect=True)


@pytest.fixture
def remote(receiver, monkeypatch):
    value = receiver
    review = value["review"]
    checked = review.verify_claim_draft(value["preview"], value["body"])
    review.apply_claim_draft(checked, value["body"], request_id=str(uuid4()), confirm_target=True)
    first = typed_edit(value, "Desktop interpretation held while the conflict is reviewed.")
    second = typed_edit(value, "Incoming interpretation requiring an explicit decision.")
    folder = value["path"].parent.parent / "remote-intent-boundary"
    folder.mkdir()
    a, b, service, ta, tb, portable, local, files = peer(value["adopted"], folder)
    from paper_daily.sync_content import content_id

    identity = content_id(dict(kind="paper", id=portable), "claims", "main")
    try:
        a.save(a.new_graph_operation("research_content", identity, first))
        incoming = b.new_graph_operation("research_content", identity, second)
        b.save(incoming)
        a.sync_once(service, ta, limit=1000)
        b.sync_once(service, tb, limit=1000)
        a.sync_once(service, ta, limit=1000)
        monkeypatch.setattr(store, "DB_PATH", b.journal.path)
        origins = [
            item["origin_id"]
            for item in invoke("list")["items"]
            if item["origin_id"].startswith("remote:")
        ]
        assert len(origins) == 1
        yield dict(
            value=value,
            a=a,
            b=b,
            service=service,
            ta=ta,
            tb=tb,
            local=local,
            origin=origins[0],
            incoming=incoming,
            identity=identity,
        )
    finally:
        files.close()


def opened(value):
    return invoke(
        "open",
        origin_id=value["origin"],
        target_id=value["local"],
        operation_id="remote-boundary-open",
    )


def test_remote_receipt_failure_rolls_back_resolution_intent_outbox_and_private_revision(
    remote, monkeypatch
):
    value = remote
    ref = opened(value)
    path = value["b"].journal.path
    tables = (
        "paper_claim_sets",
        "research_review_drafts",
        "integration_operations",
        "research_resolution_intents",
        "paperfact_sync_operations",
    )
    before = {name: rows(path, "SELECT * FROM " + name) for name in tables}
    request = dict(
        draft_id=ref["draft_id"], revision=1, operation_id="remote-failed-receipt", confirm=True
    )
    with monkeypatch.context() as patch:
        patch.setattr(
            claim_review_operations,
            "_receipt",
            lambda *a: (_ for _ in ()).throw(OSError("fixture storage failure")),
        )
        failed = local_operations.dispatch("review.claims.apply", request)
        assert not failed["ok"]
    assert {name: rows(path, "SELECT * FROM " + name) for name in tables} == before
    accepted = invoke("apply", **request)
    assert invoke("apply", **request) == accepted
    queued = value["b"].journal.pending(1000)
    assert len(queued) == 1 and queued[0]["resolution_of"] == value["incoming"]["operation_id"]
    assert rows(path, "SELECT count(*) AS n FROM research_resolution_intents") == [dict(n=1)]


def test_another_device_resolution_after_verification_preserves_new_research_and_private_text(
    remote, monkeypatch
):
    value = remote
    ref = opened(value)
    text = invoke("read", draft_id=ref["draft_id"])["draft"]
    text["claims"][0]["text"] = "Do not lose this private interpretation after another decision."
    saved = invoke(
        "save",
        draft_id=ref["draft_id"],
        revision=1,
        draft=text,
        operation_id="private-before-other-decision",
    )
    original = ResearchReview.verify_claim_draft
    newer = []

    def changed(self, *args, **kwargs):
        checked = original(self, *args, **kwargs)
        sequence = int(value["origin"].split(":", 1)[1])
        value["a"].resolve_conflict(sequence, choice="canonical", operation_id=str(uuid4()))
        value["a"].sync_once(value["service"], value["ta"], limit=1000)
        value["b"].sync_once(value["service"], value["tb"], limit=1000)
        newer.extend(rows(value["b"].journal.path, "SELECT * FROM paper_claim_sets"))
        return checked

    monkeypatch.setattr(ResearchReview, "verify_claim_draft", changed)
    failed = local_operations.dispatch(
        "review.claims.apply",
        dict(
            draft_id=ref["draft_id"],
            revision=saved["revision"],
            operation_id="stale-remote-apply",
            confirm=True,
        ),
    )
    assert not failed["ok"] and newer
    path = value["b"].journal.path
    assert rows(path, "SELECT * FROM paper_claim_sets") == newer
    assert not value["b"].journal.pending(1000)
    assert json.loads(rows(path, "SELECT body FROM research_review_drafts")[0]["body"]) == text
    assert rows(path, "SELECT count(*) AS n FROM research_resolution_intents") == [dict(n=0)]


def test_legacy_remote_claim_draft_is_readable_but_requires_explicit_reselection(remote):
    value = remote
    review = ResearchReview(value["b"].journal.path)
    try:
        original = review.preview("remote", value["origin"].split(":", 1)[1])
        current, body = review.select_claim_draft(original, value["local"])
        data = current.data
        data["expected"]["version"] = 1
        data["expected"].pop("conflict")
        legacy = _sealed(review, data)
        identifier = str(uuid4())
        review.save_claim_draft(legacy, body, str(uuid4()), draft_id=identifier)
        loaded = review.load_claim_draft(value["origin"], draft_id=identifier)
        assert loaded["body"] == body
        with pytest.raises(ValueError, match="Reselect"):
            review.verify_claim_draft(legacy, body)
        assert not value["b"].journal.pending(1000)
        selected, retained = review.select_claim_draft(legacy, value["local"], body=body)
        assert retained == body and selected.data["expected"]["version"] == 2
        checked = review.verify_claim_draft(selected, retained)
        review.apply_claim_draft(checked, retained, request_id=str(uuid4()), confirm_target=True)
        assert len(value["b"].journal.pending(1000)) == 1
    finally:
        review.close()


def test_remote_private_codec_rejects_contradictory_or_unknown_observations_without_io(remote):
    value = remote
    review = ResearchReview(value["b"].journal.path)
    try:
        current, body = review.select_claim_draft(
            review.preview("remote", value["origin"].split(":", 1)[1]), value["local"]
        )
        owner = dict(path=str(review.path), identity=review.identity, binding=review.binding)
        before = value["b"].journal.path.read_bytes()
        mutations = [
            lambda s: s["expected"]["conflict"].update(unknown_path="elsewhere"),
            lambda s: s["expected"]["conflict"].update(outstanding=True),
            lambda s: s["expected"]["conflict"].update(resolved_by=str(uuid4())),
            lambda s: s["expected"]["conflict"]["event"].update(sequence=999999),
            lambda s: s["expected"]["conflict"].update(head={}),
            lambda s: s["expected"]["conflict"]["state"].update(unknown=True),
        ]
        for change in mutations:
            data = copy.deepcopy(current.data)
            change(data)
            with pytest.raises(ValueError):
                claim_draft_resume.validate_snapshot(data, owner, body)
        assert value["b"].journal.path.read_bytes() == before
    finally:
        review.close()


def test_live_remote_target_choices_do_not_offer_a_different_paper(remote):
    value = remote
    preview = local_operations.dispatch(
        "imports.propose",
        dict(name="Another research list", papers=[dict(title="Second unrelated paper")]),
    )
    assert preview["ok"], preview
    result = local_operations.dispatch(
        "imports.commit",
        dict(
            preview_id=preview["result"]["preview_id"],
            operation_id="other-paper-import",
            selected=["0"],
        ),
    )
    assert result["ok"], result
    path = value["b"].journal.path
    other = rows(path, "SELECT id FROM papers WHERE title='Second unrelated paper'")[0]["id"]
    targets = invoke("targets", origin_id=value["origin"])
    assert [item["id"] for item in targets["items"]] == [value["local"]]
    before = rows(path, "SELECT * FROM paper_claim_sets")
    refused = local_operations.dispatch(
        "review.claims.open",
        dict(origin_id=value["origin"], target_id=other, operation_id="wrong-conflict-paper"),
    )
    assert not refused["ok"] and rows(path, "SELECT * FROM paper_claim_sets") == before
