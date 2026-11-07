# Citation results: actual operations and remaining policy

Updated 2026-11-01. Isolated `0.5.0.dev`; unreleased. No existing test changed.

The default full check passed privacy/Ruff and392 Python cases, then stopped at
the missing `cites.analyse_result` entry point. Frontend/mobile were not reached.
That attempt took 467.486 seconds including runner overhead. It was a
failure, not a complete pass. Its unchanged-input receipt remains retained.

The entry point now shares the ordinary analysis lock, explicit database/account
scope, source inputs and compound publication. The integer caller delegates to
the same result operation; callers can also read an honest reason for failure,
an absent target, an existing job, or a retained stale result. No extra model call
or change to source-verification/continuation policy is introduced.

| 操作 | 實際驗證結果 |
| --- | --- |
| 回傳數量與詳細結果，共用同一套核對及儲存流程 | 回傳已存兩項及空原因，資料庫確實保存引用 1 與 2。 背景核對原文後才回報完整；只讀介面中繼資料不能宣稱已核對。 |
| 無效或空白 AI 回覆，說明原因且不假裝存好 | 回傳零項及服務、格式或空白答案的實際原因。 不新增引用或工作收據，也不變更待同步操作。 |
| 重複工作或找不到目標時，不呼叫 AI | 回報進行中或找不到論文，不啟動第二份工作。 研究資料庫位元組保持不變。 |
| 目標中途改變時，保留產出但不覆蓋研究 | 回傳零項已發布內容，並說明產出已保留。 不覆蓋目前研究，候選紀錄仍保留兩項產生的引用資料。 |

Selected API/compound/source-coverage/multi-root tests: **133 passed**, zero
failures/errors/skips,197.78s pytest /199.11s including runner.
All source/test/script inputs stayed unchanged. These are disposable fixtures,
not live accounts, installed Mac/phone or a deployed service.

Two unchanged legacy prose/fragment cases pass. The unchanged auto-fill case
still expects ten references from two replies while the current single-attempt
operation retains one reference and reports1/10. This is an explicit pending
behavior decision, not an assertion to weaken. A separate old count-based
completeness expectation conflicts with the newer verified-source rule.
Owner questions are pending; no answer or approval has been assumed.

Do not repeat the whole suite while that known policy boundary remains open.
Continue independent features, resolve approved behavior coherently, then obtain
the full green check before commit/push/installers/release. Source-bound reading
state, attachments, history, resumption, mobile and external delivery gates remain
in the v0.5 roadmap; this API repair does not finish them.
