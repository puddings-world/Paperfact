"""Restartable structured highlight review; only IDs, revisions and proposals cross transports."""

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
    private,
    source_guard,
)


def _origin(value):
    from paper_daily.highlight_draft_resume import _reference

    try:
        return _reference(value)
    except (ValueError, TypeError):
        _fail("invalid_input", "Use a retained highlight origin_id from review.highlights.list")


def _target(value):
    if not isinstance(value, str) or not value or len(value) > 4096 or "\0" in value:
        _fail("invalid_input", "Use the exact current paper ID from review.highlights.targets")


def _page_size(value):
    if type(value) is not int or not 1 <= value <= 100:
        _fail("invalid_input", "Use a page size from 1 to 100")


def _encoded(value):
    from paper_daily.highlight_draft_revision import MAX_BYTES
    from paper_daily.research_review import encode

    try:
        if not isinstance(value, dict):
            raise ValueError
        raw = encode(value)
        if len(raw.encode("utf-8")) > MAX_BYTES:
            raise ValueError
        return raw
    except (ValueError, TypeError, UnicodeError, RecursionError):
        _fail(
            "invalid_input", "Use a bounded structured highlight draft returned by read or inspect"
        )


def _scientific(service, origin_id, conn=None):
    from paper_daily import highlight_draft_resume

    origin, identity = _origin(origin_id)
    if conn is None:
        with closing(service._connect()) as connection:
            return _scientific(service, origin_id, connection)
    row = service._record(conn, origin, identity)
    baseline, original, body = highlight_draft_resume._scientific(conn, origin, identity, row)
    service._check(conn)
    return baseline, original, body


def _science(row):
    from paper_daily.annotation_content import decode

    return decode("highlight_analysis", row["body_json"]) if row is not None else None


def _draft(service, draft_id, revision=None):
    _uuid(draft_id)
    if revision is not None:
        _revision(revision)
    with closing(service._connect()) as conn:
        if not conn.execute(
            "SELECT 1 FROM sqlite_master WHERE name='research_review_drafts'"
        ).fetchone():
            _fail("not_found", "Saved highlight draft not found")
        row = conn.execute(
            "SELECT origin,origin_id FROM research_review_drafts WHERE draft_id=?", (draft_id,)
        ).fetchone()
    if row is None or row[0] != "highlight_resume":
        _fail("not_found", "Saved highlight draft not found")
    loaded = service.load_highlight_draft(row[1], draft_id=draft_id)
    if loaded is None or loaded.get("preview") is None or loaded["state"] in {"foreign", "corrupt"}:
        _fail("review_unavailable", "Draft needs recovery in the app; retain your edited proposal")
    if revision is not None and loaded["revision"] != revision:
        _fail("conflict", "Draft revision changed; read it again and retain your text")
    return loaded


def list_highlights(after: dict | None = None, limit: int = 30):
    from paper_daily.research_review import TABLES

    _page_size(limit)
    cursor = ("", "")
    if after is not None:
        if (
            not isinstance(after, dict)
            or set(after) != {"origin", "id"}
            or not isinstance(after["origin"], str)
            or after["origin"] not in {*TABLES, "sidecar", "archived_draft"}
            or not isinstance(after["id"], str)
            or len(after["id"]) > 256
        ):
            _fail("invalid_input", "Use the exact next cursor from the previous highlight page")
        cursor = after["origin"], after["id"]
    items = []
    with _review() as service, closing(service._connect()) as conn:
        next_cursor = None
        for _ in range(5):
            page = service.page(after=cursor, limit=100)
            for index, item in enumerate(page["items"]):
                cursor = item["origin"], item["id"]
                origin, identity = cursor
                if origin not in {"generation", "sidecar", "remote", "archived_draft"}:
                    continue
                reference = identity if origin == "archived_draft" else origin + ":" + identity
                try:
                    _scientific(service, reference, conn)
                except ValueError:
                    continue
                items.append(
                    dict(
                        origin_id=reference,
                        summary=item.get("summary") or "Retained highlight draft",
                    )
                )
                if len(items) == limit:
                    more = index + 1 < len(page["items"]) or page["next"] is not None
                    return _output(
                        dict(
                            items=items,
                            next=dict(origin=cursor[0], id=cursor[1]) if more else None,
                            editable=not service.recovery and service.binding is not None,
                        )
                    )
            if page["next"] is None:
                next_cursor = None
                break
            cursor = tuple(page["next"])
            next_cursor = dict(origin=cursor[0], id=cursor[1])
        service._check(conn)
        return _output(
            dict(
                items=items,
                next=next_cursor,
                editable=not service.recovery and service.binding is not None,
            )
        )


def inspect_origin(origin_id: str):
    from paper_daily import highlight_draft_revision

    _origin(origin_id)
    with _review() as service:
        baseline, original, raw = _scientific(service, origin_id)
        proposal = (
            highlight_draft_revision.parse(baseline, raw)
            if raw is not None
            else highlight_draft_revision.editable(baseline)
        )
        return _output(
            dict(
                origin_id=origin_id,
                draft=proposal,
                baseline=_science(baseline),
                original=_science(original),
                source_document_hash=baseline["document_hash"],
                can_apply=False,
                fresh_source_checked=False,
                editable=not service.recovery and service.binding is not None,
            )
        )


def targets(origin_id: str, after: str = "", limit: int = 30):
    _origin(origin_id)
    _page_size(limit)
    if not isinstance(after, str) or len(after) > 4096:
        _fail("invalid_input", "Use the exact next paper cursor")
    with _review() as service:
        origin, identity = _origin(origin_id)
        return _output(
            service.highlight_draft_targets(
                service.preview(origin, identity), after=after, limit=limit
            )
        )


def open_highlight(origin_id: str, target_id: str, operation_id: str, draft: dict | None = None):
    _origin(origin_id)
    _target(target_id)
    _operation(operation_id)
    raw = _encoded(draft) if draft is not None else None
    arguments = dict(
        origin_id=origin_id, target_id=target_id, operation_id=operation_id, draft=draft
    )

    def prepare(service, fingerprint):
        origin, identity = _origin(origin_id)
        preview, body = service.select_highlight_draft(
            service.preview(origin, identity), target_id, body=raw
        )
        key = str(uuid5(NAMESPACE_URL, "paperfact:local-highlight-review:" + fingerprint))
        return preview, body, key, None

    return private(
        "review.highlights.open", arguments, prepare, _review_factory=_review, _receipt_fn=_receipt
    )


def read_highlight(draft_id: str):
    from paper_daily import highlight_draft_revision

    with _review() as service:
        loaded = _draft(service, draft_id)
        data = loaded["preview"].data
        return _output(
            dict(
                draft_id=draft_id,
                revision=loaded["revision"],
                state=loaded["state"],
                target=data["target"],
                draft=highlight_draft_revision.parse(data["retained"], loaded["body"]),
                target_at_review=_science(data["current"]),
                baseline=_science(data["retained"]),
                source_document_hash=data["source_hash"],
                can_apply=False,
                fresh_source_checked=False,
            )
        )


def save(draft_id: str, revision: int, draft: dict, operation_id: str):
    from paper_daily import highlight_draft_revision

    _uuid(draft_id)
    _revision(revision)
    raw = _encoded(draft)
    arguments = dict(draft_id=draft_id, revision=revision, draft=draft, operation_id=operation_id)

    def prepare(service, _fingerprint):
        loaded = _draft(service, draft_id, revision)
        try:
            highlight_draft_revision.parse(loaded["preview"].data["retained"], raw)
        except ValueError:
            _fail(
                "invalid_input",
                "Edited highlight fields must match the original draft source and bounds",
            )
        return loaded["preview"], raw, draft_id, revision

    return private(
        "review.highlights.save", arguments, prepare, _review_factory=_review, _receipt_fn=_receipt
    )


def _verified(service, draft_id, revision):
    loaded = _draft(service, draft_id, revision)
    ready = service.verify_highlight_draft(loaded["preview"], loaded["body"])
    with closing(service._connect()) as conn:
        _check_revision(service, conn, draft_id, revision)
    return loaded, ready


def verify(draft_id: str, revision: int):
    with _review() as service, source_guard(service):
        _loaded, ready = _verified(service, draft_id, revision)
        return _output(
            dict(
                draft_id=draft_id,
                revision=revision,
                report=service.highlight_draft_report(ready),
                source_document_hash=ready.data["source_hash"],
                can_apply=False,
                fresh_source_checked=True,
                note="Original/locations inspected, not semantic support. Apply verifies again.",
            )
        )


def page(draft_id: str, revision: int, page_index: int, offset: int = 0, limit: int = 500):
    if (
        type(page_index) is not int
        or page_index < 0
        or type(offset) is not int
        or offset < 0
        or type(limit) is not int
        or not 1 <= limit <= 500
    ):
        _fail("invalid_input", "Use a zero-based page/offset and a word limit from 1 to 500")
    import pymupdf

    from paper_daily import highlight_draft_originals
    from paper_daily.pdf_selection_text import level_words

    with _review() as service, source_guard(service):
        loaded = _draft(service, draft_id, revision)
        preview = loaded["preview"]
        # Reading can help repair missing quotes; it never needs a complete mark plan.
        proof = highlight_draft_originals.prepare(
            service, preview, preview.data["source_hash"], reference=(draft_id, revision)
        )
        if page_index >= proof.pages:
            _fail("invalid_input", "Page is outside this draft's inspected original")
        with pymupdf.open(stream=proof.data, filetype="pdf") as document:
            words = [
                dict(order=index, text=word[4]) for index, word in level_words(document[page_index])
            ]
        if (
            len(words) > 100000
            or sum(len(word["text"].encode("utf-8")) for word in words) > 1024 * 1024
        ):
            _fail("result_too_large", "This page exceeds the word inspection limit")
        highlight_draft_originals.revalidate(proof)
        with closing(service._connect()) as conn:
            _check_revision(service, conn, draft_id, revision)
        return _output(
            dict(
                source_document_hash=proof.document_hash,
                page_index=page_index,
                page_count=proof.pages,
                fresh_source_checked=True,
                words=words[offset : offset + limit],
                total=len(words),
                next_offset=offset + limit if offset + limit < len(words) else None,
            )
        )


def apply(
    draft_id: str,
    revision: int,
    operation_id: str,
    confirm: bool = False,
    restore_deleted: bool = False,
):
    _uuid(draft_id)
    _revision(revision)
    _operation(operation_id)
    if type(confirm) is not bool or type(restore_deleted) is not bool:
        _fail("invalid_input", "Confirmation and restoration must be explicit booleans")
    if not confirm:
        _fail(
            "confirmation_required",
            "Inspect the highlight draft and original before confirming Apply",
        )
    arguments = dict(
        draft_id=draft_id,
        revision=revision,
        operation_id=operation_id,
        confirm=confirm,
        restore_deleted=restore_deleted,
    )
    with _review() as service:
        fingerprint = _fingerprint(service, "review.highlights.apply", arguments)
        with closing(service._connect()) as conn:
            prior = _prior(service, conn, operation_id, fingerprint)
        if prior is not None:
            return prior
        with source_guard(service):
            # A peer request may have committed while this one waited for the OS lock.
            with closing(service._connect()) as conn:
                prior = _prior(service, conn, operation_id, fingerprint)
            if prior is not None:
                return prior
            try:
                loaded, ready = _verified(service, draft_id, revision)
            except (ValueError, OSError):
                with closing(service._connect()) as conn:
                    prior = _prior(service, conn, operation_id, fingerprint)
                if prior is not None:
                    return prior
                raise
            request_id = str(
                uuid5(NAMESPACE_URL, "paperfact:local-highlight-decision:" + fingerprint)
            )

            def complete(conn, outcome):
                prior = _prior(service, conn, operation_id, fingerprint)
                if prior is not None:
                    return
                # The shared highlight transaction already CAS-saved these exact words.
                _check_revision(service, conn, draft_id, revision + 1)
                saved = dict(draft_id=draft_id, revision=revision + 1)
                result = dict(
                    operation_id=operation_id,
                    status="applied",
                    decision=outcome["decision"],
                    **saved,
                )
                _receipt(service, conn, operation_id, fingerprint, result)

            service.apply_highlight_draft(
                ready,
                loaded["body"],
                request_id=request_id,
                confirm_target=True,
                restore_deleted=restore_deleted,
                draft_id=draft_id,
                revision=revision,
                _operation_receipt=complete,
            )
            with closing(service._connect()) as conn:
                result = _prior(service, conn, operation_id, fingerprint)
            if result is None:
                _fail("review_unavailable", "Decision needs receipt recovery; retain operation_id")
            return result


OPERATIONS = {
    "review.highlights.list": list_highlights,
    "review.highlights.inspect": inspect_origin,
    "review.highlights.targets": targets,
    "review.highlights.open": open_highlight,
    "review.highlights.read": read_highlight,
    "review.highlights.save": save,
    "review.highlights.verify": verify,
    "review.highlights.page": page,
    "review.highlights.apply": apply,
}
