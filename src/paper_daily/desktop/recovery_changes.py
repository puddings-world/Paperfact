"""Progressive old-device change review and explicit native note-copy action."""

from contextlib import closing
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from paper_daily import research_generation as generation
from paper_daily import sync_authority_backup as backup
from paper_daily import sync_recovery_candidates as candidates
from paper_daily import sync_recovery_choices as choices
from paper_daily import sync_recovery_claim_group as claim_group
from paper_daily import sync_recovery_deck_group as deck_group
from paper_daily import sync_recovery_highlight_group as highlight_group
from paper_daily import sync_recovery_lineage_group as lineage_group
from paper_daily import sync_recovery_note_copy as note_copy
from paper_daily import sync_recovery_original as original_choice
from paper_daily import sync_recovery_reading_context as reading_context
from paper_daily import sync_recovery_reading_group as reading_group
from paper_daily import sync_recovery_target as target
from paper_daily.manual_highlight_ops import _readonly_connection
from paper_daily.workspace_service import Cancelled, SnapshotChanged

GROUP_ACTIONS = (
    "use_original", "retire_original", "lineage_group", "reading_group",
    "highlight_group", "deck_group", "claim_group",
)

TEXT = {
    "en": {
        "choose": "Review changes in a restored workspace…",
        "refresh": "Refresh review",
        "compare": "Compare selected change",
        "copy": "Copy as new note",
        "already": (
            "This recorded change was already copied. Later edits or deletion of that copy "
            "remain unchanged; inspect it in the restored workspace."
        ),
        "retry": "Retry this copy",
        "next": "Next changes",
        "previous": "Previous changes",
        "old": "Old device's recorded content",
        "new": "Restored workspace's current content",
        "initial": (
            "Choose a service backup above, then choose a separately joined restored workspace."
        ),
        "pick": "Choose the restored workspace folder containing papers.db",
        "loaded": (
            "{count} recorded changes outside this backup. Select one to "
            "compare. This is not a full research/file audit."
        ),
        "empty": (
            "No recorded changes outside this backup. Unsaved drafts, "
            "uncaptured work and files are not certified."
        ),
        "unsupported": (
            "This change remains pending. Copying needs verified parent mappings and, "
            "for positioned notes, the exact original PDF. Other content or older "
            "formats need a separate recovery action."
        ),
        "ready": (
            "Compare both versions, then copy as a distinct note. Existing "
            "notes stay unchanged. This makes no AI call. If destination sync is enabled, "
            "the new note can synchronize."
        ),
        "saved": (
            "Saved a new note in the selected restored workspace. Refresh the"
            " review before another action. Remote acceptance has not been "
            "checked."
        ),
        "saved_changed": (
            "The copy was saved in the selected workspace, but the review "
            "changed. Reopen the review to inspect it."
        ),
        "failed": (
            "Could not finish this step. Existing research is preserved. "
            "Retry the same action, or refresh after changes."
        ),
        "stale": "The review changed. Refresh before comparing or copying.",
        "stopped": "Stopped. Refresh the review when ready; no workspace was switched.",
        "retired": "Deleted in this workspace",
        "absent": "Not present in this workspace",
        "index": "Checking old device and backup…",
        "target": "Checking restored workspace history…",
        "comparison": "Comparing the selected change…",
        "write": "Saving one new note…",
    },
    "zh-TW": {
        "choose": "到還原工作區審閱變更…",
        "refresh": "重新檢查",
        "compare": "比對選定變更",
        "copy": "另存為新筆記",
        "already": "這筆變更已另存過。副本後續的編輯或刪除保留；請到還原工作區檢視。",
        "retry": "重試這次另存",
        "next": "下一批變更",
        "previous": "上一批變更",
        "old": "舊裝置記錄的內容",
        "new": "還原工作區目前內容",
        "initial": ("先在上方選擇服務備份，再選擇已獨立加入同步的還原工作區。"),
        "pick": "選擇含 papers.db 的還原工作區資料夾",
        "loaded": ("有 {count} 筆不在備份中的變更。選擇一筆比對；這不代表完整研究與附件稽核。"),
        "empty": ("未找到備份以外的已記錄變更；未儲存草稿、未捕捉操作與檔案仍未完整核對。"),
        "unsupported": (
            "這筆變更仍保留待處理。另存筆記需要核實父項對應；綁定 "
            "PDF 位置的筆記也需核實原文。其他類型需使用各自的復原操作。"
        ),
        "ready": (
            "比對後可另存新筆記，既有內容保留。不呼叫 AI；目標工作區啟用同步時，新筆記會排入同步。"
        ),
        "saved": ("已另存到選定的還原工作區。請重新檢查再處理其他變更；尚未查詢遠端接收狀態。"),
        "saved_changed": ("新筆記已存入選定工作區，但檢查內容已改變；請重新開啟審閱。"),
        "failed": ("這一步未完成，既有研究保留。可重試同一次操作；資料改變時請重新檢查。"),
        "stale": "審閱內容已改變，請重新檢查後再比對或另存。",
        "stopped": "已停止；可稍後重新檢查，工作區未切換。",
        "retired": "此工作區已刪除",
        "absent": "此工作區尚無此內容",
        "index": "核對舊裝置與服務備份…",
        "target": "核對還原工作區歷史…",
        "comparison": "比對選定變更…",
        "write": "儲存一份新筆記…",
    },
}


TEXT["en"].update({
    "claim_group": "Use old complete claim group",
    "group_blocked": "This complete group needs further review: ",
    "ready_claim_group": (
        "Review the claims and both exact analysis inputs together. Confirmation replaces "
        "this group and includes its verified PDF; manual notes and the active PDF are preserved."
    ),
    "confirm_claim_group": (
        "Use this old claim set, deep explanation and close reading together, with its exact PDF? "
        "Different/deleted group members are replaced/restored; earlier history and manual notes "
        "are retained. This does not certify the research judgments or call AI."
    ),
    "group_dive": "Deep explanation", "group_close_reading": "Close reading",
    "group_claims": "Claims", "group_judgment": "Proposed judgment",
    "copy_original": "Copy note and original",
    "ready_original": (
        "This note needs its original PDF. Copy the note and verified original together; "
        "existing notes and the active PDF stay unchanged. Destination sync can upload both."
    ),
    "confirm_original": (
        "Copy this note and its verified original PDF into the selected restored workspace? "
        "Both are queued for destination sync. Existing notes and the active PDF stay unchanged."
    ),
    "action": "Action", "review": "Compare only", "keep": "Keep current content",
    "add": "Add old content", "replace": "Use old version", "restore": "Restore old content",
    "apply": "Apply selected action", "retry_action": "Retry selected action",
    "ready_action": "This change remains pending. Select an action after comparing both versions.",
    "already_action": "This action was already recorded. Later edits remain unchanged.",
    "decision_saved": (
        "Decision saved locally. Refresh to insp"
        "ect it; remote acceptance is unchecked."
    ),
    "kept": "Kept current content. Decision recorded locally; no research operation was created.",
    "decision_changed": (
        "Decision recorded, but the review cha"
        "nged. Reopen it to inspect the result."
    ),
    "confirm_title": "Apply the reviewed version?",
    "confirm_body": "{action}? This writes a new version in the selected restored workspace. "
                    "Earlier history is retained. Check both content panes before continuing.",
})
TEXT["zh-TW"].update({
    "claim_group": "使用舊版整組主張研究",
    "group_blocked": "這整組研究仍需核對：",
    "ready_claim_group": (
        "請一起比對主張與兩份原始分析。確認後會替換這整組內容並帶入核實的 PDF；"
        "手動筆記與目前 PDF 保留。"
    ),
    "confirm_claim_group": (
        "確定一起使用舊版主張、深入分析、逐段講解與對應 PDF？"
        "差異或已刪除的組內項目將被替換或復原；舊歷史與手動筆記保留。"
        "不會呼叫 AI，也不代表已核實研究判斷。"
    ),
    "group_dive": "深入分析", "group_close_reading": "逐段講解",
    "group_claims": "主張", "group_judgment": "研究判斷（待核實）",
    "copy_original": "另存筆記與原文",
    "ready_original": (
        "這筆筆記需要原文 PDF。可一起另存筆記與核實的原文；"
        "既有筆記與目前 PDF 保持不變。目標工作區可同步兩者。"
    ),
    "confirm_original": (
        "確定將這筆筆記與核實的原文 PDF 一起另存到選定的還原工作區？"
        "兩者都會排入目標工作區同步；既有筆記與目前 PDF 保持不變。"
    ),
    "action": "處理方式", "review": "只比較",
    "keep": "保留目前內容", "add": "新增舊內容",
    "replace": "使用舊版本", "restore": "還原舊內容",
    "apply": "套用所選方式", "retry_action": "重試所選操作",
    "ready_action": "此項變更仍待處理。比較兩版內容後，再選擇處理方式。",
    "already_action": "此操作已記錄，後續編輯保持不變。",
    "decision_saved": (
        "決定已存在本機，請重新檢查"
        "結果；尚未確認遠端接受狀態。"
    ),
    "kept": "已保留目前內容並記錄決定，沒有建立研究資料變更。",
    "decision_changed": (
        "決定已記錄，但檢查內容已"
        "變動；請重新開啟查看結果。"
    ),
    "confirm_title": "確定套用比較後的版本？",
    "confirm_body": (
        "{action}？這會在所選還原工作區寫入"
        "新版本，先前歷史仍會保留。請先核對兩側內容。"
    ),
})


TEXT["en"].update({
    "highlight_group": "Use old complete highlights",
    "ready_highlight_group": "Compare quotes, roles and reasons before confirming. "
                             "Quotes match the exact PDF; manual and hidden choices stay.",
    "confirm_highlight_group": "Save this analysis, verified original and all located highlights? "
                               "Existing manual/unrelated marks and current hidden choices remain. "
                               "This replaces or restores AI content; older history remains. "
                               "Scientific support is not certified and no AI call is made.",
    "group_highlight_analysis": "Selected research highlights",
    "group_ai_highlight": "PDF highlight", "group_hidden": "Hidden", "group_shown": "Shown",
    "deck_group": "Use old complete deck",
    "deck_originals": "Recorded originals",
    "ready_deck_group": "Compare slides, speaker notes and sources before confirming. "
                        "Exact originals and image assets are included. No AI call is made.",
    "confirm_deck_group": "Save this complete old deck and its verified originals? "
                          "This replaces or restores the selected slot; earlier history remains. "
                          "Open editors keep their drafts. Scientific support is not certified.",
})
TEXT["zh-TW"].update({
    "highlight_group": "使用舊版完整重點與標註",
    "ready_highlight_group": (
        "先比較重點句、角色與理由。每句都會核對到原始 P"
        "DF；手動畫線與隱藏選擇會保留。"
    ),
    "confirm_highlight_group": (
        "要一起儲存這份重點分析、原文與完整定位標註嗎？手"
        "動與其他標註，以及目前的隱藏選擇會保留。將取代或"
        "還原 AI 內容，舊紀錄仍保留。這不代表已驗證科"
        "學論述，也不會呼叫 AI。"
    ),
    "group_highlight_analysis": "所選研究重點",
    "group_ai_highlight": "PDF 重點標註",
    "group_hidden": "隱藏",
    "group_shown": "顯示",
    "deck_group": "使用舊版完整簡報",
    "deck_originals": "已記錄原文",
    "ready_deck_group": (
        "先比較投影片、講稿與來源，再確認套用完整簡報。會"
        "一併保留原始 PDF 與圖片，不呼叫 AI。"
    ),
    "confirm_deck_group": (
        "要儲存這份完整舊簡報及核對過的原文嗎？將取代或還"
        "原所選簡報，舊紀錄仍保留。已開啟編輯器的草稿不會"
        "被丟棄；這不代表已驗證科學論述。"
    ),
})


TEXT["en"].update({
    "copy_manual": (
        "Copy as new highlight"
    ),
    "copy_manual_original": (
        "Copy highlight and original"
    ),
    "ready_manual": (
        "Compare the exact quotation and position, then copy as a distinct manu"
        "al highlight. Existing marks stay unchanged."
    ),
    "ready_manual_original": (
        "Compare the exact quotation and position. Copy the verified original a"
        "nd a new manual highlight together; existing marks stay unchanged."
    ),
    "already_manual": (
        "This highlight was already copied. Later edits or deletion stay unchan"
        "ged."
    ),
    "saved_manual": (
        "Saved a new manual highlight locally. Remote acceptance is unchecked."
    ),
    "saved_manual_changed": (
        "The manual highlight was saved, but the review changed. Reopen it to i"
        "nspect the result."
    ),
    "confirm_manual": (
        "Copy this selection as a new manual highlight? Existing marks and late"
        "r edits stay unchanged. No AI call is made."
    ),
    "confirm_manual_original": (
        "Copy this verified original and a new manual highlight together? Exist"
        "ing marks stay unchanged and the active primary PDF is not switched. N"
        "o AI call is made."
    ),
    "manual_highlight": (
        "Manual highlight"
    ),
})
TEXT["zh-TW"].update({
    "copy_manual": (
        "複製為新手動畫線"
    ),
    "copy_manual_original": (
        "一起複製畫線與原文"
    ),
    "ready_manual": (
        "先比較引文與位置，再複製為新的手動畫線；現有標記"
        "不會被覆蓋。"
    ),
    "ready_manual_original": (
        "先比較引文與位置。會一起複製核對過的原文與新的手"
        "動畫線；現有標記不會被覆蓋。"
    ),
    "already_manual": (
        "這筆手動畫線已經複製過。之後的修改或刪除不會被覆"
        "蓋。"
    ),
    "saved_manual": (
        "已在本機儲存新的手動畫線；尚未核對遠端接收狀態。"
    ),
    "saved_manual_changed": (
        "手動畫線已儲存，但比較畫面已變動。請重新開啟查看"
        "結果。"
    ),
    "confirm_manual": (
        "要將這段選取範圍複製為新的手動畫線嗎？現有標記與"
        "後續修改會保留，不會呼叫 AI。"
    ),
    "confirm_manual_original": (
        "要一起複製核對過的原文與新的手動畫線嗎？現有標記"
        "會保留，也不會切換目前原文或呼叫 AI。"
    ),
    "manual_highlight": (
        "手動畫線"
    ),
})

TEXT["en"].update({
    "reading_context_ready": (
        "Verified the saved explanations and original. Comparison only; applyin"
        "g this group is not available yet."
    ),
    "reading_context_issue": (
        "Saved link context could not be verified: "
    ),
    "group_reading_links": (
        "Explanation links"
    ),
    "reading_no_links": (
        "No saved explanation links."
    ),
})
TEXT["zh-TW"].update({
    "reading_context_ready": (
        "已核對舊版講解與原文；目前可比較，尚未提供這組內"
        "容的套用動作。"
    ),
    "reading_context_issue": (
        "無法核對舊版解說連結來源："
    ),
    "group_reading_links": (
        "解說連結"
    ),
    "reading_no_links": (
        "沒有已儲存的解說連結。"
    ),
})

TEXT["en"].update({
    "reading_group": "Use old complete explanation group",
    "ready_reading_group": (
        "Verified the saved explanations, highlights, links and original. Compare all members, "
        "then confirm. Missing old explanations will clear their corresponding current content."
    ),
    "confirm_reading_group": (
        "Use these old explanations, highlight analysis, links and exact original together? "
        "An absent old explanation clears the corresponding current explanation. Manual and "
        "PDF marks stay unchanged. No AI will be called."
    ),
})
TEXT["zh-TW"].update({
    "reading_group": "\u4f7f\u7528\u820a\u7248\u6574\u7d44\u8b1b\u89e3",
    "ready_reading_group": (
        "已核對講解、重點、連結與原文。"
        "請比較後確認；舊版缺少的講解會清除目前對應內容"
        "。"
    ),
    "confirm_reading_group": (
        "確認一起使用舊版講解、重點分析、連結與原文？"
        "舊版缺少的講解會清除目前對應講解。"
        "手動與 PDF 畫線維持不變，不呼叫 AI。"
    ),
})


TEXT["en"].update({
    "lineage_group": (
        "Use old complete lineage report"
    ),
    "group_lineage": (
        "Research lineage and sources"
    ),
    "lineage_prior_gap": (
        "Earlier research gap"
    ),
    "lineage_current_change": (
        "Change introduced by this study"
    ),
    "lineage_later_development": (
        "Later research development"
    ),
    "lineage_unlocated": (
        "Source passage not located; scientific support remains unresolved."
    ),
    "ready_lineage_group": (
        "Verified the exact originals and saved passage locations. Compare the complete"
        " report, then confirm. Scientific influence and support are not certified."
    ),
    "confirm_lineage_group": (
        "Use this complete saved lineage report and all its available exact originals? "
        "This replaces the current report for the same corpus. Other research and activ"
        "e PDFs stay unchanged. No AI will be called."
    ),
})
TEXT["zh-TW"].update({
    "lineage_group": (
        "使用舊版整組研究脈絡"
    ),
    "group_lineage": (
        "研究脈絡與來源"
    ),
    "lineage_prior_gap": (
        "既有研究缺口"
    ),
    "lineage_current_change": (
        "本篇帶來的改變"
    ),
    "lineage_later_development": (
        "後續研究發展"
    ),
    "lineage_unlocated": (
        "原文位置未確認；學術支持關係仍待核實。"
    ),
    "ready_lineage_group": (
        "已核對各篇原文與已存引句位置。請比較整份報告後"
        "確認；不代表已證明學術影響或支持關係。"
    ),
    "confirm_lineage_group": (
        "確認一起使用這份舊版脈絡報告與各篇可用原文？同"
        "一組論文的目前報告會被取代。其他研究與目前開啟"
        "的 PDF 維持不變，不呼叫 AI。"
    ),
})


TEXT["en"].update({
    "use_original": (
        "Restore retained original source"
    ),
    "retire_original": (
        "Retire retained original source"
    ),
    "group_original_source": (
        "Retained original version"
    ),
    "ready_use_original": (
        "Verified the exact retained PDF. Compare the source and current state, then co"
        "nfirm restoration. Research and active PDFs stay unchanged."
    ),
    "ready_retire_original": (
        "Review this exact current original version before confirming retirement. Cache"
        "d bytes and research history stay; dependent source checks may become unavaila"
        "ble."
    ),
    "confirm_use_original": (
        "Restore this exact retained PDF source association? A retired source receives "
        "a new native version. Other research and active PDFs stay unchanged. No AI wil"
        "l be called."
    ),
    "confirm_retire_original": (
        "Retire the displayed current original-source association? Cached bytes, notes "
        "and history stay. Research depending on this source version may require source"
        " review. The active PDF is not deleted or closed. No AI will be called."
    ),
})
TEXT["zh-TW"].update({
    "use_original": (
        "恢復這個原文版本"
    ),
    "retire_original": (
        "停用這個原文來源"
    ),
    "group_original_source": (
        "保留的原文版本"
    ),
    "ready_use_original": (
        "已核對保留的正確 PDF。請比較原文與目前狀態"
        "後確認恢復；研究內容與開啟中的 PDF 維持不"
        "變。"
    ),
    "ready_retire_original": (
        "請核對目前這份原文版本後確認停用。原文快取與研"
        "究歷史保留；依賴此版本的來源核對可能暫時無法使"
        "用。"
    ),
    "confirm_use_original": (
        "確認恢復這份保留 PDF 的來源關聯？已停用來"
        "源會建立新版本。其他研究與開啟中的 PDF 維"
        "持不變，不呼叫 AI。"
    ),
    "confirm_retire_original": (
        "確認停用目前顯示的原文來源關聯？原文快取、筆記"
        "與歷史保留。依賴此版本的研究可能需要重新核對來"
        "源。不刪除或關閉目前 PDF，不呼叫 AI。"
    ),
})


class RecoveryChanges(QWidget):
    def __init__(self, panel):
        super().__init__(panel)
        self.panel = panel
        self.t = TEXT["zh-TW" if self.owner.zh else "en"]
        self.snapshot = self.destination = self.observed = self.page = self.plan = None
        self.failed_copy = self._confirming = False
        self.action_plans = {}
        self.offset = 0
        self.previous_button = QPushButton(self.t["previous"])
        self.choose_button = QPushButton(self.t["choose"])
        self.refresh_button = QPushButton(self.t["refresh"])
        self.next_button = QPushButton(self.t["next"])
        self.compare_button = QPushButton(self.t["compare"])
        self.copy_button = QPushButton(self.t["copy"])
        self.copy_button.setProperty("role", "primary")
        self.action_select = QComboBox()
        self.action_select.setAccessibleName(self.t["action"])
        self.action_select.currentIndexChanged.connect(self.action_changed)
        for button in self.buttons:
            button.setAutoDefault(False)
        self.choose_button.clicked.connect(self.choose)
        self.refresh_button.clicked.connect(self.reload)
        self.next_button.clicked.connect(self.next_page)
        self.previous_button.clicked.connect(self.previous_page)
        self.compare_button.clicked.connect(self.compare)
        self.copy_button.clicked.connect(self.copy)
        self.location, self.notice = QLabel(), QLabel(self.t["initial"])
        for label in (self.location, self.notice):
            label.setWordWrap(True)
            label.setTextFormat(Qt.TextFormat.PlainText)
            label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.rows = QListWidget()
        self.rows.setAccessibleName("Recovery changes" if not self.owner.zh else "待復原變更")
        self.rows.currentRowChanged.connect(self.selection_changed)
        self.rows.itemActivated.connect(lambda _item: self.compare())
        self.old, self.current = QPlainTextEdit(), QPlainTextEdit()
        previews = QSplitter(Qt.Orientation.Horizontal)
        for field, caption in ((self.old, self.t["old"]), (self.current, self.t["new"])):
            field.setReadOnly(True)
            field.setAccessibleName(caption)
            group = QWidget()
            group_layout = QVBoxLayout(group)
            group_layout.setContentsMargins(0, 0, 0, 0)
            group_layout.addWidget(QLabel(caption))
            group_layout.addWidget(field)
            previews.addWidget(group)
        self.splitter = QSplitter(Qt.Orientation.Vertical)
        self.splitter.addWidget(self.rows)
        self.splitter.addWidget(previews)
        self.splitter.setSizes([140, 240])
        self.splitter.setMinimumHeight(260)
        top, actions = QHBoxLayout(), QHBoxLayout()
        top.addWidget(self.choose_button)
        top.addWidget(self.refresh_button)
        actions.addWidget(self.previous_button)
        actions.addWidget(self.next_button)
        actions.addStretch()
        actions.addWidget(self.compare_button)
        self.action_row = QWidget()
        action_layout = QHBoxLayout(self.action_row)
        action_layout.setContentsMargins(0, 0, 0, 0)
        action_layout.addWidget(QLabel(self.t["action"]))
        action_layout.addWidget(self.action_select, 1)
        action_layout.addWidget(self.copy_button)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 12, 0, 0)
        layout.setSpacing(8)
        layout.addLayout(top)
        layout.addWidget(self.location)
        layout.addWidget(self.notice)
        layout.addWidget(self.splitter)
        layout.addLayout(actions)
        layout.addWidget(self.action_row)
        self.splitter.hide()
        self.controls(False)

    @property
    def owner(self):
        return self.panel.owner

    @property
    def buttons(self):
        return (
            self.choose_button,
            self.refresh_button,
            self.next_button,
            self.previous_button,
            self.compare_button,
            self.copy_button,
        )

    def reset_source(self, selected):
        self.snapshot = selected
        self.offset = 0
        self.destination = self.observed = self.page = self.plan = None
        self.rows.clear()
        self.location.clear()
        self.splitter.hide()
        self.notice.setText(self.t["initial"])

    def controls(self, active):
        active = bool(
            active and not self._confirming and self.snapshot
            and self.owner._adoption_context_current()
        )
        self.choose_button.setEnabled(active)
        self.refresh_button.setEnabled(bool(active and self.destination))
        self.next_button.setEnabled(
            bool(active and self.page and self.observed and self.page["next_offset"] is not None)
        )
        self.previous_button.setEnabled(bool(active and self.observed and self.offset))
        self.rows.setEnabled(bool(active and self.observed))
        self.compare_button.setEnabled(bool(active and self.observed and self.selected()))
        self.copy_button.setEnabled(bool(active and self.observed and self.plan))
        action = self.action_select.currentData()
        key = "retry" if action == "copy" else "retry_action"
        selected_plan = self.action_plans.get(action, (None, False))[0]
        manual = getattr(selected_plan, "manual_highlight", False)
        label = ("copy_manual_original" if getattr(selected_plan, "with_original", False)
                 else "copy_manual") if action == "copy" and manual else (
            "copy_original" if action == "copy" and getattr(
                self.plan, "with_original", False) else action or "apply")
        self.copy_button.setText(self.t[key if self.failed_copy else label])
        self.action_select.setEnabled(bool(active and self.observed and self.action_plans))
        self.action_row.setVisible(bool(self.observed and self.action_plans))

    def selected(self):
        item = self.rows.currentItem()
        return item.data(Qt.ItemDataRole.UserRole) if item is not None else None

    def action_changed(self, _index):
        action = self.action_select.currentData()
        plan, already = self.action_plans.get(action, (None, False))
        self.plan, self.failed_copy = (None if already else plan), False
        if action:
            key = ("already" if action == "copy" else "already_action") if already else (
                "ready" if action == "copy" else "ready_action"
            )
            if action == "copy" and not already and getattr(plan, "with_original", False):
                key = "ready_original"
            if action in GROUP_ACTIONS and not already:
                key = "ready_" + action
            if action == "copy" and getattr(plan, "manual_highlight", False):
                key = ("already_manual" if already else "ready_manual_original"
                       if plan.with_original else "ready_manual")
            self.notice.setText(self.t[key])
        self.controls(not self.owner.busy and not self.owner._invalid)

    def selection_changed(self, _row):
        self.action_plans = {}
        self.action_select.clear()
        self.plan, self.failed_copy = None, False
        self.old.clear()
        self.current.clear()
        self.controls(not self.owner.busy and not self.owner._invalid)

    def choose(self):
        if not self.choose_button.isEnabled():
            return False
        selected = QFileDialog.getExistingDirectory(self, self.t["pick"])
        return self.load(selected) if selected else False

    def reload(self):
        if not self.refresh_button.isEnabled():
            return False
        return self.load(self.destination)

    def _cancelled(self, ticket):
        service = self.owner.service
        return (
            ticket.cancelled
            or Path(service.current_path()).resolve() != service.path
            or tuple(generation._identity(service.path)) != service.identity
        )

    def _start(self, kind, work):
        def run(ticket, progress):
            ticket.check()
            self.owner.service.check()
            try:
                return work(ticket, progress)
            except backup.BackupCancelled:
                raise Cancelled() from None
            except ValueError:
                if kind in {"compare", "copy", "page"}:
                    raise SnapshotChanged() from None
                raise

        return self.owner._start("device_changes_" + kind, run)

    def load(self, folder):
        if (
            not folder
            or not self.snapshot
            or self.owner.busy
            or not self.owner._adoption_context_current()
        ):
            return False
        source, snapshot = self.owner.service.path, self.snapshot
        folder = Path(folder)
        self.observed = self.page = self.plan = None
        self.rows.clear()
        self.splitter.hide()
        self.destination = folder
        self.location.setText(str(folder))

        def run(ticket, progress):
            from paper_daily.workspace_sync import local_binding

            progress("device_changes:index")
            binding = local_binding(source)
            if binding is None:
                raise ValueError("Old device requires an existing sync journal")
            index = candidates.prepare(
                source, snapshot, binding["workspace_id"], cancelled=lambda: self._cancelled(ticket)
            )
            progress("device_changes:target")
            observed = target.observe(
                index, folder / "papers.db", cancelled=lambda: self._cancelled(ticket)
            )
            return observed, observed.source.page(cancelled=lambda: self._cancelled(ticket)), 0

        return self._start("load", run)

    def next_page(self):
        if not self.next_button.isEnabled():
            return False
        return self._page_at(self.page["next_offset"])

    def previous_page(self):
        if not self.previous_button.isEnabled():
            return False
        return self._page_at(max(0, self.offset - 20))

    def _page_at(self, offset):
        observed = self.observed
        self.plan = None

        def run(ticket, _progress):
            observed._check(lambda: ticket.check())
            page = observed.source.page(after=offset, cancelled=lambda: self._cancelled(ticket))
            return observed, page, offset

        return self._start("page", run)

    def compare(self):
        if not self.compare_button.isEnabled():
            return False
        observed, selected = self.observed, self.selected()
        self.plan, self.failed_copy = None, False

        def run(ticket, progress):
            progress("device_changes:comparison")

            def stopped():
                return self._cancelled(ticket)

            comparison = observed.compare(selected, cancelled=stopped)
            operation = comparison["source"]["operation"]
            supported = (
                operation["version"] == 2
                and (operation["entity_type"] == "note" or note_copy.is_manual_highlight(operation))
                and operation["action"] == "put"
            )
            plan, already = None, False
            if supported:
                request_id = str(
                    uuid5(
                        NAMESPACE_URL,
                        "paperfact:recovery-copy-ui:v1:"
                        + candidates._json(
                            [
                                observed.binding,
                                operation["workspace_id"],
                                operation["device_id"],
                                operation["operation_id"],
                                candidates._fingerprint(operation),
                            ]
                        ),
                    )
                )
                with closing(_readonly_connection(observed.database)) as conn:
                    already = (
                        conn.execute(
                            "SELECT 1 FROM paperfact_sync_operations WHERE operation_id=?",
                            (request_id,),
                        ).fetchone()
                        is not None
                    )
                try:
                    plan = note_copy.prepare(observed, selected, request_id, cancelled=stopped)
                except (OSError, ValueError) as error:
                    if note_copy.is_manual_highlight(operation):
                        comparison["manual_copy_issue"] = str(error)[:240]
                    # Missing parent/source proof keeps comparison readable.
                    # A previously saved request must still validate its receipt.
                    observed._check(backup._guard(30, stopped))
                    if already:
                        raise
                    if (operation["payload"].get("anchor") is not None
                            or note_copy.is_manual_highlight(operation)):
                        try:
                            plan = note_copy.prepare(
                                observed, selected, request_id, with_original=True,
                                cancelled=stopped,
                            )
                        except (OSError, ValueError) as error:
                            if note_copy.is_manual_highlight(operation):
                                comparison["manual_copy_issue"] = str(error)[:240]
                            observed._check(backup._guard(30, stopped))
            plans = self._metadata_plans(observed, selected, comparison, stopped)
            if (operation["payload"].get("feature") == "reading_links"
                    and "reading_group" not in plans):
                try:
                    comparison["reading_context"] = reading_context.resolve(
                        observed.source, selected, cancelled=stopped,
                    )
                except (OSError, ValueError) as error:
                    comparison["reading_context_issue"] = str(error)[:240]
                observed._check(backup._guard(30, stopped))
            return observed, selected, comparison, plan, already, plans

        return self._start("compare", run)

    def _metadata_plans(self, observed, selected, comparison, stopped):
        operation = comparison["source"]["operation"]
        options, current_action = ["keep"], None
        if (
            operation["version"] == 2 and operation["entity_type"] in choices.KINDS
            and operation["action"] == "put"
        ):
            current = comparison["target"]["entity_state"]
            parents = [
                dict(parent["expected"], incarnation=parent["current"]["incarnation"])
                for parent in comparison["target"]["parents"] if parent["current"] is not None
            ]
            current_action = (
                "add" if current is None else
                "restore" if not current["active"] or current["parents"] != parents else "replace"
            )
            options.extend(("add", "replace", "restore"))
        plans = {}
        for action in options:
            request_id = str(uuid5(NAMESPACE_URL, "paperfact:recovery-choice-ui:v1:" +
                candidates._json([
                    observed.binding, operation["workspace_id"], operation["device_id"],
                    operation["operation_id"], candidates._fingerprint(operation), action,
                ])))
            with closing(_readonly_connection(observed.database)) as conn:
                saved = conn.execute(
                    "SELECT 1 FROM integration_operations WHERE id=?", (request_id,)
                ).fetchone() is not None
                native = conn.execute(
                    "SELECT 1 FROM paperfact_sync_operations WHERE operation_id=?", (request_id,)
                ).fetchone() is not None
            if action != "keep" and action != current_action and not (saved or native):
                continue
            try:
                plan = choices.prepare(observed, selected, action, request_id, cancelled=stopped)
            except ValueError:
                if saved or native:
                    raise
                continue
            plans[action] = (plan, saved)
        if operation["entity_type"] == "research_file" and (
            operation["action"] == "delete"
            or operation["payload"].get("feature") == "original_source"
        ):
            action = "use_original" if operation["action"] == "put" else "retire_original"
            request = str(uuid5(NAMESPACE_URL, "paperfact:original-choice-ui:" + candidates._json([
                observed.binding, operation["operation_id"],
                candidates._fingerprint(operation), action,
            ])))
            try:
                plan = original_choice.prepare(observed, selected, request, action=action,
                                               cancelled=stopped)
            except (OSError, ValueError) as error:
                comparison[action + "_issue"] = str(error)[:240]
                with closing(_readonly_connection(observed.database)) as conn:
                    if conn.execute("SELECT 1 FROM integration_operations WHERE id=?",
                                    (request,)).fetchone():
                        raise
                observed._check(backup._guard(60, stopped))
            else:
                plans[action] = (plan, plan.already)
        if operation["entity_type"] == "research_content" and operation["payload"].get(
            "feature"
        ) == "lineage":
            request = lineage_group.review_request(observed, operation)
            try:
                group = lineage_group.prepare(
                    observed, selected, request, replace=True, cancelled=stopped,
                )
            except (OSError, ValueError) as error:
                comparison["lineage_group_issue"] = str(error)[:240]
                with closing(_readonly_connection(observed.database)) as conn:
                    if conn.execute("SELECT 1 FROM integration_operations WHERE id=?",
                                    (request,)).fetchone():
                        raise
                observed._check(backup._guard(60, stopped))
            else:
                plans["lineage_group"] = (group, group.already)
        if operation["entity_type"] == "research_content" and operation["payload"].get(
            "feature"
        ) == "reading_links":
            request = str(uuid5(NAMESPACE_URL, "paperfact:reading-group-ui:" + candidates._json([
                observed.binding, operation["operation_id"], candidates._fingerprint(operation),
            ])))
            try:
                group = reading_group.prepare(
                    observed, selected, request, replace=True, cancelled=stopped,
                )
            except (OSError, ValueError) as error:
                comparison["reading_group_issue"] = str(error)[:240]
                with closing(_readonly_connection(observed.database)) as conn:
                    if conn.execute("SELECT 1 FROM integration_operations WHERE id=?",
                                    (request,)).fetchone():
                        raise
                observed._check(backup._guard(60, stopped))
            else:
                plans["reading_group"] = (group, group.already)
        if operation["entity_type"] == "research_content" and operation["payload"].get(
            "feature"
        ) == "claims":
            request = str(uuid5(NAMESPACE_URL, "paperfact:claim-group-ui:" + candidates._json([
                observed.binding, operation["operation_id"], candidates._fingerprint(operation),
            ])))
            try:
                group = claim_group.prepare(
                    observed, selected, request, replace=True, cancelled=stopped,
                )
            except (OSError, ValueError) as error:
                comparison["claim_group_issue"] = str(error)[:240]
                with closing(_readonly_connection(observed.database)) as conn:
                    if conn.execute("SELECT 1 FROM integration_operations WHERE id=?",
                                    (request,)).fetchone():
                        raise
                observed._check(backup._guard(60, stopped))
            else:
                plans["claim_group"] = (group, group.already)
        if operation["entity_type"] == "research_file" and operation["payload"].get(
            "feature"
        ) == "deck":
            request = str(uuid5(NAMESPACE_URL, "paperfact:deck-group-ui:" + candidates._json([
                observed.binding, operation["operation_id"], candidates._fingerprint(operation),
            ])))
            try:
                group = deck_group.prepare(
                    observed, selected, request, replace=True, cancelled=stopped,
                )
            except (OSError, ValueError) as error:
                comparison["deck_group_issue"] = str(error)[:240]
                with closing(_readonly_connection(observed.database)) as conn:
                    if conn.execute("SELECT 1 FROM integration_operations WHERE id=?",
                                    (request,)).fetchone():
                        raise
                observed._check(backup._guard(60, stopped))
            else:
                plans["deck_group"] = (group, group.already)
        if operation["entity_type"] == "research_content" and operation["payload"].get(
            "feature"
        ) == "highlight_analysis":
            request = str(uuid5(NAMESPACE_URL, "paperfact:highlight-group-ui:" + candidates._json([
                observed.binding, operation["operation_id"], candidates._fingerprint(operation),
            ])))
            try:
                group = highlight_group.prepare(
                    observed, selected, request, replace=True, cancelled=stopped,
                )
            except (OSError, ValueError) as error:
                comparison["highlight_group_issue"] = str(error)[:240]
                with closing(_readonly_connection(observed.database)) as conn:
                    if conn.execute("SELECT 1 FROM integration_operations WHERE id=?",
                                    (request,)).fetchone():
                        raise
                observed._check(backup._guard(60, stopped))
            else:
                plans["highlight_group"] = (group, group.already)
        return plans

    def _reading_context_text(self, context):
        from paper_daily import reading_links
        from paper_daily.answer_content import reading_text

        members = context["members"]
        displays = []
        bodies = []
        for member in members[:3]:
            data = member["data"]
            if member["feature"] in {"dive", "close_reading"}:
                body = data["body"] if data else None
                bodies.append(body)
                if data:
                    data = dict(data, body=reading_text(
                        body, legacy_dive=member["feature"] == "dive") or body)
            displays.append(dict(feature=member["feature"], source=data, current=None))
        parts = [self._group_text(displays, "source"), self.t["group_reading_links"]]
        sections = {row["id"]: row for row in reading_links.sections(*bodies)}
        quotes = members[2]["data"]["body_json"]["items"]
        for link in members[3]["data"]["body_json"]["links"]:
            parts.extend([quotes[link["quote"]]["text"], sections[link["section"]]["title"],
                          link["explanation"]])
        if not members[3]["data"]["body_json"]["links"]:
            parts.append(self.t["reading_no_links"])
        return "\n\n".join(parts)

    def _deck_text(self, comparison, side):
        value = comparison[side]
        if value is None:
            return self.t["retired"] if comparison["state"] == "retired" else self.t["absent"]
        deck = value["deck"]
        parts = [deck["title"]]
        for index, slide in enumerate(deck["slides"], 1):
            parts.extend([str(index) + ". " + slide["title"], slide["takeaway"],
                          *slide["bullets"], slide["speaker_notes"]])
            for element in slide.get("elements") or []:
                if element.get("text"):
                    parts.append(element["text"])
                if element["kind"] == "table":
                    parts.extend(" | ".join(row) for row in element.get("rows", []))
        for row in deck["sources"]:
            parts.extend(value for value in (row["label"], row.get("text"), row.get("url"))
                         if value)
        parts.extend(row.get("caption") or row["label"] for row in deck["figures"])
        if side == "source" and comparison.get("original_owners"):
            parts.append(self.t["deck_originals"])
            parts.extend(row["title"] + " (" + row["sha256"][:12] + ")"
                         for row in comparison["original_owners"])
        return "\n\n".join(parts)

    def _group_text(self, members, side):
        parts = []
        for member in members:
            feature, data = member["feature"], member[side]
            parts.append(self.t["group_" + feature])
            if data is None:
                parts.append(self.t["retired"] if side == "current" and member.get(
                    "state"
                ) == "retired" else self.t["absent"])
            elif feature == "original_source":
                parts.extend([member["title"], data["source_document_hash"],
                              str(data["assets"][0]["size"]) + " bytes"])
                if side == "source":
                    parts.append(self.t["use_original" if member["source_action"] == "put"
                                        else "retire_original"])
            elif feature == "lineage":
                report = data["body_json"]["report"]
                selected = {row["id"]: row for row in report["sources"]}
                for source in report["sources"]:
                    parts.extend([source["identity"]["title"], source["document_hash"][:12]
                                  if source["availability"] == "available" else
                                  self.t["lineage_unlocated"]])
                for statement in report["statements"]:
                    parts.extend([self.t["lineage_" + statement["stage"]], statement["text"],
                                  self.t["group_judgment"] + ": " + statement["judgment"]["status"],
                                  statement["judgment"]["reason"]])
                    for passage in statement["passages"]:
                        location = passage["location"]
                        parts.extend([selected[passage["source_id"]]["identity"]["title"],
                                      passage["quote"], "p. " + str(location["page"])
                                      if location["state"] == "located" else
                                      self.t["lineage_unlocated"]])
                if side == "source":
                    for original in member.get("originals", []):
                        parts.append(original["title"] + " (" + original["sha256"][:12] + ")")
            elif feature == "highlight_analysis":
                for item in data["body_json"]["items"]:
                    parts.extend([item["kind"] + " / p. " + str(item["page"]),
                                  item["text"], item["reason"]])
            elif feature == "ai_highlight":
                parts.extend([data["quote"], data["reason"],
                              self.t["group_hidden" if data["hidden"] else "group_shown"]])
            elif feature == "reading_links":
                for link in data["body_json"]["links"]:
                    parts.extend([link["section"], "Quote " + str(link["quote"] + 1),
                                  link["explanation"]])
            elif feature != "claims":
                parts.append(data["body"])
            else:
                for claim in data["body_json"]["report"]["claims"]:
                    judgment = claim["judgment"]
                    parts.append(claim["text"] + "\n" + self.t["group_judgment"] + ": "
                                 + judgment["status"] + " ? " + judgment["reason"])
                    parts.extend(passage["quote"] for passage in claim["passages"])
        return "\n\n".join(parts)

    def _completion(self, receipt, changed=False):
        if receipt.get("format") == note_copy.MANUAL_FORMAT:
            return self.t["saved_manual_changed" if changed else "saved_manual"]
        if "choice" not in receipt:
            return self.t["saved_changed" if changed else "saved"]
        return self.t["decision_changed" if changed else
                      "kept" if receipt["choice"] == "keep" else "decision_saved"]

    def copy(self):
        if self._confirming or not self.copy_button.isEnabled():
            return False
        plan, action = self.plan, self.action_select.currentData()
        include_original = action == "copy" and getattr(plan, "with_original", False)
        manual = action == "copy" and getattr(plan, "manual_highlight", False)
        if (manual or action in {"replace", "restore"}
                or action in GROUP_ACTIONS or include_original):
            self._confirming = True
            self.controls(False)
            try:
                answer = QMessageBox.question(
                    self, self.t["confirm_title"],
                    self.t["confirm_manual_original" if include_original else "confirm_manual"]
                    if manual else self.t["confirm_" + action] if action in GROUP_ACTIONS else
                    self.t["confirm_original"] if include_original else
                    self.t["confirm_body"].format(action=self.t[action]),
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.No,
                )
            finally:
                self._confirming = False
            if self.owner.disposed or self.owner._closing:
                return False
            self.controls(not self.owner.busy and not self.owner._invalid)
            if answer != QMessageBox.StandardButton.Yes:
                return False
        if (
            plan is not self.plan or self.owner.busy
            or not self.owner._adoption_context_current()
        ):
            return False

        def run(ticket, progress):
            progress("device_changes:write")
            receipt = plan.apply(cancelled=lambda: self._cancelled(ticket))
            # A post-commit observation failure cannot turn a successful save into
            # a false "nothing saved" error. Delivery validates this cheap fence.
            try:
                from paper_daily.workspace_sync import local_binding

                observed = plan.observed
                if local_binding(observed.database, require_capture=True) != observed.binding:
                    raise ValueError("Saved target was rebound")
                fence = (
                    tuple(generation._identity(observed.database)),
                    candidates.review._version(observed.database),
                )
            except (OSError, ValueError):
                fence = None
            return receipt, fence

        return self._start("copy", run)

    def stage(self, stage):
        key = stage.removeprefix("device_changes:")
        if key in ("index", "target", "comparison", "write"):
            self.notice.setText(self.t[key])
            self.owner.status.setText(self.t[key])

    def finish(self, worker, kind):
        owner = self.owner
        copied = kind == "device_changes_copy" and worker.result is not None and not worker.error
        current = owner._adoption_context_current() and not owner._closing
        if not current or worker.error == "changed":
            if worker.error == "changed":
                owner._invalid = True
            self.observed = self.page = self.plan = None
            self.rows.clear()
            self.splitter.hide()
            owner.status.setText(
                self._completion(worker.result[0], True) if copied else self.t["stale"]
            )
            return
        if copied:
            try:
                observed = self.plan.observed
                observed.source._check(lambda: None)
                native, versions = worker.result[1]
                stable = (
                    native == observed.identity
                    and tuple(generation._identity(observed.database)) == native
                    and candidates.review._version(observed.database) == versions
                )
            except (OSError, ValueError, TypeError, AttributeError):
                stable = False
            self.observed = self.page = self.plan = None
            self.failed_copy = False
            message = self._completion(worker.result[0], not stable)
            self.notice.setText(message)
            owner.status.setText(message)
            self.old.clear()
            self.current.clear()
            return
        if worker.error == "snapshot_changed":
            self.observed = self.page = self.plan = None
            self.rows.clear()
            self.splitter.hide()
            self.notice.setText(self.t["stale"])
            owner.status.setText(self.t["stale"])
            return
        if worker.error or worker.ticket.cancelled or worker.result is None:
            self.failed_copy = kind == "device_changes_copy" and self.plan is not None
            self.notice.setText(self.t["stopped"] if worker.ticket.cancelled else self.t["failed"])
            owner.status.setText(self.notice.text())
            return
        try:
            observed = worker.result[0]
            observed._check(lambda: None)  # Bounded identities/versions, no SQL or PDF reads.
            if kind in ("device_changes_load", "device_changes_page"):
                self.observed, self.page, self.offset = worker.result
                self.rows.clear()
                for position, row in enumerate(self.page["items"], start=self.offset + 1):
                    item = QListWidgetItem(self._row_label(row, position))
                    item.setData(Qt.ItemDataRole.UserRole, row["change_id"])
                    item.setToolTip(self._row_tooltip(row))
                    self.rows.addItem(item)
                self.rows.setCurrentRow(0 if self.rows.count() else -1)
                self.splitter.setVisible(bool(self.rows.count()))
                self.notice.setText(
                    self.t["loaded"].format(count=self.page["change_count"])
                    if self.rows.count()
                    else self.t["empty"]
                )
                if self.rows.count():
                    self.rows.setFocus()
            else:
                _observed, selected, comparison, plan, already, plans = worker.result
                if observed is not self.observed or selected != self.selected():
                    raise ValueError("Selected recovery change changed")
                source = comparison["source"]["operation"]
                effective = comparison["target"]["effective_operation"]
                self.old.setPlainText(self._content(source))
                self.current.setPlainText(self._content(effective))
                if comparison.get("reading_context"):
                    self.old.setPlainText(self._reading_context_text(comparison["reading_context"]))
                self.action_plans = dict(plans)
                if plan is not None:
                    self.action_plans["copy"] = (plan, already)
                group_action = next((key for key in GROUP_ACTIONS
                                     if key in self.action_plans), "claim_group")
                group = self.action_plans.get(group_action, (None, False))[0]
                if group is not None and group.comparison:
                    render = self._deck_text if group_action == "deck_group" else self._group_text
                    self.old.setPlainText(render(group.comparison, "source"))
                    self.current.setPlainText(render(group.comparison, "current"))
                self.action_select.blockSignals(True)
                self.action_select.clear()
                self.action_select.addItem(self.t["review"], "")
                for action in self.action_plans:
                    label = "copy_original" if action == "copy" and getattr(
                        plan, "with_original", False
                    ) else action
                    if action == "copy" and getattr(plan, "manual_highlight", False):
                        label = "copy_manual_original" if plan.with_original else "copy_manual"
                    self.action_select.addItem(self.t[label], action)
                if plan is not None:
                    self.action_select.setCurrentIndex(self.action_select.findData("copy"))
                elif group is not None:
                    self.action_select.setCurrentIndex(self.action_select.findData(group_action))
                self.action_select.blockSignals(False)
                self.action_changed(self.action_select.currentIndex())
                self.notice.setText(
                    self.t["already" if already else "ready_original" if getattr(
                        plan, "with_original", False
                    ) else "ready" if plan is not None else
                           "ready_" + group_action if group is not None and not group.already else
                           "already_action" if group is not None else
                           "ready_action" if len(plans) > 1 else "unsupported"]
                )
                issue = next((comparison[key + "_issue"] for key in GROUP_ACTIONS
                              if comparison.get(key + "_issue")), None)
                if issue:
                    self.notice.setText(self.t["group_blocked"] + issue)
                if comparison.get("manual_copy_issue") and plan is None:
                    self.notice.setText(comparison["manual_copy_issue"])
                if plan is not None and plan.manual_highlight:
                    key = ("already_manual" if already else "ready_manual_original"
                           if plan.with_original else "ready_manual")
                    self.notice.setText(self.t[key])
                if (comparison.get("reading_context") and "reading_group" not in plans
                        and not comparison.get("reading_group_issue")):
                    self.notice.setText(self.t["reading_context_ready"])
                elif comparison.get("reading_context_issue"):
                    self.notice.setText(self.t["reading_context_issue"]
                                        + comparison["reading_context_issue"])
                self.old.setFocus()
            owner.status.setText(self.notice.text())
        except (OSError, ValueError, TypeError):
            self.observed = self.page = self.plan = None
            self.rows.clear()
            self.splitter.hide()
            self.notice.setText(self.t["stale"])
            owner.status.setText(self.t["stale"])

    def _domain(self, kind):
        labels = {
            "note": ("Note", "筆記"),
            "list": ("List", "清單"),
            "paper": ("Paper", "論文"),
            "membership": ("List membership", "清單收錄"),
            "reading_state": ("Reading progress", "閱讀進度"),
            "paper_document": ("Paper PDF", "論文 PDF"),
            "research_content": ("Research content", "研究內容"),
            "research_file": ("Research file", "研究檔案"),
            "list_order": ("Paper order", "論文排序"),
            "workspace_list_order": ("List order", "清單排序"),
            "inbox_item": ("Research inbox", "研究收件匣"),
        }
        return labels.get(kind, ("Other change", "其他變更"))[self.owner.zh]

    def _row_label(self, row, position):
        action = (
            ("Deleted", "刪除變更") if row["action"] == "delete" else ("Saved change", "儲存變更")
        )[self.owner.zh]
        return f"{position}. {self._domain(row['entity_type'])} · {action}"

    def _row_tooltip(self, row):
        labels = {
            "unconfirmed_not_in_backup": ("Awaiting confirmation", "尚待確認"),
            "acknowledged_after_backup": ("Confirmed after backup", "備份之後已確認"),
            "received_after_backup": ("Received after backup", "備份之後已收到"),
        }
        state = labels.get(row["category"], ("Recorded change", "已記錄變更"))[self.owner.zh]
        reference = "參考識別碼" if self.owner.zh else "Reference"
        return f"{state}\n{reference}: {row['entity_id']}"

    def _content(self, operation):
        if operation is None:
            return self.t["absent"]
        if operation["action"] == "delete":
            return self.t["retired"]
        payload = operation["payload"]
        if operation["entity_type"] == "note":
            return payload["body"]
        if note_copy.is_manual_highlight(operation):
            anchor = payload["data"]["anchor"]
            return (self.t["manual_highlight"] + "\n\n" + payload["data"]["quote"]
                    + "\n\np. " + str(anchor["p0"] + 1) + " - " + str(anchor["p1"] + 1))
        if (operation["entity_type"] == "research_content"
                and payload.get("feature") == "lineage"):
            return self._group_text([dict(feature="lineage", source=payload["data"])], "source")
        if (operation["entity_type"] == "research_content"
                and payload.get("feature") == "reading_links"):
            links = payload["data"]["body_json"]["links"]
            return "\n\n".join(link["section"] + "\n" + link["explanation"]
                                 for link in links) or self.t["reading_no_links"]
        import json

        return json.dumps(payload, ensure_ascii=False, indent=2)
