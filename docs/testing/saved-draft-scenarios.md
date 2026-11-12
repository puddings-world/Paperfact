# Saved draft preservation and inspection

Updated 2026-11-01. Isolated `0.5.0.dev`; unreleased. This is the implemented
preserve/inspect slice, not the full saved-draft resumption requirement.

| 情境 | 真正做了什麼 | 必須看到或保存的結果 |
| --- | --- | --- |
| 同一請求的兩份草稿，在副本與備份中各自保存 | 用同一請求識別碼保存兩份不同草稿，重新開啟變體清單。 建立副本與備份，獨立恢復後讀取私人恢復紀錄。 | 兩份紀錄、原始JSON字串與正確PDF位元組都完整保留。 不建立舊的可執行草稿資料表，也不把私人請求識別碼送進研究同步操作。 |
| 在準備好的副本中，分別讀取與匯出歷史草稿 | 準備包含兩份真實草稿的副本，開啟真正的審閱服務。 分別讀取歷史預覽，匯出各自的文字。 | 兩份不同文字都讀得到，預覽不能編輯或套用目前研究。 匯出文字不包含舊資料庫路徑及原生資料庫識別資訊。 |
| 中英文視窗顯示正確草稿，未核對前禁止寫入 | 用中英文開啟副本的真實視窗，逐項選擇草稿。 複製文字，直接嘗試套用與保留服務，關閉後檢查歷史和待同步資料。 | 顯示可理解的歷史草稿名稱與原文字，未支援操作停用。 複製不帶入原擁有者中繼資料，歷史與待同步資料不變，也不建立決策收據。 |
| 即使重新計算指紋，也拒絕損壞的草稿快照 | 逐項改動重複JSON欄位、型別、版本、父項識別與欄位、顯示資料、來源型別或文字長度。 重新計算私人指紋後，再嘗試封存每種損壞格式。 | 每種格式都明確拒絕，不因指紋相符就誤收。 來源資料庫位元組完全不變。 |
| 逐字驗證歷史字串，不開啟舊擁有者資料庫 | 保留擁有者JSON的合法空白，重新計算私人指紋。 禁止開檔及實體SQL連線，只允許可信的記憶體結構檢查，再進行驗證。 | 原始字串逐字保存，只回報宣告的PDF識別。 不開啟歷史路徑；單靠解析測試不能證明PDF存在。 |
| 真實遠端衝突草稿，作為私人紀錄保存 | 讓兩個測試裝置真正產生衝突，再保存編輯後的審閱草稿。 完整讀回紀錄，再把待處理布林值改成數字並重新計算指紋。 | 合法紀錄完整保留為私人中繼資料。 拒絕變造的觀察值，不把舊衝突狀態當成目前寫入權限。 |
| 驗證真實第二版衝突關係，拒絕變造的目前版本 | 讓真實清單綜述產生衝突，保存當時顯示的審閱基準。 分別測合法資料及活動型別、未知欄位、父項版本、外來或重複版本標頭、顯示內容遭改動。 | 合法的私人關係快照逐字保留。 即使重新計算指紋也拒絕所有變造格式，舊觀察紀錄不授予寫入權限。 |

## Coherent evidence and remaining journey

The authoritative combined citation/draft/review/recovery/Qt selection passed
**240 cases, zero failures/errors/skips**,551.56s pytest /553.88s runner on942
unchanged source/test/script inputs. No old assertion changed. Whole Ruff passes.
Historical133 and99/8 selections overlap this gate; do not add them as new work.

The original two-variant workflow failed at unsupported research_review_drafts.
After archive support it passed storage/recovery but failed to find readable
draft entries. Actual service/Qt inspection then passed. New fixture admission:
the maintained draft-list API returns an items/next envelope, not a raw list;
the new observer was corrected without dropping its two-variant assertion.

The formerly failing detached-reader audit is now repaired, including direct
backups, deduplication, formatting, bounds and actual bilingual Qt actions.
[Current reader evidence](detached-draft-reader-scenarios.md). The evidence above
is the earlier preservation snapshot, not the newer reader execution.
Fresh current-target/source verification and reviewed edited application remain
required by the [full contract](../review-draft-resumption.md).

No live model/account, owner research, installed Mac/phone, hosted service or
scientific-quality evaluation was used. Full default check is still not green;
the pending citation continuation/completeness rules remain explicit. No commit,
push, installer, deployment or release is claimed.
