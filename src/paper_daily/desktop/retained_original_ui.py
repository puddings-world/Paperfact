"""Original-version controls for retained slide review; no primary replacement."""

from __future__ import annotations

import threading

from PySide6.QtCore import QObject, QTimer
from PySide6.QtWidgets import QComboBox, QHBoxLayout, QPushButton, QWidget

TEXT = {
    "en": {
        "open": "Open retained original",
        "checking": "Verifying retained original…",
        "opened": "Retained original opened read-only; the current PDF is unchanged.",
        "failed": "Retained original unavailable. Check retained files or refresh, then retry.",
        "version": "Original",
        "verify_first": "First: {action}",
        "verify_help": "Verify the restored slides first; this does not apply or replace a deck.",
        "draft_help": (
            "Verify the draft sources first; opening the original does not apply any edits."
        ),
        "changed": "The retained source changed; refresh before opening.",
    },
    "zh-TW": {
        "open": "開啟保留原文",
        "checking": "正在驗證保留原文…",
        "opened": "已開啟唯讀保留原文；目前閱讀的 PDF 維持原樣。",
        "failed": "無法開啟保留原文；請檢查檔案或重新核對後重試。",
        "version": "原文版本",
        "verify_first": "請先{action}",
        "verify_help": "先核對還原的簡報，之後即可唯讀開啟原文；核對不會自動套用簡報。",
        "draft_help": "請先核對草稿原文；開啟原文不會套用編輯。",
        "changed": "保留來源已變更，請重新核對後開啟。",
    },
}


class RetainedOriginalControl(QObject):
    def __init__(self, owner, language, *, claim_reader=False, highlight_reader=False):
        super().__init__(owner)
        self.owner, self.language = owner, language
        if claim_reader and highlight_reader:
            raise ValueError("Select exactly one typed independent original reader")
        self.claim_reader, self.highlight_reader = claim_reader, highlight_reader
        self.t = TEXT.get(language, TEXT["en"])
        self.widget = QWidget(owner)
        layout = QHBoxLayout(self.widget)
        layout.setContentsMargins(0, 0, 0, 0)
        self.versions = QComboBox()
        self.versions.setAccessibleName(self.t["version"])
        self.versions.setSizeAdjustPolicy(
            QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon
        )
        self.versions.setMinimumContentsLength(18)
        self.button = QPushButton(self.t["open"])
        self.button.setAutoDefault(False)
        self.button.clicked.connect(self.open)
        layout.addWidget(self.versions, 1)
        layout.addWidget(self.button)
        self.widget.hide()
        self.viewer = None
        self.opening = False
        self.cancelled = threading.Event()
        self.future = None
        self._closing_result = None

    def invalidate(self):
        self.cancelled.set()
        if self.future is not None:
            self.future.cancel()
        self.opening = False
        self.widget.hide()
        if self.viewer is not None and not self.viewer.disposed:
            self.viewer.close()

    def display(self, data):
        self.invalidate()
        self.versions.clear()
        if data.get("origin") in {
            "archived_resume",
            "archived_note_resume",
            "claim_resume",
            "highlight_resume",
        }:
            if data.get("source_hash"):
                self.versions.addItem(
                    self.t["version"] + " " + data["source_hash"][:12], data["source_hash"]
                )
            self.widget.setVisible(self.versions.count() > 0)
            self.controls()
            return
        if data.get("origin") not in {"local_deck", "enrolled_deck"}:
            return
        for item in data.get("original_manifest", []):
            sha = item["sha256"]
            label = self.t["version"] + " " + sha[:12] + f" · {item['size'] / 1024**2:.2f} MB"
            self.versions.addItem(label, sha)
        selected = self.versions.findData(data.get("source_hash"))
        if selected >= 0:
            self.versions.setCurrentIndex(selected)
        self.widget.setVisible(self.versions.count() > 0)
        self.controls()

    def _needs_verification(self):
        from paper_daily.proposal_recovery_review import virtual

        preview = self.owner.preview
        if preview is not None and (
            (self.claim_reader and preview.data.get("origin") == "claim_resume")
            or (self.highlight_reader and preview.data.get("origin") == "highlight_resume")
        ):
            return False
        if preview is not None and preview.data.get("origin") in {
            "archived_resume",
            "archived_note_resume",
            "claim_resume",
            "highlight_resume",
        }:
            return not preview.data["apply"] or preview.data.get("resume_state") != "ready"
        return preview is not None and virtual(preview.data.get("id"))

    def controls(self):
        archived = self._needs_verification()
        draft = self.owner.preview is not None and self.owner.preview.data.get("origin") in {
            "archived_resume",
            "archived_note_resume",
            "claim_resume",
            "highlight_resume",
        }
        action = self.owner.words["verify_draft" if draft else "verify_slides"]
        help_text = self.t["draft_help" if draft else "verify_help"]
        self.button.setText(
            self.t["verify_first"].format(action=action) if archived else self.t["open"]
        )
        self.button.setToolTip(help_text if archived else "")
        ready = (
            self.owner.preview is not None
            and not self.owner.disposed
            and not self.owner.busy
            and not archived
        )
        self.button.setEnabled(ready and self.versions.count() > 0 and not self.opening)
        self.versions.setEnabled(ready and not self.opening)
        activity = getattr(self.owner, "_original_activity", None)
        if activity is not None:
            activity(self.opening)

    def open(self):
        owner = self.owner
        if owner.disposed or owner.busy or self.opening or owner.preview is None:
            return False
        if self._needs_verification():
            draft = owner.preview.data.get("origin") in {
                "archived_resume",
                "archived_note_resume",
                "claim_resume",
                "highlight_resume",
            }
            owner.status.setText(self.t["draft_help" if draft else "verify_help"])
            return False
        selected = self.versions.currentData()
        if not selected:
            return False
        from paper_daily.desktop import original_version

        if self.viewer is not None and not self.viewer.disposed:
            if (
                getattr(self.viewer.snapshot, "highlight_read_proof", None) is not None
                and original_version.highlight_read_status(self.viewer.snapshot) == "recheck"
            ):
                self.viewer.check()
                return False
            if (
                getattr(self.viewer.snapshot, "claim_read_proof", None) is not None
                and original_version.claim_read_status(self.viewer.snapshot) == "recheck"
            ):
                self.viewer.check()
                return False
            if (
                getattr(self.viewer.snapshot, "draft_proof", None) is not None
                and original_version.draft_status(self.viewer.snapshot) == "recheck"
            ):
                self.viewer.check()
                return False
            if (
                self.viewer._closing
                or not self.viewer.current()
                or not original_version.metadata_current(self.viewer.snapshot)
            ):
                self.viewer.close()
                owner.status.setText(self.t["changed"])
                return False
            if self.viewer.snapshot and self.viewer.snapshot.document_hash == selected:
                self.viewer.show()
                self.viewer.raise_()
            else:
                self.viewer.close()
            return False

        # A pending private autosave is our own write, not changed research.
        # Flush it before capturing the original's database/source fence.
        claim_read = (
            self.claim_reader
            and owner.preview.data.get("origin") == "claim_resume"
            and not owner.verified
        )
        highlight_read = (
            self.highlight_reader and owner.preview.data.get("origin") == "highlight_resume"
        )
        # Independent reads use immutable source scope, including unsaved manual text.
        if not (claim_read or highlight_read) and not owner._save_pending(all_items=True):
            return False
        expected, generation = owner.preview, owner.generation
        cancelled = threading.Event()
        self.cancelled = cancelled
        self.opening = True
        self.controls()
        owner.status.setText(self.t["checking"])

        def current():
            return bool(
                not cancelled.is_set()
                and not owner.disposed
                and owner.generation == generation
                and owner.preview is not None
                and owner.preview.serialized == expected.serialized
            )

        def prepare():
            try:
                if highlight_read:
                    return original_version.prepare_highlight_draft_read(
                        owner.service, expected, selected, cancelled=cancelled.is_set
                    )
                if claim_read:
                    return original_version.prepare_claim_draft_read(
                        owner.service, expected, selected, cancelled=cancelled.is_set
                    )
                if expected.data.get("origin") in {
                    "archived_resume",
                    "archived_note_resume",
                    "claim_resume",
                    "highlight_resume",
                }:
                    return original_version.prepare_resumed_draft(
                        owner.service, expected, selected, cancelled=cancelled.is_set
                    )
                return original_version.prepare_retained(
                    owner.service,
                    expected,
                    selected,
                    cancelled=cancelled.is_set,
                )
            except (OSError, ValueError, RuntimeError):
                return None

        def received(snapshot):
            if self.cancelled is cancelled:
                self.opening = False
                self.controls()
            if not current():
                return
            if snapshot is None:
                owner.status.setText(self.t["failed"])
                return
            from paper_daily.desktop.main import palette

            owner.pal = dict(getattr(owner.parent(), "pal", None) or palette())
            try:
                viewer = original_version.OriginalVersionDialog(
                    snapshot,
                    owner,
                    current=current,
                    language=self.language,
                )
            except (OSError, ValueError, RuntimeError):
                owner.status.setText(self.t["changed"])
                return
            self.viewer = viewer
            viewer.closed.connect(self._closed)
            viewer.invalidated.connect(
                lambda: owner.status.setText(self.t["changed"]) if current() else None
            )
            viewer.show()
            owner.status.setText(self.t["opened"])

        owner._submit("original", prepare, received)
        self.future = owner.jobs[-1][0]
        return True

    def _closed(self):
        viewer = self.sender()
        if self.viewer is viewer:
            self.viewer = None
        viewer.deleteLater()
        if self._closing_result is not None and not self.owner.disposed:
            result, self._closing_result = self._closing_result, None
            QTimer.singleShot(0, lambda: self.owner.done(result))

    def request_close(self, result):
        self.cancelled.set()
        if self.future is not None:
            self.future.cancel()
        if self.viewer is not None and not self.viewer.disposed:
            # Apply saved all drafts before becoming busy. Retire its authority
            # now; waiting for a read-only renderer must not let a held writer
            # publish after the user has requested this review to close.
            if self.owner.busy:
                self.owner.service.close()
            self._closing_result = result
            self.viewer.close()
            if self.viewer is not None and not self.viewer.disposed:
                return False
        return True
