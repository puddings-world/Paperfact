# Analysis completion integration — 2026-11-03

Status: isolated, uncommitted v0.5 candidate. Not an installed release.

## Behavior implemented

- Citation analysis accepts an explicit additional-call budget of 0, 1 or 2.
  Default 0 preserves manual continuation. Extra prompts contain missing keys only;
  already valid answers survive malformed replies and no-progress responses.
  Calls stay inside the admitted job/account scope and stop on stale input.
- CLI `cites --completion-calls 1` exposes that bound. Desktop controls and the
  full-analysis orchestration policy still need integration; this is not a global
  auto-completion setting.
- Followup analysis now has a shared `analyse_result` entry point. The existing
  integer API delegates to it. Service failure returns a useful reason, duplicate
  work is refused, and a subsequent explicit retry can succeed. Missing papers
  do not trigger a lookup. Existing scope/publication protections remain.
- Research-context cards distinguish an earlier failure, unprepared analysis,
  and a verified empty lookup. The empty state does not offer a no-op analysis
  button. Metadata rendering does not hash a PDF on the UI thread.
- Reading-link audit checks the exact analysis/explanation fingerprint before
  borrowing a current quote. Changed or legacy links preserve text and request
  review instead of attaching the wrong passage.

## Approved legacy expectation changes

The owner approved bounded opt-in continuation and source-based completion in
`workspace-ux-20261103.md`. The old auto-fill test now explicitly enables a budget;
row counts and legacy `followups.checked` timestamps alone no longer imply
verified completion. The existing actual queried-empty tests remain unchanged.
The service failure fixture now intercepts the lookup seam used by the scoped
operation, rather than bypassing the new operation through the old public wrapper.
Existing expected failure text was preserved by correcting the product message.

## Verification ledger

| Receipt | Result | What it establishes |
|---|---|---|
| `link-provenance-final` | 76 passed | Stale/legacy links cannot borrow changed passages; saved explanations survive. |
| `citation-continuation-v2` | 62 passed | Initial bounded core and citation source coverage; predates missing-only prompt refinement. |
| `followup-result-integration` | 68 passed, 1 failed | Failure copy mismatch; corrected in product. |
| `followup-cli-policy` | 7 passed, 1 failed | Missing context-state adapter; restored and wired into the pane. |
| `followup-cli-policy-v2` | 43 passed | Followup retry/admission, CLI limits, context state and native citation actions. |

The 43-case run included privacy/Ruff, took 19.98 seconds including the wrapper,
and recorded zero drift across 1,167 frozen source inputs. These selections overlap;
do not sum them into an overall suite count. Tests use isolated research and mocked
providers, not real model calls or user accounts. Three additional native card
rendering cases were added after this run and are included in the next full gate.

Full gate `v05-completion-full-20261103` was started with `scripts/check.py` without
a narrowed profile. Its authoritative selection/status is the nested checker
report and log, not the wrapper's inherited selection label. Record its terminal
result before committing. No full pass is claimed by this document.

## Remaining v0.5 delivery work

1. Surface continuation policy in desktop admission and whole-analysis jobs.
2. Simplify nested sync connection setup; saved connections first, manual details
   as a separate task. Keep authentication separate from authorization to upload.
3. Complete the roadmap's writer/history/recovery and professional-reading gates.
4. Pass a coherent full suite, package it, and test installed Windows/Apple Silicon
   Mac offline/reconnect plus a physical phone. Fixture coverage is not that test.
5. Hosted identity, operator/budget, recovery and encryption decisions remain open.
   No public sync login, deployment, release or user-data migration occurred.

The fixes reuse existing local-integration and provider-scope patterns. No new
global skill rule or global installation is warranted by this checkpoint.
