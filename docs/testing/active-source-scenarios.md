# Inspect the original cited by a presentation

Development candidate; not an installed release. Updated 2026-11-01.

## What changes for the reader

Suppose a saved slide cites PDF A, while the left reader displays a newer PDF B.
Clicking that slide's source opens the verified A in a separate read-only window.
B stays selected, and unsent notes and slide drafts stay in their editors. A
source referring to B still uses the left reader's existing navigation.

The page indicator means **the declared page**, not a verified matching passage.
The viewer does not assess whether that passage supports a scientific claim.

## These tests describe actions, not feature counts

| Reader action or failure | What the test actually does | Required visible or saved result |
| --- | --- | --- |
| Open a cited older original | Public package retention, Verify/Apply, load saved slides, emit the real preview-link signal. Run once for local storage and once for an enrolled workspace. | One independent viewer contains byte-exact A; loaded B, unsent note, all SQL rows and saved files remain unchanged. |
| Click the same source 25 times | Count actual background preparations and open viewer identities. Deny model/account calls. | One preparation, off the GUI thread; one reusable read-only viewer. |
| Keep editing a slide | Type an unsaved alternative slide title and stop the test's autosave timer, then open its unchanged saved source. | The draft title remains unsaved and visible; exact A opens; saved files do not change. |
| Change the source itself | Add an unsaved source assertion to the loaded deck before clicking. | Saved-source proof refuses; the source draft remains; no read window or research write. |
| Switch paper or source while preparing | Hold the actual original preparation, change the reader context, then release it. | No late viewer for the old context; unsent note and saved research remain. |
| Close while preparing | Hold preparation, attempt close and release. | Close waits for owned work to drain; no late original window. |
| Switch workspaces before delivery | Hold preparation and select a different, physically created fixture database. | No result is delivered to either wrong reader; the other database is byte-exact. |
| Retry after a read failure | Raise a private raw failure in the preparation seam, then restore the real helper and click again. | Sanitized status, no leaked raw path/SQL text; explicit retry opens the same saved original. |
| Save an unrelated note | Open A, insert a real note, ask the viewer to check, and await worker revalidation. | The same original authority remains readable; the new note is retained. GUI admission performs no SQL, JSON decode, hashing or PDF parse. |
| Close while a fallback page renderer is held | Use the real fallback renderer behind a finite hold, invoke the parent transition barrier, click the source another 25 times and release. | The closing viewer stays owned until drain; no duplicate preparation or late reopened viewer. |
| Launch restart/update preparation | Hold the source worker and call the shared parent preparation barrier repeatedly. | Transition is refused while the worker is owned; it becomes available after drain. This case does not run an installer. |
| Click a current-PDF or material source | Observe real left-reader navigation for B; emit the separate MaterialsPanel signal for A. | B still navigates normally. Materials do not borrow the saved-deck permission; this earlier check does not exercise their separate adapter. The later [material UI scenarios](material-ui-scenarios.md) record that adapter's local results. |

The pure backend controls additionally exercise changed source/body bytes even
with restored modification time, actual native database/index replacement,
retired source operations, paper deletion/recreation, a foreign device binding,
incomplete/corrupt PDF bytes, ambiguous local owners, malformed/nonobject JSON,
and rejecting oversized bodies **before** allocation/read. These are disposable
native files and databases, not production accounts or research.

## Verification boundaries

- Source ownership and complete bytes do not prove scholarly correctness.
- A local catalog can establish a unique same-paper owner of original bytes;
  it does not certify that the original generated every claim in the slide.
- Multiple qualifying local owners currently refuse, even with the same hash.
- Materials use their own captured provenance adapter with separately recorded
  local evidence. Detached archives and other receipt formats remain incomplete.
  This saved-deck path must not search global caches by hash.
- No left-PDF activation, note autosave, AI call, login, download or sync enrollment
  is caused by opening this original.
- Offscreen Qt is not installed Windows/Mac or phone acceptance.

## Failure evidence retained during development

The original independent two-case audit was red because the ordinary source action
had no separate original viewer. All 17 original assertions remain. The new
asynchronous adapter adds bounded worker/viewer drain, and the fixture disables
unrelated legacy automatic highlight analysis before loading B. It does not loosen
the current-B source guard or change expected source/PDF bytes.

The first broad UI run was deliberately interrupted after repeated failures;
no pass count is claimed. A minimal first-failure run exposed overly broad new
busy/draft admission. Source reads now depend on saved source, file and lifetime
witnesses, while preserving drafts and allowing unrelated work.

A later new UI test observed the database with a writable SQLite connection;
its close could checkpoint and change the proof's interference fence. Only that
new observer became read-only. Its byte/state and native-only assertions remain.
The corrected two-case note test passed; its failure record is retained.

Exact current integration results are linked from the development status after
the matching source-frozen gate finishes. Historical/overlapping counts are not
added together, and none imply a complete check, installer or release.

## Current recorded results

- Actual UI/audit: **26 passed, 0 failures/errors/skips**,151.70s pytest/152.97s
  wrapper;919 inputs unchanged. Receipt: `build/active-original-ui-final-result.json`.
- Backend plus maintained original/local/retained viewers and parent transitions:
  **94 passed, 0 failures/errors/skips**,306.58s pytest/307.80s wrapper; the same919
  inputs unchanged. Receipt: `build/active-original-shared-integration-result.json`.
- Four Chinese native Qt screenshots at860/620width were inspected. A separate
  two-case manual capture passed13.05s with no source drift. No installed Mac or
  phone was used. Receipt: `build/active-source-visual-result.json`.
- The reviewed bilingual catalog individually describes all11 new desktop
  functions/26expanded cases. Full inventory7934 is discovery only. The overall
  full check is still failed; these selections do not certify a release.

The actual test XML shows local UI cases taking roughly2.5–3.7seconds each and
managed cases8.1–9.2seconds in this run, including their different fixture setup.
This is measured per-case elapsed time, not an estimated live AI wait or a
percentage of v0.5 completion.

Existing ownership/native-change patterns already cover the verified behavior;
this checkpoint adds project evidence and no new global skill rule/installation.
