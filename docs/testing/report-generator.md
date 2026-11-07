# Test explanation report: verification and limits

Status: implemented in the isolated 0.5 integration candidate, not committed or
released. This is developer documentation and a local report, separate from the
app, research data and sync service.

## Reviewed behavior map

| Test source | Scenario and observable result |
|---|---|
| `test_test_report.py` | Known catalog entries expose setup/actions/outcomes/limits, exact parameter expansion and source identity. Unknown functions remain explicitly undocumented. |
| `test_test_report.py` | Changed/missing source, absent digest, missing function and changed parameter sets are marked for review; unrelated new cases preserve still-valid explanations. |
| `test_test_report.py` | Malformed/duplicate inputs and escaping source paths refuse generation; prose and parameter HTML are escaped; template-like prose remains exact text. |
| `test_test_report.py` | Failed replacement keeps the complete previous HTML and cleans temporary output; explicit retry succeeds. Output cannot overwrite source. Selected/skipped collection stays visible. |
| `test_test_inventory.py` | A real fresh pytest subprocess collects two parameter cases from a test that would raise if executed. No test body runs; exact IDs/function/file counts are saved. |
| `test_test_inventory.py` | Failed collection preserves previous inventory; explicit retry replaces it. Collection skips and selected scope are recorded. Invalid scopes/output paths are rejected before importing tests. |

Ruff and 44 Python cases passed, zero skips (latest local receipt
`build/merge-resolutions/collector-source-after.xml`). The earlier report-only
receipt remains preserved; the later selection includes the collector source
isolation regression. These are partial checks;
the complete merged application gate is still required before commit/release.

## Collection source identity

The collector temporarily prepends the selected checkout's `src` directory and
restores the caller's complete import path even when collection fails. A real
subprocess fixture includes a conflicting installed package and verifies that
collection imports the selected checkout. If a different `paper_daily` package
is already loaded in-process, collection refuses and requires a fresh interpreter;
it does not delete modules or mix implementations. Inherited dependencies remain
available. This source selection does not make test-module imports a sandbox.

The application checker needs the equivalent subprocess source pin; its separate
maintenance-line candidate and full check are not certified by these 44 cases.

## Actual browser checks

Fresh headless Chrome profiles, no existing user profile, rendered the generated
checkpoint report and verified search, reviewed-only filtering, empty state,
clearing filters and input focus. An actual 390px iframe initially overflowed to
419px; wrapping was corrected and the repeated measurement is now390px/390px.
The old measurement is preserved in `report-browser-before-width.json` and the
seven successful checks in `report-browser-result.json`, under the same ignored
`build/merge-resolutions/` directory. Desktop and narrow-view screenshots are
local evidence, not installed-device or iPhone/Android acceptance.

The supplied checkpoint inventory has429files/3640functions/6469cases; only the
five reviewed functions are explained. The generators run no model, login,
research operation, upload or deployment. Collection imports repository test code;
it does not constitute a sandbox for arbitrary third-party test modules.

## Remaining work

- Review the rest of the catalog from actual assertions/fixtures; do not invent
  descriptions from names or green totals.
- Link execution receipts only with explicit tested-source provenance. Current
  HTML deliberately presents no current pass/fail status inferred from collection.
- Finish the normal integration/full gate before committing these files.
