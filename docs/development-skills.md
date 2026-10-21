# 開發經驗與跨 agent skills

以 `skills/` 作為唯一編輯來源，Git diff 可檢查每次規則變動。這是開發工具，
不會改動 Paperfact 使用者的 AI 帳號、研究資料或遙測同意狀態。

```text
實作／修正 → 測試與觀察 → 候選經驗
                            ↓ 檢查適用條件、隱私、證據
                     skills/*/SKILL.md
                            ↓ sync_skills.py --write
                  ┌─────────┴──────────┐
           .agents/skills        .claude/skills
            Codex、Gemini          Claude Code
```

共用內容採 `SKILL.md` 的 name / description 與相對 references，
不放特定 agent 的權限設定。依官方文件，Codex 使用
[`.agents/skills`](https://learn.chatgpt.com/docs/build-skills)，
Gemini CLI 也支援[這個共用位置](https://geminicli.com/docs/cli/skills/)，
Claude Code 使用[`.claude/skills`](https://code.claude.com/docs/en/skills)。
這些是 CLI／專案內的技能載入方式，不代表三家網頁聊天服務會自動同步。

## 使用

目前包含：

| Skill | 適用時機 |
| --- | --- |
| `agentic-pattern-harvest` | 從完成的修正整理可重用方法 |
| `agentic-provider-routing` | 功能、帳號、provider、model 解耦 |
| `agentic-usage-refresh` | 背景用量查詢、快取與跨帳號競態 |
| `agentic-private-events` | 不存問答原文的操作節點與同意機制 |

在 repo 中開啟 agent 時，可要求「使用 agentic-pattern-harvest 整理這次修正」。
Codex CLI 可用 `$agentic-pattern-harvest`，Claude Code 可用
`/agentic-pattern-harvest`；Gemini 可用 `/skills list` 檢查發現的技能，
再以自然語言要求使用。實際啟用仍受各工具版本、workspace trust、權限與
技能設定控制；未出現時重新載入技能或重啟 agent。技能安裝不需要重啟 Paperfact。

修改來源後：

```powershell
.\.venv\Scripts\python.exe scripts/sync_skills.py --write
.\.venv\Scripts\python.exe scripts/check.py
```

只檢查同步狀態用 `python scripts/sync_skills.py`；不一致會回傳非零。
完整檢查也會驗證來源與兩份產物一致，避免只改其中一個 agent 的版本。
同步先檢查全部目標，遇到本地修改會停止，不會覆寫其他技能、刪除舊檔或
安裝到使用者全域目錄。單檔替換是原子的，多檔不是交易；中斷後可重新執行。
移除／改名 skill 需明確整理舊產物與 manifest，工具會拒絕自動刪除。
目前僅同步 Markdown；新增可執行 scripts 需要另外審查同步範圍。

## 如何持續累積

AGENTS.md、CLAUDE.md、GEMINI.md 提醒開發 agent 在有意義的工作完成時檢查
是否值得更新 skill。這是工作流程提醒，不是監控背景程序；不保證每次對話
自動提煉，也不會把用戶回饋或原始聊天轉成可執行指令。

每筆經驗留下問題、決策、限制、實作／測試位置與結果。狀態區分：

- `candidate`：推測或設計，尚未驗證，先留在設計筆記。
- `validated-local`：本 repo 有實作與回歸證據，可成為附限制的 skill。
- `reused`：不同任務或專案再次驗證，逐漸成為較通用的方法。
- `retired`：前提失效或被更好的方法取代，需同步修訂 skill。

現在這三個架構模式屬於 `validated-local`，還不能稱為已跨專案驗證的範式。
「共通規則」保持簡短；案例、provider 版本限制與證據放 references 按需讀取。
可執行的通用程式碼仍應抽成 library/function，skill 負責教 agent 何時、如何使用。
MCP 適合提供實際工具呼叫介面，與這個技能內容層各有用途。

要分享至其他 repo，可把完整 skill 資料夾放進對應專案技能目錄；證據中的
Paperfact 路徑是來源標記，在另一個專案使用時應找當地實作與測試。
跨機器發佈可後續獨立成版本化的 skill repo／plugin，目前沒有全域安裝或發佈。
