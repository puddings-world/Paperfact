import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {MemoryStore,copy} from '../store.mjs';
import {Engine} from '../engine.mjs';
import {receive,stable} from '../domain.mjs';
import {demoTransport,operation,ref,PAPER} from '../fixture.mjs';
import {sourceFileId} from '../artifacts.mjs';
import {contentId} from '../ids.mjs';
import {digest} from '../artifact-engine.mjs';
import {exportPositionRecovery,preparePositionRecovery,importPositionRecovery,legacyRecovery,MAX_RECOVERY_BYTES} from '../position-recovery.mjs';
import {primaryReference} from '../primary-source-retention.mjs';
const event=(operation,sequence)=>({sequence,outcome:'accepted',operation,head:{revision:sequence,operation}});
async function fixture() {
  const transport=await demoTransport(),store=new MemoryStore('demo-workspace','demo-phone');
  await store.update(state=>receive(state,transport.events));
  const bytes=new Uint8Array(await readFile(new URL('./fixtures/position-two-pages.pdf',import.meta.url))),hash=await digest(bytes);
  const body=new TextEncoder().encode(stable({version:1,paper_id:PAPER,document_hash:hash})),bodyHash=await digest(body);
  const document=operation('paper_document',PAPER,{paper_id:PAPER,sha256:hash,size:bytes.length,media_type:'application/pdf'},
    {operationId:'accepted-primary-B',parents:[ref('paper',PAPER)]});
  const manifest={paper_id:PAPER,feature:'original_source',slot:hash,format_version:1,source_document_hash:hash,
    input_versions:{schema_version:1,complete:false,entities:[],documents:[],inputs_sha256:null},
    body:{sha256:bodyHash,size:body.length,media_type:'application/json'},
    assets:[{id:'original',role:'original_pdf',sha256:hash,size:bytes.length,media_type:'application/pdf'}]};
  const source=operation('research_file',sourceFileId(PAPER,hash),manifest,{operationId:'original-B',device:'demo-phone',parents:document.parents});
  const position=operation('research_content',contentId({kind:'paper',id:PAPER},'reading_position',hash),
    {scope:{kind:'paper',id:PAPER},feature:'reading_position',key:hash,source_document_hash:hash,
      data:{page:2,recorded_at:'2026-10-31T00:00:00Z',method:'entered'}},
    {operationId:crypto.randomUUID(),device:'demo-phone',parents:document.parents});
  await store.update(state=>{
    receive(state,[event(document,state.cursor+1)]);
    state.positionRetentions={[source.entity_id]:{version:1,document,manifest,source_operation:null,source_operation_id:null}};
    state.positionIntents={[position.operation_id]:{version:1,operation:position,source_id:source.entity_id,manifest,
      parents:source.parents,observed:{paper_incarnation:source.parents[0].incarnation,source_operation_id:null,
        source_incarnation:null,position_operation_id:null,position_incarnation:null,position_action:null},retention_id:source.entity_id}};
    state.outbox.push({operation:source,acknowledged:null},{operation:position,acknowledged:null});
    state.artifactFiles[hash]={size:bytes.length,chunks:[bytes],verified:true};
    state.artifactFiles[bodyHash]={size:body.length,chunks:[body],verified:true};
  });
  return {store,engine:new Engine(store),hash,source,position};
}
test('v1 export shape and bytes remain exact without position work',async()=>{
  const state=new MemoryStore('work','device');await state.update(row=>{row.drafts.a='note';row.files.secret={};});
  const engine=new Engine(state),before=await state.read();
  assert.equal(JSON.stringify(await engine.exportLocal()),JSON.stringify(legacyRecovery(before)));
  assert.equal(stable(await state.read()),stable(before));
});
test('v2 exports closed source closure and old pending operations only as archives without changing state',async()=>{
  const {engine,store,hash,position}=await fixture(),before=await store.read(),value=await engine.exportLocal();
  assert.equal(value.version,2);assert.deepEqual(value.required_capabilities,['reading_position']);
  assert.equal(value.archives[0].positions[0].id,position.operation_id);
  assert.equal(value.archives[0].outbox.length,2);assert.equal(value.blobs.length,2);
  const blob=value.blobs.find(row=>row.sha256===hash);
  assert.equal(await digest(Uint8Array.from(atob(blob.base64),char=>char.charCodeAt(0))),hash);
  assert(!JSON.stringify(value).includes('token'));assert.equal(stable(await store.read()),stable(before));
});
for(const mode of ['unknown-field','unknown-capability','bad-archive-id','wrong-workspace','bad-base64','changed-bytes','extra-blob','missing-blob','extra-source-field','float-page'])
  test('invalid recovery refuses '+mode+' before any state/cursor/outbox change',async()=>{
    const {store,engine}=await fixture(),value=await exportPositionRecovery(await store.read()),before=await store.read();
    let text;
    if(mode==='unknown-field')value.extra=true;
    if(mode==='unknown-capability')value.required_capabilities.push('unknown');
    if(mode==='bad-archive-id')value.archives[0].id='a'.repeat(64);
    if(mode==='wrong-workspace')value.archives[0].workspace='other';
    if(mode==='bad-base64')value.blobs[0].base64='!'+value.blobs[0].base64.slice(1);
    if(mode==='changed-bytes')value.blobs[0].base64='A'+value.blobs[0].base64.slice(1);
    if(mode==='extra-blob')value.blobs.push(copy(value.blobs[0]));
    if(mode==='missing-blob')value.blobs.pop();
    if(mode==='extra-source-field')value.archives[0].sources[0].sender_path='private.pdf';
    text=JSON.stringify(value);
    if(mode==='float-page')text=text.replace('"page":2','"page":2.0');
    await assert.rejects(preparePositionRecovery(engine,text));
    assert.equal(stable(await store.read()),stable(before));
  });
test('source byte limit is checked before reading/encoding or changing a private cache',async()=>{
  const {store,engine,hash}=await fixture();
  await store.update(state=>{
    const retention=Object.values(state.positionRetentions)[0];
    retention.document.payload.size=33*1024**2;retention.manifest.assets[0].size=33*1024**2;
    state.receipts[retention.document.operation_id].operation.payload.size=33*1024**2;
    state.artifactFiles[hash].size=33*1024**2;
  });
  const before=await store.read();await assert.rejects(engine.exportLocal());assert.equal(stable(await store.read()),stable(before));
});
test('raw recovery exceeds 64 MiB refuses before JSON parsing and import requires sealed preparation',async()=>{
  const {store,engine}=await fixture(),before=await store.read();
  await assert.rejects(preparePositionRecovery(engine,' '.repeat(MAX_RECOVERY_BYTES+1)),/position_recovery_size_limit/);
  await assert.rejects(importPositionRecovery(engine,{}),/position_recovery_preparation_required/);
  assert.equal(stable(await store.read()),stable(before));
});
test('known retired ownership stays privately exportable but never becomes live authority',async()=>{
  const {store,engine,source}=await fixture();
  await store.update(state=>{state.graph['research_file/'+source.entity_id]={incarnation:'retired',parents:source.parents,deleted:true,structure_revision:10};});
  const before=await store.read(),document=Object.values(before.positionRetentions)[0].document;
  assert.throws(()=>primaryReference(before,document),/position_original_retired/);
  const value=await engine.exportLocal();assert.equal(value.archives[0].sources[0].manifest.slot,source.payload.slot);
  assert.equal(value.blobs.length,2);assert.equal(stable(await store.read()),stable(before));
});
test('archived source references preserve exact old/new paper lifetimes without hash-only reparenting or duplicate PDF bytes',async()=>{
  const {store,engine,source,position}=await fixture();
  await store.update(state=>{
    delete state.positionRetentions;
    state.receipts[source.operation_id]=event(source,state.cursor+1);
    state.positionIntents[position.operation_id].observed.source_operation_id=source.operation_id;
    const newer=copy(source);newer.operation_id='new-lifetime-source';newer.incarnation=newer.operation_id;
    newer.parents[0].incarnation='new-paper-lifetime';
    state.receipts[newer.operation_id]=event(newer,state.cursor+2);
    state.entities['research_file/'+source.entity_id]={operation:newer,revision:state.cursor+2,created:state.cursor+2};
    const id=crypto.randomUUID();state.positionCandidates={[id]:{paper_id:PAPER,document_hash:source.payload.slot,
      data:copy(position.payload.data),observed:{...copy(state.positionIntents[position.operation_id].observed),
        paper_incarnation:'new-paper-lifetime',source_operation_id:newer.operation_id,source_incarnation:newer.incarnation},
      resolvedBy:null,reason:'source_unavailable'}};
  });
  const value=await engine.exportLocal(),rows=value.archives[0].sources;
  assert.equal(rows.length,2);assert.notEqual(rows[0].reference,rows[1].reference);
  assert.equal(rows[0].id,rows[1].id);assert.equal(value.blobs.length,2);
  assert.equal(value.archives[0].positions[1].reason,'source_unavailable');
});
test('re-export of private recovery also preserves newly typed ordinary note drafts',async()=>{
  const {store,engine}=await fixture(),original=await engine.exportLocal();
  await store.update(state=>{
    state.positionRecoveries={[original.archives[0].id]:{archive:original.archives[0],reviewed:{}}};
    delete state.positionIntents;delete state.positionRetentions;state.outbox=[];state.drafts.fresh='New note draft';
  });
  const value=await engine.exportLocal();assert.equal(value.archives.length,2);
  assert(value.archives.some(item=>item.drafts.fresh==='New note draft'));
  assert.equal(value.blobs.length,2);
});
