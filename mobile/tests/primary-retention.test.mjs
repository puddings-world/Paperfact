import test from 'node:test';
import assert from 'node:assert/strict';
import {primaryReference,preparePrimaryRetention,registerPositionIntent,reconcilePositionIntents} from '../primary-source-retention.mjs';
import {MemoryStore} from '../store.mjs';
import {demoTransport,operation,ref,PAPER} from '../fixture.mjs';
import {receive,enqueue,stable} from '../domain.mjs';
import {sourceFileId} from '../artifacts.mjs';
import {contentId,uuid5Name} from '../ids.mjs';
const SHA='a'.repeat(64),event=(operation,sequence)=>({sequence,outcome:'accepted',operation,head:{revision:sequence,operation}});
async function fixture() {
  const transport=await demoTransport(),store=new MemoryStore('demo-workspace','demo-phone');
  await store.update(state=>receive(state,transport.events));
  const document=operation('paper_document',PAPER,{paper_id:PAPER,sha256:SHA,size:20,media_type:'application/pdf'},
    {operationId:'accepted-primary-B',parents:[ref('paper',PAPER)]});
  await store.update(state=>receive(state,[event(document,state.cursor+1)]));
  return {store,document};
}
function source(document) {
  const hash=document.payload.sha256,id=sourceFileId(PAPER,hash);
  const payload={paper_id:PAPER,feature:'original_source',slot:hash,format_version:1,source_document_hash:hash,
    input_versions:{schema_version:1,complete:false,entities:[],documents:[],inputs_sha256:null},
    body:{sha256:'b'.repeat(64),size:100,media_type:'application/json'},
    assets:[{id:'original',role:'original_pdf',sha256:hash,size:20,media_type:'application/pdf'}]};
  return operation('research_file',id,payload,{operationId:'original-B',parents:document.parents});
}
test('accepted exact B reference remains valid after current C without hash/current-document inference',async()=>{
  const {store,document}=await fixture();const C={...structuredClone(document),operation_id:'current-C',payload:{...document.payload,sha256:'c'.repeat(64)}};
  await store.update(state=>receive(state,[event(C,state.cursor+1)]));
  const state=await store.read(),before=stable(state),reference=primaryReference(state,document,PAPER);
  assert.equal(reference.hash,SHA);assert.equal(reference.parent.incarnation,document.parents[0].incarnation);
  assert.equal(state.entities['paper_document/'+PAPER].operation.payload.sha256,'c'.repeat(64));
  assert.equal(stable(state),before);
});
for(const change of ['wrong-paper-same-hash','missing-receipt','unaccepted-receipt','changed-parent','changed-reference'])test('exact primary authority refuses '+change,async()=>{
  const {store,document}=await fixture(),state=await store.read();let selected=document,expected=PAPER;
  if(change==='wrong-paper-same-hash')expected='11111111-1111-4111-8111-111111111111';
  if(change==='missing-receipt')delete state.receipts[document.operation_id];
  if(change==='unaccepted-receipt')state.receipts[document.operation_id].outcome='conflict';
  if(change==='changed-parent')state.graph['paper/'+PAPER].incarnation='new-parent';
  if(change==='changed-reference'){selected=structuredClone(document);selected.payload.size++;}
  const before=stable(state);assert.throws(()=>primaryReference(state,selected,expected));assert.equal(stable(state),before);
});
test('known retirement cannot be hidden by optimistic pending source put',async()=>{
  const {store,document}=await fixture(),original=source(document);
  await store.update(state=>{
    receive(state,[event(original,state.cursor+1)]);
    const deleted={...original,operation_id:'retired-B',action:'delete',payload:{}};
    receive(state,[event(deleted,state.cursor+1)]);
    enqueue(state,{...original,operation_id:'pending-restore',incarnation:'pending-restore',device_id:state.device});
  });
  const state=await store.read();
  assert.throws(()=>primaryReference(state,document),/^Error: position_original_retired$/);
});
test('sender or persisted count metadata cannot prepare a source',async()=>{
  const {document}=await fixture();
  await assert.rejects(preparePrimaryRetention(document,new Uint8Array(20),{sha256:SHA,size:20,pageCount:3}),/pdf_count_required/);
});
test('known source retirement quarantines dependent position with exact entered data, not a replay job',async()=>{
  const {store,document}=await fixture(),original=source(document),id=contentId({kind:'paper',id:PAPER},'reading_position',SHA);
  const position=operation('research_content',id,{scope:{kind:'paper',id:PAPER},feature:'reading_position',key:SHA,
    source_document_hash:SHA,data:{page:2,recorded_at:'2026-10-31T00:00:00Z',method:'entered'}},
    {operationId:crypto.randomUUID(),device:'demo-phone',parents:document.parents});
  await store.update(state=>{
    receive(state,[event(original,state.cursor+1)]);enqueue(state,position);
    registerPositionIntent(state,position,original,{paper_incarnation:document.parents[0].incarnation,
      source_operation_id:original.operation_id,source_incarnation:original.incarnation,
      position_operation_id:null,position_incarnation:null,position_action:null});
    receive(state,[event({...original,operation_id:'retired-B',action:'delete',payload:{}},state.cursor+1)]);
    reconcilePositionIntents(state);
  });
  const state=await store.read();assert.deepEqual(state.outbox,[]);
  assert.deepEqual(state.positionCandidates[position.operation_id].data,position.payload.data);
  assert.equal(state.positionCandidates[position.operation_id].reason,'source_unavailable');
  assert(!state.entities['research_content/'+id]);
});
test('a retirement and fresh restore received in one batch cannot reactivate an older unsent position',async()=>{
  const {store,document}=await fixture(),original=source(document),id=contentId({kind:'paper',id:PAPER},'reading_position',SHA);
  const position=operation('research_content',id,{scope:{kind:'paper',id:PAPER},feature:'reading_position',key:SHA,
    source_document_hash:SHA,data:{page:2,recorded_at:'2026-10-31T00:00:00Z',method:'entered'}},
    {operationId:crypto.randomUUID(),device:'demo-phone',parents:document.parents});
  await store.update(state=>{
    receive(state,[event(original,state.cursor+1)]);enqueue(state,position);
    registerPositionIntent(state,position,original,{paper_incarnation:document.parents[0].incarnation,
      source_operation_id:original.operation_id,source_incarnation:original.incarnation,
      position_operation_id:null,position_incarnation:null,position_action:null});
    const retired={...original,operation_id:'retired-before-restored',action:'delete',payload:{}};
    const restored={...original,operation_id:'fresh-restored-source',incarnation:'fresh-restored-source'};
    receive(state,[event(retired,state.cursor+1),event(restored,state.cursor+2)]);
    reconcilePositionIntents(state);
  });
  const state=await store.read();assert.deepEqual(state.outbox,[]);
  assert.deepEqual(state.positionCandidates[position.operation_id].data,position.payload.data);
  assert.equal(state.positionCandidates[position.operation_id].reason,'source_unavailable');
});
function entered(document,requestId=crypto.randomUUID()) {
  return operation('research_content',contentId({kind:'paper',id:PAPER},'reading_position',SHA),
    {scope:{kind:'paper',id:PAPER},feature:'reading_position',key:SHA,source_document_hash:SHA,
      data:{page:2,recorded_at:'2026-10-31T00:00:00Z',method:'entered'}},
    {operationId:requestId,device:'demo-phone',parents:document.parents});
}
function observed(document,original=null) {
  return {paper_incarnation:document.parents[0].incarnation,source_operation_id:original?.operation_id??null,
    source_incarnation:original?.incarnation??null,position_operation_id:null,position_incarnation:null,position_action:null};
}
test('separate retirement pages and restart keep the old candidate private; explicit fresh lifetime is allowed',async()=>{
  const {store,document}=await fixture(),original=source(document),old=entered(document);
  await store.update(state=>{
    receive(state,[event(original,state.cursor+1)]);enqueue(state,old);
    registerPositionIntent(state,old,original,observed(document,original));
    receive(state,[event({...original,operation_id:'separate-delete',action:'delete',payload:{}},state.cursor+1)]);
    reconcilePositionIntents(state);
  });
  const restarted=new MemoryStore('demo-workspace','demo-phone',await store.read());
  const restored={...original,operation_id:'separate-restore',incarnation:'separate-restore'},fresh=entered(document);
  await restarted.update(state=>{
    receive(state,[event(restored,state.cursor+1)]);reconcilePositionIntents(state);
    assert.deepEqual(state.outbox,[]);assert.equal(state.positionCandidates[old.operation_id].resolvedBy,null);
    enqueue(state,fresh);registerPositionIntent(state,fresh,restored,observed(document,restored));reconcilePositionIntents(state);
  });
  const state=await restarted.read();assert.equal(state.outbox.length,1);
  assert.equal(state.outbox[0].operation.operation_id,fresh.operation_id);
  assert.deepEqual(state.positionCandidates[old.operation_id].data,old.payload.data);
});
test('an exact deterministic own source pair survives accepted acknowledgement, receive and restart unchanged',async()=>{
  const {store,document}=await fixture(),position=entered(document),original=source(document);
  original.operation_id=uuid5Name('paperfact:position-original:'+position.operation_id);
  original.incarnation=original.operation_id;original.device_id='demo-phone';
  await store.update(state=>{
    state.positionRetentions={[original.entity_id]:{version:1,document,manifest:original.payload,
      source_operation_id:original.operation_id,source_operation:original}};
    enqueue(state,original);enqueue(state,position);
    registerPositionIntent(state,position,original,observed(document),original.entity_id);
    state.outbox[0].acknowledged=event(original,state.cursor+1);reconcilePositionIntents(state);
    assert.equal(state.outbox.length,2);
    receive(state,[state.outbox[0].acknowledged]);reconcilePositionIntents(state);
  });
  const restarted=new MemoryStore('demo-workspace','demo-phone',await store.read());
  await restarted.update(reconcilePositionIntents);const state=await restarted.read();
  assert.equal(state.outbox.length,1);assert.deepEqual(state.outbox[0].operation,position);
  assert.equal(state.positionCandidates?.[position.operation_id],undefined);
});
for(const stage of ['acknowledged','received'])test('a mutable later retention cannot upgrade an older null-incarnation intent via '+stage,async()=>{
  const {store,document}=await fixture(),position=entered(document),original=source(document);
  original.operation_id='different-request-source';original.incarnation=original.operation_id;original.device_id='demo-phone';
  await store.update(state=>{
    state.positionRetentions={[original.entity_id]:{version:1,document,manifest:original.payload,
      source_operation_id:original.operation_id,source_operation:original}};
    enqueue(state,original);enqueue(state,position);
    registerPositionIntent(state,position,original,observed(document),original.entity_id);
    state.outbox[0].acknowledged=event(original,state.cursor+1);
    if(stage==='received')receive(state,[state.outbox[0].acknowledged]);
    reconcilePositionIntents(state);
  });
  const state=await store.read();assert(!state.outbox.some(row=>row.operation.operation_id===position.operation_id));
  assert.deepEqual(state.positionCandidates[position.operation_id].data,position.payload.data);
});
for(const present of [false,true])test('an old null-incarnation intent without a provable own pair is retained; canonical present='+present,async()=>{
  const {store,document}=await fixture(),position=entered(document),original=source(document);
  await store.update(state=>{
    if(present)receive(state,[event(original,state.cursor+1)]);enqueue(state,position);
    registerPositionIntent(state,position,original,observed(document));reconcilePositionIntents(state);
  });
  const state=await store.read();assert.deepEqual(state.outbox,[]);
  assert.equal(state.positionCandidates[position.operation_id].reason,'source_unavailable');
});
