"""Bounded saved SQL annotation adapters; input digests never identify a PDF."""

from __future__ import annotations

import json

from paper_daily import annotation_content, claim_content, research_audit

LINK_STATES = {"matched", "analysis_missing", "analysis_changed", "source_changed", "quote_missing"}


def _item(identity, feature, text, row, *, passages=(), related=None, state=None):
    return dict(
        id=identity,
        feature=feature,
        text=text,
        document_hash=row.get("document_hash"),
        passages=list(passages),
        reference=None,
        provenance=dict(
            record_hash=claim_content.hashed(row),
            input_hash=row.get("source_hash"),
            related_record_hash=claim_content.hashed(related) if related else None,
            link_state=state,
        ),
    )


def _passage(quote, row, page):
    return dict(quote=quote, document_hash=row["document_hash"], page=page, anchor=None)


def annotation_items(feature, row, *, related=None):
    """Use closed saved content, not cache paths or the currently loaded document."""
    try:
        annotation_content.validate_row(feature, row)
        body = annotation_content.decode(feature, row["body_json"])
        if feature == "research_questions":
            return [
                _item(
                    "research_questions:" + str(index),
                    feature,
                    entry["question"] + "\n\n" + entry["why"],
                    row,
                    passages=[_passage(entry["evidence"], row, entry["page"])],
                )
                for index, entry in enumerate(body["items"])
            ]
        if feature != "reading_links":
            raise ValueError("Unsupported saved audit annotation")
        analysis = None
        state = "analysis_missing"
        if related is not None:
            if related["paper_id"] != row["paper_id"]:
                raise ValueError("Linked highlights have another owner")
            annotation_content.validate_row("highlight_analysis", related)
            analysis = annotation_content.decode("highlight_analysis", related["body_json"])
            state = (
                "analysis_changed"
                if body["analysis_hash"] != related["source_hash"]
                else "source_changed"
                if row["document_hash"] != related["document_hash"]
                else "matched"
            )
        items = []
        for index, link in enumerate(body["links"]):
            linked = state
            if linked == "matched" and link["quote"] >= len(analysis["items"]):
                linked = "quote_missing"
            passages = []
            if linked == "matched":
                quote = analysis["items"][link["quote"]]
                passages = [_passage(quote["text"], row, quote["page"])]
            items.append(
                _item(
                    "reading_links:" + str(index),
                    feature,
                    link["explanation"],
                    row,
                    passages=passages,
                    related=related,
                    state=linked,
                )
            )
        return items or [
            _item("reading_links:empty", feature, "", row, related=related, state=state)
        ]
    except (ValueError, TypeError, KeyError, RecursionError, UnicodeError):
        raise research_audit.AuditError("invalid_saved_content") from None


def context_items(row):
    """This schema records no PDF provenance, including for reading recommendations."""
    from paper_daily.sync_content import _integer, _stamp, _text

    def pairs(values):
        result = {}
        for key, value in values:
            if key in result:
                raise ValueError("Duplicate context field")
            result[key] = value
        return result

    try:
        if set(row) != {"paper_id", "summary", "reading_json", "written_at", "edited"}:
            raise ValueError("Unexpected saved context fields")
        _text(row["paper_id"], 4096, nullable=False, nonempty=True)
        _text(row["summary"], 32 * 1024)
        _stamp(row["written_at"])
        _integer(row["edited"], maximum=1)
        reading = (
            json.loads(row["reading_json"], object_pairs_hook=pairs)
            if row["reading_json"] is not None
            else []
        )
        if not isinstance(reading, list) or len(reading) > 100:
            raise ValueError("Invalid saved recommendations")
        for entry in reading:
            if not isinstance(entry, dict) or set(entry) != {"title", "direction", "why"}:
                raise ValueError("Unexpected recommendation fields")
            for value in entry.values():
                _text(value, 8192, nullable=False)
        return [_item("paper_context:summary", "paper_context", row["summary"] or "", row)] + [
            _item(
                "paper_context:reading:" + str(index),
                "paper_context",
                entry["title"] + "\n" + entry["direction"] + "\n" + entry["why"],
                row,
            )
            for index, entry in enumerate(reading)
        ]
    except (ValueError, TypeError, KeyError, RecursionError, UnicodeError):
        raise research_audit.AuditError("invalid_saved_content") from None
