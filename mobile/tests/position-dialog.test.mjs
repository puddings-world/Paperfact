import test from 'node:test';
import assert from 'node:assert/strict';
import {readingPositionDialog} from '../position-dialog.mjs';
import {POSITION_COPY,positionChoices} from '../position-view.mjs';
import {MemoryStore,copy} from '../store.mjs';
import {Engine} from '../engine.mjs';
import {demoTransport,operation,PAPER} from '../fixture.mjs';
import {enqueue,receive,stable} from '../domain.mjs';
import {contentId} from '../ids.mjs';
import {sourceFileId} from '../artifacts.mjs';
class Node {
 constructor(tag,attrs={},children=[]){this.tag=tag;this.attrs=attrs;this.children=children.flat();this.events={};this.value=attrs.value??'';this.disabled=false;}
 append(...children){this.children.push(...children);}
 replaceChildren(...children){this.children=children;}
 addEventListener(type,fn){this.events[type]=fn;}
 setAttribute(key,value){this.attrs[key]=value;}
 removeAttribute(key){delete this.attrs[key];}
 close(){this.open=false;this.events.close?.();}
 showModal(){this.open=true;}
 remove(){this.removed=true;}
 focus(){this.focused=true;}
 set innerHTML(_value){assert.fail('Unsafe position HTML');}
 get text(){return this.children.map(value=>value instanceof Node?value.text:String(value)).join('\n');}
 all(tag){return [...(this.tag===tag?[this]:[]),...this.children.filter(value=>value instanceof Node).flatMap(value=>value.all(tag))];}
}
const el=(tag,attrs={},...children)=>new Node(tag,attrs,children),tick=()=>new Promise(resolve=>setImmediate(resolve));
async function until(fn){const end=Date.now()+3000;while(!await fn()){assert(Date.now()<end,'Position UI did not settle');await tick();}}
const event=(operation,sequence)=>({sequence,outcome:'accepted',operation,head:{revision:sequence,operation}});
async function setup({language='en',current=()=>true,blocked=()=>false,openGate=null,saveGate=null,deferred=false,openError=null}={}){
 const transport=await demoTransport(),store=new MemoryStore('demo-workspace','demo-phone'),engine=new Engine(store),calls={open:0,save:0,draft:0},live=new Set();
 await store.update(state=>receive(state,transport.events));
 const initial=positionChoices(await store.read(),PAPER).options[0],parent=copy(initial.document.parents[0]);
 const observe=hash=>({paper_incarnation:parent.incarnation,source_operation_id:null,source_incarnation:null,
   position_operation_id:null,position_incarnation:null,position_action:null});
 const actions={
  open:async(_engine,_paper,choice,options)=>{calls.open++;if(openGate)await openGate;
   if(!options.current()||options.signal.aborted)throw Error('cancelled');if(openError)throw Error(openError);
   return {captured:{hash:choice.hash,json:JSON.stringify({observed:observe(choice.hash)})},bytes:new Uint8Array([37,80,68,70]),pageCount:2};},
  save:async(_engine,captured,request)=>{calls.save++;if(saveGate)await saveGate;
   await store.update(state=>{if(!request.current())throw Error('cancelled');
    enqueue(state,operation('research_content',contentId({kind:'paper',id:PAPER},'reading_position',captured.hash),
      {scope:{kind:'paper',id:PAPER},feature:'reading_position',key:captured.hash,source_document_hash:captured.hash,
       data:{page:request.page,recorded_at:request.recordedAt,method:'entered'}},
      {operationId:request.requestId,device:'demo-phone',parents:[parent]}));});
   return {status:'saved'};},
  draft:async(_engine,captured,request,options)=>{calls.draft++;await store.update(state=>{
   if(!options.current())throw Error('cancelled');state.positionDrafts??={};state.positionDrafts[PAPER+'/'+captured.hash]={
    pageText:request.pageText,requestId:request.requestId,recordedAt:request.recordedAt,observed:request.observed,primary_document:initial.document};});}
 };
 const urls={createObjectURL:()=>{const url='blob:fixture-'+live.size;live.add(url);return url;},revokeObjectURL:url=>live.delete(url)};
 const options={engine,paper:PAPER,language,current,blocked,actions,urls};
 const view=readingPositionDialog(el,options),loading=view.refresh();if(!deferred)await loading;
 return {store,engine,view,calls,live,initial,options,loading};
}
function type(view,value){view.controls.page.value=value;view.controls.page.events.input();}
function click(view,key){view.controls[key].attrs.onclick();}
function named(view,name){return view.dialog.all('button').find(node=>node.text===name);}

test('bilingual manual page form is disabled until count, enforces bounds and creates one exact entered value',async()=>{
 for(const language of ['en','zh-TW']){
  const {view,store,calls,live}=await setup({language});assert(view.dialog.text.includes(POSITION_COPY[language].hint));
  assert(view.controls.save.disabled);type(view,'3');assert(view.controls.save.disabled);type(view,'2');assert(!view.controls.save.disabled);
  click(view,'save');for(let i=0;i<20;i++)click(view,'save');await until(()=>view.disposed);
  const state=await store.read();assert.equal(calls.save,1);assert.equal(state.outbox.length,1);
  assert.equal(state.outbox[0].operation.payload.data.page,2);assert.equal(state.outbox[0].operation.payload.data.method,'entered');assert.equal(live.size,0);
 }
});
test('failure retains typed page and stable request; exact retry saves once without touching note drafts',async()=>{
 const {view,store}=await setup();await store.update(state=>{state.drafts.reader='Kept note draft';});type(view,'2');store.failure='fixture_storage_failure';
 click(view,'save');await until(()=>!view.pending);assert.equal(view.controls.page.value,'2');assert(view.dirty);assert.equal((await store.read()).outbox.length,0);
 store.failure=null;click(view,'save');await until(()=>view.disposed);assert.equal((await store.read()).outbox.length,1);assert.equal((await store.read()).drafts.reader,'Kept note draft');
});
test('dirty close offers Cancel-first Keep/Discard; Keep is durable through reopening without active jobs',async()=>{
 const {view,store,options}=await setup();type(view,'2');view.dispose();assert(!view.disposed);
 assert(named(view,POSITION_COPY.en.editing).attrs.autofocus==='');named(view,POSITION_COPY.en.editing).attrs.onclick();assert(!view.disposed);
 view.dispose();named(view,POSITION_COPY.en.keep).attrs.onclick();await until(()=>view.disposed);
 assert.equal((await store.read()).outbox.length,0);assert.equal(Object.values((await store.read()).positionDrafts)[0].pageText,'2');
 const reopened=readingPositionDialog(el,options);await reopened.refresh();assert.equal(reopened.controls.page.value,'2');reopened.dispose();assert(reopened.disposed);
});
test('current C arriving while selected B is dirty neither replaces the source nor erases page text',async()=>{
 const {view,store,calls,initial}=await setup();type(view,'2');
 await store.update(state=>{const C=copy(initial.document);C.operation_id='current-C';C.payload.sha256='c'.repeat(64);receive(state,[event(C,state.cursor+1)]);});
 await view.refresh(false);assert.equal(view.controls.select.value,initial.hash);assert.equal(view.controls.page.value,'2');assert(view.dirty);
 assert(view.dialog.text.includes(POSITION_COPY.en.newer));assert.equal(calls.open,1);
 click(view,'save');await until(()=>view.disposed);assert.equal((await store.read()).outbox[0].operation.payload.key,initial.hash);
});
test('known retirement invalidates B while retaining visible text until explicit discard',async()=>{
 const {view,store,initial,calls}=await setup();type(view,'2');
 await store.update(state=>{state.graph['research_file/'+sourceFileId(PAPER,initial.hash)]={active:false};});await view.refresh(false);
 assert(view.controls.save.disabled);assert.equal(view.controls.page.value,'2');assert(view.dialog.text.includes(POSITION_COPY.en.changed));
 click(view,'save');assert.equal(calls.save,0);view.dispose();assert(!view.disposed);assert(named(view,POSITION_COPY.en.keep).disabled);
 named(view,POSITION_COPY.en.discard).attrs.onclick();assert(view.disposed);assert.equal((await store.read()).outbox.length,0);
});
test('global busy or note draft blocks remembering and opening another viewer without discarding text',async()=>{
 let blocked=true;const {view,store}=await setup({blocked:()=>blocked});type(view,'2');assert(view.controls.save.disabled);
 click(view,'save');assert.equal((await store.read()).outbox.length,0);assert.equal(view.controls.page.value,'2');
 let prevented=false;view.controls.open.events.click({preventDefault(){prevented=true;}});assert(prevented);
 blocked=false;await view.refresh(false);assert(!view.controls.save.disabled);view.dispose();named(view,POSITION_COPY.en.discard).attrs.onclick();
});
test('close during held local save cancels admission, then keeps a reopenable private draft',async()=>{
 let release;const gate=new Promise(resolve=>release=resolve),{view,store,options,calls}=await setup({saveGate:gate});type(view,'2');click(view,'save');
 await until(()=>calls.save===1);view.dispose();assert(!view.disposed);release();await until(()=>!view.pending);
 assert.equal((await store.read()).outbox.length,0);assert.equal(view.controls.page.value,'2');
 named(view,POSITION_COPY.en.keep).attrs.onclick();await until(()=>view.disposed);
 const reopened=readingPositionDialog(el,options);await reopened.refresh();assert.equal(reopened.controls.page.value,'2');reopened.dispose();
});
test('workspace/auth change keeps page text visible but disables all late writes',async()=>{
 let current=true;const {view,store,calls}=await setup({current:()=>current});type(view,'2');current=false;await view.refresh(false);
 click(view,'save');assert.equal(calls.save,0);assert.equal(view.controls.page.value,'2');assert(view.controls.save.disabled);
 view.dispose();named(view,POSITION_COPY.en.discard).attrs.onclick();assert.equal((await store.read()).outbox.length,0);
});
test('held B count remains the selected earlier version when C arrives before delivery',async()=>{
 let release;const gate=new Promise(resolve=>release=resolve),{view,store,initial,loading}=await setup({openGate:gate,deferred:true});
 await until(()=>view.pending);await store.update(state=>{const C=copy(initial.document);C.operation_id='C-during-count';C.payload.sha256='c'.repeat(64);receive(state,[event(C,state.cursor+1)]);});
 await view.refresh(false);release();await loading;
 assert.equal(view.controls.select.value,initial.hash);assert(!view.controls.page.disabled);
 const label=view.dialog.all('p').find(node=>node.attrs.class==='position-source');assert(label.text.includes(POSITION_COPY.en.earlier));
 assert.equal((await store.read()).outbox.length,0);view.dispose();
});
test('closing held count waits for cancellation and suppresses late URL/field delivery',async()=>{
 let release;const gate=new Promise(resolve=>release=resolve),{view,store,live,loading,calls}=await setup({openGate:gate,deferred:true});
 await until(()=>calls.open===1);for(let n=0;n<20;n++)click(view,'check');assert.equal(calls.open,1);
 view.dispose();assert(!view.disposed);release();await loading;
 assert(view.disposed);assert.equal(live.size,0);assert.equal(view.controls.page.value,'');assert.equal((await store.read()).outbox.length,0);
});
for(const change of ['paper','auth','parent','source'])test('held preparation refuses late delivery after '+change,async()=>{
 let current=true,release;const gate=new Promise(resolve=>release=resolve),{view,store,engine,initial,loading,live,calls}=await setup({current:()=>current,openGate:gate,deferred:true});
 await until(()=>calls.open===1);
 if(change==='paper')current=false;
 if(change==='auth')engine.disconnect();
 if(change==='parent')await store.update(state=>{state.graph['paper/'+PAPER].incarnation='new-parent';});
 if(change==='source')await store.update(state=>{state.graph['research_file/'+sourceFileId(PAPER,initial.hash)]={active:false};});
 await view.refresh(false);release();await loading;
 assert.equal(live.size,0);assert.equal(view.controls.page.value,'');assert(view.controls.save.disabled);assert.equal((await store.read()).outbox.length,0);view.dispose();
});
test('source change keeps dirty B until explicit Keep or Discard, then checks only the chosen C',async()=>{
 const {view,store,initial,calls}=await setup();type(view,'2');let C;
 await store.update(state=>{C=copy(initial.document);C.operation_id='new-C-choice';C.payload.sha256='c'.repeat(64);receive(state,[event(C,state.cursor+1)]);});await view.refresh(false);
 view.controls.select.value=C.payload.sha256;view.controls.select.events.change();assert.equal(view.controls.select.value,initial.hash);assert.equal(calls.open,1);
 named(view,POSITION_COPY.en.editing).attrs.onclick();assert.equal(view.controls.page.value,'2');
 view.controls.select.value=C.payload.sha256;view.controls.select.events.change();named(view,POSITION_COPY.en.keep).attrs.onclick();await until(()=>!view.pending&&calls.open===2);
 assert.equal(view.controls.select.value,C.payload.sha256);assert.equal((await store.read()).positionDrafts[PAPER+'/'+initial.hash].pageText,'2');assert.equal((await store.read()).outbox.length,0);view.dispose();
});
test('oversized recovery file refuses before reading bytes or changing private/live state',async()=>{
 const {view,store}=await setup(),before=await store.read();view.controls.importFile.files=[{size:64*1024**2+1,text:()=>assert.fail('Oversized file read')}];
 view.controls.importFile.events.change();await until(()=>!view.pending);assert.equal(stable(await store.read()),stable(before));
 assert(view.dialog.text.includes(POSITION_COPY.en.recoveryLimit));view.dispose();
});
test('background refresh cannot strand a newly opened dialog before its requested count',async()=>{
 const {view,store,options,calls}=await setup();view.dispose();
 const read=store.read.bind(store);let first=true,release,started;
 const gate=new Promise(resolve=>release=resolve),began=new Promise(resolve=>started=resolve);
 store.read=async()=>{const state=await read();if(first){first=false;started();await gate;}return state;};
 const opened=readingPositionDialog(el,options),loading=opened.refresh();await began;await opened.refresh(false);release();await loading;
 assert.equal(calls.open,2);assert(!opened.controls.page.disabled);assert.equal((await read()).outbox.length,0);opened.dispose();
});
test('legacy recovery import is explicitly unsupported and cannot replay its old outbox or drafts',async()=>{
 const {view,store,engine}=await setup(),before=await store.read(),text=JSON.stringify(await engine.exportLocal());
 view.controls.importFile.files=[{size:new TextEncoder().encode(text).length,text:async()=>text}];view.controls.importFile.events.change();
 await until(()=>!view.pending);assert.equal(stable(await store.read()),stable(before));assert(view.dialog.text.includes(POSITION_COPY.en.importLimit));view.dispose();
});
for(const code of ['file_too_large','pdf_count_size_limit'])test('actual count limit is actionable and never enables an unverified page: '+code,async()=>{
 const {view,store}=await setup({openError:code});assert(view.controls.save.disabled);assert(view.dialog.text.includes(POSITION_COPY.en.tooLarge));
 assert.equal((await store.read()).outbox.length,0);view.dispose();
});
test('default bilingual copy stays compact while both native-viewer facts remain in the closed help disclosure',async()=>{
 for(const language of ['en','zh-TW']){
  const {view,initial}=await setup({language}),t=POSITION_COPY[language];
  const visible=view.dialog.children.filter(node=>node.tag!=='details').map(node=>node.text).join('\n');
  assert(visible.includes(t.hint));assert(!visible.includes(t.viewerHelp));assert(!visible.includes(t.jump));
  const help=view.dialog.all('details').find(node=>node.text.includes(t.viewerHelp));assert(help&&help.text.includes(t.jump));assert(!help.open&&!Object.hasOwn(help.attrs,'open'));
  assert.equal(view.dialog.all('p').find(node=>node.attrs.id==='position-page-info').text,`${t.checked}: 2.`);
  const identifier=view.dialog.all('small').find(node=>node.attrs.title===initial.hash);assert(identifier.text.startsWith(t.identifier));assert(identifier.text.endsWith(initial.hash.slice(0,12)));
  view.dispose();
 }
});
