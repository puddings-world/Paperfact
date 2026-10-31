# Desktop claim evidence

The reader's research menu has one optional **Review claims against the original** entry
(`核對論證與原文…`). Opening or reloading it reads saved claim sets without account
access or an AI call. It leaves note/Q&A drafts and legacy claim note cards unchanged.

The first five central proposals appear in producer order. Each card separates the proposed
judgment and open questions from original quoted passages. Located, missing and ambiguous
quotes have distinct labels. A located quote does not verify semantic support; no confidence
score or verified-conclusion badge is shown. English and Traditional Chinese share this scope.

Generate is an explicit action using the `claims` task's captured provider/account/model route.
Regeneration asks for confirmation. Missing access opens existing AI onboarding without
resubmitting automatically. One worker runs at a time; actual producer stages feed both the
local status and activity board. An indeterminate indicator avoids an invented percentage.
Failure keeps saved cards and permits explicit retry. Cancellation and stale source/parent
results remain retained research candidates instead of silently replacing the current set.

Source navigation verifies the exact loaded original's owner, document identity and SHA256
outside the GUI thread, then checks the current reader again before focusing it. An older or
unavailable source stays readable with an original-version limitation; its stored page does
not authorize a jump into a different PDF. A missing loaded owner makes the view read-only.

Paper/workspace changes invalidate pending UI application. Closing requests cancellation and
waits asynchronously for the worker; parent close/update is guarded while it is active. No
worker termination, token persistence, silent enrollment or alternate claim writer is added.

Deleted sets have a separate Restore proposals action. Its confirmation defaults to Cancel;
opening the view, reloading it, or cancelling confirmation performs no account lookup or AI call.
Only confirmed restoration forwards `restore_deleted=True` to the shared producer. A changed
report during confirmation requires rechecking before account access. The backend captures the
exact tombstone, original source, input and owner; successful restoration creates a new graph
incarnation. Ordinary regeneration/force never implies restoration. Empty or malformed output,
cancellation and late source changes keep the deletion and retained candidate history intact.

Freshness uses the host's existing `WorkspaceChanges.changed` signal plus a two-second background
saved-report read to cover unlisted papers outside the list-visible revision counter. Signals are
coalesced while work is active, with one follow-up read. Unchanged reads preserve card widgets,
expanded proposals, scroll and keyboard focus. No polling query or PDF hashing runs on the GUI
thread. Known pending changes block stale actions; background work never edits reader drafts.
Closing waits asynchronously for a freshness worker just as it does for explicit generation.

Focused fixture verification: 88 tests passed, including 12 presentation/keyboard cases,
20 restoration/freshness cases,
34 prior actual Qt claim-view cases, 4 entry/parent guard cases and 18 unchanged task-menu
regressions. Tests use isolated
unbound/enrolled databases, actual generated PDFs and simulated completions. Live providers,
native platform presentation and semantic appraisal were not tested. The parent integration
runs the complete project gate before declaring the release complete.

## Reading the cards

The dialog uses the reader window's Paperfact palette, bundled Noto Sans TC family and shared
purple AI action treatment. A compact heading introduces the review; proposed judgments remain
visually distinct from quote-location labels and the always-visible semantic-validation limit.
Cards keep their natural height. Empty/deleted views use a short heading and one status
explanation, with explicit generation/restoration beside saved reload.

Reason/open questions and original passages are keyboard disclosures (Space and Return/Enter toggle). Return is consumed locally; it
never falls through to the dialog default AI action.
Reasons start collapsed; original passages start open so source navigation stays immediately
available. Disclosure choices survive saved reloads and expanding the remaining proposals;
quiet unchanged reads preserve the same widgets/focus. Long text wraps at narrow widths.
Disclosing saved text performs no account access, AI call or research write. The interaction
is immediate, with no decorative animation or additional motion dependency.


For generated, imported or synchronized original A/current B research, **View original version**
opens a separate
read-only byte-verified PDF window; the existing current-reader source jump remains guarded.
See [Original-version inspection](original-version-viewer.md) for exact ownership, lifecycle,
o-applied-receipt/offline behavior and the required unbound-source follow-on boundary.
