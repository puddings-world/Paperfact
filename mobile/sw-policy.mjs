export const SHELL =['./', './index.html', './style.css', './app.mjs', './browser-pairing.mjs', './workspace-startup.mjs', './store.mjs', './domain.mjs',
'./reading-position-schema.mjs', './position-json.mjs', './pdf-page-count.mjs',
'./reading-position-report.mjs',
'./primary-source-retention.mjs',
'./reading-position-ops.mjs',
'./position-view.mjs', './position-dialog.mjs',
'./position-recovery.mjs',
'./vendor/pdfjs-6.4.299/pdf.mjs', './vendor/pdfjs-6.4.299/pdf.worker.mjs',
'./vendor/pdfjs-6.4.299/LICENSE', './vendor/pdfjs-6.4.299/provenance.json',
'./lineage-originals.mjs', './lineage-source-view.mjs', './lineage.mjs', './lineage-ops.mjs', './lineage-view.mjs', './later-outcomes.mjs', './engine.mjs', './transport.mjs', './fixture.mjs', './i18n.mjs', './view.mjs', './manifest.webmanifest',
'./icon.svg', './sw-policy.mjs', './content.mjs', './chat-view.mjs', './annotations.mjs', './claims.mjs', './reading-goal.mjs', './list-pins.mjs', './research-activity.mjs', './inbox-schema.mjs', './inbox-ops.mjs', './inbox-view.mjs', './ids.mjs', './artifacts.mjs', './artifact-engine.mjs', './legacy-workflow.mjs', './legacy-view.mjs'];
export function cacheable(request, scope) {
  const url = new URL(request.url),
  base = new URL(scope);
  return request.method === 'GET' && ! request.headers.has('authorization') && ! url.search && url.origin === base.origin && SHELL.some(path => new URL(path,
  base).href === url.href);
}
