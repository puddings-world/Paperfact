# Paper identity: finding and merging duplicate records (v0.5)

Status: detection implemented (`paper_identity.find`, `paperfact duplicates`);
merge proposed below, not implemented. Branch `feature/0.5-paper-identity`.

## Why

One paper stored as two records splits the reader's work: notes and analysis on
one, the list membership on the other, and the list shows it twice. Duplicates
already exist in a single library, before any sync:

- **Roster against Semantic Scholar.** S2 files papers under their first-posting
  year, so the ICLR 2017 S2 fallback holds many ICLR 2018 papers a second time.
- **Roster against proceedings.** Virtual-site ids (`ICML:2026:v63808`) and
  proceedings ids (`ICML:2026:kavak26a`) for the same paper.
- **List import against the corpus.** `import-list` creates `ref:` records even
  when the corpus already holds the paper (STaR, ReasoningBank, SkillOS).

Cross-device work adds a fourth source: two devices that each imported the same
bibliography before their workspaces were joined. Sync deliberately never merges
papers by title (see [sync-operations.md](sync-operations.md)), so joining needs
the explicit proposal and merge described here.

Measured on the owner's library (78,824 papers, 5,200 list memberships), 6.5 s:
185 groups sharing an identifier (73 touching a list), 2 to check, 148 likely
(by title, from list papers). Of the 11 likely groups whose titles differ, 10 were
true duplicates on inspection; the miss was two same-author papers in one year.

## Detection

| Kind | Rule | Merge |
|---|---|---|
| `same` | Shared DOI (any `doi.org` form, case-folded), arXiv id (version dropped; the arXiv DOI counts) or S2 id, and the titles agree under `same_paper` | proposed |
| `check` | Shared identifier, titles disagree: an identifier is probably wrong | only after the reader looks |
| `likely` | No conflict (different arXiv ids or DOIs, years more than 2 apart), and an identical normalised title or: same first-author surname, years within 1, same method name before a colon, 40% shared words and `same_paper` | proposed for review |

`openalex.same_paper` is tuned to forgive a bibliography's paraphrase, so alone it
pairs distinct real titles ("Language Modeling Is Compression" / "Proxy Compression
for Language Modeling"). Method names are compared with their symbols before
normalising, so PredRNN and PredRNN++ stay apart. Title comparison starts from
list papers (or the papers asked about); identifiers are checked library-wide.

Each group orders its records by the reader's work on them (list memberships,
notes, dives, close readings, chat, highlights, pins, reading log, context) and
names the first as the copy to keep.

## Merge (next step, proposed)

`paper_identity.merge(conn, keep, drop)` moves everything from `drop` onto `keep`
in one transaction, then removes `drop`. It runs only on a group the reader
confirmed in a preview that lists what moves and what collides.

| Data | On collision |
|---|---|
| List memberships | One membership per list: earlier `added_at` and position; both reasons kept, joined, when they differ; reading state takes the furthest (`read` > `delivered` > `pending`) |
| Notes, chat, highlights, reading log | Moved; nothing collides (own ids) |
| Dives, close readings, paper context (one per paper) | Keep's copy stays current; drop's copy kept as a recoverable older version, never deleted |
| References, citing works, resources, authors | Union; keep wins on equal keys |
| Paper metadata | Keep's fields win; empty fields filled from drop (DOI, arXiv, S2, abstract, PDF URL) |
| Files keyed by paper id (PDFs, highlights, figures, decks) | Moved when keep has none; otherwise kept beside as an older version |
| `kv` keys naming the paper | Rewritten |

Safety: refuse when `drop` is enrolled in sync until the merge exists as a sync
operation (an alias from the dropped portable id to the kept one, so peers and
retries converge); refuse unknown tables with a `paper_id` column rather than
leave rows behind; take a database backup first, as other bulk operations do.
`import-list` should then reuse a corpus record found by identifier instead of
creating a `ref:` duplicate.

## Not in scope

Automatic merging without review; merging by abstract or embedding similarity;
changing `same_paper` itself (its thresholds guard PDF resolution).

## Integration safety note (2026-10-30)

This branch integrates detection only. Do not expose the later local merge
prototype unchanged: independent fixture checks found stale embedded deck/cache
ownership, cross-PDF legacy-anchor risk, no displayed-base application guard,
and no durable recovery for a process crash between file moves and SQL commit.
Repair these boundaries and test actual post-merge readers before enabling merge.
The proposed portable-ID alias operation remains required for synchronized peers.
