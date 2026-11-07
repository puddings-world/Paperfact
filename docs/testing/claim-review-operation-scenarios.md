# 外部 agent 如何安全修訂研究主張：本輪實測

2026-11-02，隔離 `0.5.0.dev`；未發布，日常 Windows／Mac 安裝版沒有替換。
這頁保留前輪工具範圍。後續已補上[真正離線主張往返與恢復](claim-continuity-scenarios.md)；各輪結果不相加。

**兩段證據：首輪101項通過、1項失敗後停止（446.92秒）；修正驗收清單後，
相關及尚未執行群組49項通過（30.69秒），零失敗／錯誤／跳過。**
兩段各自凍結輸入、零執行中變動；中間只擴充驗收腳本與其工具數預期，產品
程式沒有改動。首輪已通過的主張／筆記／桌面案例沒有全部重跑。
兩段均使用正式 `scripts/check.py --profile focused`，隱私檢查與Ruff通過。
不將重疊案例相加，也不稱作單一整版通過。
[精確結果與選取範圍](claim-review-operation-results.json)。

## 研究者／agent 真的做了什麼

| 操作情境 | 測試如何操作 | 必須看到／保存的結果 | 對應測試 |
| --- | --- | --- | --- |
| 修改一份主張後套用 | 找保留稿、選論文、改字、保存、讀原文、確認、再重送 | 完整主張與A版來源保存一次；目前閱讀的B版不換走；後來的新分析不被舊重送覆蓋 | `test_public_claim_list_inspect_save_source_words_confirm_and_retry` |
| 多個 agent 同時重送 | 同時開同一稿8次，再重送套用4次 | 相同要求回同一結果；只有一份私稿、一個正式變更 | `test_concurrent_open_and_apply_reuse_one_private_and_formal_result` |
| 磁碟／收據寫入失敗 | 分別在開稿、私存、套用時故意使最後的收據寫入失敗 | 正式內容與同步佇列保持原狀，私稿不只存一半；原要求能重試 | `test_public_receipt_failure_rolls_back_private_and_canonical_state`，3組 |
| 核對期間別人又改字 | 原文核對後、正式提交前，另一操作先保存新私稿 | 舊套用被拒絕；新文字仍在，正式內容與同步佇列不變 | `test_late_private_edit_aborts_the_formal_transaction_without_losing_text` |
| 恢復到獨立研究庫 | 用真正備份恢復的稿分頁查看，再選目標並套用 | 能用恢復副本自己的A版來源；B版仍保持目前選取 | `test_recovered_origins_are_readable_and_editable_only_after_adoption` |
| 傳錯參數 | 傳路徑、錯誤ID、布林當版本號等7種要求 | 拒絕並保持資料庫位元組不變 | `test_bad_external_shapes_never_start_a_write`，7組 |
| 成功後重送，剛好另一工作在核對 | 先成功套用，再持有真正的來源工作鎖並重送 | 直接回已接受結果；改了要求則衝突，內容不變 | `test_accepted_apply_replay_does_not_wait_for_unrelated_source_work` |
| 新要求遇到來源忙碌 | 分別在核對、讀頁、套用時持有真正的工作鎖，再解除重試 | 回可重試的忙碌錯誤，沒有半筆保存；解除後同一要求成功 | `test_busy_source_returns_retryable_error_and_same_request_succeeds_after_release`，3組 |

上表18個案例在 `tests/test_claim_review_operations.py`；案例多於函式是因為
相同行為用多個失敗位置／輸入各跑一次，不代表18個獨立功能。

## 真正 CLI／MCP 程序，不只直接呼叫函式

| 操作情境 | 實際啟動／中斷 | 保存結果 | 對應測試 |
| --- | --- | --- | --- |
| CLI每步重開 | 每個命令啟動獨立Python程序，依序開稿、存稿、核對、讀頁、套用與重送 | 主張文字、版本、A來源與收據跨程序保留；拒絕任意來源路徑 | `test_cli_process_restart_preserves_claim_fields_and_apply_receipt` |
| CLI同時套用 | 兩個真正程序同時送相同要求 | 相同成功結果，只有一個正式變更 | `test_parallel_cli_processes_share_the_source_job_and_one_decision` |
| 唯讀恢復副本 | CLI查看真正獨立恢復資料，再嘗試開可編輯稿 | 查看不遷移資料庫；開稿被拒絕；全部位元組及schema不變 | `test_detached_cli_inspection_preserves_database_bytes_and_schema` |
| MCP重啟再繼續 | 官方MCP SDK發現工具、開／存稿、重啟server、讀回、套用、重送與更改要求 | 26個工具與權限註記正確；原稿完整、重送一次、更改要求衝突；錯型別拒絕 | `test_official_mcp_discovers_claim_tools_and_rechecks_after_server_restart` |

上表4個案例在 `tests/test_claim_review_transports.py`。

## 為什麼還測既有功能

這次共用筆記的私稿／收據邏輯，並接到原本的正式套用交易，因此首輪也測：
筆記操作與MCP、筆記邊界、桌面主張編輯、主張套用、清單建立CLI／MCP、
唯讀分析稽核，以及跨程序工作鎖；首輪在安裝包驗收的舊工具清單停止，後兩者
由後續檢查執行。兩處既有測試的工具總數由17增加為26，安裝包驗收腳本的
精確集合加入9個新工具；原工具、重試與重開檢查都保留。

## 本輪真正抓到的錯誤

已成功套用的要求原先仍會等待另一工作釋放來源鎖，最後錯報忙碌。
新增測試先失敗，再修為先查已接受收據；未完成要求仍須取得鎖並完整核對。
整合還抓到安裝包驗收腳本只接受17個工具；擴充其精確清單及數量預期後，
重跑受影響的清單整合及未執行的稽核／工作鎖群組，沒有重跑未變動的全部前段。
早先也重現兩筆相同要求同時準備來源而互相使核對失效；使用既有OS工作鎖
串行來源準備，保留原本的完整性檢查。所有失敗紀錄保留在本機證據中。

## 沒有證明的事情

- 沒有呼叫真實付費AI、重複登入帳號，或讀寫日常研究庫。
- 合成PDF與本機SQLite證明資料行為，不證明AI的學術判斷正確。
- 沒有驗收安裝包、實體Mac／手機、正式雲端、外部host設定畫面。
- 尚待真正sidecar／遠端衝突修訂、離線端修改主張後同步回來，以及其他格式。
- 整版檢查仍未通過；引用分析的新舊完成／補跑行為差異仍需解決。

[英文介面契約](../local-claim-review.md) · [整體現況](current-status.zh-TW.md) ·
[主張桌面操作與畫面](claim-draft-application-scenarios.md) · [測試入口](README.md)
