"""Stateless local transports over the native, typed note-review workflow.

Only durable draft IDs/revisions and bounded source intents cross process
boundaries. No caller supplies paths, signed preview JSON or byte capabilities.
Private saves and their retry receipts share a transaction. Final decisions also
include the note/source/outbox and saved private state in that same transaction.
"""

from __future__ import annotations

import json
import re
from contextlib import closing
from uuid import NAMESPACE_URL, uuid5

from paper_daily.review_operation_journal import (
    _check_revision,
    _fail,
    _fingerprint,
    _operation,
    _output,
    _prior,
    _receipt,
    _review,
    _revision,
    _uuid,
)

_HASH = re.compile(r"[0-9a-f]{64}")


def _origin(value):
    if not isinstance(value, str) or not _HASH.fullmatch(value):
        _fail("invalid_input", "Use a saved historical note ID from review.notes.list")


def _source(value):
    from paper_daily.note_source_refs import reference

    try:
        return dict(reference(value))
    except ValueError:
        _fail("invalid_input", "Use only kind/document_hash from this draft's source list")


def _anchor(value):
    from paper_daily.sync_content import validate_anchor

    try:
        if value is None:
            raise ValueError
        validate_anchor(value)
        return dict(value)
    except ValueError:
        _fail("invalid_input", "Use PDF page/raw word coordinates; do not submit quotation text")


def _body(value):
    try:
        valid = isinstance(value, str) and len(value.encode("utf-8")) <= 200 * 1024
    except UnicodeError:
        valid = False
    if not valid:
        _fail("invalid_input", "Draft text must be valid UTF-8 and at most 200 KiB")


def _draft(service, draft_id, revision=None):
    from paper_daily.research_review_drafts import TABLE

    _uuid(draft_id)
    if revision is not None:
        _revision(revision)
    with closing(service._connect()) as conn:
        if conn.execute("SELECT 1 FROM sqlite_master WHERE name=?", (TABLE,)).fetchone() is None:
            _fail("not_found", "Saved note draft not found")
        row = conn.execute(
            "SELECT origin,origin_id FROM research_review_drafts WHERE draft_id=?", (draft_id,)
        ).fetchone()
    if row is None or row[0] != "archived_note_resume":
        _fail("not_found", "Saved note draft not found")
    loaded = service.load_draft(row[0], row[1], draft_id=draft_id)
    if loaded is None or loaded.get("preview") is None or loaded["state"] in {"foreign", "corrupt"}:
        _fail(
            "review_unavailable", "Draft belongs to an earlier owner or needs recovery in the app"
        )
    if revision is not None and loaded["revision"] != revision:
        _fail("conflict", "Draft revision changed; read the saved draft again")
    return loaded


def _private(operation, arguments, prepare):
    from paper_daily.review_operation_journal import private

    return private(operation, arguments, prepare, _review_factory=_review, _receipt_fn=_receipt)


def list_notes(after: str = "", limit: int = 30):
    from paper_daily import archived_review_drafts, review_draft_resumption

    if after:
        _origin(after)
    if not isinstance(after, str) or type(limit) is not int or not 1 <= limit <= 100:
        _fail("invalid_input", "Use a saved note cursor and a limit of 1-100")
    with _review() as service, closing(service._connect()) as conn:
        records = archived_review_drafts._records(conn)
        items = []
        for identity in sorted(records):
            if identity <= after:
                continue
            record, summary = records[identity]
            try:
                adapter = review_draft_resumption.archived(record)
            except ValueError:
                continue
            if adapter.ORIGIN == "archived_note_resume":
                items.append(dict(origin_id=identity, summary=summary))
                if len(items) > limit:
                    break
        service._check(conn)
        return _output(
            dict(
                items=items[:limit],
                next=items[limit - 1]["origin_id"] if len(items) > limit else None,
                editable=not service.recovery and service.binding is not None,
            )
        )


def targets(origin_id: str, after: str = "", limit: int = 30):
    _origin(origin_id)
    if not isinstance(after, str) or type(limit) is not int or not 1 <= limit <= 100:
        _fail("invalid_input", "Use a note cursor and a limit of 1-100")
    if after:
        _uuid(after)
    with _review() as service:
        preview = service.preview("archived_draft", origin_id)
        if service._resume_adapter(preview).ORIGIN != "archived_note_resume":
            _fail("invalid_input", "Select a historical note draft")
        return _output(service.resume_targets(preview, after=after, limit=limit))


def open_note(origin_id: str, target_id: str, operation_id: str):
    _origin(origin_id)
    _uuid(target_id)
    arguments = dict(origin_id=origin_id, target_id=target_id, operation_id=operation_id)

    def prepare(service, fingerprint):
        from paper_daily.archived_note_resume import ORIGIN

        preview = service.resume_draft(service.preview("archived_draft", origin_id), target_id)
        if preview.data["origin"] != ORIGIN:
            _fail("invalid_input", "Select a historical note draft")
        identity = str(uuid5(NAMESPACE_URL, "paperfact:local-note-review:" + fingerprint))
        return preview, preview.data["retained"]["body"], identity, None

    return _private("review.notes.open", arguments, prepare)


def read_note(draft_id: str):
    with _review() as service:
        loaded = _draft(service, draft_id)
        data = loaded["preview"].data
        current = dict(data["current"])
        if current["anchor"] is not None:
            current["anchor"] = json.loads(current["anchor"])
        choice = data["expected"].get("source_choice")
        return _output(
            dict(
                draft_id=draft_id,
                revision=loaded["revision"],
                state=loaded["state"],
                target=data["target"],
                current={
                    key: current[key] for key in ("body", "kind", "created_at", "page", "anchor")
                },
                retained={**data["retained"], "body": loaded["body"]},
                source_document_hash=data["source_hash"],
                recorded_source=choice["recorded_source"] if choice else data["source_hash"],
                can_apply=False,
                position_evidence=(
                    "reviewed_passage"
                    if isinstance(data["retained"]["anchor"], dict)
                    and "selection" in data["retained"]["anchor"]
                    else "legacy_position_unconfirmed"
                    if data["retained"]["page"] is not None
                    or data["retained"]["anchor"] is not None
                    else "unpositioned"
                ),
            )
        )


def sources(draft_id: str, revision: int):
    with _review() as service:
        loaded = _draft(service, draft_id, revision)
        from paper_daily import note_source_mapping

        note_source_mapping._base(service, loaded["preview"])
        items = service.note_source_references(loaded["preview"])
        return dict(
            items=[
                dict(
                    reference={key: item[key] for key in ("kind", "document_hash")},
                    availability=item["availability"],
                )
                for item in items
            ],
            note="Declared intents only; page inspection checks current owned bytes",
        )


def page(
    draft_id: str, revision: int, source: dict, page_index: int, offset: int = 0, limit: int = 500
):
    if (
        type(page_index) is not int
        or page_index < 0
        or type(offset) is not int
        or offset < 0
        or type(limit) is not int
        or not 1 <= limit <= 500
    ):
        _fail("invalid_input", "Use a zero-based page/offset and a limit of 1-500 words")
    source = _source(source)
    with _review() as service:
        loaded = _draft(service, draft_id, revision)
        inspected = service.inspect_note_source_reference(loaded["preview"], source)
        value = service.note_source_page(loaded["preview"], inspected, page_index)
        total = len(value["words"])
        return _output(
            dict(
                source=source,
                page_index=page_index,
                page_count=inspected.pages,
                words=value["words"][offset : offset + limit],
                total=total,
                next_offset=offset + limit if offset + limit < total else None,
            )
        )


def map_source(draft_id: str, revision: int, source: dict, anchor: dict, operation_id: str):
    source, anchor = _source(source), _anchor(anchor)
    _uuid(draft_id)
    _revision(revision)
    arguments = dict(
        draft_id=draft_id,
        revision=revision,
        source=source,
        anchor=anchor,
        operation_id=operation_id,
    )

    def prepare(service, _fingerprint):
        loaded = _draft(service, draft_id, revision)
        inspected = service.inspect_note_source_reference(loaded["preview"], source)
        chosen = service.choose_note_source(loaded["preview"], inspected, anchor)
        return chosen, loaded["body"], draft_id, revision

    return _private("review.notes.map", arguments, prepare)


def clear(draft_id: str, revision: int, operation_id: str):
    _uuid(draft_id)
    _revision(revision)
    arguments = dict(draft_id=draft_id, revision=revision, operation_id=operation_id)

    def prepare(service, _fingerprint):
        loaded = _draft(service, draft_id, revision)
        return service.clear_note_position(loaded["preview"]), loaded["body"], draft_id, revision

    return _private("review.notes.clear", arguments, prepare)


def save(draft_id: str, revision: int, body: str, operation_id: str):
    _uuid(draft_id)
    _revision(revision)
    _body(body)
    arguments = dict(draft_id=draft_id, revision=revision, body=body, operation_id=operation_id)

    def prepare(service, _fingerprint):
        loaded = _draft(service, draft_id, revision)
        return loaded["preview"], body, draft_id, revision

    return _private("review.notes.save", arguments, prepare)


def decide(
    draft_id: str, revision: int, operation_id: str, decision: str = "apply", confirm: bool = False
):
    from paper_daily.research_review import digest
    from paper_daily.research_review_drafts import DraftStore

    _uuid(draft_id)
    _revision(revision)
    _operation(operation_id)
    if (
        not isinstance(decision, str)
        or decision not in {"apply", "keep"}
        or type(confirm) is not bool
    ):
        _fail("invalid_input", "Choose apply or keep, with an explicit boolean confirmation")
    if decision == "apply" and confirm is not True:
        _fail("confirmation_required", "Inspect the saved note and source before confirming Apply")
    arguments = dict(
        draft_id=draft_id,
        revision=revision,
        operation_id=operation_id,
        decision=decision,
        confirm=confirm,
    )
    with _review() as service:
        fingerprint = _fingerprint(service, "review.notes.decide", arguments)
        with closing(service._connect()) as conn:
            prior = _prior(service, conn, operation_id, fingerprint)
        if prior is not None:
            return prior
        loaded = _draft(service, draft_id, revision)
        preview = (
            service.verify_resumed_draft(loaded["preview"])
            if decision == "apply"
            else loaded["preview"]
        )
        request_id = "local-note:" + digest(operation_id)

        def complete(conn, outcome):
            _check_revision(service, conn, draft_id, revision)
            saved = DraftStore(service).save_in(
                conn, preview, loaded["body"], request_id, draft_id=draft_id, revision=revision
            )
            result = dict(
                operation_id=operation_id, status="decided", decision=outcome["decision"], **saved
            )
            _receipt(service, conn, operation_id, fingerprint, result)

        service.decide(
            preview,
            keep=decision == "keep",
            body=loaded["body"],
            request_id=request_id,
            confirm_target=confirm,
            _note_receipt=complete,
        )
        with closing(service._connect()) as conn:
            result = _prior(service, conn, operation_id, fingerprint)
        if result is None:
            _fail("review_unavailable", "Decision needs receipt recovery; retain this operation_id")
        return result


OPERATIONS = {
    "review.notes.list": list_notes,
    "review.notes.targets": targets,
    "review.notes.open": open_note,
    "review.notes.read": read_note,
    "review.notes.sources": sources,
    "review.notes.page": page,
    "review.notes.map": map_source,
    "review.notes.clear": clear,
    "review.notes.save": save,
    "review.notes.decide": decide,
}
