# Build a reading route from a research question

Choose **建立清單 → 描述主題／研究問題**. Describe what you want to understand,
your application, background, time range and exclusions. An optional seed paper
can guide the search; a formatted bibliography is not required.

![Preview a research route before saving](images/topic-research.png)

## Choose the output

| Output | What you receive |
| --- | --- |
| 核心清單＋閱讀路徑 | Grouped papers, selection reasons, suggested reading order and research gaps. |
| 先定範圍，再逐篇深入 | A proposed question, scope and criteria alongside a reading list. Confirm the scope, save the list, then optionally start full-text analysis. |
| 逐篇文獻註解（摘要層級） | Methods, findings and limitations for each selected paper, with excerpts from retrieved abstracts. Extra model calls are required. |
| 系統性回顧規畫（PRISMA 前置） | Draft inclusion/exclusion criteria, extraction fields, appraisal plan and unresolved scope questions. This prepares a review; it does not perform formal screening or certify PRISMA compliance. |

Choose **搜尋深度** independently of the output:

| Depth | Suggested reading list | Search rounds |
| --- | --- | --- |
| 快速入門 | Up to 8 papers | Up to 1 |
| 標準調查 | Up to 16 papers | Up to 2 |
| 深入調查 | Up to 30 papers | Up to 3 |

The first round searches complementary queries. Additional rounds inspect gaps
and search for missing foundations, evaluation methods or counterevidence. These
are bounded searches: deeper means broader coverage and more model usage, not a
claim of exhaustive coverage or full-text reading. No multi-agent swarm is launched.

## Review, then save

The dialog shows the account/model for list creation. **切換 AI** changes this
feature's route. A running investigation keeps its starting connection snapshot.
It displays the current stage and elapsed time, without a fabricated percentage.
Cancellation waits for an in-flight request to return, then discards the result.

Review the branches, roles, reasons, prerequisites and gaps. Double-click a
candidate to open its retrieved source. Uncheck unwanted papers;
**以勾選文獻建立清單** saves only the checked papers. Scope-based modes also require
checking that you reviewed the question and criteria in the explanation tab.
To revise the draft scope, edit your research request and investigate again.
Renaming the list does not require another model call. Changing the topic, output
or depth invalidates the old preview. Closing an unsaved preview leaves no list.

Paper identities and links come from scholarly search results, not model memory.
Semantic Scholar is tried first; OpenAlex is a fallback when it returns no usable
results or fails. Partial search failures are disclosed. No results means no
list. Suggested prerequisites are not asserted citation edges. Missing abstracts
remain explicitly marked. Annotation evidence excerpts are copied from retrieved
abstract passages; this verifies their origin, not the correctness of every AI
interpretation. Check the source before relying on a claim.

The selected-paper route, annotations, scope plan and source/search records are
saved in **清單綜覽**, where they can be edited and included in research bundles.
Existing paper records and analyses are preserved.

## Download the originals

Discovery preserves PDF URLs and derives arXiv PDF links from verified repository
landing pages or DOI identifiers. The preview's **PDF 來源** column distinguishes
an available link from a paper that still needs a source lookup.

Opening a list automatically queues missing PDFs, at most three at once. Each row
keeps its original height. A short indicator on the title line shows download
percentages from the server's actual content length, or a waiting/lookup label
when the total is unknown. Hover for received bytes and failure details. Completed
downloads use the normal **有 PDF** tag; the progress bar disappears. Downloading
uses public sources and does not invoke AI.

Use **暫停本清單下載** or **重試／繼續下載**. Uncheck **開啟清單時自動下載 PDF**
to stop background prefetch and remember that preference. Switching lists keeps
existing jobs and their paper identities; failed jobs wait for an explicit retry
instead of restarting on every refresh. Shared papers are downloaded once.

HTML login pages, unreadable PDFs and incomplete transfers are rejected. Partial
files are cleaned up; existing originals are preserved. The reader and analysis
downloader share a file lock with background prefetch. Closing waits for active
requests to stop and clean up, so it can take a few seconds. A source may refuse
access or have no open PDF; **補 PDF** remains available from the paper's context
menu. Downloads are limited to 150 MB per file.

## Continue with full-text AI analysis

After saving, **開啟清單並逐篇深入分析…** offers a separate confirmation explaining
time and usage. It opens that list and uses the existing analysis pipeline and
each analysis feature's configured account/model, with login checks. This obtains
available PDFs and fills missing paper analyses; unavailable papers can remain
incomplete. Opening a list can download PDFs, but does not start AI analysis.

The list overview is not automatically rewritten after analysis. Update it from
the list overview when ready, and verify evidence missing from the abstracts.
A systematic review still needs documented screening decisions, exclusions,
appropriate quality assessment and synthesis. [PRISMA 2020](https://www.prisma-statement.org/prisma-2020)
is a reporting guideline; this output is a planning aid, not a completed review.

To import an existing bibliography, use **貼上參考文獻／已知論文清單** instead.
Public search references: [Semantic Scholar](https://api.semanticscholar.org/api-docs/graph),
[OpenAlex](https://help.openalex.org/api/). Coverage and availability depend on the
upstream indexes; this workflow does not require their optional API keys.
