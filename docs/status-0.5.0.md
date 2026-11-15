# v0.5.0 current status

Updated 2026-11-15. **Development, unreleased; no complete beta acceptance.**

Common native candidate [c1cbef2 / run 43688772032](https://github.com/puddings-world/Paperfact/actions/runs/43688772032),
clean source `c1cbef20d48d29e2767bed60a6393298819389d4`, version `0.5.0.dev`.
All three native reports pass: four PDFs preserved, CLI/MCP retry/restart, normal
reader/handoff, packaged service restart and citation graphs. Mac arm64 additionally
passes three starts and native foreground; Windows passes installer/reinstall/
uninstall with research preserved; Linux passes AppImage integration. Jobs took
4m37s / 6m45s / 3m09s (Mac / Windows / Linux). [Exact downloads and physical gates](testing/mac-acceptance-0.5.md).

Included functionality beyond the older cb6ca66 candidate:

- Focal-only offline preparation follows exact native annotation/Lineage originals,
  including source lifetime pins. Missing/corrupt originals remain partial; unrelated
  primary PDFs stay unbound.
- Mobile **Prepare offline reading** verifies the current PDF, native declared
  originals and current decks. It deduplicates jobs, retains verified items for retry
  and refuses stale/unknown provenance as complete. Shell v29 is built, not hosted.
  The actual CI artifact passes Windows Chromium preparation, repeated activation,
  EN/ZH touch layout and fresh offline-document/cached-only verification.
- Existing private compound/referenced/unreferenced reading-text preservation,
  scoped citation graphs, nightly delivered-paper controls and explicit default-off
  new-folder automatic-sync permission remain included. Native credential-store
  and installed two-device journeys are still unrecorded.

For frozen c1cbef2, the local release representatives passed: Python 52, frontend 24, mobile
96 and actual JS/Python protocol in 129.5s, CPU bounded. CI passes critical 14 and
one source first-sync representative per OS, plus frozen acceptance; Windows mobile
artifact checks pass 5/5. A corrected delayed-tail fixture retains all original
assertions and the missing-history refusal. Earlier red evidence stays in the ledger.
These gates overlap; counts do not represent distinct release requirements.

The CI v29 asset ID is
`6573854331ecc52eebe3e10d63d3901dc3aa8e2c4fe34bdfebd36755745b41eb`.
It is verified, not deployed. Update client/service/assets together; old headerless
peers are refused. Close older test-app processes before replacing a test bundle.
Full runtime adoption, remaining source/recovery mapping, persistent authority/history,
survey audit, old-release upgrade and hosted/physical-device acceptance remain open.
No tag, public release, production deployment or daily-workspace migration occurred.

Source after this candidate now uses verified history in the actual desktop and
mobile sync entries and bounded HTTP. Received data/cursor/proof and acknowledgment/proof commit
atomically. A completed receive tail older than a retained acknowledgment is
refused before writes, preserving the note and pending receipt for retry.
Inbox preparation is bounded and compared to actual local records;
new writes verify the observed tip in the authority transaction. Concurrent advance
retries, forged proofs stop, and inactive backup proof records remain preserved.
Mobile v30 saves received/acknowledged proofs with the local transaction and retains
inactive v3 recovery observations. Actual desktop/mobile attachment uploads now
carry the retained prefix into server mutation transactions, including a second
check after physical verification and before ownership. Device-control guards,
native legacy-ack review/adoption UI and durable authority fencing remain open. Candidate c1cbef2 has not been rebuilt for
this source. See the [contract and limits](sync-http.md#verified-desktop-flow-and-wire-contract).

The integration line is `develop/0.5`. Preserved snapshots and unintegrated
candidates are listed in [workspace stabilization](workspace-stabilization-2026-11-14.md);
they are not automatically promoted into release evidence.

| Area | Current evidence | Remaining gate |
|---|---|---|
| Offline sync, history/conflicts and attachments | Preserved implementation checkpoint integrated; scoped fixtures, critical journeys and native Mac candidate evidence retained; compound graph-intake notes now retain source-authored creation times across native peers and retries; desktop/mobile now compare the retained history frontier before upload or attachment preparation, pausing with preservation guidance for missing/different history | Remaining recovery/mapping scope and actual installed multi-device journey |
| Saved desktop connection | Explicit reconnection and device-local startup opt-in; exact-credential/workspace fences, offline backoff and real MainWindow fixture delivery | Native vault prompts, installed restart/upgrade and hosted first-device issuance |
| Device pairing | Desktop create/copy/pair/join controls, native pending retry before enrollment, independent keys and verified destination storage; local fixtures pass | Real native vaults, hosted first-device issuance and installed/physical-device acceptance |
| Mobile PWA | Scoped deck inputs survive authenticated transfer and offline reopen; v29 reading preparation plus execution and received-plus-acknowledged history guards included in the verified candidate artifact. Offline/domain/service evidence plus actual JS/Python pairing, verification and revocation; same-origin cookie UI, per-tab binding and four actual Chromium journeys pass; operator key creation/loading and CLI restart verified; pinned static artifact and review-only HTTPS template prepared | Live HTTPS host, platform key permissions, Safari and physical phone acceptance |
| Scientific audit and recovery UI | Desktop current-corpus action uses the shared sealed worker with per-quotation findings, honest source-count progress and existing activity reporting; CLI/MCP use `corpus_key`, with independent generated/imported/bound originals and stable passage indices; owner-aware source-checks.v3 refuses equal-byte foreign-paper attribution through deterministic audit, retrieval, appraisal and fact binding; native alias and bilingual GUI checks pass. Confirmed atomic explanation-link and native Lineage groups (including fresh multi-paper original dependencies), with exact historical context; explicit original-source restoration/retirement preserves cache and later decisions; restored-original Lineage rebinding rechecks retained native originals/quotes and publishes fresh source pins without silently reviving the old report; confirmed native Lineage retirement reaches an independent peer while preserving exact report history, originals and notes; explicit historical source inspection shared by note/claim/highlight/explanation/deck recovery, with current target-source access unchanged; confirmed manual-highlight removal and source-verified original-identity restore, with native creation/projection checks, sealed owned-PDF witnesses, atomic receipts, peer delivery and later-decision-safe retries; typed metadata/note/manual-mark copies, exact-original highlight analysis/marks, complete native deck (including verified related-paper originals) and portable claim-group recovery; exact historical input pins from local/accepted history, original passage checks, atomic receipts and independent peer delivery verified locally | Other scientific deletion choices and legacy manual/source-lifetime mapping, foreign-workspace deck mapping, legacy/source-lifetime mapping, unavailable originals, installed corpus-action acceptance, historical/legacy corpus mapping, list-survey audit and scholarly evaluation |
| Metadata recovery | Recorded parent decisions preserve metadata, reading/order and note copies; positioned notes can atomically include verified post-backup originals, with native peer delivery verified locally; confirmed plain/positioned note deletion uses exact native history/projection checks, one atomic receipt/outbox transaction, independent peer delivery and later-restore-safe retries; confirmed claim-analysis deletion now preserves its original/deep/section research, with exact creation/projection guards, atomic decision/outbox, independent peer delivery and default-No desktop confirmation; known CLI/MCP import control records can now be archived privately during first enrollment while live research/PDFs/order are retained, with old preview/retry authority left inactive | Remaining scientific deletion/audit integration, legacy source mapping, unavailable originals and unproved parent migrations |
| Tests and resource use | Affected HTTP/blob/device/browser requirements: 149 passed in 22.2s total; mobile transport/engine/cache 31 in 3.594s; actual JS/Python HTTP 2.344s; four real headless Chromium cookie/reload/reconnect/forget journeys in 14.39s. Daily critical remains 14; release 38 selectors includes one real execution-restart representative | Frozen GUI-client/installed sync acceptance, historical deduplication and native resource cap on Mac/Linux |
| Release | Common clean c1cbef2 candidate in run 43688772032: local curated release 52 Python/24 frontend/96 mobile plus actual protocol; critical14/first-sync/frozen acceptance on all three CI platforms. Four PDFs, normal reader/handoff, sync restart/graph and CLI/MCP preserved; Mac three starts/foreground, Windows install/reinstall/uninstall, Linux AppImage; CI mobile5/5 and actual Windows Chrome offline reload | Old-release upgrade/coexistence, shortcut/registration/input/long-running/corpus/recovery UI, real-provider, hosted/two-device and physical phone journeys remain open; no public release/deployment |

The preserved checkpoint is integrated locally. Immediate priority is completing recovery
UX and durable private pairing/hosting, then installed-device acceptance. Existing
release requirements are selected by behavior, not historical test count. Three-platform candidate CI has passed; public-release and installed-device acceptance remain open.

The exact inventory, preservation scope and migration prerequisites are in
[workspace stabilization](workspace-stabilization-2026-11-14.md).
The [execution board](parallel-work-0.5.0.md) records actual claims and current scope. Detailed older evidence remains in the development/continuation
ledgers; overlapping case counts are not summed into a completion percentage.
