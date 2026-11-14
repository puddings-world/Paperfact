"""Two explicit clicks: verify selected originals, then include saved science in sync."""

import weakref
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFileDialog, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from paper_daily import lineage_package_native, lineage_sets
from paper_daily.lineage_direct_adoption import DirectAdoption
from paper_daily.manual_highlight_ops import _readonly_connection
from paper_daily.workspace_service import Ticket


class LineageAdoptionAction(QWidget):
    def __init__(self, owner):
        super().__init__(owner)
        self._owner = weakref.ref(owner)
        self.plan = self.service = self.ticket = self.expected = None
        self.button = QPushButton()
        self.reset_button = QPushButton(
            "重新選原文" if owner.language == "zh-TW" else "Choose again"
        )
        self.button.setAutoDefault(False)
        self.reset_button.setAutoDefault(False)
        self.button.clicked.connect(self.start)
        self.reset_button.clicked.connect(self.reset)
        self.reset_button.clicked.connect(owner._controls)
        self.label = QLabel()
        self.label.setWordWrap(True)
        self.label.setTextFormat(Qt.TextFormat.PlainText)
        row = QHBoxLayout()
        row.addWidget(self.button)
        row.addWidget(self.reset_button)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addLayout(row)
        layout.addWidget(self.label)
        self.reset()

    @property
    def owner(self):
        return self._owner()

    @property
    def zh(self):
        return self.owner.language == "zh-TW"

    def reset(self):
        self.plan = self.service = self.expected = None
        self.label.clear()
        self.button.setText("選原文並核對同步…" if self.zh else "Verify originals for sync…")
        self.reset_button.setVisible(False)

    def controls(self, enabled, entry):
        current = bool(entry and entry["current"] and entry.get("can_adopt"))
        selected = entry["row"] if entry else None
        if self.expected is not None and selected != self.expected:
            self.reset()
        self.setVisible(current or self.plan is not None or self.ticket is not None)
        self.button.setEnabled(bool(enabled and current))
        self.reset_button.setEnabled(bool(enabled and self.plan is not None))
        self.reset_button.setVisible(self.plan is not None)
        for button, role in (
            (self.button, "primary" if self.plan is not None else "secondary"),
            (self.owner.generate_button, "secondary" if self.plan is not None else "primary"),
        ):
            if button.property("role") != role:
                button.setProperty("role", role)
                button.style().unpolish(button)
                button.style().polish(button)
                button.update()
        self.button.setToolTip(
            "保留科學敘述與模型紀錄；核對原文後另行確認。原文與本分析會加入工作區同步，不呼叫 AI。"
            if self.zh
            else "Keep science/model records. Verify PDFs, then confirm separately. "
            "Originals and analysis join workspace sync; no AI call."
        )

    def _selected(self):
        owner = self.owner
        index = owner.results.currentIndex()
        if not 0 <= index < len(owner._entries):
            return None
        entry = owner._entries[index]
        return entry["row"] if entry["current"] and entry.get("can_adopt") else None

    def start(self):
        owner = self.owner
        if owner.busy or not owner._check() or owner._closing:
            return False
        row = self._selected()
        if row is None:
            return False
        if self.plan is not None:
            if row != self.expected:
                self.reset()
                return False
            service, plan = self.service, self.plan
            ticket = Ticket()
            self.ticket = ticket

            def apply(_stop, _progress):
                return service.apply(plan, ticket=ticket)

            started = owner._start("adopt_apply", apply)
        else:
            body = lineage_sets.decode(row["body_json"])
            selected, lines = {}, []
            for source in body["report"]["sources"]:
                if source["availability"] != "available":
                    continue
                title = source["identity"]["title"]
                caption = "選擇精確原文：" if self.zh else "Choose exact original: "
                filename, _filter = QFileDialog.getOpenFileName(
                    owner,
                    caption + title[:120] + " / " + source["document_hash"][:12],
                    "",
                    "PDF (*.pdf)",
                )
                if not filename or owner.busy or not owner._check() or self._selected() != row:
                    return False
                selected[source["id"]] = Path(filename)
                lines.append(title + " — " + Path(filename).name)
            database, root, native = owner.path, owner.path.parent, owner.identity
            ticket = Ticket()
            self.ticket, self.expected = ticket, row
            self.label.setText("\n".join(lines))

            def prepare(_stop, _progress):
                service = DirectAdoption(database, root)
                if tuple(service.receiver.identity) != tuple(native):
                    raise ValueError("Original database was replaced")
                info = service.inspect(row["paper_id"], row["corpus_key"], ticket=ticket)
                if info["row"] != row:
                    raise ValueError("Displayed saved report changed")
                plan = service.prepare(row["paper_id"], row["corpus_key"], selected, ticket=ticket)
                return service, plan

            started = owner._start("adopt_prepare", prepare)
        if not started:
            self.ticket = None
        else:
            owner.status.setText(
                "正在核對原文與同步資料…" if self.zh else "Checking originals and sync data…"
            )
        return started

    def cancel(self):
        if self.ticket is not None:
            self.ticket.cancel()

    def finish(self, worker, same):
        owner, ticket = self.owner, self.ticket
        self.ticket = None
        if not same or owner._closing:
            if ticket is not None and ticket.published:
                owner.status.setText(
                    "已儲存在原工作區；請重新開啟查看。"
                    if self.zh
                    else "Saved in the original workspace; reopen to review."
                )
            self.reset()
            return
        if worker.error or worker.result is None or worker.cancelled.is_set():
            self.plan = self.service = None
            self.button.setText("選原文並核對同步…" if self.zh else "Verify originals for sync…")
            owner.status.setText(
                owner.t["stopped"]
                if worker.cancelled.is_set()
                else "核對未完成。請選擇相同版本的 PDF，或重新讀取已存分析後重試；原內容保留。"
                if self.zh
                else "Could not verify. Choose matching PDFs or refresh the saved report; "
                "existing content is preserved."
            )
            return
        if worker.kind == "adopt_prepare":
            service, plan = worker.result
            try:
                if self._selected() != self.expected:
                    raise ValueError("Selected analysis changed")
                with _readonly_connection(owner.path) as conn:
                    service.receiver._check(conn)
                    current = lineage_package_native.saved_in(
                        conn, self.expected["paper_id"], self.expected["corpus_key"]
                    )
                    if current != self.expected:
                        raise ValueError("Saved report changed before review delivery")
            except (OSError, ValueError):
                self.reset()
                owner._needs_refresh = True
                owner.status.setText(owner.t["refresh_needed"])
                return
            self.service, self.plan = service, plan
            self.button.setText("確認納入同步" if self.zh else "Confirm inclusion in sync")
            owner.status.setText(
                "原文已核對。科學敘述與模型紀錄不變；請確認將本分析與原文納入同步。"
                if self.zh
                else "Originals verified. Science/model records stay unchanged. "
                "Confirm to include this analysis and its originals in sync."
            )
        else:
            row = self.expected
            for entry in owner._entries:
                if entry["row"] == row:
                    entry["can_adopt"] = False
            self.reset()
            owner.status.setText(owner.t["queued_sync"])
