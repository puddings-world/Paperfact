"""Versioned local usage acknowledgement, independent of optional analytics."""

from datetime import UTC, datetime

from paper_daily import feedback

POLICY = "paperfact-usage-v1"
TEXT = (
    "Paperfact 將清單、論文與研究資料保存在你的電腦。\n\n"
    "使用 AI 功能時，相關內容會傳送到你選擇的 AI 服務，並依該服務方案計算用量。"
    "請先確認使用的帳號與模型；閱讀已匯入的內容不需要登入 AI。\n\n"
    "分享研究資料包時，請確認其中的論文、筆記與分析適合分享；"
    "資料包不包含你的 AI 登入憑證。"
)


def accepted():
    if not feedback.path().exists():
        return False
    with feedback._connect() as db:
        return bool(db.execute(
            "SELECT 1 FROM app_agreements WHERE purpose='usage' AND version=?", (POLICY,)
        ).fetchone())


def accept(*, analytics):
    if type(analytics) is not bool:
        raise ValueError("Analytics choice must be a boolean")
    timestamp = datetime.now(UTC).isoformat()
    with feedback._connect() as db:
        db.execute("BEGIN IMMEDIATE")
        feedback._save_choice(db, analytics, True, timestamp)
        db.execute("INSERT OR REPLACE INTO app_agreements VALUES ('usage', ?, ?)",
                   (POLICY, timestamp))
