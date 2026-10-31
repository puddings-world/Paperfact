import test from 'node:test';
import assert from 'node:assert/strict';
import {activityReport,canOpenSavedNote,activateActivity,ACTIVITY_COPY,researchActivityDialog} from '../research-activity.mjs';
import {demoTransport,PAPER,operation,ref} from '../fixture.mjs';
import {receive,stable} from '../domain.mjs';
import {MemoryStore,emptyState} from '../store.mjs';
const NOTE='33333333-3333-4333-8333-333333333333';
const event=(op,sequence,outcome='accepted',head=null)=>({sequence,outcome,operation:op,head:head??{revision:sequence,operation:op}});
async function fixture({own=false}={}) {
  const transport=await demoTransport(),state=emptyState('demo-workspace','demo-phone');receive(state,transport.events);
  const target=state.entities['paper_document/'+PAPER].operation;
  const hash=target.payload.sha256,anchor={p0:0,o0:1,p1:0,o1:2,document_hash:hash};
  const op=operation('note',NOTE,{paper_id:PAPER,body:'Exact saved note <script>literal</script>',kind:'note',created_at:'2026-10-30T12:00:00Z',page:1,anchor},
    {operationId:'source-note',device:own?'demo-phone':'demo-desktop',parents:[ref('paper',PAPER)]});
  receive(state,[event(op,state.cursor+1)]);
  return {state,op,hash,anchor,target,transport};
}
test('received sequence order, truthful metadata state and recorded source-pinned note survive offline reopen',async()=>{
  const {state,hash,anchor}=await fixture(),before=stable(state),report=activityReport(state);
  assert.deepEqual(report.recent.map(r=>r.sequence),[7,6,5,4,3,2,1]);
  assert.equal(report.recent.find(r=>r.entity_type==='paper_document').status,'manifest_waiting');
  const row=report.continue[0];assert.equal(row.operation_id,'source-note');assert.deepEqual(row.resume,{note_id:NOTE,source_hash:hash,anchor});
  assert.equal(report.coverage,'received_note_reading_updates');assert.equal(stable(state),before);
  const reopened=new MemoryStore('demo-workspace','demo-phone',state);
  assert.deepEqual(activityReport(await reopened.read()),report);
  assert.deepEqual((await reopened.read()).outbox,[]);
});
test('accepted own echo is hidden while own recorded reading/note activity and conflicts remain useful',async()=>{
  const {state,op}=await fixture({own:true}),sequence=state.cursor+1,bad={...op,operation_id:'own-conflict'};
  receive(state,[event(bad,sequence,'conflict',{revision:sequence-1,operation:op})]);
  const report=activityReport(state);
  assert(!report.recent.some(row=>row.operation_id==='source-note'));
  assert.equal(report.continue[0].operation_id,'source-note');
  assert.equal(report.recent[0].status,'conflict_retained');assert.equal(report.recent[0].origin,'this_device');
});
test('verified flag is labelled only as a binding record, never as present PDF bytes',async()=>{
  const {state,hash,target}=await fixture();state.files[hash]={verified:true,size:target.payload.size,chunks:[]};
  assert.equal(activityReport(state).recent.find(row=>row.entity_type==='paper_document').status,'binding_recorded');
  assert(!Object.values(ACTIVITY_COPY.en).some(text=>text==='PDF downloaded'));
});
for(const kind of ['pending','parent-replaced','parent-deleted','note-deleted'])test('continue hides stale or unapplied activity: '+kind,async()=>{
  const {state,op}=await fixture();
  if(kind==='pending')state.outbox.push({operation:{...op,operation_id:'pending-local'}});
  if(kind==='parent-replaced')state.graph['paper/'+PAPER].incarnation='new-paper';
  if(kind==='parent-deleted')state.graph['paper/'+PAPER].active=false;
  if(kind==='note-deleted')receive(state,[event({...op,operation_id:'delete-note',action:'delete',payload:{}},state.cursor+1)]);
  const report=activityReport(state);assert(!report.continue.some(row=>row.operation_id==='source-note'));
  if(kind.startsWith('parent'))assert(report.recent.every(row=>row.paper_id===null));
});
test('open paper is explicit, read-only and preserves drafts/outbox without network',async()=>{
  const {state}=await fixture(),store=new MemoryStore('demo-workspace','demo-phone',state),row=activityReport(state).continue[0],calls=[];
  state.drafts.other='Kept draft';await store.update(next=>{next.drafts.other='Kept draft';});const before=stable(await store.read());
  assert.equal(await activateActivity({store,row,open:id=>calls.push(id)}),'opened');
  assert.deepEqual(calls,[PAPER]);assert.equal(stable(await store.read()),before);
});
test('saved note needs actual loaded owner and exact current source, and never moves native viewport',async()=>{
  const {state,hash}=await fixture(),store=new MemoryStore('demo-workspace','demo-phone',state),row=activityReport(state).continue[0],calls=[];
  for(const loaded of [null,{paper_id:'other',hash},{paper_id:PAPER,hash:'b'.repeat(64)}]) {
    assert.equal(canOpenSavedNote(state,row,loaded),false);
    assert.equal(await activateActivity({store,row,locate:true,loaded:()=>loaded,openNote:()=>assert.fail('Wrong source opened')}),'source');
  }
  assert.equal(await activateActivity({store,row,locate:true,loaded:()=>({paper_id:PAPER,hash}),openNote:(p,n)=>calls.push([p,n])}),'note_opened');
  assert.deepEqual(calls,[[PAPER,NOTE]]);
});
test('a retained draft for the target note blocks source action after restart without losing words',async()=>{
  const {state,hash}=await fixture();state.drafts[NOTE]='Keep the older draft';
  const store=new MemoryStore('demo-workspace','demo-phone',state),row=activityReport(state).continue[0];
  assert.equal(await activateActivity({store,row,locate:true,loaded:()=>({paper_id:PAPER,hash}),openNote:()=>assert.fail('Draft replaced')}),'drafts');
  assert.equal((await store.read()).drafts[NOTE],'Keep the older draft');
});
for(const change of ['close','switch-workspace','switch-connection','draft','parent'])test('late activity action rejects '+change,async()=>{
  const {state}=await fixture(),base=new MemoryStore('demo-workspace','demo-phone',state),row=activityReport(state).continue[0];
  let release,start,current=true,dirty=false,first=true;const gate=new Promise(r=>release=r),started=new Promise(r=>start=r);
  const store={read:async()=>{const value=await base.read();if(first){first=false;start();await gate;}return value;}};
  const pending=activateActivity({store,row,current:()=>current,blocked:()=>dirty,open:()=>assert.fail('Late navigation')});await started;
  if(change==='draft')dirty=true;else if(change==='parent')await base.update(next=>{next.graph['paper/'+PAPER].active=false;});else current=false;
  release();assert(['changed','drafts'].includes(await pending));
});
test('bounded received window ignores wall-clock text and rejects malformed selected events',async()=>{
  const {state}=await fixture(),op=state.entities['note/demo-note'].operation;
  for(let i=8;i<=300;i++)receive(state,[event({...op,operation_id:'edit-'+i},i)]);
  const report=activityReport(state);assert.equal(report.window,200);assert.equal(report.has_more,true);assert.equal(report.recent[0].sequence,300);
  state.receipts['edit-300'].operation.workspace_id='foreign';assert.throws(()=>activityReport(state));
});
class Node {
  constructor(tag,attrs,children){this.tag=tag;this.attrs=attrs;this.children=children.flat();this.events={};}
  append(...children){this.children.push(...children);}
  replaceChildren(...children){this.children=children;}
  addEventListener(type,callback){this.events[type]=callback;}
  close(){this.events.close?.();}
  remove(){this.removed=true;}
  set innerHTML(_){throw Error('Unsafe markup');}
  get text(){return this.children.map(c=>c instanceof Node?c.text:String(c)).join('\n');}
  buttons(){return [...(this.tag==='button'?[this]:[]),...this.children.filter(c=>c instanceof Node).flatMap(c=>c.buttons())];}
}
const el=(tag,attrs={},...children)=>new Node(tag,attrs,children),tick=()=>new Promise(r=>setImmediate(r));
test('bilingual text-only view, empty state, duplicate click and failure/retry preserve visible truth',async()=>{
  const {state}=await fixture(),report=activityReport(state);
  report.continue[0].title='<script>literal title</script>';
  for(const language of ['en','zh-TW']) {
    let resolve,calls=0;const gate=new Promise(r=>resolve=r);
    const view=researchActivityDialog(el,{language,read:async()=>report,activate:async()=>{calls++;await gate;return 'opened';}});
    await view.refresh();assert(view.dialog.text.includes('<script>literal title</script>'));assert(view.dialog.text.includes(ACTIVITY_COPY[language].native));
    const open=view.dialog.buttons().find(b=>b.text===ACTIVITY_COPY[language].open);open.attrs.onclick();open.attrs.onclick();assert.equal(calls,1);resolve();await tick();assert(view.dialog.removed);
  }
  let fail=true;const empty=researchActivityDialog(el,{read:async()=>{if(fail)throw Error('read');return {recent:[],continue:[]};}});
  await empty.refresh();assert(empty.dialog.text.includes(ACTIVITY_COPY.en.unavailable));fail=false;await empty.refresh();assert(empty.dialog.text.includes(ACTIVITY_COPY.en.empty));
});
test('close or context switch during local read prevents late display and duplicate refresh',async()=>{
  let resolve,calls=0,current=true;const gate=new Promise(r=>resolve=r);
  const view=researchActivityDialog(el,{current:()=>current,read:async()=>{calls++;return gate;}});
  const first=view.refresh();void view.refresh();assert.equal(calls,1);current=false;view.dispose();resolve({recent:[],continue:[]});await first;assert(!view.dialog.text.includes(ACTIVITY_COPY.en.empty));
});
test('successful explicit navigation closes the owned dialog even when it changes view context',async()=>{
  const {state}=await fixture();let current=true;
  const view=researchActivityDialog(el,{current:()=>current,read:async()=>activityReport(state),activate:async()=>{current=false;return 'opened';}});
  await view.refresh();view.dialog.buttons().find(b=>b.text===ACTIVITY_COPY.en.open).attrs.onclick();await tick();assert(view.dialog.removed);
});
test('a connection change while idle clears old data and disables stale controls',async()=>{
  const {state}=await fixture();let current=true;
  const view=researchActivityDialog(el,{current:()=>current,read:async()=>activityReport(state)});await view.refresh();
  assert(view.dialog.text.includes('Synthetic')||view.dialog.text.includes('learn'));
  current=false;view.check();assert(view.dialog.text.includes(ACTIVITY_COPY.en.changed));
  assert(!view.dialog.text.includes('How explanations'));assert(view.dialog.buttons().filter(b=>b.text!==ACTIVITY_COPY.en.close).every(b=>b.disabled));
});
test('language keys and Unicode codepoint title bounds agree with the Python projection',async()=>{
  assert.deepEqual(Object.keys(ACTIVITY_COPY.en).sort(),Object.keys(ACTIVITY_COPY['zh-TW']).sort());
  const {state}=await fixture(),old=state.entities['paper/'+PAPER].operation;
  receive(state,[event({...old,operation_id:'rename',payload:{...old.payload,title:'😀'.repeat(200)}},state.cursor+1)]);
  assert.equal(activityReport(state).continue[0].title,'😀'.repeat(160));
});
