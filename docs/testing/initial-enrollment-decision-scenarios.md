# Review decisions before first sync

Updated 2026-11-01. Isolated `0.5.0.dev`, unreleased. This adds private decision
history preservation, not saved edited-draft resumption or complete sync.

## What the researcher can do

After explicitly applying or keeping a retained research result, prepare a new
sync copy without losing the decision record or its declared original PDF.
The original database stays unchanged. Decision history remains private metadata;
it never recreates an old job, authorizes a write, or follows an observed path.
The copy preview names its retained decision-history count in English/Chinese.

## Actual actions and visible or stored outcomes

| 情境 | 實際操作 | 必須看到或保存的結果 |
| --- | --- | --- |
| 套用或保留審閱結果，再建立獨立副本 | 使用真正測試 PDF 建立過期提案，明確選擇目標後，以同一請求重試套用或保留。 準備同步副本與完整備份，再恢復到獨立資料夾。 | 已存研究內容與私人決策紀錄逐字一致；新副本不建立舊工作或審閱權限。 備份包含正確原文；來源資料庫及 PDF 保持不變。 |
| 只有決策歷史還引用的原文，也必須保存 | 保留真正的提案後清理舊工作紀錄，把主 PDF 換成 B 並另存 A。 分別測試 A 存在、缺檔、被其他內容取代時建立副本。 | A 存在時，完整備份包含逐位元相同的原文。 A 缺失或變更時拒絕檢查與建立，不留下半套副本或備份。 |
| 解析歷史紀錄，不取得檔案或資料庫權限 | 替真正的決策紀錄加入不影響意義的 JSON 空白。 禁止建立 SQL 連線及開檔，再進行封存與驗證。 | 逐字保留原始字串，只回報宣告的來源雜湊。 不建立 SQL 連線或開檔；單靠這個解析案例不能證明 PDF 存在。 |
| 拒絕格式損壞的決策，不猜測其意思 | 逐項改成未知欄位、決策不一致、錯誤型別、重複 JSON 鍵、非有限數字或過長識別碼。 嘗試封存每種格式，並比對原資料庫位元組。 | 每一種損壞格式都以驗證錯誤拒絕。 來源資料庫不變，紀錄不會變成可執行操作。 |
| 未宣告 PDF 的決策，仍可完整保存 | 將合法未宣告來源的紀錄封存後讀回。 再修改內部請求識別碼，但保持外層封存識別碼不變。 | 紀錄逐字一致，需要的原文集合保持空白。 遭改動的封存會被拒絕，不捏造 PDF 來源。 |
| 取消或建立失敗後，能明確重試 | 分別在檢查後取消、建立中改動決策紀錄、最後發布資料夾時故意失敗。 確認沒有半成品，恢復後重試，再嘗試寫入已存在的目的地。 | 失敗不發布副本或備份；PDF 位元組不變。 重試只保存一份正確紀錄，既有目的地不會被覆寫。 |
| 副本視窗以中英文顯示決策歷史，連點不重複建立 | 用英文及繁體中文打開真正的副本視窗，重複要求檢查。 選擇新的副本及備份路徑，連按兩次建立，再讀取已存封存內容。 | 顯示可理解的決策歷史名稱與數量；兩個目的地未選好前不能建立。 只保存一份逐字相同的紀錄，完成後能開啟副本，原資料庫保持不變。 |

## Evidence and limits

Shared enrollment/review/draft/backup/Qt selection: 158 cases,
zero failures/errors/skips, 370.41 seconds including runner overhead,
936 unchanged source/test/script inputs. This is a selected gate,
not a whole-application pass. Ruff passes. No real AI, account, owner research,
deployed service, installed Mac or phone was used. Reviewed explanations cover all
7 new functions /26 expanded cases; this does not explain the whole suite.

The genuine pre-fix workflow refused `unsupported table: research_review_receipts`.
New fixture corrections retain the exact saved-receipt assertion: detached restore
uses `recovery_records.data`; `close_readings` has no document_hash column; missing
originals use the maintained explicit ValueError rather than returning a supported
plan. Early failures and beforeimages remain in build receipts; no old test changed.

Saved edited drafts, capture candidates, file/compound/integration formats,
fresh explicit reattachment, complete source/history propagation, full verification,
production identity/service and physical-device acceptance remain required.
No commit, installer, deployment or release is claimed.
