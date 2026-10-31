import {countPDFPages,requirePDFPageProof} from './pdf-page-count.mjs';
import {Engine} from './engine.mjs';
import {IndexedStore} from './store.mjs';
import {HttpTransport} from './transport.mjs';
import {sourceFileId} from './artifacts.mjs';
import {openPrimaryPositionSource,openPositionSource,saveEnteredPosition,positionPageHint,prepareRecoveryReview,saveRecoveryReview} from './reading-position-ops.mjs';
import {preparePositionRecovery,importPositionRecovery,recoveryReport} from './position-recovery.mjs';
import {stable} from './domain.mjs';
import {positionReport} from './reading-position-report.mjs';
const result=document.querySelector('#result'),results=[],violations=[];
document.addEventListener('securitypolicyviolation',event=>violations.push(event.violatedDirective));
const assert=(value,message)=>{if(!value)throw Error(message);};
const hash=async bytes=>[...new Uint8Array(await crypto.subtle.digest('SHA-256',bytes))].map(b=>b.toString(16).padStart(2,'0')).join('');
async function rejected(promise,code) {try {await promise;}catch(error){assert(!code||error.message===code,'Wrong refusal: '+error.message);return;}throw Error('Expected refusal');}
async function check(name,run) {
  try {await run();results.push('PASS '+name);}catch(error){results.push('FAIL '+name+': '+error.message);}
  result.textContent=results.join('\n');
}
const bytes=new Uint8Array(await (await fetch('./tests/fixtures/position-two-pages.pdf')).arrayBuffer()),sha256=await hash(bytes);
const originalWorker=globalThis.Worker,live=new Set();
class TrackedWorker extends originalWorker {
  constructor(...args){super(...args);live.add(this);}
  terminate(){live.delete(this);return super.terminate();}
}
globalThis.Worker=TrackedWorker;
let proof;
await check('actual pinned parser counts verified bytes on real worker, no transferred cache buffer',async()=>{
  proof=await countPDFPages({bytes,sha256});assert(proof.pageCount===2,'Wrong actual page count');
  assert(bytes.length>0 && await hash(bytes)===sha256,'Caller bytes changed');
  assert(live.size===0,'Successful worker survived');requirePDFPageProof(proof,sha256,2);
});
await check('unforgeable local count proof and actual upper page bound',async()=>{
  await rejected(Promise.resolve().then(()=>requirePDFPageProof({...proof},sha256,1)),'pdf_count_required');
  await rejected(Promise.resolve().then(()=>requirePDFPageProof(proof,sha256,3)),'page_out_of_bounds');
  await rejected(countPDFPages({bytes,sha256:'a'.repeat(64)}),'corrupt_file');assert(live.size===0,'Hash failure started worker');
});
await check('malformed and encrypted real PDFs do not create count proof or leave workers',async()=>{
  const malformed=new TextEncoder().encode('%PDF-1.7\nnot a page tree\n%%EOF');
  await rejected(countPDFPages({bytes:malformed,sha256:await hash(malformed)}));
  const encrypted=new Uint8Array(await (await fetch('./tests/fixtures/position-encrypted.pdf')).arrayBuffer());
  await rejected(countPDFPages({bytes:encrypted,sha256:await hash(encrypted)}),'pdf_password_required');
  assert(live.size===0,'Failure worker survived');
});
await check('PDF document JavaScript is inert in count-only parser under product CSP',async()=>{
  globalThis.__positionPdfExecuted=false;
  const scripted=new Uint8Array(await (await fetch('./tests/fixtures/position-scripted.pdf')).arrayBuffer());
  assert((await countPDFPages({bytes:scripted,sha256:await hash(scripted)})).pageCount===1,'Scripted document count');
  assert(globalThis.__positionPdfExecuted===false && violations.length===0,'PDF action or CSP violation');
});
class HeldWorker extends TrackedWorker {
  constructor(){super(new URL('./tests/fixtures/held-pdf-worker.mjs',import.meta.url),{type:'module'});}
}
await check('held real worker cancellation and duplicate count cannot create a second worker',async()=>{
  globalThis.Worker=HeldWorker;const controller=new AbortController();
  const pending=countPDFPages({bytes,sha256},{signal:controller.signal});
  const refusal=rejected(pending,'cancelled');
  for(let tick=0;tick<200 && !live.size;tick++)await new Promise(resolve=>setTimeout(resolve,5));
  assert(live.size===1,'Held worker did not start');
  await rejected(countPDFPages({bytes,sha256}),'pdf_parser_busy');assert(live.size===1,'Duplicate worker');
  controller.abort();await refusal;assert(live.size===0,'Cancelled worker survived');globalThis.Worker=TrackedWorker;
});
await check('held real worker deadline terminates and retry succeeds',async()=>{
  globalThis.Worker=HeldWorker;
  await rejected(countPDFPages({bytes,sha256},{timeoutMs:1000}),'pdf_parse_timeout');
  assert(live.size===0,'Timed out worker survived');globalThis.Worker=TrackedWorker;
  assert((await countPDFPages({bytes,sha256})).pageCount===2,'Retry count failed');
});
await check('unavailable real worker refuses; no main-thread fake-worker fallback',async()=>{
  globalThis.Worker=undefined;await rejected(countPDFPages({bytes,sha256}),'pdf_worker_required');globalThis.Worker=TrackedWorker;
});
const fixtureResponse=await fetch('/__position_fixture');
if(fixtureResponse.ok) {
  const fixture=await fixtureResponse.json(),uploads=[],pushed=[];let loseSourceResponse=true;
  const transport=new HttpTransport(location.origin,{fetch:async(url,options)=>{
    const route=new URL(url).pathname,body=JSON.parse(options.body);
    if(route==='/v1/blobs/append'){const size=atob(body.data).length;assert(size<=1024,'A PDF was uploaded');uploads.push(size);}
    if(route==='/v1/push')pushed.push(structuredClone(body.operation));
    const response=await fetch(url,options);
    if(route==='/v1/push' && body.operation.payload?.feature==='original_source' && loseSourceResponse) {
      loseSourceResponse=false;await response.body.cancel();throw Error('fixture_lost_source_response');
    }
    return response;
  }});
  let store=await IndexedStore.open(fixture.workspace,'phone'),engine=new Engine(store,{transport}),B=fixture.current_hash,recoveryText;
  const command=async value=>(await fetch('/__position_command',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({command:value})})).json();
  await check('phone-first primary B count is read-only until explicit entered save, then source+position commit atomically',async()=>{
    await engine.importProjection(fixture.projection);await engine.connect(fixture.token);await engine.sync();await engine.download(fixture.paper);
    const before=await store.read(),opened=await openPrimaryPositionSource(engine,fixture.paper);
    assert(opened.pageCount===2,'Wrong primary count');assert((await store.read()).outbox.length===0,'Passive position/outbox');
    assert(Object.keys((await store.read()).positionRetentions??{}).length===0,'Passive source authority');
    assert(!Object.hasOwn(before.artifactFiles,B),'Primary B already retained before intent');
    const request={page:2,recordedAt:'2026-10-31T02:00:00Z',requestId:crypto.randomUUID()};
    const other=new Engine(store,{transport});await other.connect(fixture.token);
    await rejected(saveEnteredPosition(other,opened.captured,{...request,requestId:crypto.randomUUID()}),'stale_position_scope');
    other.disconnect();assert((await store.read()).outbox.length===0,'Another engine reused a loaded-view proof');
    const saved=await saveEnteredPosition(engine,opened.captured,request),again=await saveEnteredPosition(engine,opened.captured,request);
    assert(saved.status==='saved' && JSON.stringify(saved)===JSON.stringify(again),'Retry result changed');
    const state=await store.read();assert(state.outbox.length===2,'Duplicate/missing atomic intents');
    assert(state.outbox[0].operation.payload.feature==='original_source' && state.outbox[1].operation.payload.feature==='reading_position','Wrong dependency ordering');
    assert(state.artifactFiles[B].verified && state.positionRetentions[sourceFileId(fixture.paper,B)],'Missing exact B preservation');
    assert(state.outbox[1].operation.payload.data.method==='entered','Invented native observation');
    recoveryText=JSON.stringify(await engine.exportLocal());assert(JSON.parse(recoveryText).version===2,'Pending source pair was not exported');
    assert(!JSON.stringify(state).includes(fixture.token),'Credential persisted');
    engine.disconnect();store.close();store=await IndexedStore.open(fixture.workspace,'phone');engine=new Engine(store,{transport});
    assert((await store.read()).outbox.length===2,'IndexedDB restart lost dependent intents');
  });
  await check('lost source response retries exact IDs, sends JSON body only, and cannot send position before accepted source',async()=>{
    await engine.connect(fixture.token);await rejected(engine.sync(),'connection_failed');
    assert(pushed.length===1 && pushed[0].payload.feature==='original_source','Position sent before source acceptance');
    assert((await store.read()).outbox.length===2,'Lost source response lost pending pair');
    await engine.sync();const state=await store.read();assert(state.outbox.length===0,'Pair did not settle');
    assert(pushed.length===3 && pushed[0].operation_id===pushed[1].operation_id && pushed[2].payload.feature==='reading_position','Retry IDs/order changed');
    assert(uploads.length===1 && uploads[0]<1024,'Uploaded more than the deterministic body');
    const actual=await command('inspect');assert(actual.all_positions.some(row=>row[0]===B&&row[1]===2&&row[2]==='entered'),'Desktop did not receive B page');
    assert(positionReport(state,fixture.paper).positions.some(row=>row.document_hash===B&&row.page===2),'Phone canonical B position missing');
  });
  await check('primary C update cannot replace retained B; offline restart rechecks exact B and hint never claims viewport',async()=>{
    const next=await command('primary');assert(next.current_hash!==B,'Primary did not become C');
    await engine.sync();await engine.download(fixture.paper);assert((await engine.pdf(fixture.paper)).sha256===next.current_hash,'Primary C unavailable');
    engine.disconnect();store.close();store=await IndexedStore.open(fixture.workspace,'phone');engine=new Engine(store);
    const opened=await openPositionSource(engine,fixture.paper,B);
    assert(opened.pageCount===2 && await hash(opened.bytes)===B,'Retained B changed');
    assert((await engine.pdf(fixture.paper)).sha256===next.current_hash,'Opening B changed current C');
    await rejected(positionPageHint(engine,opened.captured,2,{loadedHash:next.current_hash}),'position_source_not_loaded');
    await rejected(positionPageHint(engine,opened.captured,2,{loadedHash:B,blocked:()=>true}),'position_draft_or_busy');
    assert(await positionPageHint(engine,opened.captured,2,{loadedHash:B})===2,'Explicit validated hint unavailable');
    store.close();assert(live.size===0,'Primary-retention worker survived');
  });
  await check('fresh independent HTTP desktop exports and strictly restores B with C using fresh package source ownership',async()=>{
    const peer=await command('peer');
    assert(peer.peer && peer.package_positions===2 && peer.backup_positions===2 && peer.detached_no_active_identity &&
      peer.fresh_package_source_owner && peer.retained_B===B && peer.current_C!==B,'Independent preservation failed');
  });
  await check('unsent v2 independently reparses B, imports privately on a fresh device, and survives repeat/restart/export without replay',async()=>{
    let stage='open';try {
    store=await IndexedStore.open(fixture.workspace,'recovery-phone');engine=new Engine(store,{transport:new HttpTransport(location.origin)});
    stage='authenticate';await engine.connect(fixture.recovery_token);stage='receive';await engine.sync();const before=await store.read();
    stage='prepare';const prepared=await preparePositionRecovery(engine,recoveryText);stage='import';const ids=await importPositionRecovery(engine,prepared);
    assert(ids.length===1,'Wrong retained archive count');await importPositionRecovery(engine,prepared);
    const state=await store.read();
    for(const key of ['workspace','device','cursor','graph','entities','receipts','outbox','conflicts','drafts'])
      assert(stable(state[key])===stable(before[key]),'Import changed live '+key);
    assert(recoveryReport(state).length===1 && state.artifactFiles[B].verified,'Retained source/candidate missing');
    stage='re-export';const again=await engine.exportLocal();assert(again.version===2 && again.archives.length===1 && again.blobs.length===2,'Re-export dropped or duplicated archive');
    engine.disconnect();store.close();store=await IndexedStore.open(fixture.workspace,'recovery-phone');engine=new Engine(store,{transport:new HttpTransport(location.origin)});
    assert(recoveryReport(await store.read()).length===1 && (await store.read()).outbox.length===0,'Restart revived old jobs');
    } catch(error){
      let detail='native fetch succeeds';try{const holder={request:globalThis.fetch};await holder.request('/__position_fixture');}
      catch(probe){detail=probe.name+': '+probe.message;}
      throw Error(stage+': '+error.message+'; '+detail);
    }
  });
  await check('recovery page bounds, cancellation, changed epoch and failed atomic write leave all live/private state unchanged',async()=>{
    const before=await store.read(),value=JSON.parse(recoveryText),archive=value.archives[0],position=archive.positions[0];
    position.data.page=3;position.operation.payload.data.page=3;
    archive.outbox.find(item=>item.operation.operation_id===position.id).operation.payload.data.page=3;
    const {id,...metadata}=archive;archive.id=await hash(new TextEncoder().encode(stable(metadata)));
    await rejected(preparePositionRecovery(engine,JSON.stringify(value)),'page_out_of_bounds');
    const cancel=new AbortController();cancel.abort();await rejected(preparePositionRecovery(engine,recoveryText,{signal:cancel.signal}),'cancelled');
    let current=true;const prepared=await preparePositionRecovery(engine,recoveryText,{current:()=>current});current=false;
    await rejected(importPositionRecovery(engine,prepared),'cancelled');
    const stale=await preparePositionRecovery(engine,recoveryText);engine.disconnect();
    await rejected(importPositionRecovery(engine,stale),'cancelled');
    assert(stable(await store.read())===stable(before),'Failed preparation/import mutated state');
    const failedStore=await IndexedStore.open(fixture.workspace,'failure-phone'),failedEngine=new Engine(failedStore),empty=await failedStore.read();
    const valid=await preparePositionRecovery(failedEngine,recoveryText),update=failedStore.update.bind(failedStore);
    failedStore.update=change=>update(state=>{change(state);throw Error('fixture_atomic_failure');});
    await rejected(importPositionRecovery(failedEngine,valid),'fixture_atomic_failure');
    assert(stable(await failedStore.read())===stable(empty),'Aborted IndexedDB transaction retained private data');
    failedStore.update=update;await importPositionRecovery(failedEngine,valid);
    assert(recoveryReport(await failedStore.read()).length===1,'Atomic import retry failed');failedStore.close();
  });
  await check('explicit recovery review requires fresh authenticated proof and IDs, preserves primary C, and publishes only the new entered position',async()=>{
    const item=recoveryReport(await store.read())[0];await rejected(prepareRecoveryReview(engine,item.archive_id,item.row_id),'not_connected');
    await engine.connect(fixture.recovery_token);await engine.sync();
    const opened=await prepareRecoveryReview(engine,item.archive_id,item.row_id),before=await store.read();
    assert(opened.pageCount===2 && await hash(opened.bytes)===B,'Review did not reparse exact B');
    assert(before.outbox.length===0,'Review automatically published');
    const oldId=JSON.parse(recoveryText).archives[0].positions[0].id;
    await rejected(saveRecoveryReview(engine,opened.token,{page:1,recordedAt:'2026-10-31T03:00:00Z',requestId:oldId}),'invalid_recovery_review');
    const requestId=crypto.randomUUID(),saved=await saveRecoveryReview(engine,opened.token,{page:1,recordedAt:'2026-10-31T03:00:00Z',requestId});
    assert(saved.status==='saved' && (await store.read()).outbox.length===1,'Fresh review did not create one current intent');
    assert((await store.read()).outbox[0].operation.device_id==='recovery-phone' &&
      (await store.read()).outbox[0].operation.operation_id===requestId,'Old device/request replayed');
    await engine.sync();const actual=await command('inspect');
    assert(actual.all_positions.some(row=>row[0]===B&&row[1]===1&&row[2]==='entered'),'Fresh reviewed position did not reach desktop');
    assert(actual.current_hash!==B && (await store.read()).outbox.length===0,'Review replaced primary or remained pending');
    assert(recoveryReport(await store.read())[0].reviewed_by===requestId,'Review status did not settle');
    engine.disconnect();store.close();
  });
  await check('unpublished source+position export is explicitly reviewed on a different device with fresh IDs and source-first acceptance',async()=>{
    const next=await command('primary'),hashD=next.current_hash;
    const producerStore=await IndexedStore.open(fixture.workspace,'unsent-phone'),producer=new Engine(producerStore,{transport:new HttpTransport(location.origin)});
    await producer.connect(fixture.unsent_token);await producer.sync();await producer.download(fixture.paper);
    const opened=await openPrimaryPositionSource(producer,fixture.paper),oldId=crypto.randomUUID();
    await saveEnteredPosition(producer,opened.captured,{page:2,recordedAt:'2026-10-31T04:00:00Z',requestId:oldId});
    const pending=await producerStore.read(),text=JSON.stringify(await producer.exportLocal());
    assert(pending.outbox.length===2 && !pending.receipts[pending.outbox[0].operation.operation_id],'Source was already accepted');
    producer.disconnect();producerStore.close();
    const freshStore=await IndexedStore.open(fixture.workspace,'unsent-receiver'),sent=[],freshTransport=new HttpTransport(location.origin,{fetch:async(url,options)=>{
      const body=JSON.parse(options.body);if(new URL(url).pathname==='/v1/push')sent.push(structuredClone(body.operation));
      return fetch(url,options);
    }}),fresh=new Engine(freshStore,{transport:freshTransport});
    await fresh.connect(fixture.unsent_receiver_token);await fresh.sync();
    await importPositionRecovery(fresh,await preparePositionRecovery(fresh,text));
    assert((await freshStore.read()).outbox.length===0,'Unsent old pair replayed automatically');
    const row=recoveryReport(await freshStore.read())[0],review=await prepareRecoveryReview(fresh,row.archive_id,row.row_id),newId=crypto.randomUUID();
    await saveRecoveryReview(fresh,review.token,{page:1,recordedAt:'2026-10-31T05:00:00Z',requestId:newId});
    const queued=(await freshStore.read()).outbox;assert(queued.length===2 && queued.every(item=>item.operation.device_id==='unsent-receiver' &&
      !pending.outbox.some(old=>old.operation.operation_id===item.operation.operation_id)),'Archived device/job IDs became live');
    await fresh.sync();assert(sent.length===2 && sent[0].payload.feature==='original_source' && sent[1].payload.feature==='reading_position',
      'Fresh source/position acceptance ordering failed');
    const actual=await command('inspect');assert(actual.all_positions.some(row=>row[0]===hashD&&row[1]===1),'Recovered source position missing on desktop');
    const E=await command('primary');assert(E.current_hash!==hashD,'Recovered original did not become historical');
    const peer=await command('peer-recovery');assert(peer.package_positions===3 && peer.backup_positions===3 && peer.retained_B===hashD &&
      peer.current_C===E.current_hash && peer.fresh_package_source_owner && peer.detached_no_active_identity &&
      peer.missing_history_refused_then_explicitly_downloaded,'Recovered unsent source failed strict desktop closure');
    fresh.disconnect();freshStore.close();
  });
}
await check('all parser/worker/license shell assets installed before offline continuation',async()=>{
  await navigator.serviceWorker.register('./sw.mjs',{type:'module'});await navigator.serviceWorker.ready;
  const cache=await caches.open('paperfact-mobile-shell-v12');
  for(const name of ['pdf.mjs','pdf.worker.mjs','LICENSE','provenance.json'])assert(await cache.match('./vendor/pdfjs-6.4.299/'+name),'Missing offline '+name);
});
globalThis.runOfflinePositionChecks=async()=>{
  await check('fresh real worker parses exact A offline from shell assets under unchanged CSP',async()=>{
    assert((await countPDFPages({bytes,sha256})).pageCount===2,'Offline count failed');
    assert(live.size===0 && violations.length===0,'Offline worker/CSP failure');
  });
  globalThis.Worker=originalWorker;document.body.dataset.result=results.every(row=>row.startsWith('PASS'))?'pass':'fail';
};
document.body.dataset.offlineReady='true';
