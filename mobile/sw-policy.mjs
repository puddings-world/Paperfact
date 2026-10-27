export const SHELL =['./', './index.html', './style.css', './app.mjs', './store.mjs', './domain.mjs',
'./engine.mjs', './transport.mjs', './fixture.mjs', './i18n.mjs', './view.mjs', './manifest.webmanifest',
'./icon.svg', './sw-policy.mjs', './content.mjs', './chat-view.mjs', './ids.mjs', './artifacts.mjs', './artifact-engine.mjs'];
export function cacheable(request, scope) {
  const url = new URL(request.url),
  base = new URL(scope);
  return request.method === 'GET' && ! request.headers.has('authorization') && ! url.search && url.origin === base.origin && SHELL.some(path => new URL(path,
  base).href === url.href);
}
