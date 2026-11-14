import test from 'node:test';
import assert from 'node:assert/strict';
import {lineageSourceDialog,SOURCE_COPY} from '../lineage-source-view.mjs';
import {lineageRow,PAPER} from './fixtures/lineage-data.mjs';
class Node{
 constructor(tag,attrs={},children=[]){this.tag=tag;this.attrs=attrs;this.children=children.flat();this.events={};this.disabled=false;}
 append(...children){this.children.push(...children.flat());}
 replaceChildren(...children){this.children=children;}
 setAttribute(key,value){this.attrs[key]=value;}
 addEventListener(key,fn){this.events[key]=fn;}
 close(){this.events.close?.();}
 remove(){this.removed=true;}
 get text(){return this.children.map(c=>c instanceof Node?c.text:String(c)).join(' ');}
 all(tag){return [...(this.tag===tag?[this]:[]),...this.children.filter(c=>c instanceof Node).flatMap(c=>c.all(tag))];}
 set innerHTML(_){assert.fail('Untrusted original HTML');}
}
const el=(tag,attrs,...children)=>new Node(tag,attrs,children);
function setup({actions,language='en',current=()=>true,connected=()=>true,available=()=>true,page=1}={}){
 const row=lineageRow(),sourceId=row.body.report.sources[0].id,created=[],revoked=[],calls=[];
 const lease={page_count:1,sha256:'a'.repeat(64)};
 const view=lineageSourceDialog(el,{engine:{},paper:PAPER,row,sourceId,language,page,current,connected,available,
  actions:actions??{open:async(_e,_p,_r,_s,options)=>{calls.push(options.download);return lease;},deliver:async()=>new Uint8Array([1,2,3])},
  urls:{createObjectURL(blob){created.push(blob);return 'blob:original-'+created.length;},revokeObjectURL(url){revoked.push(url);}}});
 return {view,created,revoked,calls};
}
test('bilingual original dialog opens exact PDF page and revokes every URL on replacement and close',async()=>{
 for(const language of ['en','zh-TW']){
  const {view,created,revoked,calls}=setup({language});assert(view.dialog.text.includes(SOURCE_COPY[language].scope));
  await view.load(false);assert.deepEqual(calls,[false]);assert.equal(created.length,1);
  assert.equal(view.controls.output.all('object')[0].attrs.data,'blob:original-1#page=1');
  assert(view.dialog.text.includes(SOURCE_COPY[language].ready));
  await view.load(false);assert.deepEqual(revoked,['blob:original-1']);view.dispose();view.dispose();
  assert.deepEqual(revoked,['blob:original-1','blob:original-2']);assert(view.disposed);
 }
});
test('unknown or out-of-bounds pages never become fabricated locations',async()=>{
 for(const page of [null,0,2,'1',NaN]){const {view}=setup({page});await view.load(false);
  assert.equal(view.controls.output.all('object')[0].attrs.data,'blob:original-1');view.dispose();}
});
test('repeated activation while downloading creates one job and exposes busy state',async()=>{
 let release,calls=0;const hold=new Promise(r=>release=r);
 const {view,created}=setup({actions:{open:async()=>{calls++;await hold;return {page_count:1};},deliver:async()=>new Uint8Array([1])}});
 const pending=view.load(true);for(let i=0;i<20;i++)void view.load(true);
 assert.equal(calls,1);assert(view.pending);assert(view.controls.open.disabled);assert(view.controls.download.disabled);
 assert.equal(view.dialog.attrs['aria-busy'],'true');release();await pending;assert.equal(created.length,1);assert(!view.pending);view.dispose();
});
test('closing during completion aborts presentation without creating a PDF URL',async()=>{
 let release,signal;const hold=new Promise(r=>release=r);
 const {view,created}=setup({actions:{open:async(_e,_p,_r,_s,options)=>{signal=options.signal;await hold;return {page_count:1};},deliver:async()=>new Uint8Array([1])}});
 const pending=view.load(true);view.dispose();assert(signal.aborted);release();await pending;assert.equal(created.length,0);assert(view.disposed);
});
test('changing paper while work is held closes the old dialog and refuses delivery',async()=>{
 let current=true,release;const hold=new Promise(r=>release=r);
 const {view,created}=setup({current:()=>current,actions:{open:async()=>{await hold;return {page_count:1};},deliver:async()=>new Uint8Array([1])}});
 const pending=view.load(false);current=false;release();await pending;assert(view.disposed);assert.equal(created.length,0);
});
test('failure retains a retryable dialog and does not leak raw service messages',async()=>{
 let calls=0;const {view}=setup({actions:{open:async()=>{if(++calls===1)throw new Error('private fixture detail');return {page_count:1};},deliver:async()=>new Uint8Array([1])}});
 await view.load(true);assert(view.dialog.text.includes(SOURCE_COPY.en.failed));assert(!view.dialog.text.includes('private fixture detail'));
 assert(!view.controls.download.disabled);await view.load(true);assert(view.dialog.text.includes(SOURCE_COPY.en.ready));view.dispose();
});
test('no live source permission and offline mode cannot start a download',async()=>{
 const unavailable=setup({available:()=>false});await unavailable.view.load(true);assert.deepEqual(unavailable.calls,[]);
 assert(unavailable.view.controls.open.disabled);assert(unavailable.view.controls.download.disabled);unavailable.view.dispose();
 const offline=setup({connected:()=>false});await offline.view.load(true);assert.deepEqual(offline.calls,[]);
 assert(!offline.view.controls.open.disabled);assert(offline.view.controls.download.disabled);await offline.view.load(false);assert.deepEqual(offline.calls,[false]);offline.view.dispose();
});
test('refresh of a retired source revokes the displayed URL; changed scope closes it',async()=>{
 let current=true,retired=false;const {view,revoked}=setup({current:()=>current,actions:{open:async()=>({page_count:1}),deliver:async()=>{if(retired)throw new Error('retired');return new Uint8Array([1]);}}});
 await view.load(false);retired=true;await view.refresh();assert.deepEqual(revoked,['blob:original-1']);assert.equal(view.controls.output.all('object').length,0);
 assert(view.dialog.text.includes(SOURCE_COPY.en.changed));current=false;await view.refresh();assert(view.disposed);
});

test('native dialog cancellation closes and revokes the displayed original',async()=>{
 const {view,revoked}=setup();await view.load(false);let prevented=false;
 view.dialog.events.cancel({preventDefault(){prevented=true;}});
 assert(prevented);assert(view.disposed);assert.deepEqual(revoked,['blob:original-1']);
});

test('normal close restores the live opener but changed context cannot steal focus',async()=>{
 for(const changed of [false,true]){
  let focused=0,current=true;const opener={isConnected:true,disabled:false,focus(){focused++;}};
  const ownedEl=(tag,attrs,...children)=>{const node=el(tag,attrs,...children);node.ownerDocument={activeElement:opener};return node;};
  const row=lineageRow(),view=lineageSourceDialog(ownedEl,{engine:{},paper:PAPER,row,sourceId:row.body.report.sources[0].id,current:()=>current});
  if(changed)current=false;view.dispose();assert.equal(focused,changed?0:1);
 }
});
