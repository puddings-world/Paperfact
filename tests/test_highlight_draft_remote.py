"""Real sync conflicts retain private highlight edits; lone marks cannot become analyses."""

import copy
import json
from contextlib import closing
from uuid import uuid4

import pytest
from test_highlight_draft_storage import ready as ready
from test_highlight_draft_storage import scene as scene
from test_highlight_draft_storage import workspace as workspace
from test_research_review import remote_graph as remote_graph

from paper_daily import research_generation as generation
from paper_daily import sync_content
from paper_daily.research_review import ResearchReview, encode

pytestmark = pytest.mark.parametrize("workspace", [True], indirect=True)


@pytest.mark.parametrize("feature", ["highlight_analysis", "ai_highlight"])
def test_real_remote_analysis_can_be_saved_offline_but_a_lone_mark_cannot(
    scene, remote_graph, monkeypatch, feature
):
    a, b, service, ta, tb, _list = remote_graph
    with closing(generation._connect(b.journal.path)) as conn:
        portable, local = conn.execute(
            "SELECT sync_id,local_id FROM research_paper_identity"
        ).fetchone()
    retained = scene["original"].data["retained"]["analysis"]
    source = retained["document_hash"]
    if feature == "highlight_analysis":
        key = "main"
        data = dict(
            body_json=json.loads(retained["body_json"]),
            source_hash=retained["source_hash"],
            document_hash=source,
            written_at=retained["written_at"],
        )
    else:
        mark = scene["original"].data["retained"]["marks"][0]
        key = source + ":" + mark["source_key"]
        data = {name: mark[name] for name in sync_content.FEATURES[feature][2].split()}
        data["anchor"] = json.loads(data["anchor"])
    scope = dict(kind="paper", id=portable)
    identity = sync_content.content_id(scope, feature, key)
    baseline = dict(scope=scope, feature=feature, key=key, source_document_hash=source, data=data)

    def payload(reason):
        value = copy.deepcopy(baseline)
        if feature == "highlight_analysis":
            value["data"]["body_json"]["items"][0]["reason"] = reason
        else:
            value["data"]["reason"] = reason
        return value

    a.save(a.new_graph_operation("research_content", identity, payload("Initial reason")))
    a.sync_once(service, ta, limit=1000)
    b.sync_once(service, tb, limit=1000)
    a.save(a.new_graph_operation("research_content", identity, payload("Desktop reason")))
    b.save(b.new_graph_operation("research_content", identity, payload("Laptop reason")))
    a.sync_once(service, ta, limit=1000)
    b.sync_once(service, tb, limit=1000)
    a.sync_once(service, ta, limit=1000)
    review = ResearchReview(b.journal.path)
    try:
        previews = [
            review.preview(item["origin"], item["id"])
            for item in review.page(limit=100)["items"]
            if item["origin"] == "remote"
        ]
        original = next(view for view in previews if view.data["source_hash"] == source)
        before = b.journal.pending(1000)
        if feature == "ai_highlight":
            with pytest.raises(ValueError, match="lone mark"):
                review.highlight_draft_targets(original)
            with closing(generation._connect(b.journal.path)) as conn:
                assert not conn.execute(
                    "SELECT name FROM sqlite_master WHERE name='research_review_drafts'"
                ).fetchone()
            assert b.journal.pending(1000) == before
            return
        with monkeypatch.context() as offline:
            for method in ("push", "pull", "session_info"):
                offline.setattr(
                    service,
                    method,
                    lambda *a, **k: pytest.fail("Private offline review contacted the service"),
                )
            assert review.highlight_draft_targets(original) == dict(
                items=[dict(id=local, title="Research paper")], next=None
            )
            view, raw = review.select_highlight_draft(original, local)
            draft = json.loads(raw)
            assert draft["items"][0]["reason"] == "Laptop reason"
            assert (
                json.loads(view.data["current"]["body_json"])["items"][0]["reason"]
                == "Desktop reason"
            )
            draft["items"][0]["reason"] = "Private offline comparison of both interpretations."
            body = encode(draft)
            saved = review.save_highlight_draft(view, body, str(uuid4()), draft_id=str(uuid4()))
            review.close()
            review = ResearchReview(b.journal.path)
            loaded = review.load_highlight_draft(view.data["id"], draft_id=saved["draft_id"])
            assert loaded["body"] == body and loaded["state"] == "verification_required"
            assert not loaded["preview"].data["apply"]
        assert b.journal.pending(1000) == before
        a.save(a.new_graph_operation("research_content", identity, payload("New desktop decision")))
        a.sync_once(service, ta, limit=1000)
        b.sync_once(service, tb, limit=1000)
        stale = review.load_highlight_draft(view.data["id"], draft_id=saved["draft_id"])
        assert stale["body"] == body and stale["state"] == "stale"
        assert stale["preview"].data["expected"] == view.data["expected"]
    finally:
        review.close()
