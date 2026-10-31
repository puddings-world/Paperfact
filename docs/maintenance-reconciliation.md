# Maintenance reconciliation into 0.5

Status: recorded 2026-10-31 source review and integration plan; not an ancestry merge or release.
Feature HEAD: `06183e1bfdbe02ec61dfc6d6f032b4fcb81c44cb`, plus **1089 frozen working-tree inputs**.
Master: `8bc4a3bbbf6f08cad37d888ea7c4c6cb6f491bd9`; common ancestor: `14292c30b747561716ddf67e8e34044b7c8c4622`.
The former 890-input / `94566d1` inventory is historical. It is preserved in the ignored audit artifacts.

## What the comparison proves

- There are **23 master-only ancestry commits** touching **172 paths**: 60 current files match byte for byte, 95 differ, and 17 exist only on master.
- A matching file or function does not prove behavioral equivalence through different dependencies. The matrix separates recorded fixture evidence from static observations.
- No tests or live services were run for this audit. Existing focused receipts are linked by scope; their counts overlap and must not be added together.
- The owner was running the complete 0.5 gate at capture. This audit does not establish its result, packaged-device acceptance, a release, or merged ancestry.

## Retained behavior and intentional boundaries

- **Saved chat is asynchronous now.** `reader_saved_inputs`, `reader_saved_render` and `ReaderPreparation` preserve typed turns, source leases and drafts. Main waits through queued GUI install/discard before restart/update/close; accepted normal and stale close dispose the controller. The joint focused receipt records **186 passed**. Native position cancellation on close and waiting without cancellation on update remain distinct.
- **Window lifetime is bound to the constructor workspace.** The helper, ReadyBanner and UpdateBanner match master; Main preserves richer 0.5 workers, source guards and queued preferences. The watcher/toolbar adaptation has a **91-case** receipt, and the joint gate includes the original watcher regression.
- **Translation results are source/selection/account scoped.** Selection ABA and loaded-source guards are retained with the original Unicode/no-LaTeX prompt; the existing focused receipt records **123 passed**.
- **Citation safety is adapted to native typed actions.** The native map/projection V2 rejects stale paper/workspace/list/view results; its focused receipt records **92 passed**. This is not the master one-page HTML performance implementation.
- **Generic reply parsing and completion truth are retained.** JSON caller reconciliation preserves observed publication, source/ID/quote validators, prior-good content and original call budgets. Existing receipts record 72 helper/topic cases and 272 caller/compound cases. Strict claim/appraisal decoders are excluded from generic cleanup.
- **Keep CaptureConnection.** Master's path-only `_prepared` set and plain SQLite factory are not safe replacements for observed 0.5 writers, caller transactions, replacement checks or schema guards.
- **Keep typed ClaimJob and saved claim evidence.** Master `claims.py` writes note SQL and completion KV directly. It must not replace source receipts, explicit restoration, candidates or the typed claim-set UI.
- **Keep native document authority.** Current completed-load witnesses, paper/reader/selection epochs and deliberate historical A while primary B exists remain authoritative. Cache paths and latest desired metadata do not grant navigation or write authority.
- **Keep version and provenance differences.** Feature remains `0.5.0.dev`; master is `0.4.6`. Keep the feature `model_reported` provenance flag, private/research boundaries, and current job/device identities.

## Commit matrix

?Retained? means source review plus the named existing evidence, not a new full-suite result. Broad checkpoints may contain both retained and unresolved changes.

| Master commit | Current decision |
|---|---|
| `eb83b3b` | Question entry/browser layout retained; 0.5 keeps typed pending requests and per-workspace/paper drafts. |
| `3abdf43` | Startup teardown tests and GUI entry match; richer 0.5 lifetime barriers remain. |
| `1f79466` | Kept notes still open/edit; source-bound note snapshots and observed writes intentionally replace master raw edit/delete paths. |
| `f13599c` | AI Studio Gemini key/account UI retained; routing/model-reporting/private credentials stay feature-specific. |
| `884ef10` | Broad checkpoint contains many exact files plus 0.5-specific writers, sharing/recovery and remaining performance differences; do not copy it wholesale. |
| `4862e24` | Packaging entry/build/mac verifiers and tests match; feature launch/data policy remains independent. |
| `a89944b` | Preference batch serialization remains; preserve path-bound queue and private research-KV separation. |
| `3e6e9dc` | reading_layout and tests match; early native rich-view surface retained. |
| `2911171` | Feature is 0.5.0.dev, master is 0.4.6; no version/branch/release identity copy. |
| `d650340` | Reject master path-only _prepared/plain connection factory. Bounded display-only executables discovery is adapted; cold lookup and read polling optimizations are not all ported. |
| `06fe6da` | Saved chat now uses typed worker snapshot and GUI-delivery ownership; deep dive, cached figures and highlight-word mapping are not yet fully off-GUI. |
| `9e81cf6` | Native citation projection/action/lookup guards are adapted; one-page HTML renderer is absent. Master card writers must not replace typed feature actions. |
| `4ed6208` | Progressive selected-first thumbnails and bounded content cache are absent; current pane draws every outline thumbnail synchronously. |
| `bb7122d` | Executable display discovery is adapted; worker QImage decode, sliced figure insertion and package metadata cache remain absent. |
| `ffc6f44` | warm_up module/startup hook absent; master start is not single-flight and must be bounded/owned before use. |
| `6c857a1` | Source-bound translation completion is adapted. Focus settling, background usage discovery, PDF word priming/read-ahead and watchdog context remain absent. |
| `ef34418` | Continuing-heartbeat watchdog-test fix is not present; bring with watchdog context slice while preserving its original assertions. |
| `94566d1` | Completion truth, generic reply JSON and answer cleanup retained with typed compound publication; ClaimJob/UI supersede raw SQL claim-note writer. |
| `987c365` | Constructor-owned watcher plus FlowLayout toolbar and explicit SDK child-source fixture retained. |
| `97c0676` | Both pocket PDF.js parser boundaries disable eval; template/tests/doc match. Prior exported HTML still requires re-export. |
| `f7495dd` | Stale citation actions and delayed HTML hazards addressed in stronger native typed-action context; no master HTML widget replacement. |
| `e926be9` | Window helper, ReadyBanner and UpdateBanner match; Main has additional 0.5/preparation/position/draft barriers. |
| `8bc4a3b` | Native map/projection V2 retains source/list/view scopes and rejects delayed stale work, keeping feature typed mutations. |

## Remaining bounded adaptations

These are genuine master performance or presentation differences. Each is a separate, reviewable source slice; none authorizes a whole-file Main/store/pane replacement. Stage selected slices independently under the current authorized development scope.

### Saved deep-reading preparation

Deep reading still calls saved DB/cache readers and `reading.render` synchronously. Phase 1 already captures dives, close reading and typed annotations, but explicitly excludes figures/PDF words/legacy cache previews; Phase 2 currently publishes chat only.

Source seam: `src/paper_daily/desktop/main.py::ReaderPage._load_dive`, `src/paper_daily/reader_saved_inputs.py`, `src/paper_daily/desktop/reader_saved_render.py`, `src/paper_daily/desktop/reader_preparation.py`, `src/paper_daily/figures.py`.

Add only a bounded saved-dive read/render lane over captured loaded-source ownership; extend explicit figure closure beyond current not_prepared marker. No global cached() calls in delayed worker and no second competing scheduler.

Acceptance:
- Held read during paper/workspace/native-source changes drops stale output; deliberate loaded A/current-primary B remains A.
- Malformed/missing cache gives safe retry; known-hidden/manual marks, typed chat/notes/drafts and candidates remain byte/row-exact.
- Busy includes queued GUI install/discard; close/restart/update waits; no AI/extraction write from rendering.

### Figure decoding and insertion

Extraction is already threaded, but `_entry` still decodes/scales QPixmap and `_show` creates every widget on the GUI thread. Preserve the feature generation and exact-source filtering.

Source seam: `src/paper_daily/desktop/figure_pane.py::_ExtractWorker.run`, `src/paper_daily/desktop/figure_pane.py::FigurePane._show_result/_entry`, `src/paper_daily/desktop/main.py::ReaderPage._figures_ready`, `src/paper_daily/figures.py::extract/cache_directory`.

Decode/scale bounded QImages on worker; add generation/source-bound GUI insertion slices. Keep QPixmap/widgets on GUI and existing generation signal/source hash/_jump. Fresh exact-source extraction alone may request a dive refresh.

Acceptance:
- GUI heartbeat while many/large images decode; placeholders/TOC usable before complete insertion.
- Rapid same-paper PDF replacement, cache mutation, workspace switch and close discard old generation and stop timers.
- No desired-B jump from loaded-A figure; no cache/source/publication weakening.

### PDF word preparation

Selection caches words per page but first extraction is synchronous. The slanted-word algorithm is already shared in `pdf_selection_text.py`; do not duplicate master's copy or overwrite selection epochs.

Source seam: `src/paper_daily/desktop/pdfselect.py::SelectionOverlay.words_on/set_document`, `src/paper_daily/pdf_selection_text.py::level_words`, `src/paper_daily/desktop/pdfpane.py::position_identity/position_source_version`.

Prepare a bounded requested page set on worker and prime only matching native/selection epoch. Reuse shared slanted-word algorithm; never share open PyMuPDF document across threads or replace completed-load witness.

Acceptance:
- Same words/order/anchors and highlight rects before/after priming.
- ABA clear/reselect, load failure, same-path replacement and historical A/B reject late priming.
- Programmatic jumps do not manufacture observed reading positions; no PDF hashing/parse during GUI delivery.

### Progressive slide thumbnails

`_show_deck` still draws each outline thumbnail synchronously. Master's content-only hash does not prove the bytes of mutable legacy assets.

Source seam: `src/paper_daily/desktop/presentation_pane.py::_show_deck/_thumbnail`, `src/paper_daily/desktop/slide_canvas.py`.

Placeholders plus selected-first bounded GUI drawing and LRU; key exact deck/mode/revision/render context plus verified asset revision, not default=str metadata or filename. Keep all save/recovery/observed-file guards.

Acceptance:
- Many-slide opening yields before all thumbnails; selected slide first.
- Deck/reorder/style/source/asset-byte change invalidates correctly; timers stop on close/switch.
- Rendering leaves editable content/history/recovery/conflicts and save outcomes unchanged.

### Watchdog context and export

The baseline heartbeat/stack watcher exists. Allowlisted window-system context, its strict diagnostic parser and the continuing-heartbeat test adaptation remain absent; do not install a second watcher.

Source seam: `src/paper_daily/ui_stalls.py::Watchdog/install`, `src/paper_daily/diagnostics.py::collect/_stall_context (new)`, `tests/test_ui_stalls.py`.

Extend the existing single watcher with bounded allowlisted context and matching closed report parser; port continuing-heartbeat regression together.

Acceptance:
- Allowed event/state/count/age export only; unknown/malformed context rejected.
- No titles, text, paths, keys, prompts, account IDs or second watcher.
- Continued heartbeat recovers from a stall; event/counter timers stop with accepted owner close.

### Startup and metadata warmup

Display-only executable discovery is already bounded and environment-scoped. Package metadata memoization and startup warmup are absent; the master warmup starter does not deduplicate repeated starts.

Source seam: `src/paper_daily/diagnostics.py::collect`, `src/paper_daily/executables.py`, `src/paper_daily/desktop/main.py::MainWindow.__init__/run`, `src/paper_daily/desktop/warm_up.py (new adapted helper)`.

First isolate bounded package-version memoization; then single-flight idle import/parser/display-discovery warmup after workspace and QApplication. Master warm_up.start is not a ready-made lifetime contract.

Acceptance:
- Concurrent/repeated starts dedup; close before timer/job completion has no late effects.
- No widget creation, account/login/model/network/research/config writes; actual execution still freshly resolves tools.
- Preserve early native surface, first-paper geometry, source/binding barriers and current environment-sensitive discovery.

### Background usage discovery

Usage cache refresh itself is shared/backgrounded, but UsageMonitor still reads account/config/tool discovery on its GUI timer.

Source seam: `src/paper_daily/desktop/usage_monitor.py::UsageMonitor.tick/_refresh`, `src/paper_daily/ai_choices.py`, `src/paper_daily/usage_cache.py`.

Move only discovery/config reads to one running+latest-pending owned lane; retain account-keyed shared cache and all consulted config/env scope. No global OffThread replacement.

Acceptance:
- Held read keeps GUI responsive; account/profile/model/env switch cannot publish old label or route.
- Repeated ticks dedup; error/unknown quota remains unknown; no login/paid call added.
- Accepted close disposes worker through delivery; late callback cannot refresh another workspace picker.

### Local PDF read-ahead

Master's new helper is absent. Its path-only remembered set is a performance hint, not a source proof; an adapted helper must remain read-only and bounded.

Source seam: `src/paper_daily/desktop/pdf_warm.py (new adapted helper)`, `src/paper_daily/desktop/queue_view.py::QueuePage list-focus/hover hook`, `src/paper_daily/desktop/pdfpane.py`.

One latest bounded read of already-owned local source; remembered identity/version is performance hint only, never availability or write/navigation authority. No directory/remote crawl.

Acceptance:
- Rapid list traversal bounds reads; file replacement and workspace/source switch invalidate hint.
- Missing/cancel/close leaves no leaked handle; no activation or reading-position event from warming.
- Actual PDF opening still validates bytes/native witness independently.

### Settle the focus frame

The focus frame still repaints continuously. Master's finite arrival drift is a small independent adaptation.

Source seam: `src/paper_daily/desktop/focus_scope.py::_Frame.__init__/_advance`, `tests/test_focus_scope.py`.

Finite arrival drift using master FRAME_DRIFT_MS pattern, then stop repaint timer; preserve focus/keyboard ownership.

Acceptance:
- Frame settles after bounded ticks; focus transfer gets correct new frame.
- Inactive/closed windows do not keep repainting; keyboard/panel switching remains unchanged.

### One-page citation presentation

The current native widget projection intentionally remains. If master performance parity is desired, separate pure HTML presentation from typed actions and retain map V2 source/lifetime guards.

Source seam: `src/paper_daily/desktop/cites_pane.py`, `src/paper_daily/desktop/rich_view.py`, `src/paper_daily/desktop/cites_html.py (possible new pure renderer)`.

If performance parity is desired, introduce escaped closed read-model HTML separately, then contextual widget/action adapter. Keep current native map V2 and typed editors; never replace with master raw writers.

Acceptance:
- Stable nonce+paper/owner/projection/list/action IDs; stale HTML, queued JS/load/lookup and modal editor cannot retarget.
- Same saved content/outbox/order/team/side and plain fallback; no extra top-level widgets.
- One-page rendering improves widget count without changing source jumps or enabling actions from untrusted content.

## Helper and merge policy

No newly master-only runtime helper is an unconditional whole-file port: `off_thread.py` has generic/global lanes and native-idle semantics; `pdf_warm.py` is path based; `warm_up.py` is not single-flight; `claims.py` is an incompatible writer. Small pure leaves such as figure QImage decoding, page-word extraction and package-version lookup can be adapted independently with their caller contracts.

Preserve the current ReaderPreparation/Main and native citation map V2. Do not overwrite them with master whole files, plain global connections, order-inferred chat pairing or raw note writers. Existing exact files need no duplicate implementation merely to reproduce commit history.

An eventual isolated ancestry merge still needs contextual conflict review, affected fixture checks and a coherent complete gate. A copied implementation does not make `8bc4a3b` an ancestor. Do not change version, publish, enable uploads, or touch user workspaces as part of reconciliation.

## Maintainer evidence

The ignored review workspace contains `build/maintenance-reconciliation-current.json` (all 172 path hashes and 23 decisions), `build/function-dependency-inventory.json` (21 modules; functions/imports/constants), the original source manifest and historical document, and copied evidence receipts. Key canonical receipts:

- `build/joint-v2-canonical-applied.json` ? owned window/preparation union and actual held-worker lifecycle tests.
- `build/reader-preparation-canonical-verified.json` ? earlier 370-case reader/source/reentry selection; its ?Phase 1 not wired? note describes that earlier checkpoint.
- `build/common-maintenance-verified.json`, `build/translation-verified.json` ? watcher/toolbar and translation scopes.
- `build/native-cites-map2-result.json`, `build/native-cites-v2-result.json` ? native projection guards; not one-page HTML.
- `build/reply-json-verified.json`, `build/json-callers-verified.json`, `docs/maintenance-completion-truth.md` ? parsing and typed completion boundaries.
- `build/pocket-feature-applied.json` ? exact legacy PDF.js configuration fix; existing exported HTML snapshots need re-export.

No performance timings or physical device behavior were remeasured in this review.
