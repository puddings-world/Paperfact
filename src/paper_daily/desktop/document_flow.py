"""Managed PDF verification off the UI thread, with explicit version activation."""

from __future__ import annotations

import sqlite3

from PySide6.QtCore import QObject, QThread, Slot

MESSAGES = {
    "pages": ("{count} 頁 · {hash}", "{count} pages · {hash}"),
    "checking": ("正在驗證同步原文…", "Verifying synchronized PDF…"),
    "queued": ("正在完成上一份原文驗證，稍後開啟這篇。", "Finishing the previous PDF check…"),
    "missing": ("同步原文尚未下載完成。", "The synchronized PDF is not downloaded yet."),
    "unbound": (
        "原文尚未通過驗證，請完成檔案同步後重試。",
        "Finish file synchronization before opening.",
    ),
    "detached": (
        "這篇已移除原文連結；保留的筆記仍可閱讀。",
        "This paper has no active PDF; notes remain readable.",
    ),
    "invalid": (
        "原文驗證或開啟失敗；既有研究內容仍保留。",
        "PDF verification/opening failed; research is preserved.",
    ),
    "unconfigured": (
        "此工作區尚未設定同步檔案位置。",
        "This workspace has no synchronized file location.",
    ),
    "quota": ("原文閱讀快取空間不足。", "The PDF reader cache has insufficient space."),
    "ambiguous": (
        "舊檔名對應不明，請明確選擇原文。",
        "The legacy filename is ambiguous; select the PDF explicitly.",
    ),
    "stale": (
        "原文版本已更新；請重新檢查最新版本。",
        "The document changed; check the latest version again.",
    ),
    "older": (
        "目前保留已開啟的原文版本；可自行切換最新版本。",
        "Keeping the open version; switch when ready.",
    ),
    "refresh": ("檢查／開啟最新原文", "Check / open latest PDF"),
    "anchor": (
        "這個引用尚未核對到目前 PDF 版本，保留文字但不跳轉。",
        "This reference is not verified for the open PDF; its text is preserved.",
    ),
    "manual_ai": (
        "同步原文不會自動呼叫 AI；可按「分析／補上標註」。",
        "Synchronized PDFs do not start AI automatically; analyze explicitly.",
    ),
}


def message(key, locale="zh-TW"):
    return MESSAGES.get(key, MESSAGES["invalid"])[0 if locale == "zh-TW" else 1]


def managed(paper):
    return bool(getattr(getattr(paper, "_document_status", None), "managed", False))


def _document_context(reader):
    """Refresh metadata from the already-bound DB, never a global/config workspace."""
    paper = getattr(reader, "paper", None)
    resolver = getattr(paper, "_document_reader", None)
    if paper is None or resolver is None:
        return resolver, getattr(paper, "_document_status", None)
    from paper_daily.document_reader import DocumentReader, ResolvedDocument, from_workspace

    try:
        status = resolver.inspect(paper.id)
        if isinstance(resolver, DocumentReader):
            registration = status._context[1] if status._context else None
            if registration != resolver._registered or resolver._closed:
                resolver = from_workspace(
                    resolver.db_path,
                    legacy_root=resolver.legacy_root if registration is None else None,
                )
                paper._document_reader = resolver
                status = resolver.inspect(paper.id)
    except (OSError, ValueError, sqlite3.DatabaseError):
        # A malformed/switched research context must never become legacy fallback.
        status = ResolvedDocument("managed", "invalid", paper.id, reason="context_invalid")
    paper._document_status = status
    return resolver, status


def loaded_document_valid(reader):
    """Authorize local navigation/writes, including a retained verified old version."""
    resolver, status = _document_context(reader)
    if getattr(status, "reason", None) in ("paper_missing", "context_invalid"):
        return False
    active = getattr(reader, "_active_document", None)
    if active is not None and (
        resolver is None or active.local_id != reader.paper.id or not resolver.intact(active)
    ):
        return False
    if status is None or not status.managed:
        return status is None or (status.status not in ("ambiguous", "invalid", "stale"))
    active = getattr(reader, "_active_document", None)
    return bool(
        active is not None
        and resolver is not None
        and active.local_id == reader.paper.id
        and active.sha256 == getattr(reader, "_pdf_fingerprint", None)
        and resolver.intact(active)
    )


def anchor_allowed(reader, source):
    """Legacy anchors retain compatibility; managed coordinates need exact provenance."""
    nested = source.get("anchor") if isinstance(source, dict) else None
    outer_hash = source.get("document_hash") if isinstance(source, dict) else None
    nested_hash = nested.get("document_hash") if isinstance(nested, dict) else None
    if outer_hash is not None and nested_hash is not None and outer_hash != nested_hash:
        return False
    if not loaded_document_valid(reader):
        return False
    claimed = outer_hash if outer_hash is not None else nested_hash
    if not managed(getattr(reader, "paper", None)) and claimed is None:
        return True  # Untagged legacy sources retain compatibility.
    if not isinstance(source, dict):
        return False
    fingerprint = getattr(reader, "_pdf_fingerprint", None)
    return bool(fingerprint and claimed == fingerprint)


class _DocumentWorker(QThread):
    def __init__(self, resolver, paper_id):
        super().__init__()
        self.resolver, self.paper_id = resolver, paper_id
        self.result = None

    def run(self):
        try:
            self.result = self.resolver.resolve(self.paper_id)
        except Exception:
            self.result = None


class DocumentRunner(QObject):
    """One bounded verification job; delivery occurs after its thread has finished."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._thread = None
        self._callback = None
        self._generation = 0

    @property
    def busy(self):
        return self._thread is not None

    def invalidate(self):
        self._generation += 1

    def start(self, resolver, paper_id, callback):
        if self.busy:
            return False
        from paper_daily.desktop.activity import begin

        self._activity = begin(self, message("checking"), key=f"reader-document:{paper_id}")
        if not self._activity.accepted:
            return False
        self._callback = callback
        self._started_generation = self._generation
        self._thread = _DocumentWorker(resolver, paper_id)
        self._thread.finished.connect(self._deliver)
        self._thread.start()
        return True

    @Slot()
    def _deliver(self):
        worker, callback = self._thread, self._callback
        if worker is None:
            return
        self._thread, self._callback = None, None
        self._activity.finish(bool(worker.result and worker.result.available))
        worker.deleteLater()
        if callback and self._generation == self._started_generation:
            callback(worker.paper_id, worker.result)


class ManagedDocumentReader:
    """ReaderPage mixin; it never initiates downloads, URL discovery or AI jobs."""

    def _document_auto_highlights(self, status, blocked):
        if not hasattr(self, "_legacy_highlight_tooltip"):
            self._legacy_highlight_tooltip = self.auto_highlights.toolTip()
        self.auto_highlights.setEnabled(not status.managed and not blocked)
        self.auto_highlights.setToolTip(
            message("manual_ai") if status.managed else self._legacy_highlight_tooltip
        )

    def _clear_document_view(self):
        """Clear only native PDF/coordinate state; never editors or research drafts."""
        self.pdf.unload()
        self.pdf.hide()
        self._active_document = None
        self._pdf_fingerprint = None
        self.paper._loaded_document = None
        self.paper._has_pdf = False
        self.open_external.setEnabled(False)

    def _document_unavailable(self, status):
        self._clear_document_view()
        self.pdf_note.setText(message(status))
        self.pdf_missing.setText(message(status))
        self.pdf_missing.show()
        self.document_refresh.show()
        self.document_refresh.setEnabled(not self.document_runner.busy)

    def _load_managed_document(self, *, force=False):
        resolver, status = _document_context(self)
        if resolver is None:
            return False
        blocked = status.status == "ambiguous" or status.reason in (
            "paper_missing",
            "context_invalid",
        )
        self._document_auto_highlights(status, blocked)
        if blocked:
            self._document_unavailable(status.status)
            return True
        if not status.managed:
            return False
        active = getattr(self, "_active_document", None)
        same_open = (
            active is not None
            and active.local_id == self.paper.id
            and resolver.intact(active)
            and self.pdf.page_count() > 0
        )
        if same_open and not force:
            self.paper._loaded_document = active
            self.paper._has_pdf = True
            if resolver.current(active):
                self.document_refresh.hide()
                return True
            self.pdf_note.setText(message("older"))
            self.document_refresh.show()
            return True
        if not same_open:
            self._clear_document_view()
        self.document_refresh.show()
        started = self.document_runner.start(resolver, self.paper.id, self._document_arrived)
        self.document_refresh.setEnabled(not self.document_runner.busy)
        text = message("checking" if started else "queued")
        self.pdf_note.setText(text)
        if not same_open:
            self.pdf_missing.setText(text)
            self.pdf_missing.show()
        self.highlight_status.setText(message("manual_ai"))
        return True

    def _check_document_update(self):
        """Notify without reloading editors, moving focus or starting any work."""
        if not self.paper:
            return
        resolver, status = _document_context(self)
        if resolver is None:
            return
        blocked = status.status == "ambiguous" or status.reason in (
            "paper_missing",
            "context_invalid",
        )
        self._document_auto_highlights(status, blocked)
        if blocked:
            self._document_unavailable(status.status)
            return
        active = getattr(self, "_active_document", None)
        if not status.managed:
            if active is not None and not resolver.intact(active):
                self._document_unavailable("stale")
            return
        if active is None or active.local_id != self.paper.id or not resolver.intact(active):
            self._document_unavailable("stale")
            return
        if not resolver.current(active):
            self.pdf_note.setText(message("older" if active else "stale"))
            self.document_refresh.show()
            self.document_refresh.setEnabled(not self.document_runner.busy)
        else:
            self.document_refresh.hide()
            self.pdf_note.setText(
                message("pages").format(count=self.pdf.page_count(), hash=active.sha256[:12])
            )

    def _use_latest_document(self):
        if self.paper and not self.document_runner.busy:
            self._load_managed_document(force=True)

    def _document_arrived(self, paper_id, result):
        self.document_refresh.setEnabled(True)
        if not self.paper:
            return
        if self.paper.id != paper_id:
            if managed(self.paper):
                self._load_managed_document()
            return
        resolver, _status = _document_context(self)
        if resolver is None:
            return
        active = getattr(self, "_active_document", None)
        if active is not None and not resolver.intact(active):
            self._clear_document_view()
        if result is None or not result.available or not resolver.current(result):
            status = "invalid" if result is None else result.status
            if result is not None and result.available:
                status = "stale"
            self.pdf_note.setText(message(status))
            self.pdf_missing.setText(message(status))
            if getattr(self, "_active_document", None) is None:
                self.pdf_missing.show()
            return
        if not self.pdf.load(result.path):
            self.pdf_note.setText(message("invalid"))
            active = getattr(self, "_active_document", None)
            if active is not None and active.local_id == paper_id and resolver.intact(active):
                self._pdf_fingerprint = active.sha256
                self.paper._loaded_document = active
                self.paper._has_pdf = True
                self.pdf.show()
                self.pdf_missing.hide()
                self.open_external.setEnabled(True)
                return
            self._clear_document_view()
            self.pdf_missing.setText(message("invalid"))
            self.pdf_missing.show()
            return
        if not resolver.current(result):
            self._document_unavailable("stale")
            return
        self._active_document = result
        self.paper._loaded_document = result
        self.paper._document_status = result
        self.paper._has_pdf = True
        self.pdf.show()
        self.pdf_missing.hide()
        self.document_refresh.hide()
        self.open_external.setEnabled(True)
        self.pdf_note.setText(
            message("pages").format(count=self.pdf.page_count(), hash=result.sha256[:12])
        )
        self._load_highlights(result.path, fingerprint=result.sha256, prepare=True)
        self._figures_stale = True
