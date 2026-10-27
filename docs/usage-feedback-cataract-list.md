# Usage notes from the Cataract list, 2026-10-27

Context: one researcher keeps a 63-paper "Cataract" list and reads it along two
lines at once, a venue survey (what MICCAI is doing) and a dataset-gap survey
(what a new regional dataset should enable). Papers were added through the MCP
import tools from a Claude Code session. Everything below comes from that use.

## In one paragraph

Paperfact is built around reading one paper well; a topic list is read as a set,
and that is where it ran out of features. The import flow itself was sound: the
preview caught two papers already present from other lists and reused them, the
`reason` field carried a "why read" note that shows as a tag, and no step needed
an AI call. What was missing was everywhere after import. The reason cannot be
edited later, so the only per-paper label the list has is frozen at import time.
There is no way to attach a line or tag to a paper, so the two reading lines had
to be tracked in a Markdown table in the research repository instead of in the
list. There is no list-level view of fields across papers (task, method,
evaluation data, number of centres, licence, stated limitations), so the
dataset-gap survey, which is exactly a matrix of papers by fields with the empty
cells being the finding, cannot be done inside the app. The deep-dive output is
per paper and cannot be aggregated, so quoting every limitation section across
the list means opening each paper. And the venue sweep that found the missing
MICCAI papers was a script outside the app: given a proceedings index, report
what the list lacks. The data model already supports all of this (papers are
shared records, lists are membership); the gap is the list-level UI and a
small amount of schema.

## Concrete requests, in the order they would have helped

1. Editable `reason`, or a separate per-paper tag field on list membership, with
   the tag shown and filterable in the paper table.
2. List-level fields: a list declares a few named columns, 深入分析 fills them
   from the text with a passage link, and the list view shows the matrix with
   sort, filter and CSV export. Pairs with the planned per-list reading goal.
3. Limitation harvest: collect each paper's limitation / future-work sentences
   across a list, grouped, each linked to its passage.
4. Venue sweep: given a proceedings index URL, list papers not in the list with
   their abstracts, for one-click proposal.
5. Datasets as entities (name, licence, centres, size) referenced by papers, so a
   list can answer "who used what data".

Not requested: anything that calls AI during import, or any change to the
one-paper reading flow, which worked as intended.

## Triage, 2026-10-27

| Request | Decision | Where |
|---|---|---|
| 1. Editable reason, tags | Done now: right-click **編輯閱讀理由與 #標籤…** rewrites the list note (`list_papers.citation`, already a synced membership field); `#tags` show on the row and typing `#tag` in the search box filters to them. No schema change. | current |
| 2. List-level fields matrix | 0.5, with per-list reading goals: a goal declares the columns, 深入分析 fills them with claim-level source links, and the list view shows the matrix with CSV export. Needs the claim-source model first. | 0.5 |
| 3. Limitation harvest | 0.5, as a reading-goal lens on the existing 清單綜覽 (`list_surveys`): collect limitation / future-work sentences per paper, each linked to its passage. | 0.5 |
| 4. Venue sweep | 0.5, as an optional list automation module (see agent-workflows.md, 追新論文): given a proceedings index, propose missing papers through the existing preview/commit import. | 0.5 |
| 5. Datasets as entities | After 0.5: a new entity type touches the sync schema, bundles and mobile; design it once fields (2) show which attributes are needed. | later |
