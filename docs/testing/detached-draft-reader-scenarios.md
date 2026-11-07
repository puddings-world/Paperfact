# Read human drafts after independent recovery

Updated 2026-11-01. Isolated `0.5.0.dev`; unreleased. Historical text is readable,
copyable and exportable. Fresh target/source verification and edited application
remain required; reading does not reactivate old jobs or current write authority.

| 情境 | 實際操作 | 必須看到或保存的結果 |
| --- | --- | --- |
| 禁止讀舊工作區，仍能讀出兩份恢復草稿 | 真正建立副本與備份、獨立恢復，再禁止讀取舊檔案及資料庫，檢視與匯出兩份草稿。 | 恢復區能讀出兩份正確文字，匯出不含擁有者路徑，舊來源保持不變。 |
| 一般封存與恢復區有同一草稿，不重複列出 | 把真正的恢復紀錄放到一般封存旁，每頁讀一項，再核對完整清單。 | 兩份草稿各列一次，不重複顯示一般歷史項目，完整保留兩份文字及所有恢復紀錄位元組。 |
| 恢復外層紀錄損壞時拒絕讀取，不改寫原紀錄 | 在真正的恢復紀錄中加入未知欄位、重複識別碼欄位，或改掉封存識別碼。 | 每種格式都明確拒絕，損壞與正常紀錄的位元組都保持不變。 |
| 超過單筆、項目數或總位元組限制時，不默默截斷 | 對真正恢復的工作區，分別降低單筆、筆數及總容量限制，再要求讀取清單。 | 明確拒絕，不假裝接受一部分，也不改動恢復紀錄。 |
| 外層JSON只是排版不同，草稿文字不會消失 | 只把恢復外層JSON改成縮排格式，不改內部草稿值，再檢視與匯出兩份文字。 | 兩份文字維持原樣，已排版的儲存紀錄也不被程式重新改寫。 |
| 空工作區不會冒出不存在的歷史草稿 | 開啟沒有封存與恢復紀錄的真實初始化工作區，再要求不存在的草稿。 | 清單為空，不存在的識別碼明確不可用，不捏造歷史項目。 |
| 直接備份的原始草稿，也用相同識別方式唯讀檢視 | 在已啟用的工作區保存兩份真實草稿，直接備份後恢復，核對兩份標準識別碼與文字。 | 兩份文字及原始恢復紀錄都保留，不建立舊的可執行草稿資料表。 |
| 在中英文恢復草稿視窗實際複製、匯出及取消 | 在真實Qt視窗選擇兩份草稿、複製原文、匯出檔案，再連續三次取消匯出。 | 剪貼簿與檔案包含完全相同的顯示文字、不含擁有者中繼資料，未支援編輯維持停用，恢復資料不變。 |
| 歷史草稿讀取暫停時關閉，不把結果送回已關閉視窗 | 暫停真正的預覽工作，關閉視窗後放行，再等待工作確實結束。 | 已關閉的工作階段拒絕結果，視窗保持已結束且沒有預覽，所有恢復紀錄保持不變。 |

## Evidence and limits

Current restored-reader/review/draft-CAS/native-Qt/recovery selection: **89 passed,
zero failures/errors/skips**,287.25s pytest /288.80s runner on943 unchanged inputs.
Whole Ruff passes. Existing opaque-candidate backup preservation and the older
direct recovery preview remain covered without changing their assertions.

The original current-Root audit found zero entries instead of two despite saved
records. The exact audit function now passes with old workspace files/SQL forbidden.
A second genuine direct-backup audit also initially found zero identities; raw
quarantined rows now normalize in memory to the same private archive identity.
No active old draft/job table is installed. Stored history is not rewritten.

New fixture admission: the UI passes explicit visible text to the existing export
API, so its content field is a string; the new observer was corrected to compare
that exact string. Product format and every older assertion stayed unchanged.

This uses disposable Windows SQLite/PDF fixtures and real Qt controls, not live AI,
owner research, installed Apple Silicon Mac/phone or a deployed service. Full gate
is still red at an unresolved citation-continuation policy after its missing API
was repaired. No commit, installer or release is claimed.
