import {Engine} from './engine.mjs';
import {IndexedStore} from './store.mjs';
import {HttpTransport} from './transport.mjs';
import {readingPositionDialog} from './position-dialog.mjs';
import {POSITION_COPY} from './position-view.mjs';
import {stable} from './domain.mjs';
import {recoveryReport} from './position-recovery.mjs';
const output=document.querySelector('#result'),results=[],violations=[];
const assert=(value,message)=>{if(!value)throw Error(message);};
const el=(tag,attrs={},...children)=>{
  const node=document.createElement(tag);
  for(const [key,value] of Object.entries(attrs)){if(key.startsWith('on'))node.addEventListener(key.slice(2),value);
    else if(value!==null&&value!==undefined)node.setAttribute(key,String(value));}
  for(const child of children.flat(Infinity))if(child!==null&&child!==undefined)node.append(child instanceof Node?child:document.createTextNode(String(child)));
  return node;
};
async function until(check){const end=performance.now()+10000;while(!await check()){
  assert(performance.now()<end,'UI did not settle');await new Promise(resolve=>setTimeout(resolve,10));}}
const keyTrace=[];
for(const kind of ['keydown','keypress','click'])document.addEventListener(kind,event=>{
  if((kind==='click'&&event.target.tagName!=='BUTTON')||(kind!=='click'&&!['Enter','Escape'].includes(event.key)))return;
  keyTrace.push({kind,key:event.key??null,target:event.target.tagName,label:event.target.textContent.slice(0,32),trusted:event.isTrusted});
  if(keyTrace.length>8)keyTrace.shift();
},true);
async function check(name,work){try{await work();results.push('PASS '+name);}catch(error){
  const dialogs=[...document.querySelectorAll('dialog')].map(node=>({status:node.querySelector('[role=status]')?.textContent,
    page:node.querySelector('#position-page')?.value,open:node.open,focused:document.activeElement?.tagName}));
  results.push('FAIL '+name+': '+error.message+' '+JSON.stringify({dialogs,keyTrace}));}
  output.textContent=results.join('\n');}
const type=(view,value)=>{view.controls.page.value=value;view.controls.page.dispatchEvent(new Event('input',{bubbles:true}));};
const named=(view,label)=>[...view.dialog.querySelectorAll('button')].find(node=>node.textContent===label);
const fixture=await (await fetch('/__position_fixture')).json(),command=async value=>(await fetch('/__position_command',
  {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({command:value})})).json();
document.addEventListener('securitypolicyviolation',event=>violations.push(event.violatedDirective));
const nativeWorker=globalThis.Worker,live=new Set();let created=0;
class TrackedWorker extends nativeWorker {constructor(...args){super(...args);live.add(this);created++;}terminate(){live.delete(this);return super.terminate();}}
class HeldWorker extends TrackedWorker {constructor(){super(new URL('./tests/fixtures/held-pdf-worker.mjs',import.meta.url),{type:'module'});}}
globalThis.Worker=TrackedWorker;
let store=await IndexedStore.open(fixture.workspace,'phone'),engine=new Engine(store,{transport:new HttpTransport(location.origin)}),B=fixture.current_hash,
  current=true,blocked=false,dialog=null,exported=null,currentHash=B;
await engine.connect(fixture.token);await engine.sync();await engine.download(fixture.paper);
await store.update(state=>{state.selection={list:null,paper:fixture.paper};state.drafts.reader='<script>Literal retained note draft</script>';});
const baseOptions=()=>({engine,paper:fixture.paper,current:()=>current,blocked:()=>blocked,connected:()=>!!engine.transport,
  onExport:value=>{exported=JSON.stringify(value);},onClose:()=>{dialog=null;}});
async function open(language='en'){
  const view=readingPositionDialog(el,{...baseOptions(),language});dialog=view;document.body.append(view.dialog);view.dialog.showModal();
  await view.refresh();await until(()=>!view.pending);return view;
}
async function viewport(label){document.body.dataset.metrics=label;await until(()=>document.body.dataset.metricsReady===label);}
function geometry(view){const box=view.dialog.getBoundingClientRect();assert(box.width<=innerWidth-16&&box.left>=0&&box.right<=innerWidth,'Dialog clipped');
  assert(view.dialog.scrollWidth<=view.dialog.clientWidth+1,'Dialog horizontal overflow');
  for(const node of [view.controls.page,view.controls.save,view.controls.close]){const rect=node.getBoundingClientRect();assert(rect.height>=43&&rect.left>=box.left&&rect.right<=box.right,'Primary control clipped or too small');}}

await check('actual English phone dialog checks real B; current C arrival preserves selected B and explicit Keep draft survives restart',async()=>{
  await viewport('phone-en');const before=await store.read(),view=await open();geometry(view);
  assert(view.controls.page.max==='2'&&view.controls.save.disabled,'Unverified/default page was writable');
  const help=[...view.dialog.querySelectorAll('details')].find(node=>node.textContent.includes(POSITION_COPY.en.viewerHelp));
  assert(help&&!help.open&&help.textContent.includes(POSITION_COPY.en.jump),'Native-viewer facts missing from closed help');
  assert(!view.dialog.innerText.includes(POSITION_COPY.en.viewerHelp)&&!view.dialog.innerText.includes(POSITION_COPY.en.jump),'Default screen repeats full viewer caveats');
  assert(view.dialog.querySelector('#position-page-info').textContent===`${POSITION_COPY.en.checked}: 2.`,'Verified count status not compact');
  assert((await store.read()).outbox.length===0&&!Object.keys((await store.read()).positionRetentions??{}).length,'Passive UI created authority');
  type(view,'3');assert(view.controls.save.disabled,'Out-of-bounds page enabled');type(view,'2');
  const changed=await command('primary');currentHash=changed.current_hash;await engine.sync();await engine.download(fixture.paper);await view.refresh(false);
  assert(view.controls.select.value===B&&view.controls.page.value==='2','Current C switched or erased B');
  assert(view.dialog.textContent.includes(POSITION_COPY.en.newer),'New version was not explained');
  document.body.dataset.capture='phone-en';await until(()=>document.body.dataset.captureReady==='phone-en');
  document.body.dataset.keyboard='dirty-escape-en';await until(()=>!!named(view,POSITION_COPY.en.editing));
  assert(view.dialog.open&&named(view,POSITION_COPY.en.editing)===document.activeElement,'Dirty Escape did not focus Keep editing');
  named(view,POSITION_COPY.en.keep).click();await until(()=>view.disposed);
  const kept=await store.read();assert(kept.outbox.length===0&&kept.positionDrafts[fixture.paper+'/'+B].pageText==='2','Keep draft did not stay private');
  assert(kept.drafts.reader===before.drafts.reader&&stable(kept.selection)===stable(before.selection),'Reader draft/selection changed');
  engine.disconnect();store.close();store=await IndexedStore.open(fixture.workspace,'phone');engine=new Engine(store,{transport:new HttpTransport(location.origin)});
  await engine.connect(fixture.token);const reopened=await open();assert(reopened.controls.select.value===B&&reopened.controls.page.value==='2','Draft reopened as C');
  reopened.controls.export.click();await until(()=>!!exported);assert(JSON.parse(exported).version===2,'UI export dropped private source/page draft');
  for(let i=0;i<20;i++)reopened.controls.save.click();await until(()=>reopened.disposed);
  const pending=await store.read();assert(pending.outbox.length===2&&pending.outbox[0].operation.payload.feature==='original_source'&&
    pending.outbox[1].operation.payload.key===B&&pending.outbox[1].operation.payload.data.method==='entered','Remember did not admit exact one B pair');
  assert((await engine.pdf(fixture.paper)).sha256===currentHash,'Remember changed current C');
  const exporting=await open();exporting.controls.export.click();await until(()=>!exporting.pending&&JSON.parse(exported).archives[0].outbox.length===2);
  exporting.dispose();await until(()=>exporting.disposed);await engine.sync();
});
await check('earlier original A is explicitly downloaded/checked without replacing C or making a native jump claim',async()=>{
  const view=await open(),before=await store.read();
  view.controls.select.value=fixture.source_hash;view.controls.select.dispatchEvent(new Event('change',{bubbles:true}));await until(()=>!view.pending);
  assert(view.controls.page.max==='2'&&view.controls.page.value==='2','Earlier source record/count missing');
  assert(view.controls.open.href.startsWith('blob:')&&!view.controls.open.href.includes('#page='),'Viewer jump was invented');
  assert((await engine.pdf(fixture.paper)).sha256===currentHash,'Opening A replaced C');
  assert(stable((await store.read()).outbox)===stable(before.outbox),'Checking A queued a page');
  type(view,'1');view.controls.close.click();named(view,POSITION_COPY.en.keep).click();await until(()=>view.disposed);
});
await check('real native Enter activates a single Chinese Remember on a narrow phone with preserved note draft',async()=>{
  await viewport('phone-zh');const view=await open('zh-TW');
  // A durable A draft remains selected on reopening; choose the explicit current original.
  view.controls.select.value=currentHash;view.controls.select.dispatchEvent(new Event('change',{bubbles:true}));await until(()=>!view.pending);
  geometry(view);assert(view.dialog.textContent.includes(POSITION_COPY['zh-TW'].hint),'Chinese coverage missing');
  type(view,'1');view.controls.save.focus();document.body.dataset.capture='phone-zh';await until(()=>document.body.dataset.captureReady==='phone-zh');
  document.body.dataset.keyboard='remember-zh';await until(()=>view.disposed);
  const pending=await store.read();assert(pending.outbox.filter(row=>row.operation.payload?.feature==='reading_position').length===1,'Keyboard duplicated position');
  assert(pending.drafts.reader==='<script>Literal retained note draft</script>','Keyboard discarded note text');await engine.sync();
});
await check('known deleted page requires Cancel-first explicit fresh restore and never reuses the old incarnation',async()=>{
  await command('delete-current');await engine.sync();const before=await store.read(),view=await open();
  view.controls.select.value=currentHash;view.controls.select.dispatchEvent(new Event('change',{bubbles:true}));await until(()=>!view.pending);
  assert(view.controls.page.value===''&&view.controls.save.textContent===POSITION_COPY.en.rememberAgain,'Deleted page was inferred as a live saved page');
  type(view,'2');view.controls.save.click();assert(document.activeElement.textContent===POSITION_COPY.en.cancel,'Restore did not focus Cancel');
  assert(stable((await store.read()).outbox)===stable(before.outbox),'Restore confirmation queued early');document.activeElement.click();
  assert(view.controls.page.value==='2','Cancelling restore lost entered page');view.controls.save.click();named(view,POSITION_COPY.en.confirm).click();await until(()=>view.disposed);
  const pending=await store.read(),operation=pending.outbox.at(-1).operation;
  assert(pending.outbox.length===1&&operation.payload.key===currentHash&&operation.incarnation===operation.operation_id,
    'Restore did not create one fresh exact-source incarnation');await engine.sync();
  const actual=await command('inspect');assert(actual.all_positions.some(row=>row[0]===currentHash&&row[1]===2),'Explicit restore did not reach desktop');
});
await check('real DOM recovery import keeps all archived note/outbox text readable and publishes only an explicit fresh review',async()=>{
  engine.disconnect();store.close();store=await IndexedStore.open(fixture.workspace,'recovery-phone');engine=new Engine(store,{transport:new HttpTransport(location.origin)});
  await engine.connect(fixture.recovery_token);await engine.sync();await engine.download(fixture.paper);
  const before=await store.read(),view=await open(),details=[...view.dialog.querySelectorAll('details')].at(-1);details.open=true;
  const transfer=new DataTransfer();transfer.items.add(new File([exported],'saved-page.json',{type:'application/json'}));view.controls.importFile.files=transfer.files;
  view.controls.importFile.dispatchEvent(new Event('change',{bubbles:true}));await until(async()=>!view.pending&&recoveryReport(await store.read()).length>0);
  const imported=await store.read();for(const key of ['cursor','graph','outbox','receipts','entities'])assert(stable(imported[key])===stable(before[key]),'Import changed live '+key);
  view.controls.archive.click();const text=view.dialog.querySelector('textarea[readonly]');
  assert(text.value.includes('<script>Literal retained note draft</script>')&&!globalThis.__positionScriptRan,'Archived note text hidden or executed');
  const oldIds=JSON.parse(exported).archives[0].outbox.map(row=>row.operation.operation_id);
  assert(oldIds.length===2&&oldIds.every(id=>text.value.includes(id)),'Archived pending operations hidden');
  assert(view.dialog.textContent.includes(POSITION_COPY.en.archiveHelp),'Archive limits not explained');
  const review=named(view,POSITION_COPY.en.review);assert(review&&!review.disabled,'Retained page has no explicit review');review.click();await until(()=>!view.pending);
  assert(view.controls.page.value==='2'&&view.controls.page.max==='2','Review did not recheck exact B');type(view,'1');view.controls.save.click();await until(()=>view.disposed);
  const pending=await store.read();assert(pending.outbox.length===1&&pending.outbox[0].operation.device_id==='recovery-phone'&&
    pending.outbox[0].operation.payload.key===B&&pending.outbox[0].operation.payload.data.page===1&&
    !oldIds.includes(pending.outbox[0].operation.operation_id),'Review revived an old pair or wrong source');
  assert(recoveryReport(pending)[0].reviewed_by===pending.outbox[0].operation.operation_id,'Review status missing');await engine.sync();
  const desktop=await command('inspect');assert(desktop.all_positions.some(row=>row[0]===B&&row[1]===1),'Reviewed UI page did not reach desktop');
});
await check('real held worker Cancel/duplicate/retry and Close drain safely without passive source ownership',async()=>{
  await viewport('laptop-en');globalThis.Worker=HeldWorker;const before=await store.read(),start=created;
  const view=readingPositionDialog(el,baseOptions());dialog=view;document.body.append(view.dialog);view.dialog.showModal();const work=view.refresh();
  await until(()=>live.size===1);for(let i=0;i<10;i++)view.controls.check.click();assert(created===start+1,'Duplicate count workers');
  view.controls.cancel.click();await work;await until(()=>!view.pending);assert(live.size===0,'Cancel left a worker');
  assert(stable((await store.read()).outbox)===stable(before.outbox),'Cancel queued data');
  globalThis.Worker=TrackedWorker;view.controls.check.click();await until(()=>!view.pending);assert(view.controls.page.max==='2','Count retry failed');view.dispose();await until(()=>view.disposed);
  globalThis.Worker=HeldWorker;const closed=readingPositionDialog(el,baseOptions());dialog=closed;document.body.append(closed.dialog);closed.dialog.showModal();const loading=closed.refresh();
  await until(()=>live.size===1);closed.controls.close.click();await loading;await until(()=>closed.disposed);assert(live.size===0,'Closed worker survived');
  assert(stable((await store.read()).outbox)===stable(before.outbox),'Close queued a page');globalThis.Worker=TrackedWorker;
});
await check('busy note context and changed auth keep entered text visible while refusing late writes',async()=>{
  blocked=true;const view=await open(),before=await store.read();type(view,'2');assert(view.controls.save.disabled,'Busy note allowed Remember');
  view.controls.save.click();assert(stable((await store.read()).outbox)===stable(before.outbox),'Busy save queued data');
  blocked=false;await view.refresh(false);engine.disconnect();await view.refresh(false);assert(view.controls.save.disabled&&view.controls.page.value==='2','Auth switch erased or admitted text');
  view.dispose();assert(view.dialog.open,'Changed context silently discarded draft');named(view,POSITION_COPY.en.discard).click();await until(()=>view.disposed);
});
await check('actual received retirement disables selected B and keeps dirty text without reviving cached authority',async()=>{
  await engine.connect(fixture.recovery_token);await engine.sync();const view=await open(),before=await store.read();
  view.controls.select.value=B;view.controls.select.dispatchEvent(new Event('change',{bubbles:true}));await until(()=>!view.pending);type(view,'2');
  await command('retire-b');await engine.sync();await view.refresh(false);
  assert(view.controls.save.disabled&&view.controls.page.value==='2','Retired cached B was writable or text disappeared');
  assert(stable((await store.read()).outbox)===stable(before.outbox),'Retirement revived a page intent');
  view.dispose();assert(view.dialog.open&&named(view,POSITION_COPY.en.keep).disabled,'Retired context silently kept active draft authority');
  named(view,POSITION_COPY.en.discard).click();await until(()=>view.disposed);
});
await check('read-only snapshot dialog has no editable page or count authority before current history',async()=>{
  const readStore=await IndexedStore.open(fixture.workspace,'readonly-phone'),reader=new Engine(readStore);
  await reader.importProjection(fixture.projection);const before=await readStore.read(),workers=created;
  const view=readingPositionDialog(el,{engine:reader,paper:fixture.paper,language:'zh-TW'});document.body.append(view.dialog);view.dialog.showModal();await view.refresh();
  assert(view.controls.save.disabled&&view.controls.check.disabled&&view.dialog.textContent.includes(POSITION_COPY['zh-TW'].readonly),'Snapshot appeared writable');
  assert(created===workers&&stable(await readStore.read())===stable(before),'Snapshot created source/count authority');view.dispose();readStore.close();
});
await check('shell contains both position UI modules with exact parser assets before offline reopen',async()=>{
  await navigator.serviceWorker.register('./sw.mjs',{type:'module'});await navigator.serviceWorker.ready;
  const cache=await caches.open('paperfact-mobile-shell-v12');for(const path of ['position-view.mjs','position-dialog.mjs','vendor/pdfjs-6.4.299/pdf.worker.mjs'])
    assert(await cache.match('./'+path),'Missing UI shell asset');
});
globalThis.runOfflinePositionChecks=async()=>{
  await check('offline real DOM remembered-page draft reopens on exact A and queues entered data without changing primary C or note text',async()=>{
    store.close();store=await IndexedStore.open(fixture.workspace,'phone');engine=new Engine(store);current=true;blocked=false;
    const before=await store.read(),view=await open();assert(view.controls.select.value===fixture.source_hash&&view.controls.page.value==='1','Offline draft source/page changed');
    view.controls.save.click();await until(()=>view.disposed);const after=await store.read();
    assert(after.outbox.length===before.outbox.length+1&&after.outbox.at(-1).operation.payload.key===fixture.source_hash&&
      after.outbox.at(-1).operation.payload.data.method==='entered','Offline UI lost exact entered source');
    assert(after.drafts.reader===before.drafts.reader&&(await engine.pdf(fixture.paper)).sha256===currentHash,'Offline UI changed note/current PDF');
    assert(live.size===0&&violations.length===0,'Worker or CSP violation remained');store.close();
  });
  globalThis.Worker=nativeWorker;document.body.dataset.result=results.every(row=>row.startsWith('PASS'))?'pass':'fail';
};
document.body.dataset.offlineReady='true';
