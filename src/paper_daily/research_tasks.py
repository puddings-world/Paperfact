"""Field-neutral research tasks, independent of providers and document storage.

These draft questions for the existing grounded Q&A workflow. They are not an
agent runtime, a citation validator, or evidence that an experiment was reproduced.
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class ResearchTask:
    id: str
    label: str
    instruction: str


TASKS = (
    ResearchTask('evidence', '論點與證據',
                 '整理本文最多 5 個核心論點；若數量不足就照實呈現，不要湊數。'
                 '逐項區分作者的主張、直接證據或理論推導與你的推論；'
                 '指出適用範圍、替代解釋與尚未證明的部分。'),
    ResearchTask('methods', '方法與可信度',
                 '先依原文說明研究類型；無法判斷時標示待確認。'
                 '實證研究檢查資料選取、測量、比較、混雜因素、識別假設與不確定性；'
                 '理論研究檢查定義、前提、關鍵推導或證明步驟與適用邊界；'
                 '質性研究檢查材料與情境、研究者立場、分析過程與反例。'
                 '混合方法或文獻研究可組合適用項目，區分原文明示與你的判斷，說明缺少哪些資訊。'
                 '不要硬套消融或統計檢定，不用通用分數或期刊名聲代替評估；'
                 '閱讀檢查不等於已完成形式化驗證。'),
    ResearchTask('figures', '圖表與數據',
                 '挑出支撐核心結論的圖表，逐項說明變數、比較對象、單位、樣本數、'
                 '不確定性與實際數值。若只有文字層而看不到圖像，明確說明；'
                 '不要推測圖中數據，也不要把百分比與百分點混為一談。'),
    ResearchTask('replication', '重現與實作',
                 '提出與研究類型相符、尚未執行的核對或重做計畫。'
                 '可選同一資料／程式的核對、獨立資料重做、證明重查或質性材料／分析流程查核；'
                 '只選適用方式，說明步驟、預期可核對的結論、必要資源與缺少的資訊。'
                 '區分作者已提供的材料與你的建議，列出待查的資料取得或授權條件；'
                 '不宣稱已執行、重現成功或完成形式化驗證。'),
    ResearchTask('lineage', '前作與研究脈絡',
                 '解釋本文想解決前作的哪個問題、改變哪些假設或設計，以及仍留下什麼缺口。'
                 '只有讀過相應原文才可比較前作或後續研究；僅出現在本文參考文獻中的工作'
                 '標示為作者描述、待查原文，不能當作已核實的歷史或因果關係。'),
    ResearchTask('next', '延伸我的研究',
                 '根據本文的限制提出可檢驗的研究問題。每個問題列出依據、可推翻它的證據、'
                 '最小驗證方案、必要資源與風險。區分本文發現、你的假設與待文獻查證的事項；'
                 '不要在未檢索相關文獻時聲稱想法新穎或從未有人做過。'),
)

EVIDENCE_RULES = (
    '只依本次實際提供的論文與材料作答。重要判斷附上短原文與可核對的章節／圖表位置；'
    '若資料包含可靠頁碼則附頁碼，沒有則不要編造。引用與你對引用的解讀分開呈現。'
    '原文未報告、未取得的全文、無法核實的引用都明確標記，不要補成事實。'
    '如來源不足，先列出缺少什麼與下一步如何查證。不要為各項判斷編造信心百分比。'
)


def question(task_id: str, *, goal: str = '') -> str:
    task = next((item for item in TASKS if item.id == task_id), None)
    if task is None:
        raise ValueError('Unknown research task')
    if not isinstance(goal, str) or len(goal) > 2000:
        raise ValueError('Research goal must be at most 2000 characters')
    context = f'\n\n我的研究目的：\n{goal.strip()}' if goal.strip() else ''
    return f'{task.instruction}{context}\n\n證據要求：\n{EVIDENCE_RULES}'
