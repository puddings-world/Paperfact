# Recover a draft and continue researching

Updated 2026-11-01. Isolated `0.5.0.dev`, unreleased. Desktop text resumption now
uses a fresh receiver target and process-only byte verification. No AI is called.

目前可接續：深度分析、逐段精讀、研究脈絡、清單文獻調查及閱讀目標的文字草稿。
原稿保持唯讀；「繼續編輯」先選目標、核對來源，之後另存編輯、確認套用。
重開後必須重新核對，不能把上次核對的資料當成永久權限。沒有來源紀錄的文字會維持未指定來源。

共用審閱／草稿／恢復／原文驗證 **183 項通過**（520.95 秒）；舊來源／副本／歷史備份另 **30 項通過**（92.73 秒）。兩批使用相同 946 個輸入，執行中零來源變動、零失敗／錯誤／跳過。這些是局部驗證，不是完整 App 通過。

| 情境 | 真正操作 | 必須看到或保存的結果 |
| --- | --- | --- |
| 重開後核對 A、編輯套用，保留目前 B | 將編輯私存後重開，核對真正的 A；未確認時拒絕套用，確認後套用，再重試相同請求。 | 只增加一份來源、一項研究變更及一筆決策；原稿、舊資料庫和目前 B 的內容維持原樣。 |
| 未選或已不存在的目標不會寫入研究 | 分別以空字串、不存在的論文及未選目標嘗試接續。 | 每次都拒絕，原稿文字與所有待同步操作保持相同。 |
| 缺少 A 時保留編輯，補回後可重試 | 移走接收端保存的 A，儲存編輯並核對；再補回相同 A 後重試。 | 失敗不發布資料且編輯仍在；重試核對 A，不拿目前 B 代替。 |
| 研究、論文或選用 PDF 變動時拒絕舊預覽 | 先核對草稿，再分別修改研究、重新命名論文或替換選用 PDF，嘗試套用及再次核對。 | 兩種操作都拒絕改過的狀態，新研究、待同步資料與已存草稿不被覆蓋。 |
| 決策儲存失敗時，來源與研究一併撤回 | 來源與文字寫入後，模擬決策紀錄無法儲存；恢復後重試同一請求。 | 失敗不改來源版本、研究或待同步資料，草稿仍在；重試只建立一次兩項操作。 |
| 八次同時套用只提交一份結果 | 四條工作執行緒送出八次相同文字與請求，之後用相同請求改送另一段文字。 | 相同請求得到相同決策，只存一組來源與研究及一筆決策；不同文字的重試被拒絕。 |
| 兩個視窗不會覆蓋彼此的草稿 | 第二個審閱工作階段先更新同一草稿，第一個再用舊版號儲存。 | 舊版儲存被拒絕；先存的文字與版號維持，另一份文字仍能匯出，正式研究不變。 |
| 核對途中關閉，文字保留且不晚寫入 | 讓真正的來源暫存工作暫停，關閉審閱後放行，等待同一工作結束。 | 已關閉工作階段拒絕結果，不增加待同步資料；重開仍有已存文字，重新核對前不能套用。 |
| 接續文字與 A／B 能再次備份獨立恢復 | 儲存並接受接收端編輯，再完整備份、恢復至另一個資料夾。 | 備份有正確 A 與 B，恢復研究有新文字，三份歷史草稿可讀，新的私有草稿紀錄完整相同。 |
| 備份仍拒絕被改過或未納入的 PDF | 套用後分別改動歷史 A，或新增未被研究紀錄納入的 PDF，再要求完整備份。 | 備份拒絕且不產出半套檔案，資料庫與改過的 PDF 位元組保持原樣。 |
| 接續只使用接收端檔案，不讀舊路徑 | 禁止讀取原工作區的檔案及資料庫，再在接收端選目標、核對並套用。 | 接收端能儲存正確文字，舊資料庫位元組維持相同。 |
| A 核對後被改動，不能沿用先前證明 | 核對 A 後改動其暫存物件內容，保存編輯並確認套用。 | 套用被拒絕，不新增待同步操作、不覆蓋研究，已存編輯仍在。 |
| 無原文紀錄的手動文字不冒用 B 的來源 | 目前有 B 時建立真正未綁原文的候選與草稿，封存後明確接續套用。 | 預覽區分目前 B 與未記錄來源；只新增研究操作，來源保持未指定。 |
| 其餘文字格式都能接續到指定論文或清單 | 對深度分析、研究脈絡、清單調查與閱讀目標建立真正候選、保存封存草稿，再指定論文或清單套用。 | 目前版本與私存文字分別顯示，套用文字與草稿識別正確，不捏造 PDF 來源。 |
| 以中英文真實選目標與確認視窗接續 | 連按繼續編輯、真的選目標並編輯儲存，先取消再按 Yes，連按套用後關閉重開。 | 只核對一次，顯示 A／B 正確版本，取消不改研究，只提交一份結果；重開仍有文字且不自動再套用。 |
| 取消選目標時，原稿維持唯讀且不寫入 | 從歷史草稿開啟真正的目標視窗後取消。 | 預覽與顯示文字完全相同，套用停用，不建立私有草稿或研究操作。 |
| 視窗核對失敗時保留原稿，補檔後可重試 | 移走 A，在視窗選目標並等待失敗；補回 A 後再選一次。 | 失敗有原因，原稿維持唯讀、不改研究；重試後能編輯，原文字仍相同。 |
| 核對中的結果不會送到另一份草稿或已關閉視窗 | 暫停來源核對，分別關閉真正視窗或切到另一份草稿，再放行並等待原工作。 | 關閉後拒絕結果；切換後另一份原稿維持選用與唯讀，兩種情境都不發布研究。 |

## Evidence and limits

The original receiver audit failed because no resumption entry existed. The new
full-flow assertion then caught source A missing from the research outbox; the
source expectation now spans the actual caller-owned commit and receipt. Another
real re-backup audit exposed an owned-object fast path overlooking the duplicate
historical PDF; that path now verifies referenced aliases. Changed or unknown PDF
content still blocks a complete backup and leaves data/output unchanged.

New fixture corrections did not weaken product assertions: competing generation
requests use independent identities; exact PDF comparisons reuse captured bytes
rather than a separately randomized PDF; Qt confirmation clicks the actual button.
An isolated native reproduction found `done(Yes)` returns NoButton, whereas
clicking Yes returns Yes. The held new harness was explicitly stopped and is not
reported as a pass. Existing test files and assertions remain unchanged.

This edit-only set does not exercise typed note/claim/highlight/deck resumption.
The text-draft original viewer now has [separate scenarios](draft-original-scenarios.md). Detached recovery first needs an explicitly adopted
editable workspace; old paths/bindings never grant authority. Exact-source staging
does not certify scientific support. New-format peer transfer, remaining writer/
history formats, grounded lineage, durable audits, production identity/service,
full check, installers and actual Windows/Mac/phone acceptance remain required.
The known citation continuation/completion policy discrepancy still prevents a
current full green gate. No commit, push, installer or release is claimed.
