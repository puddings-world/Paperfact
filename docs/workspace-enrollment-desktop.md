# Prepare a reviewed workspace copy from the desktop

Open **Workspace and recovery -> Prepare workspace copy**. The flow is local and
explicit: preview coverage, choose a new workspace folder and an independent new
backup path, prepare the verified copy, then optionally open it in a separate app
window. The current workspace and its open drafts stay selected.

This UI calls the existing `EnrollmentService.plan` and `.prepare`; it does not
provide another migration format, write research to the source, issue service
credentials, upload, connect or adopt a workspace in place. It does not ask for an
AI account and never starts an agent or a paper download.

## Coverage before copying

The coverage check runs in a worker. It locates existing current PDF paths through
the app's document reader using local paper IDs, then the enrollment service
verifies the explicit mapping and complete supported research/file inventory.
The preview shows paper/list/note counts, current PDFs, retained originals,
archived source receipts, excluded private settings, and every reported blocker.
PDF names are shown for review; titles are never used to infer identity.

Already-bound sources are reported by the service's coverage checks without
materializing their managed reader caches. Missing PDFs are not downloaded or
invented. Unknown history, files, schema writers and unsupported scopes remain
visible blockers; preparation is disabled until coverage is supported. A preview
is a coverage report, not a frozen snapshot of every byte: preparation rechecks
the current saved source and validates it again before publication.

The UI consumes the tested enrollment history, imported-original and nullable-list
adapters. It preserves imported original A beside current PDF B through the shared
service, archives old local ownership observations, and does not normalize a NULL
list note to an empty string. Unknown legacy decks still block when no complete
accepted publication history can represent them.

## Background, retry and closing

Preparation is enabled only after supported coverage and explicit absolute output
paths. Both outputs must be new and separate from the source and each other;
existing directories or backup files are never replaced. An unsuccessful retry
with unchanged destinations retains its request UUID. Choosing different paths
starts a distinct request.

Buttons immediately show an indeterminate running state and become unavailable
for repeated activation. Stage messages follow actual service/verification events;
there are no invented percentages or time estimates. PDF discovery progress is
throttled, and an old worker cannot change a newer task's visible phase.

Stop/Escape/close requests cancellation and waits for the worker's safe boundary;
a running QThread is not destroyed. Current research jobs block starting the flow.
If they start while it runs, the ticket is cancelled. Workspace path, physical DB
identity and installed binding changes invalidate delayed results. The final
publication ticket checks the captured workspace again even if a GUI poll has not
run. Source changes reported by the service require another coverage check.
Failures retain path selections and display a short recovery message rather than
raw exceptions or research/provider content.

## Opening the result

Success reports only `prepared_for_review`, with `adopted=False`, `uploaded=False`
and `runtime_enrollment_complete=False`. Opening is a separate button; it uses the
existing `workspace_open` contract to start the prepared database in another
process. It neither rebinds nor closes the original reader. Repeated opening is
coalesced, and opening failure can be retried without preparing another copy.

The existing service's coverage/adoption limitations remain in
[the enrollment service contract](workspace-enrollment.md). Server workspace/device
issuance, remembered connection and synchronization remain separate operations.
No credentials are copied into the candidate or independent recovery archive.

## Verification

`tests/test_enrollment_dialog.py` exercises actual SQL/PDF/copy/recovery output,
empty and unsupported sources, imported originals and NULL notes, repeated clicks,
chooser cancellation, active jobs, failure/retry, stale binding/path/DB replacement,
closing with work active, and explicit opening without a real app/process launch.
It also checks bilingual labels and narrow-window geometry. Existing workspace
and opening tests run separately alongside the service fixtures.

Fixture screenshots in the isolated build directory cover English, Traditional
Chinese and a narrow window. The headless Windows renderer loads existing local
fonts only for that process; no system font or app setting is changed. Native
macOS/Linux windows and live server/device enrollment are not claimed by those
screenshots or fixture tests.
