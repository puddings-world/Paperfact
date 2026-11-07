"""Confirmed human groups preserve private words, curated marks, A/B and atomic retries."""

import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from uuid import uuid4

import pytest
from test_highlight_draft_verification import ready as ready
from test_highlight_draft_verification import scene as scene
from test_highlight_draft_verification import source_pair as source_pair
from test_highlight_draft_verification import workspace as workspace
from test_highlight_generation import change_mark
from test_research_generation import rows

from paper_daily import manual_highlight_ops, sync_capture, sync_source_files
from paper_daily import research_generation as generation
from paper_daily.document_reader import DocumentReader
from paper_daily.research_review import ResearchReview, encode, validate_receipt
from paper_daily.research_review_drafts import validate_record
from paper_daily.sync_files import file_id

pytestmark = pytest.mark.parametrize("workspace", [True], indirect=True)


def snapshot(value):
    with closing(generation._connect(value["path"])) as conn:
        names = {
            row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        return {
            name: [dict(row) for row in conn.execute('SELECT * FROM "' + name + '" ORDER BY rowid')]
            for name in (
                "paper_highlight_analysis",
                "pdf_ai_highlights",
                "pdf_highlights",
                "research_review_drafts",
                "research_review_receipts",
                "paperfact_sync_operations",
                "research_file_versions",
            )
            if name in names
        }


def apply(value, checked, **options):
    return value["review"].apply_highlight_draft(
        checked,
        options.pop("body", value["body"]),
        request_id=options.pop("request_id", str(uuid4())),
        confirm_target=options.pop("confirm_target", True),
        **options,
    )


def fresh(value):
    preview, raw = value["review"].select_highlight_draft(value["original"], "paper")
    return preview, raw


def checked(value):
    return value["review"].verify_highlight_draft(value["preview"], value["body"])


def assert_b(value):
    assert value["current"].path.read_bytes() == value["current_bytes"]
    assert (
        DocumentReader.from_workspace(value["path"]).resolve("paper").sha256
        == value["current"].sha256
    )


def test_confirmed_group_keeps_manual_hidden_and_private_content_with_one_retry(source_pair):
    value = source_pair
    # Add a genuine manual mark to A; select again to observe that user-owned layer.
    proof = value["review"].prepare_highlight_original(value["preview"])
    owner = manual_highlight_ops.capture_owner(value["path"], "paper")
    view = manual_highlight_ops.load(
        owner, proof.path if hasattr(proof, "path") else proof.source_path, proof.document_hash
    )
    retained = value["preview"].data["expected"]["highlights"]["marks"][0]
    manual_highlight_ops.add(view, json.loads(retained["anchor"]), retained["quote"])
    value["preview"], value["body"] = fresh(value)
    body = json.loads(value["body"])
    body["items"][0]["reason"] = "A human revision after reviewing the complete original."
    value["body"] = encode(body)
    private_before = rows(value["path"], "SELECT * FROM pdf_highlights")
    verified = checked(value)
    request = str(uuid4())
    report = value["review"].highlight_draft_report(verified)
    outcome = apply(value, verified, request_id=request)
    after = snapshot(value)
    for _ in range(5):
        assert apply(value, verified, request_id=request) == outcome
    assert snapshot(value) == after
    saved = after["paper_highlight_analysis"][0]
    assert json.loads(saved["body_json"]) == report["analysis"]
    assert saved["source_hash"] == verified.data["retained"]["source_hash"]
    marks = after["pdf_ai_highlights"]
    assert len(marks) == 2 and sum(mark["hidden"] for mark in marks) == 1
    assert (
        next(mark for mark in marks if mark["quote"] == body["items"][0]["text"])["reason"]
        == body["items"][0]["reason"]
    )
    assert rows(value["path"], "SELECT * FROM pdf_highlights") == private_before
    drafts = after["research_review_drafts"]
    assert len(drafts) == 1 and validate_record(drafts[0])["body"] == value["body"]
    assert not json.loads(drafts[0]["preview_json"])["apply"]
    assert len(after["research_review_receipts"]) == 1
    assert validate_receipt(after["research_review_receipts"][0])["origin"] == "highlight_resume"
    from paper_daily.review_decisions import latest_in

    with closing(value["review"]._connect()) as conn:
        assert latest_in(conn, "generation", value["original"].data["id"]) == "applied"

    relevant = [
        op
        for op in value["client"].journal.pending(1000)
        if op["operation_id"] == request or op.get("payload", {}).get("feature") == "ai_highlight"
    ]
    assert sum(op["operation_id"] == request for op in relevant) == 1
    assert_b(value)
    assert value["review"].prepare_highlight_original(verified).data == value["original_bytes"]


def test_concurrent_repeated_application_has_one_private_and_public_commit(source_pair):
    value = source_pair
    verified, request = checked(value), str(uuid4())
    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(lambda _: apply(value, verified, request_id=request), range(8)))
    assert outcomes == [dict(decision="applied", operation_id=request)] * 8
    assert len(rows(value["path"], "SELECT * FROM research_review_receipts")) == 1
    assert len(rows(value["path"], "SELECT * FROM research_review_drafts")) == 1
    assert_b(value)


@pytest.mark.parametrize("change", ["body", "unverified", "demoted", "closed", "confirmation"])
def test_no_stale_or_unconfirmed_capability_changes_research(source_pair, change):
    value = source_pair
    verified = checked(value)
    options = {}
    if change == "body":
        draft = json.loads(value["body"])
        draft["items"][0]["reason"] = "Changed after verifying the original."
        options["body"] = encode(draft)
    elif change == "unverified":
        verified = value["preview"]
    elif change == "demoted":
        value["review"].require_draft_verification(verified)
    elif change == "closed":
        value["review"].close()
    else:
        options["confirm_target"] = False
    before = snapshot(value)
    with pytest.raises(ValueError):
        apply(value, verified, **options)
    assert snapshot(value) == before
    assert_b(value)


def test_unresolved_quote_never_publishes_a_partial_group(source_pair):
    value = source_pair
    draft = json.loads(value["body"])
    draft["items"][1]["text"] = "A quote which does not occur anywhere in the original."
    value["body"] = encode(draft)
    verified = checked(value)
    assert verified.data["resume_state"] == "needs_location"
    before = snapshot(value)
    with pytest.raises(ValueError, match="every highlight quote"):
        apply(value, verified)
    assert snapshot(value) == before


@pytest.mark.parametrize("stage", ["analysis", "second_mark", "decision", "private"])
def test_failure_after_earlier_writes_rolls_back_group_source_outbox_and_words(
    source_pair, monkeypatch, stage
):
    value = source_pair
    verified, request = checked(value), str(uuid4())
    before = snapshot(value)
    with monkeypatch.context() as patch:
        if stage in {"analysis", "second_mark"}:
            quote = json.loads(value["body"])["items"][1]["text"]
            with closing(sqlite3.connect(value["path"])) as conn, conn:
                conn.execute(
                    "CREATE TRIGGER fail_human_group BEFORE "
                    + ("UPDATE" if stage == "analysis" else "INSERT")
                    + " ON "
                    + ("paper_highlight_analysis" if stage == "analysis" else "pdf_ai_highlights")
                    + (
                        " WHEN NEW.quote=" + "'" + quote.replace("'", "''") + "'"
                        if stage == "second_mark"
                        else ""
                    )
                    + " BEGIN SELECT RAISE(ABORT,'injected write failure'); END"
                )
        else:

            def failure(*a, **k):
                raise OSError("injected receipt failure")

            if stage == "decision":
                patch.setattr(ResearchReview, "_receipt", staticmethod(failure))
            else:
                from paper_daily.research_review_drafts import DraftStore

                patch.setattr(DraftStore, "save_in", failure)
        with pytest.raises((OSError, sqlite3.DatabaseError), match="injected"):
            apply(value, verified, request_id=request)
    assert snapshot(value) == before
    if stage in {"analysis", "second_mark"}:
        with closing(sqlite3.connect(value["path"])) as conn, conn:
            conn.execute("DROP TRIGGER fail_human_group")
    assert apply(value, verified, request_id=request)["decision"] == "applied"
    assert_b(value)


@pytest.mark.parametrize("layer", ["analysis", "hidden", "manual"])
def test_changed_curated_layer_after_verification_refuses_without_overwrite(source_pair, layer):
    value = source_pair
    verified = checked(value)
    with (
        closing(generation._connect(value["path"])) as conn,
        conn,
        sync_capture.suppress_capture(conn),
    ):
        if layer == "analysis":
            conn.execute("UPDATE paper_highlight_analysis SET written_at='newer'")
        elif layer == "hidden":
            conn.execute("UPDATE pdf_ai_highlights SET hidden=0")
        else:
            conn.execute(
                "INSERT INTO pdf_highlights(paper_id,document_hash,anchor,quote,created_at) "
                "SELECT paper_id,document_hash,anchor,quote,'manual' "
                "FROM pdf_ai_highlights LIMIT 1"
            )
    before = snapshot(value)
    with pytest.raises(ValueError, match="changed"):
        apply(value, verified)
    assert snapshot(value) == before


@pytest.mark.parametrize(
    "layer", ["analysis", "mark", "manual", "parent", "source", "private", "decision"]
)
def test_mutating_trusted_receipt_callback_cannot_commit_a_partial_or_rebound_group(
    source_pair, layer
):
    value = source_pair
    verified = checked(value)
    before = snapshot(value)

    def mutate(conn, result):
        with sync_capture.suppress_capture(conn):
            if layer == "analysis":
                conn.execute("UPDATE paper_highlight_analysis SET written_at='unexpected'")
            elif layer == "mark":
                conn.execute("UPDATE pdf_ai_highlights SET reason='unexpected'")
            elif layer == "manual":
                conn.execute(
                    "INSERT INTO pdf_highlights(paper_id,document_hash,anchor,quote,created_at) "
                    "SELECT paper_id,document_hash,anchor,quote,'manual' "
                    "FROM pdf_ai_highlights LIMIT 1"
                )
            elif layer == "private":
                conn.execute("UPDATE research_review_drafts SET body='changed private words'")
            elif layer == "decision":
                conn.execute("UPDATE research_review_receipts SET decision='kept'")
            elif layer == "parent":
                conn.execute("UPDATE papers SET title='unexpected'")
            else:
                client = conn._capture_client
                identity = file_id(
                    verified.data["expected"]["paper_sync_id"],
                    sync_source_files.FEATURE,
                    verified.data["source_hash"],
                )
                operation = client.new_graph_operation_in(
                    conn, "research_file", identity, {}, action="delete"
                )
                assert client.journal.apply_in(conn, operation, client.writer)["applied"]
                conn._capture_graph_cache = None

    with pytest.raises(ValueError, match="changed|retired"):
        apply(value, verified, _operation_receipt=mutate)
    assert snapshot(value) == before
    assert_b(value)


@pytest.mark.parametrize("layer", ["analysis", "mark"])
def test_deleted_analysis_or_mark_needs_explicit_restoration_and_keeps_tombstone(
    source_pair, layer
):
    value = source_pair
    before_token = value["preview"].data["expected"]["observation"]
    if layer == "mark":
        change_mark(value["path"], delete=True)
    else:
        with closing(generation._connect(value["path"])) as conn:
            observed = sync_capture.observe_target(conn, "paper", "paper", "highlight_analysis")
            with sync_capture.expecting(conn, [observed]):
                conn.execute("DELETE FROM paper_highlight_analysis WHERE paper_id='paper'")
                conn.commit()
    value["preview"], value["body"] = fresh(value)
    verified = checked(value)
    before = snapshot(value)
    with pytest.raises(ValueError, match="restoration"):
        apply(value, verified)
    assert snapshot(value) == before
    apply(value, verified, restore_deleted=True)
    with closing(generation._connect(value["path"])) as conn:
        now = sync_capture.observe_target(conn, "paper", "paper", "highlight_analysis")
    assert now["active"]
    if layer == "analysis":
        assert now["incarnation"] != before_token["incarnation"]
    assert len(rows(value["path"], "SELECT * FROM pdf_ai_highlights")) == 2
    assert_b(value)


def test_identical_accepted_retry_does_not_replace_later_analysis_or_restore_retired_source(
    source_pair,
):
    value = source_pair
    verified, request = checked(value), str(uuid4())
    outcome = apply(value, verified, request_id=request)
    with closing(generation._connect(value["path"])) as conn, conn:
        conn.execute("BEGIN IMMEDIATE")
        client = conn._capture_client
        identity = file_id(
            verified.data["expected"]["paper_sync_id"],
            sync_source_files.FEATURE,
            verified.data["source_hash"],
        )
        with sync_capture.suppress_capture(conn):
            operation = client.new_graph_operation_in(
                conn, "research_file", identity, {}, action="delete"
            )
            assert client.journal.apply_in(conn, operation, client.writer)["applied"]
            conn.execute("UPDATE paper_highlight_analysis SET written_at='later human work'")
    before = snapshot(value)
    assert apply(value, verified, request_id=request) == outcome
    assert snapshot(value) == before
    changed = json.loads(value["body"])
    changed["items"][0]["reason"] = "Different payload cannot reuse a committed decision."
    with pytest.raises(ValueError, match="retry changed"):
        apply(value, verified, body=encode(changed), request_id=request)
    assert snapshot(value) == before


def test_exact_private_revision_and_public_group_commit_together(source_pair):
    value = source_pair
    request, draft_id = str(uuid4()), str(uuid4())
    saved = value["review"].save_highlight_draft(
        value["preview"], value["body"], request, draft_id=draft_id
    )
    verified = checked(value)
    before = snapshot(value)
    with pytest.raises(ValueError):
        apply(value, verified, draft_id=draft_id, revision=saved["revision"] + 1)
    assert snapshot(value) == before
    result = apply(
        value, verified, request_id=request, draft_id=draft_id, revision=saved["revision"]
    )
    assert result["decision"] == "applied"
    assert len(rows(value["path"], "SELECT * FROM research_review_drafts")) == 1
    assert_b(value)


def test_lost_commit_reply_returns_committed_group_without_duplicate_words(
    source_pair, monkeypatch
):
    value = source_pair
    verified, request = checked(value), str(uuid4())
    lost = []

    class LostReply(sync_capture.CaptureConnection):
        def commit(self):
            accepted = self.execute(
                "SELECT 1 FROM research_review_receipts WHERE request_id=?", (request,)
            ).fetchone()
            super().commit()
            if accepted and not lost:
                lost.append(True)
                raise OSError("committed reply lost")

    def connect():
        conn = sqlite3.connect(value["path"], factory=LostReply)
        value["review"]._check(conn)
        return conn

    monkeypatch.setattr(value["review"], "_connect", connect)
    with pytest.raises(OSError, match="reply lost"):
        apply(value, verified, request_id=request)
    after = snapshot(value)
    assert apply(value, verified, request_id=request) == dict(
        decision="applied", operation_id=request
    )
    assert snapshot(value) == after
    assert len(after["research_review_receipts"]) == 1
    assert len(after["research_review_drafts"]) == 1


@pytest.mark.parametrize("at_commit", [False, True])
def test_cancelled_apply_rolls_back_private_and_public_writes(source_pair, at_commit):
    value = source_pair
    verified = checked(value)
    before = snapshot(value)
    cancelled = [False]

    def receipt(conn, result):
        cancelled[0] = True

    with pytest.raises(ValueError, match="cancelled"):
        apply(
            value,
            verified,
            cancelled=(lambda: cancelled[0]) if at_commit else (lambda: True),
            _operation_receipt=receipt,
        )
    assert snapshot(value) == before
    assert_b(value)


def test_injected_same_body_analysis_operation_does_not_escape_final_group_checks(source_pair):
    value = source_pair
    verified = checked(value)
    before = snapshot(value)

    def receipt(conn, result):
        from paper_daily import sync_content

        row = dict(conn.execute("SELECT * FROM paper_highlight_analysis").fetchone())
        payload = sync_content.content_payload(conn, "paper_highlight_analysis", row)
        client = conn._capture_client
        operation = client.new_graph_operation_in(
            conn, "research_content", verified.data["expected"]["observation"]["entity_id"], payload
        )
        with sync_capture.suppress_capture(conn):
            assert client.journal.apply_in(conn, operation, client.writer)["applied"]
        conn._capture_graph_cache = None

    with pytest.raises(ValueError, match="operation changed"):
        apply(value, verified, _operation_receipt=receipt)
    assert snapshot(value) == before


def test_unrelated_note_during_receipt_is_preserved_with_the_complete_group(source_pair):
    value = source_pair
    verified = checked(value)

    def receipt(conn, result):
        conn.execute(
            "INSERT INTO notes(paper_id,body,created_at) VALUES('paper','Keep this note',"
            "'2026-11-02T00:00:00+00:00')"
        )

    assert apply(value, verified, _operation_receipt=receipt)["decision"] == "applied"
    assert rows(value["path"], "SELECT body FROM notes") == [dict(body="Keep this note")]
    assert len(rows(value["path"], "SELECT * FROM pdf_ai_highlights")) == 2
    assert_b(value)


def test_omitted_quote_keeps_history_but_reader_shows_only_the_current_group(source_pair):
    value = source_pair
    with (
        closing(generation._connect(value["path"])) as conn,
        conn,
        sync_capture.suppress_capture(conn),
    ):
        conn.execute("UPDATE pdf_ai_highlights SET hidden=0")
    value["preview"], value["body"] = fresh(value)
    draft = json.loads(value["body"])
    omitted = draft["items"].pop(0)
    value["body"] = encode(draft)
    verified = checked(value)
    apply(value, verified)
    saved = rows(value["path"], "SELECT * FROM paper_highlight_analysis")[0]
    assert saved["source_hash"] == value["preview"].data["retained"]["source_hash"]
    # The page-text provenance is unchanged; current items decide visible marks.
    assert len(rows(value["path"], "SELECT * FROM pdf_ai_highlights")) == 2
    proof = value["review"].prepare_highlight_original(verified)
    owner = manual_highlight_ops.capture_owner(value["path"], "paper")
    view = manual_highlight_ops.load(owner, proof.source_path, proof.document_hash)
    assert [mark["quote"] for mark in view.marks] == [draft["items"][0]["text"]]
    assert omitted["text"] not in [mark["quote"] for mark in view.marks]
    assert_b(value)


@pytest.mark.parametrize("source_change", ["retired", "bytes"])
def test_original_changed_after_verification_never_creates_a_new_decision(
    source_pair, source_change
):
    from paper_daily import review_draft_sources

    value = source_pair
    verified = checked(value)
    if source_change == "retired":
        with closing(generation._connect(value["path"])) as conn:
            conn.execute("BEGIN IMMEDIATE")
            client = conn._capture_client
            identity = file_id(
                verified.data["expected"]["paper_sync_id"],
                sync_source_files.FEATURE,
                verified.data["source_hash"],
            )
            operation = client.new_graph_operation_in(
                conn, "research_file", identity, {}, action="delete"
            )
            with sync_capture.suppress_capture(conn):
                assert client.journal.apply_in(conn, operation, client.writer)["applied"]
            conn.commit()
    else:
        prepared = value["review"]._resume_sources[review_draft_sources.key(verified.data)]
        path, _version = prepared.proof.files[verified.data["source_hash"]]
        path.write_bytes(b"damaged isolated original")
    before = snapshot(value)
    with pytest.raises(ValueError):
        apply(value, verified)
    assert snapshot(value) == before
    assert_b(value)


def test_replacement_database_after_verification_is_never_a_destination(source_pair):
    value = source_pair
    verified = checked(value)
    replacement = value["path"].with_suffix(".replacement.sqlite")
    with (
        closing(sqlite3.connect(value["path"])) as original,
        closing(sqlite3.connect(replacement)) as new,
    ):
        original.backup(new)
    replacement.replace(value["path"])
    before = snapshot(value)
    with pytest.raises(ValueError, match="replaced"):
        apply(value, verified)
    assert snapshot(value) == before
