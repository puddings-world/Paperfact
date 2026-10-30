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
                 '列出本文最核心的 3–5 個論點。逐項區分作者的主張、實際證據與你的推論；'
                 '指出證據支持到什麼範圍，以及哪些部分尚未證明。'),
    ResearchTask('methods', '方法與可信度',
                 '評估本文的研究設計與識別假設。依研究類型檢查適用的比較基準、'
                 '樣本／資料選取、測量、混雜因素、洩漏、消融、統計不確定性或理論假設；'
                 '不適用的項目註明原因，不要把所有論文硬套成實驗研究。'),
    ResearchTask('figures', '圖表與數據',
                 '挑出支撐核心結論的圖表，逐項說明變數、比較對象、單位、樣本數、'
                 '不確定性與實際數值。若只有文字層而看不到圖像，明確說明；'
                 '不要推測圖中數據，也不要把百分比與百分點混為一談。'),
    ResearchTask('replication', '重現與實作',
                 '整理可執行的重現計畫：輸入資料、前處理、參數、軟硬體、評估方式、'
                 '預期可核對結果，以及缺少哪些資訊。區分作者已提供的資訊與你的建議；'
                 '列出待查的程式碼／資料授權，不要聲稱已執行或重現成功。'),
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
