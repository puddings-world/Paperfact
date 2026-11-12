import test from 'node:test';
import assert from 'node:assert/strict';
import {SHELL} from '../sw-policy.mjs';

test('activating a new offline shell replaces stale view code without touching research caches',async()=>{
  const names=['self','caches','fetch'],previous=new Map(names.map(name=>[name,Object.getOwnPropertyDescriptor(globalThis,name)]));
  const listeners=new Map(),scope='https://paperfact.invalid/mobile/',current='paperfact-mobile-shell-v16';
  const stored=new Map([['paperfact-mobile-shell-v15',new Map([['view.mjs','stale view']])],['research-protected',new Map([['note','private words']])]]);
  let installed=[],network=0;
  try {
    Object.defineProperty(globalThis,'self',{configurable:true,value:{registration:{scope},addEventListener:(name,callback)=>listeners.set(name,callback)}});
    Object.defineProperty(globalThis,'fetch',{configurable:true,value:async()=>{network++;throw Error('unexpected network');}});
    Object.defineProperty(globalThis,'caches',{configurable:true,value:{
      keys:async()=>[...stored.keys()],delete:async name=>stored.delete(name),
      open:async name=>{
        if(!stored.has(name))stored.set(name,new Map());
        const cache=stored.get(name);
        return {addAll:async files=>{installed=[...files];for(const file of files)cache.set(new URL(file,scope).href,'fresh '+file);},
          match:async request=>cache.has(request.url)?new Response(cache.get(request.url)):undefined};
      }
    }});
    await import('../sw.mjs?workspace-selection-upgrade');
    const run=async name=>{let task;listeners.get(name)({waitUntil:promise=>{task=promise;}});assert(task);await task;};
    await run('install');
    assert.deepEqual(installed,[...SHELL]);
    assert(installed.includes('./view.mjs'));assert(installed.includes('./workspace-startup.mjs'));
    await run('activate');
    assert(!stored.has('paperfact-mobile-shell-v15'));assert(stored.has(current));
    assert.deepEqual([...stored.get('research-protected')],[['note','private words']]);
    let response;
    listeners.get('fetch')({request:new Request(new URL('./view.mjs',scope)),respondWith:promise=>{response=promise;}});
    assert.equal(await (await response).text(),'fresh ./view.mjs');
    for(const request of [new Request(new URL('./v1/pull',scope)),new Request(new URL('./view.mjs',scope),{headers:{Authorization:'Bearer synthetic'}})]){
      let intercepted=false;
      listeners.get('fetch')({request,respondWith:()=>{intercepted=true;}});
      assert.equal(intercepted,false);
    }
    assert.equal(network,0);
  } finally {
    for(const name of names){const descriptor=previous.get(name);if(descriptor)Object.defineProperty(globalThis,name,descriptor);else delete globalThis[name];}
  }
});
