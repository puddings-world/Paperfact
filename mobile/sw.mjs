import {
  SHELL,
  cacheable
} from './sw-policy.mjs';
const CACHE = 'paperfact-mobile-shell-v7';
self.addEventListener('install', event => {
  event.waitUntil(caches.open(CACHE).then(cache => cache.addAll(SHELL)));
});
self.addEventListener(
'activate',
event => {
  event.waitUntil(caches.keys().then(keys => Promise.all(keys.filter(key => key.startsWith('paperfact-mobile-shell-') && key !== CACHE).map(key => caches.delete(key)))));
}
);
self.addEventListener(
'fetch',
event => {
  if(! cacheable(event.request, self.registration.scope)) return;
  event.respondWith(caches.open(CACHE).then(async cache =>(await cache.match(event.request)) ?? fetch(event.request)));
}
);
