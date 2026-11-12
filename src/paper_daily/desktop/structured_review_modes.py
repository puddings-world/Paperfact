"""Explicit typed content adapters for the shared native draft lifecycle."""

import hashlib

from paper_daily import claim_draft_revision, highlight_draft_revision
from paper_daily.desktop.claim_fields import ClaimFields
from paper_daily.desktop.claim_fields import readable as claim_readable
from paper_daily.desktop.highlight_fields import HighlightFields
from paper_daily.desktop.highlight_fields import readable as highlight_readable
from paper_daily.research_review import encode
from paper_daily.research_review_drafts import SNAPSHOT


class ClaimMode:
    domain = "claim_resume"
    reader_options = dict(claim_reader=True)
    fields = ClaimFields
    readable = staticmethod(claim_readable)
    restore_invalidates = True

    def targets(self, service, preview, **options):
        return service.claim_draft_targets(preview, **options)

    def select(self, service, preview, target, **options):
        return service.select_claim_draft(preview, target, **options)

    def load(self, service, identity, **options):
        return service.load_claim_draft(identity, **options)

    def save(self, service, preview, body, request, **options):
        return service.save_claim_draft(preview, body, request, **options)

    def parse(self, data, body):
        return claim_draft_revision.parse(data["retained"]["body_json"], body)

    def remote(self, data):
        return data["expected"]["version"] == 2

    def restoration(self, data, draft, report=None):
        token = data["expected"]["observation"]
        return token["incarnation"] is not None and not token["active"]

    def verify(self, service, preview, body, restoring, cancelled):
        ready = service.verify_claim_draft(
            preview, body, restore_deleted=restoring, cancelled=cancelled
        )
        return ready, service.claim_draft_report(ready)

    def checked(self, fields, report):
        return True

    def allow_apply(self, dialog):
        return True

    def apply(self, service, preview, body, request, persisted, restoring, cancelled):
        return service.apply_claim_draft(preview, body, request_id=request, confirm_target=True)

    def after_apply(self, result, persisted):
        return persisted

    def summary(self, fields):
        return fields.assertion.toPlainText()[:240]

    def copy(self, fields):
        lines = []
        for claim in fields.draft()["claims"]:
            lines.extend([claim["text"], claim["judgment"]["reason"]])
            lines.extend(item["quote"] for item in claim["passages"])
        return "\n\n".join(lines)


class HighlightMode:
    domain = "highlight_resume"
    reader_options = dict(highlight_reader=True)
    fields = HighlightFields
    readable = staticmethod(highlight_readable)
    restore_invalidates = False

    def targets(self, service, preview, **options):
        return service.highlight_draft_targets(preview, **options)

    def select(self, service, preview, target, **options):
        return service.select_highlight_draft(preview, target, **options)

    def load(self, service, identity, **options):
        return service.load_highlight_draft(identity, **options)

    def save(self, service, preview, body, request, **options):
        return service.save_highlight_draft(preview, body, request, **options)

    def parse(self, data, body):
        return highlight_draft_revision.parse(data["retained"], body)

    def remote(self, data):
        return data["expected"]["conflict"] is not None

    def restoration(self, data, draft, report=None):
        expected = data["expected"]
        token = expected["observation"]
        if (token["incarnation"] is not None and not token["active"]) or (
            expected["current"] is None and expected["highlights"]["known"]
        ):
            return True
        keys = (
            [mark["source_key"] for mark in report["marks"]]
            if report and report["all_quotes_located"]
            else [
                hashlib.sha256(f"{item['page']}:{item['text']}".encode()).hexdigest()
                for item in draft["items"]
                if item["page"] is not None
            ]
        )
        return any(
            (observed := expected["highlights"]["tokens"].get(data["source_hash"] + ":" + key))
            and observed["incarnation"] is not None
            and not observed["active"]
            for key in keys
        )

    def verify(self, service, preview, body, restoring, cancelled):
        ready = service.verify_highlight_draft(preview, body, cancelled=cancelled)
        return ready, service.highlight_draft_report(ready)

    def checked(self, fields, report):
        fields.set_report(report)
        return report["all_quotes_located"]

    def allow_apply(self, dialog):
        return dialog.restore.isHidden() or dialog.restore.isChecked()

    def apply(self, service, preview, body, request, persisted, restoring, cancelled):
        private = dict(persisted)
        snapshot = encode({key: preview.data[key] for key in SNAPSHOT})

        def receipt(conn, result):
            saved = conn.execute(
                "SELECT body,request_id,preview_json,revision "
                "FROM research_review_drafts WHERE draft_id=?",
                (persisted["draft_id"],),
            ).fetchone()
            # Return the CAS from this exact commit, not a new read after committing.
            # An accepted retry after someone else's private edit must keep the old
            # observation, so later typing cannot silently replace that newer draft.
            if saved is not None and tuple(saved[:3]) == (body, request, snapshot):
                private["revision"] = saved[3]

        result = service.apply_highlight_draft(
            preview,
            body,
            request_id=request,
            confirm_target=True,
            restore_deleted=restoring,
            cancelled=cancelled,
            _operation_receipt=receipt,
            **persisted,
        )
        return result, private

    def after_apply(self, result, persisted):
        return result[1]

    def summary(self, fields):
        return fields.quote.toPlainText()[:240]

    def copy(self, fields):
        return "\n\n".join(item["text"] + "\n" + item["reason"] for item in fields.draft()["items"])
