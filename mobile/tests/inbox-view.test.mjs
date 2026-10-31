import test from 'node:test';
import assert from 'node:assert/strict';
import {MemoryStore} from '../store.mjs';
import {Engine} from '../engine.mjs';
import {researchInboxDialog,INBOX_COPY} from '../inbox-view.mjs';
import {SHELL} from '../sw-policy.mjs';
class Node {
 constructor(tag,attrs={},children=[]){this.tag=tag;this.attrs=attrs;this.children=children.flat();this.events={};this.value=attrs.value??'';}
 append(...children){this.children.push(...children);}
 replaceChildren(...children){this.children=children;}
 addEventListener(type,callback){this.events[type]=callback;}
 close(){this.events.close?.();}
 remove(){this.removed=true;}
 focus(){this.focused=true;}
 set innerHTML(_value){assert.fail('Inbox rendered unsafe markup');}
 get text(){return this.children.map(value=>value instanceof Node?value.text:String(value)).join('\n');}
 buttons(){return [...(this.tag==='button'?[this]:[]),...this.children.filter(value=>value instanceof Node).flatMap(value=>value.buttons())];}
}
const el=(tag,attrs={},...children)=>new Node(tag,attrs,children);
const tick=()=>new Promise(resolve=>setImmediate(resolve));
async function until(check){const limit=Date.now()+3000;while(!await check()){assert(Date.now()<limit,'Inbox UI did not finish');await tick();}}
async function setup(language='en'){
 const store=new MemoryStore('workspace','phone'),engine=new Engine(store),view=researchInboxDialog(el,{engine,language});
 await view.refresh();return {store,engine,view};
}
async function type(view,text){view.controls.text.value=text;view.controls.text.events.input();await tick();}
test('small bilingual saved-first dialog restores durable exact draft after close/reopen',async()=>{
 assert.deepEqual(Object.keys(INBOX_COPY.en).sort(),Object.keys(INBOX_COPY['zh-TW']).sort());
 for(const language of ['en','zh-TW']){
  const {store,engine,view}=await setup(language);assert(view.dialog.text.includes(INBOX_COPY[language].hint));
  await type(view,'<script>Exact private idea</script>');
  await until(async()=>Object.values((await store.read()).inboxDrafts??{}).some(row=>row.text==='<script>Exact private idea</script>'));
  await view.dispose();assert(view.dialog.removed);assert.equal((await store.read()).outbox.length,0);
  const reopened=researchInboxDialog(el,{engine,language});await reopened.refresh();
  assert.equal(reopened.controls.text.value,'<script>Exact private idea</script>');
  assert(reopened.dialog.text.includes('<script>Exact private idea</script>'));await reopened.dispose();
 }
});
test('duplicate Save is one job and persistent local state does not touch reader drafts',async()=>{
 const {store,view}=await setup();await store.update(state=>{state.drafts.reader='Keep reader draft';});
 await type(view,'Offline input');await until(async()=>Object.keys((await store.read()).inboxDrafts??{}).length===1);
 let start,release;const began=new Promise(resolve=>start=resolve),gate=new Promise(resolve=>release=resolve),original=store.update.bind(store);let hold=true;
 store.update=async change=>{if(hold){start();await gate;}return original(change);};
 view.controls.save.attrs.onclick();await began;for(let i=0;i<15;i++)view.controls.save.attrs.onclick();
 assert.equal((await store.read()).outbox.length,0);hold=false;release();await until(()=>!view.pending);
 const state=await store.read();assert.equal(state.outbox.length,1);assert.equal(state.outbox[0].operation.payload.text,'Offline input');assert.equal(state.drafts.reader,'Keep reader draft');
 assert(view.dialog.text.includes(INBOX_COPY.en.saved));assert.equal(view.controls.text.value,'');await view.dispose();
});
test('failed save keeps draft and exact retry succeeds once',async()=>{
 const {store,view}=await setup();await type(view,'Retry input');await until(async()=>Object.keys((await store.read()).inboxDrafts??{}).length===1);
 store.failure='storage_write_failed';view.controls.save.attrs.onclick();await until(()=>!view.pending);
 assert(view.dialog.text.includes(INBOX_COPY.en.failed));assert.equal(view.controls.text.value,'Retry input');assert.equal((await store.read()).outbox.length,0);
 store.failure=null;view.controls.save.attrs.onclick();await until(()=>!view.pending);
 assert.equal((await store.read()).outbox.length,1);await view.dispose();
});
test('close during held save cancels before atomic write and retains draft through restart',async()=>{
 const {store,engine,view}=await setup();await type(view,'Keep while closing');await until(async()=>Object.keys((await store.read()).inboxDrafts??{}).length===1);
 let start,release;const began=new Promise(resolve=>start=resolve),gate=new Promise(resolve=>release=resolve),original=store.update.bind(store);let hold=true;
 store.update=async change=>{if(hold){start();await gate;}return original(change);};
 view.controls.save.attrs.onclick();await began;const closing=view.dispose();assert(!view.dialog.removed);hold=false;release();await closing;
 assert(view.dialog.removed);assert.equal((await store.read()).outbox.length,0);
 const reopened=researchInboxDialog(el,{engine});await reopened.refresh();assert.equal(reopened.controls.text.value,'Keep while closing');await reopened.dispose();
});
test('workspace/connection change during local read suppresses old display and all writes',async()=>{
 const store=new MemoryStore('workspace','phone'),engine=new Engine(store);let current=true,start,release;
 const began=new Promise(resolve=>start=resolve),gate=new Promise(resolve=>release=resolve),read=store.read.bind(store);
 store.read=async()=>{const value=await read();start();await gate;return value;};
 const view=researchInboxDialog(el,{engine,current:()=>current}),pending=view.refresh();await began;current=false;release();await pending;view.check();
 assert(view.dialog.text.includes(INBOX_COPY.en.changed));assert(view.controls.save.disabled);assert.equal((await read()).outbox.length,0);await view.dispose();
});
test('delete and restore use inline Cancel-first explicit decisions and retain old text',async()=>{
 const {store,view}=await setup();await type(view,'Recoverable capture');await until(async()=>Object.keys((await store.read()).inboxDrafts??{}).length===1);
 view.controls.save.attrs.onclick();await until(()=>!view.pending);
 const remove=()=>view.dialog.buttons().find(button=>button.text===INBOX_COPY.en.remove);
 remove().attrs.onclick();await tick();let cancel=view.dialog.buttons().find(button=>button.text===INBOX_COPY.en.cancel);assert(cancel?.attrs.autofocus==='');
 cancel.attrs.onclick();await tick();assert.equal((await store.read()).outbox.length,1);
 remove().attrs.onclick();await tick();view.dialog.buttons().find(button=>button.text===INBOX_COPY.en.confirm).attrs.onclick();await until(()=>!view.pending&&!!view.dialog.buttons().find(button=>button.text===INBOX_COPY.en.restore));
 assert.equal((await store.read()).outbox.length,2);view.dialog.buttons().find(button=>button.text===INBOX_COPY.en.restore).attrs.onclick();await tick();
 view.dialog.buttons().find(button=>button.text===INBOX_COPY.en.confirm).attrs.onclick();await tick();
 assert.equal(view.controls.text.value,'Recoverable capture');view.controls.save.attrs.onclick();await until(()=>!view.pending);
 const operations=(await store.read()).outbox.map(row=>row.operation);assert.equal(operations.length,3);assert.notEqual(operations[2].incarnation,operations[0].incarnation);await view.dispose();
});
test('new source modules have exact shell closure and live URLs are never anchors or fetch calls',()=>{
 for(const name of ['inbox-schema.mjs','inbox-ops.mjs','inbox-view.mjs'])assert(SHELL.includes('./'+name));
 const {dialog}=researchInboxDialog(el,{engine:new Engine(new MemoryStore('workspace','phone'))});
 assert(!dialog.children.some(node=>node.tag==='a'));
});

test('owned Inbox controls never refresh or replace the existing global reader',async()=>{
 const store=new MemoryStore('workspace','phone'),engine=new Engine(store,{onChange:()=>assert.fail('Inbox refreshed the reader')});
 await store.update(state=>{state.selection={list:'reading',paper:'loaded-paper'};state.drafts.loaded='Keep note draft';});
 const view=researchInboxDialog(el,{engine});await view.refresh();await type(view,'Workspace-owned capture');
 await until(async()=>Object.keys((await store.read()).inboxDrafts??{}).length===1);
 view.controls.save.attrs.onclick();await until(()=>!view.pending);await view.dispose();
 const state=await store.read();assert.deepEqual(state.selection,{list:'reading',paper:'loaded-paper'});assert.equal(state.drafts.loaded,'Keep note draft');assert.equal(state.outbox.length,1);
});
