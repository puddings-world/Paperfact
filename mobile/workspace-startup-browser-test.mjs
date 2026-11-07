/** Real browser IndexedDB and actual app startup; synthetic cached work only. */
import {IndexedStore,MemoryStore,scopeKey,copy} from './store.mjs';
import {Engine} from './engine.mjs';
import {demoTransport,PAPER,MEMBER} from './fixture.mjs';
import {receive} from './domain.mjs';
import {WORKSPACE_HINT_KEY,rememberWorkspace,forgetWorkspaceHint} from './workspace-startup.mjs';

const results=[],assert=(value,message)=>{if(!value)throw Error(message);};
const output=document.querySelector('#result');
const workspace='resume-workspace',device='resume-phone',origin='https://resume.invalid';
let cache,saved;
async function check(name,run){try{await run();results.push('PASS '+name);}catch(error){results.push('FAIL '+name+': '+error.message);}output.textContent=results.join('\n');}
async function until(test,label){for(let i=0;i<150;i++){if(await test())return;await new Promise(r=>setTimeout(r,30));}throw Error('Timed out '+label);}
async function rawScope(action){
  const db=cache.db;
  return new Promise((resolve,reject)=>{let value;const tx=db.transaction('scopes','readwrite'),table=tx.objectStore('scopes');
    value=action(table);tx.oncomplete=()=>resolve(value);tx.onabort=tx.onerror=()=>reject(Error('fixture transaction'));});
}
async function rawGet(key){return new Promise((resolve,reject)=>{let value;const tx=cache.db.transaction('scopes','readonly'),req=tx.objectStore('scopes').get(key);
  req.onsuccess=()=>value=copy(req.result);tx.oncomplete=()=>resolve(value);tx.onabort=tx.onerror=reject;});}
let frame;
async function openApp(){
  frame?.remove();frame=document.createElement('iframe');frame.title='Actual offline workspace reader';frame.width='390';frame.height='844';
  document.body.append(frame);frame.src='./index.html';
  await until(()=>frame.contentDocument?.querySelector('.layout'),'actual app startup');
  return frame.contentDocument;
}

await check('Missing database resume aborts creation instead of inventing an empty workspace',async()=>{
  assert(await IndexedStore.openExisting('missing','phone')===null,'missing database returned a store');
  if(indexedDB.databases)assert(!(await indexedDB.databases()).some(db=>db.name==='paperfact-mobile-v1'),'resume created a database');
});
await check('Cached-only scope preserves real pending work and rejects absent or wrong-owner records',async()=>{
  const fixture=await demoTransport(),state=new MemoryStore(workspace,device);
  const events=copy(fixture.events);
  for(const event of events){event.operation.workspace_id=workspace;if(event.head?.operation)event.head.operation.workspace_id=workspace;}
  await state.update(value=>receive(value,events));
  const engine=new Engine(state);
  await engine.draft('demo-note','Resume private draft',await engine.observeNote('demo-note',PAPER));
  await engine.reading(MEMBER,'demo-list',PAPER,'read');
  saved=await state.read();saved.selection={list:'demo-list',paper:PAPER};
  cache=await IndexedStore.open(workspace,device);await cache.update(value=>Object.assign(value,copy(saved)));
  const reopened=await IndexedStore.openExisting(workspace,device);assert(reopened,'existing store missing');
  assert(JSON.stringify(await reopened.read())===JSON.stringify(saved),'saved state changed');reopened.close();
  assert(await IndexedStore.openExisting('absent-scope','phone')===null,'absent scope created');
  assert(await rawGet(scopeKey('absent-scope','phone'))===undefined,'absent row written');
  await rawScope(table=>table.put({...copy(saved),workspace:'other-owner'},scopeKey('broken-scope','phone')));
  let refused=false;try{await IndexedStore.openExisting('broken-scope','phone');}catch(error){refused=error.message==='wrong_scope';}
  assert(refused,'wrong owner accepted');assert((await rawGet(scopeKey('broken-scope','phone'))).workspace==='other-owner','corrupt row overwritten');
});
await check('A deleted cached scope cannot reappear through an already reopened handle',async()=>{
  const reopened=await IndexedStore.openExisting(workspace,device);
  await rawScope(table=>table.delete(scopeKey(workspace,device)));
  let refused=false;try{await reopened.read();}catch(error){refused=error.message==='workspace_not_cached';}
  assert(refused,'missing scope became an empty state');
  try{await reopened.update(value=>{value.drafts.note='must not be inserted';});}catch{}
  assert(await rawGet(scopeKey(workspace,device))===undefined,'strict cached update recreated a row');reopened.close();
  await cache.update(value=>Object.assign(value,copy(saved)));
});
await check('Actual startup reopens cached drafts and queue without a token, then explicit demo forgets only the hint',async()=>{
  assert(rememberWorkspace({workspace,device,origin}),'hint write failed');
  const doc=await openApp();
  await until(()=>doc.querySelector('.workspace')?.textContent===workspace,'cached workspace');
  assert(doc.querySelector('header button').disabled,'startup authenticated automatically');
  doc.querySelector('#tab-notes').click();
  await until(()=>doc.querySelector('#note-editor')?.value==='Resume private draft','private draft');
  assert(JSON.stringify(await cache.read())===JSON.stringify(saved),'startup changed queue/draft/cursor');
  assert(!localStorage.getItem(WORKSPACE_HINT_KEY).includes('token'),'credential hint persisted');
  [...doc.querySelectorAll('header button')].find(b=>['Connection','連線'].includes(b.textContent)).click();
  const inputs=doc.querySelector('dialog').querySelectorAll('.fields input');
  assert(inputs[0].value===workspace&&inputs[1].value===device&&inputs[2].value===origin&&!inputs[3].value,'connection fields/blank credential wrong');
  [...doc.querySelectorAll('dialog button')].find(b=>['Open demo workspace','開啟示範工作區'].includes(b.textContent)).click();
  await until(()=>localStorage.getItem(WORKSPACE_HINT_KEY)===null,'explicit demo choice');
  assert(JSON.stringify(await cache.read())===JSON.stringify(saved),'demo choice changed private state');
});
await check('Library paper restores without a selected list and retained draft stays unchanged',async()=>{
  saved.selection={list:null,paper:PAPER};
  await cache.update(value=>Object.assign(value,copy(saved)));
  assert(rememberWorkspace({workspace,device,origin}),'library hint write failed');
  const doc=await openApp();
  await until(()=>doc.querySelector('.workspace')?.textContent===workspace,'library cached workspace');
  assert(doc.querySelector('#tab-notes'),'library paper was not restored');
  doc.querySelector('#tab-notes').click();
  await until(()=>doc.querySelector('#note-editor')?.value==='Resume private draft','library retained draft');
  assert(JSON.stringify(await cache.read())===JSON.stringify(saved),'library startup changed saved state');
});
for(const kind of ['missing','malformed','corrupt'])await check('Unusable '+kind+' hint leaves research intact and exposes Connection',async()=>{
  if(kind==='corrupt')await rawScope(table=>table.put({...copy(saved),workspace:'corrupt-scope',device:'phone',entities:null},scopeKey('corrupt-scope','phone')));
  if(kind==='malformed')localStorage.setItem(WORKSPACE_HINT_KEY,'{"token":"do-not-use"}');
  else rememberWorkspace({workspace:kind==='missing'?'absent-scope':'corrupt-scope',device:'phone',origin});
  const doc=await openApp();
  await until(()=>doc.querySelector('#notice-text')?.textContent.includes('last workspace')||doc.querySelector('#notice-text')?.textContent.includes('上次工作區'),'resume warning');
  assert([...doc.querySelectorAll('header button')].some(b=>['Connection','連線'].includes(b.textContent)),'connection missing');
  assert(JSON.stringify(await cache.read())===JSON.stringify(saved),'fallback changed private work');
  assert(await rawGet(scopeKey('absent-scope','phone'))===undefined,'fallback invented missing scope');
});
frame?.remove();cache?.close();forgetWorkspaceHint();
document.body.dataset.result=results.some(line=>line.startsWith('FAIL'))?'fail':'pass';
output.textContent=results.join('\n')+'\n'+document.body.dataset.result.toUpperCase();
