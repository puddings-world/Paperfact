"""Only initial absent registered annotation IDs can create a known-empty graph baseline."""

import copy

import pytest
from test_sync_files import LOCAL
from test_sync_files import codec as codec_fixture
from test_sync_files import pair as pair_fixture

from paper_daily import annotation_content, annotation_reader
from paper_daily.enrollment_tombstones import establish_in, project_absent

codec = codec_fixture
pair = pair_fixture


@pytest.mark.parametrize("feature", list(annotation_content.FEATURES))
def test_empty_baseline_has_one_retryable_tombstone_and_converges_without_a_put(pair, feature):
    service, a, b, _fa, _fb, ta, tb = pair
    with a.journal.transaction() as conn:
        op = establish_in(conn, a, feature=feature, paper_id=LOCAL, request_id="initial-" + feature)
    before = a.journal.pending(1000)
    with a.journal.transaction() as conn:
        assert (
            establish_in(conn, a, feature=feature, paper_id=LOCAL, request_id="initial-" + feature)
            == op
        )
    assert a.journal.pending(1000) == before and op["payload"] == {} and op["action"] == "delete"
    a.sync_once(service, ta)
    b.sync_once(service, tb)
    assert annotation_reader.saved(b.journal.path, LOCAL, feature)["known"] is True
    with b.journal.transaction() as conn:
        assert not conn.execute(
            f'SELECT * FROM "{annotation_content.FEATURES[feature]}"'
        ).fetchall()


def test_later_failure_rolls_back_known_marker_projection_and_outbox(pair):
    _service, a, _b, *_ = pair
    before = a.journal.pending(1000)
    with pytest.raises(RuntimeError), a.journal.transaction() as conn:
        establish_in(conn, a, feature="claims", paper_id=LOCAL, request_id="rolled-back")
        raise RuntimeError("later enrollment write failed")
    assert a.journal.pending(1000) == before
    assert annotation_reader.saved(a.journal.path, LOCAL, "claims") is None
    with a.journal.transaction() as conn:
        assert not conn.execute("SELECT * FROM research_content_projection").fetchall()


def test_wrong_parent_epoch_unknown_feature_and_untracked_content_are_not_retired(pair):
    _service, a, _b, *_ = pair
    with a.journal.transaction() as conn:
        op = establish_in(conn, a, feature="claims", paper_id=LOCAL, request_id="valid-first")
    bad = copy.deepcopy(op)
    bad["parents"][0]["incarnation"] = "wrong-parent"
    with a.journal.transaction() as conn:
        with pytest.raises(ValueError, match="exact current paper"):
            project_absent(conn, bad)
        with pytest.raises(ValueError):
            establish_in(conn, a, feature="unknown", paper_id=LOCAL, request_id="unknown")
    assert annotation_reader.saved(a.journal.path, LOCAL, "claims") == {"claims": [], "known": True}
