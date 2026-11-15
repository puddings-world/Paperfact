# v0.5.0 current status

Updated 2026-11-15. **Development, unreleased; no complete beta acceptance.**

Latest native delivery: Mac arm64/Linux use clean3b344c7
([run43714643158](https://github.com/puddings-world/Paperfact/actions/runs/43714643158));
Windows uses clean4ee3427
([run43715636579](https://github.com/puddings-world/Paperfact/actions/runs/43715636579)).
Mac5m30s/Linux2m55s/Windows7m34s pass packaged0.4.3 format initialization/export
preservation and all11 strict sync protocol checks. Windows additionally passes
isolated install/reinstall/uninstall with research preserved. Its first archive
preflight failed because Git changed line endings; the corrected follow-up passes
without changing verification. App runtime is unchanged between the two commits.
The [Mac guide](testing/mac-acceptance-0.5.md) records exact artifacts/hashes.
These are separate source commits, not one common build. Installed old-binary,
physical-device and hosted acceptance remain open; no public release was created.
The following355382c evidence is the previous common all-platform baseline.

Previous common native baseline [355382c / run43705488673](https://github.com/puddings-world/Paperfact/actions/runs/43705488673),
clean source `355382c7557150c98aee08be7b6fd12ea8274791`, version `0.5.0.dev`.
All three packaged reports pass: four PDFs, CLI/MCP retry/restart, reader/handoff,
verified-history service restart and citation graphs. Mac arm64 passes three starts
and native foreground; Linux passes AppImage integration. Windows passes install,
reinstall and uninstall with research preserved. Jobs took 3m07s/8m37s/3m25s
(Mac/Windows/Linux); older-release upgrade and registry/shortcuts remain untested.
[Exact Mac downloads and physical gates](testing/mac-acceptance-0.5.md).

Included functionality:

- Focal-only offline preparation follows exact native annotation/Lineage originals,
  including source lifetime pins. Missing/corrupt originals remain partial; unrelated
  primary PDFs stay unbound.
- Mobile **Prepare offline reading** verifies the current PDF, native declared
  originals and current decks. It deduplicates jobs, retains verified items for retry
  and refuses stale/unknown provenance as complete. Shell v31 is built, not hosted.
  The actual CI artifact passes Windows Chromium preparation, repeated activation,
  EN/ZH touch layout and fresh offline-document/cached-only verification.
- Existing private compound/referenced/unreferenced reading-text preservation,
  scoped citation graphs, nightly delivered-paper controls and explicit default-off
  new-folder automatic-sync permission remain included. Native credential-store
  and installed two-device journeys are still unrecorded.

Current affected checks and exact historical results are in the
[continuation ledger](testing/continuation-20261112.md). This candidate runs
critical14, first-sync preservation and six source lifetime journeys per OS before
packaging. Frozen acceptance checks actual guarded writes, wrong-proof refusal,
exact retry and history after restart. Counts overlap and are not a completion
percentage; no exhaustive historical run was performed for this candidate.

The CI v31 asset ID is
`8b6f4eac84eeedabd025cfa2237cc18c3312a16834405313028e6f7263493229`.
It is verified, not deployed. Update client/service/assets together; old headerless
peers are refused. Close older test-app processes before replacing a test bundle.
Full runtime adoption, remaining source/recovery mapping, persistent authority/history,
survey audit, old-release upgrade and hosted/physical-device acceptance remain open.
No tag, public release, production deployment or daily-workspace migration occurred.

This candidate uses verified history in the actual desktop and
mobile sync entries and bounded HTTP. Received data/cursor/proof and acknowledgment/proof commit
atomically. A completed receive tail older than a retained acknowledgment is
refused before writes, preserving the note and pending receipt for retry.
Inbox preparation is bounded and compared to actual local records;
new writes verify the observed tip in the authority transaction. Concurrent advance
retries, forged proofs stop, and inactive backup proof records remain preserved.
Mobile v31 saves received/acknowledged proofs with the local transaction and retains
inactive v3 recovery observations. Actual desktop/mobile attachment uploads now
carry the retained prefix into server mutation transactions, including a second
check after physical verification and before ownership. Actual desktop device
controls now require prepared proofs; fresh invitation claims recheck the original
issuer prefix. Explicit sync initializes missing legacy proof tables without
resetting damaged evidence. Source after355382c adds explicit desktop legacy-ack review and default-No
proof adoption, with read-only/resumable comparison and no automatic upload or
cursor reset. Windows Qt/native fixtures pass; a rebuilt/installed Mac journey
remains open. Durable authority fencing remains open. Same-host listener exclusion now holds through
admitted-worker drain; initialized services refuse observed database replacement
or removal without recreating missing files. This is not distributed fencing or
durable control-history protection. Source after897cd7a also makes official
serve reject unverified mutation routes and unbound new pairing claims; actual
Chrome accepts the existing v31 artifact against that strict service. Mac/Linux3b344c7 now package these changes; Windows acceptance remains blocked
at the old-source preflight. Source also adds pinned
old-source backward-export/schema-initialization preservation, passing on both
Mac/Linux packages in that run. Known absent0.5 export extensions now preserve old
workspace sharing; malformed present extensions still fail. This is not an
installed old-binary or GUI upgrade pass. See the [contract and limits](sync-http.md#verified-desktop-flow-and-wire-contract).

The integration line is `develop/0.5`. Preserved snapshots and unintegrated
candidates are listed in [workspace stabilization](workspace-stabilization-2026-11-14.md);
they are not automatically promoted into release evidence.

| Area | Current evidence | Remaining gate |
|---|---|---|
| Offline sync, history/conflicts and attachments | Preserved implementation checkpoint integrated; scoped fixtures, critical journeys and native Mac candidate evidence retained; compound graph-intake notes now retain source-authored creation times across native peers and retries; desktop/mobile now compare the retained history frontier before upload or attachment preparation, pausing with preservation guidance for missing/different history | Remaining recovery/mapping scope and actual installed multi-device journey |
| Saved desktop connection | Explicit reconnection and device-local startup opt-in; exact-credential/workspace fences, offline backoff and real MainWindow fixture delivery | Native vault prompts, installed restart/upgrade and hosted first-device issuance |
| Device pairing | Desktop create/copy/pair/join controls, native pending retry before enrollment, independent keys and verified destination storage; local fixtures pass | Real native vaults, hosted first-device issuance and installed/physical-device acceptance |
| Mobile PWA | Scoped deck inputs survive authenticated transfer and offline reopen; v31 reading preparation plus execution and received-plus-acknowledged history guards included in the verified candidate artifact. Offline/domain/service evidence plus actual JS/Python pairing, verification and revocation; same-origin cookie UI, per-tab binding and four actual Chromium journeys pass; operator key creation/loading and CLI restart verified; pinned static artifact and review-only HTTPS template prepared | Live HTTPS host, platform key permissions, Safari and physical phone acceptance |
| Scientific audit and recovery UI | Desktop current-corpus action uses the shared sealed worker with per-quotation findings, honest source-count progress and existing activity reporting; CLI/MCP use `corpus_key`, with independent generated/imported/bound originals and stable passage indices; owner-aware source-checks.v3 refuses equal-byte foreign-paper attribution through deterministic audit, retrieval, appraisal and fact binding; native alias and bilingual GUI checks pass. Confirmed atomic explanation-link and native Lineage groups (including fresh multi-paper original dependencies), with exact historical context; explicit original-source restoration/retirement preserves cache and later decisions; restored-original Lineage rebinding rechecks retained native originals/quotes and publishes fresh source pins without silently reviving the old report; confirmed native Lineage retirement reaches an independent peer while preserving exact report history, originals and notes; explicit historical source inspection shared by note/claim/highlight/explanation/deck recovery, with current target-source access unchanged; confirmed manual-highlight removal and source-verified original-identity restore, with native creation/projection checks, sealed owned-PDF witnesses, atomic receipts, peer delivery and later-decision-safe retries; typed metadata/note/manual-mark copies, exact-original highlight analysis/marks, complete native deck (including verified related-paper originals) and portable claim-group recovery; exact historical input pins from local/accepted history, original passage checks, atomic receipts and independent peer delivery verified locally | Other scientific deletion choices and legacy manual/source-lifetime mapping, foreign-workspace deck mapping, legacy/source-lifetime mapping, unavailable originals, installed corpus-action acceptance, historical/legacy corpus mapping, list-survey audit and scholarly evaluation |
| Metadata recovery | Recorded parent decisions preserve metadata, reading/order and note copies; positioned notes can atomically include verified post-backup originals, with native peer delivery verified locally; confirmed plain/positioned note deletion uses exact native history/projection checks, one atomic receipt/outbox transaction, independent peer delivery and later-restore-safe retries; confirmed claim-analysis deletion now preserves its original/deep/section research, with exact creation/projection guards, atomic decision/outbox, independent peer delivery and default-No desktop confirmation; known CLI/MCP import control records can now be archived privately during first enrollment while live research/PDFs/order are retained, with old preview/retry authority left inactive | Remaining scientific deletion/audit integration, legacy source mapping, unavailable originals and unproved parent migrations |
| Tests and resource use | Latest affected HTTP/device/browser/admin122 in23.2s total; mobile17 plus actual JS/Python protocol5.3s; candidate verifier/lifetime30 in15.2s. Exact CI mobile pin/offline journey2.9s. Checks are sequential with Windows two-core/25-percent governor. Critical14 and release38 selectors unchanged; [behavior map](testing/README.md#what-the-native-candidate-actually-verifies) | Frozen GUI-client/installed sync acceptance, historical deduplication and native resource cap on Mac/Linux |
| Release | Clean355382c candidate/run43705488673: all three native critical14, first-sync and six lifetime source journeys plus frozen verified-history protocol pass; four PDFs, normal reader/handoff and CLI/MCP preserved; Mac three starts/foreground, Windows install/reinstall/uninstall with research preserved, Linux AppImage. Exact CI mobile artifact and Windows Chrome offline reload pass | Old-release upgrade/coexistence, shortcut/registration/input/long-running/corpus/recovery UI, real-provider, hosted/two-device and physical phone journeys remain open; no public release/deployment |

The preserved checkpoint is integrated locally. Immediate priority is completing recovery
UX and durable private pairing/hosting, then installed-device acceptance. Existing
release requirements are selected by behavior, not historical test count. Latest three-platform candidate CI has passed; public-release and installed-device acceptance remain open.

The exact inventory, preservation scope and migration prerequisites are in
[workspace stabilization](workspace-stabilization-2026-11-14.md).
The [execution board](parallel-work-0.5.0.md) records actual claims and current scope. Detailed older evidence remains in the development/continuation
ledgers; overlapping case counts are not summed into a completion percentage.


Source-only screenshot readiness waits for saved/rendered content and refuses
blank PNGs. Local plain/WebEngine capture checks pass; native Mac screenshot
changes await the next coherent candidate. App runtime is unchanged.


Source afterc4edb7b now captures actual survey input paper lifetimes. A same-content
paper recreation retains a candidate instead of overwriting the old overview;
older pending inputs without lifetime observations require review. Normal enrolled
generation/edit still reaches an independent peer. These are private publication
guards, not complete portable claim sources or a new native artifact.


Source afterd4a4ff7 adds the internal versioned list-survey evidence codec and sealed
owned-original proposal engine. Actual prompt/input hashes and lifetimes, original
quote checks, explicit missing states and currentness are locally verified, including
registered managed originals and foreign equal-byte refusal. No UI/AI dispatch,
canonical storage, sync/package/recovery integration or new native build is claimed.
See the [engine contract](analysis-audit.md#source-aware-survey-engine-local-implementation-not-a-shipped-workflow).


Source aftera705cea retains actual survey originals as atomic private PDF/receipt
pairs, with exact retry/cancel/corruption handling and explicit exclusion from
claim-original grants. Independent detached backup/restore preserves those bytes
as inactive provenance. It does not save or synchronize a canonical survey report.
The next report publisher must use a list-owned verified artifact (256KiB operation
limit versus1MiB report), followed by peer/package/mobile/recovery and UI integration.


Source after6b7bf46 adds the native list-owned survey artifact seam. Complete report
bytes use existing verified blobs, not an enlarged inline journal operation.
Metadata names the list owner and exact native source lifetimes; uploads wait for
received original outcomes and stale sources retain conflicts. A peer can receive
and materialize the exact report without activating its PDFs. Trusted proposal
publication, bundle/recovery, mobile codec and UI/AI dispatch remain open. This
source-only checkpoint does not replace the previously delivered Mac/Windows builds.


Source after245535c adds trusted native survey preparation/publication. Pre-dispatch
sealed observations include report absence/version and actual portable originals.
The caller-owned savepoint publishes originals plus the report/outbox atomically;
retries reuse the same intent, while newer/retired targets and changed originals
fail closed. Local materialization is off-lock and can retry an interrupted pending
intent, including a no-network completion entry after reconnecting from disk.
Completion rechecks native database identity before activation. Plain survey rows
and installed builds are unchanged. Mobile/package/
recovery mapping, durable stale-result review and UI/AI integration remain open.
