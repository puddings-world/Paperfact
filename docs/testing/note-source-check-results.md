# 本輪實際驗收結果：筆記位置與來源身分

2026-11-01，隔離 `0.5.0.dev`，尚未發布。這是實際執行結果，不是只收集測試名稱。

本輪來源位置／檔案庫邊界 **21 項通過**（350.86 秒整輪）；文字／筆記／原文視窗互動 **56 項通過**（573.89 秒）。相同 960 個程式與測試輸入，執行中零變動、零失敗／錯誤／跳過。這是指定範圍，不是整版通過。

下面展開本輪新增的 **23 個案例**；它們已包含在上面兩組，不能再相加。
耗時包含隔離資料準備、衝突、備份／恢復與收尾，不代表使用 App 按一次按鈕的延遲。

| 實際驗收項目 | 結果 | 案例合計耗時 |
| --- | --- | --- |
| 引用不存在的詞時，保留人工稿並拒絕套用 | 通過 1/1 | 27.64 秒 |
| 核對後換綁或替換檔案庫，不能沿用舊資格 | 通過 4/4 | 117.50 秒 |
| 歷史缺件或遭改動時拒絕，補回後讀得到兩份稿 | 通過 2/2 | 49.71 秒 |
| 有位置卻沒有 PDF 版本的草稿，不冒用目前原文 | 通過 2/2 | 47.42 秒 |
| 草稿頁碼超過其原文時不套用 | 通過 1/1 | 23.64 秒 |
| 新增無關快取，不會被誤當成換綁 | 通過 1/1 | 24.54 秒 |
| 重新核對失敗，舊的套用資格立即失效 | 通過 1/1 | 30.76 秒 |
| 指定另一筆筆記，保留接收端身分與建立時間 | 通過 1/1 | 27.07 秒 |
| 真正存在的單詞與跨頁位置可通過 | 通過 3/3 | 0.03 秒 |
| 旋轉標籤、缺字位置與倒置範圍不算有效引用 | 通過 4/4 | 0.02 秒 |
| 同頁的兩個端點只解析一次 | 通過 1/1 | 0.01 秒 |
| 原文失效後關閉視窗、停用套用，修復後可重試 | 通過 2/2 | 52.61 秒 |

每項到底做什麼、必須保存什麼，見[逐項操作說明](note-source-boundary-scenarios.md)。

## 哪些還不能從這份結果推論

整版最後仍是 392 項通過後遇到 1 項失敗，沒有新的完整通過；前端／手機階段未到達。
這輪沒有測真實 AI 登入／學術品質、Mac／手機安裝版或正式同步服務。
位置來源對應介面、更多父層／跨論文情境與其餘恢復類型仍待完成。

<details><summary>來源對照與可重現紀錄</summary>

同版本來源地圖與 JUnit 在 ignored `build/`：`note-boundaries-final`、
`note-owner-ui-interactions` 的 `-inputs.json`、`-result.json`、`.xml` 及 `.log`。
公開追蹤的情境與來源雜湊在 `docs/testing/catalog.json`；本機整合證據以該工作區為準，
不代表 canonical checkout 的程式已替換或有可下載安裝包。

- `tests/test_note_draft_boundary_controls.py::test_note_word_anchor_outside_actual_original_refuses_without_writes` · `55368a19a8d74be31ce72055e832bc58f89bcd05e3f463cc3bddf68a52f5fdf8`
- `tests/test_note_draft_boundary_controls.py::test_late_recovered_store_rebind_revokes_apply_and_original_revalidation` · `55368a19a8d74be31ce72055e832bc58f89bcd05e3f463cc3bddf68a52f5fdf8`
- `tests/test_note_draft_boundary_controls.py::test_incomplete_or_changed_provenance_refuses_then_repair_restores_both_variants` · `55368a19a8d74be31ce72055e832bc58f89bcd05e3f463cc3bddf68a52f5fdf8`
- `tests/test_note_draft_boundary_controls.py::test_position_without_a_recorded_pdf_remains_a_private_unresolved_draft` · `55368a19a8d74be31ce72055e832bc58f89bcd05e3f463cc3bddf68a52f5fdf8`
- `tests/test_note_draft_boundary_controls.py::test_note_page_outside_exact_a_never_uses_current_b_instead` · `55368a19a8d74be31ce72055e832bc58f89bcd05e3f463cc3bddf68a52f5fdf8`
- `tests/test_note_draft_boundary_controls.py::test_unrelated_cache_write_allows_same_source_revalidation_and_note_apply` · `55368a19a8d74be31ce72055e832bc58f89bcd05e3f463cc3bddf68a52f5fdf8`
- `tests/test_note_draft_boundary_controls.py::test_failed_reverification_revokes_old_apply_proof_and_retry_preserves_private_text` · `55368a19a8d74be31ce72055e832bc58f89bcd05e3f463cc3bddf68a52f5fdf8`
- `tests/test_note_draft_boundary_controls.py::test_explicit_other_note_target_preserves_its_creation_identity_and_original_target` · `55368a19a8d74be31ce72055e832bc58f89bcd05e3f463cc3bddf68a52f5fdf8`
- `tests/test_pdf_selection_ranges.py::test_valid_single_word_and_cross_page_positions_are_accepted` · `62a4abde28bfe3e4e6ace1b4af813faeb695a633b50ca3996d97726dffd1b517`
- `tests/test_pdf_selection_ranges.py::test_rotated_missing_and_reversed_endpoints_cannot_claim_a_selectable_location` · `62a4abde28bfe3e4e6ace1b4af813faeb695a633b50ca3996d97726dffd1b517`
- `tests/test_pdf_selection_ranges.py::test_verifying_a_range_extracts_only_its_two_endpoint_pages` · `62a4abde28bfe3e4e6ace1b4af813faeb695a633b50ca3996d97726dffd1b517`
- `tests/test_note_draft_resumption_ui.py::test_rebound_source_invalidates_native_view_and_failed_recheck_disables_apply_until_retry` · `e7959a5b83533ef2bed77e219d6060501eee17df316e66661b410fbb824454fc`

</details>

[功能地圖](acceptance-overview.html) · [中文現況](current-status.zh-TW.md)
