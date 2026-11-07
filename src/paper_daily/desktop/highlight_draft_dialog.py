"""Native highlight review with typed source verification and atomic group application."""

from paper_daily.desktop.claim_draft_dialog import LABELS as COMMON_LABELS
from paper_daily.desktop.claim_draft_dialog import StructuredDraftDialog
from paper_daily.desktop.structured_review_modes import HighlightMode

LABELS = dict(COMMON_LABELS)
LABELS.update(
    {
        "title": ("Revise original highlights", "修訂原文重點"),
        "highlights": ("Original highlights", "原文重點"),
        "quote": ("Exact original quotation", "原文完整引句"),
        "reason": ("Why this passage matters", "為何值得畫重點"),
        "quote_hint": (
            "Copy a complete quotation from original A (at least 20 characters).",
            "從原文A複製完整句子（至少20字元）。",
        ),
        "reason_hint": (
            "Explain its role, evidence or limitations for your research.",
            "說明對研究問題、證據或限制的重要性。",
        ),
        "role": ("Research role", "研究角色"),
        "role_problem": ("Problem", "研究問題"),
        "role_contribution": ("Contribution", "貢獻"),
        "role_method": ("Method", "方法"),
        "role_evidence": ("Evidence", "證據"),
        "role_limitation": ("Limitation", "限制"),
        "role_definition": ("Definition", "定義"),
        "add_highlight": ("Add highlight", "新增重點"),
        "occurrence": ("Repeated quotation location", "重複引句的位置"),
        "choose_occurrence": ("Choose a matching passage…", "選擇對應原文段落…"),
        "occurrence_at": ("Match {index} · page {page}", "位置{index} · 第{page}頁"),
        "restore": (
            "Restore deleted analysis or selected highlights",
            "恢復已刪除的分析或所選重點",
        ),
        "not_located": (
            "Some quotations need a location; repair them and check again.",
            "部分引句尚未定位；請修正後重新核對。",
        ),
        "loc_invalid_anchor": ("Invalid location", "位置無效"),
        "loc_source_changed": ("Source changed", "來源已變更"),
        "target": ("Select the paper to revise…", "選擇要修訂的論文…"),
        "choose": ("Review target", "審閱此論文"),
        "verification": ("Quotation locations", "引句位置"),
        "cancel": ("Cancel work", "取消工作"),
    }
)


class HighlightDraftDialog(StructuredDraftDialog):
    def __init__(self, database, origin, identity, parent=None, *, language="en"):
        super().__init__(
            database,
            origin,
            identity,
            parent,
            language=language,
            mode=HighlightMode(),
            labels=LABELS,
        )
