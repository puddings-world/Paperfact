import test from 'node:test';
import assert from 'node:assert/strict';
import {MemoryStore} from '../store.mjs';
import {Engine} from '../engine.mjs';
import {projection,stable,validateOperation} from '../domain.mjs';
import {demoTransport,PAPER,operation,ref} from '../fixture.mjs';
import {artifactJSON,fileId,validateArtifact,validateDeck,validatePNG} from '../artifacts.mjs';
import {digest} from '../artifact-engine.mjs';
const PNG=Uint8Array.from(Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAIAAAACCAIAAAD91JpzAAAACXBIWXMAAA7EAAAOxAGVKw4bAAAADklEQVR4nGM4AQYMEAoAQa4JYQOnncMAAAAASUVORK5CYII=','base64'));
const bytes=value=>new TextEncoder().encode(stable(value));
const versions={schema_version:1,complete:false,entities:[],documents:[],inputs_sha256:null};
async function fixture(title='Original',image=PNG) {
  const body={version:1,evidence_asset:null,deck:{
    paper_id:PAPER,paper_title:'Research 🧪',title,mode:'notes',audience:'Researchers',minutes:5,
    slides:[{title:'Key result',section:'Method',takeaway:'A useful result',bullets:['Evidence matters'],
      speaker_notes:'Explain the background.',sources:['figure-1'],figure:'figure-1',elements:null}],
    sources:[{id:'figure-1',label:'Figure 1',kind:'figure',page:1}],
    figures:[{id:'figure-1',label:'Figure 1',asset_id:'image',caption:'The result',page:1}],
    coverage:['Method'],created_at:'2026-10-26T00:00:00Z',deck_id:'fixture-deck',source_hash:'',generation:{},edited:false,version:1
  }};
  const raw=bytes(body), bodyHash=await digest(raw), imageHash=await digest(image);
  return {body,blobs:new Map([[bodyHash,raw],[imageHash,image]]),payload:{
    paper_id:PAPER,feature:'deck',slot:'notes',format_version:1,source_document_hash:null,input_versions:structuredClone(versions),
    body:{sha256:bodyHash,size:raw.length,media_type:'application/json'},
    assets:[{id:'image',role:'figure',sha256:imageHash,size:image.length,media_type:'image/png'}]
  }};
}
async function setup() {
  const transport=await demoTransport(), store=new MemoryStore('demo-workspace','demo-phone');
  const engine=new Engine(store,{transport}); await engine.connect('fixture-token'); await engine.sync();
  return {transport,store,engine};
}
async function publish(state,entry,id='deck-one') {
  const entity=fileId(PAPER,'notes'), old=state.transport.state.entities['research_file/'+entity];
  for (const [hash,blob] of entry.blobs) state.transport.blobs.set(hash,blob);
  const op=operation('research_file',entity,entry.payload,{operationId:id,device:'demo-phone',parents:[ref('paper',PAPER)],
    incarnation:old?.operation.incarnation??id,base:old?.revision??0});
  assert.equal((await state.transport.push('fixture-token',op)).outcome,'accepted');
  await state.engine.sync(); return entity;
}
test('canonical JSON keeps Python floats and Unicode but rejects duplicates and noncanonical whitespace',()=>{
  const raw=new TextEncoder().encode('{"layout":[200.0,1e-07],"title":"研究 🧪"}');
  assert.equal(artifactJSON(raw).layout[0],200);
  assert.equal(artifactJSON(raw).title,'研究 🧪');
  for(const value of ['{"a":1,"a":2}','{"b":1,"a":2}','{"a": 1}','{"a":NaN}','[1,]','1 2'])
    assert.throws(()=>artifactJSON(new TextEncoder().encode(value)));
});
test('closed manifest rejects credentials, paths, mismatched IDs and oversized assets',async()=>{
  const data=await fixture(), id=fileId(PAPER,'notes');
  validateArtifact(data.payload,id,[ref('paper',PAPER)]);
  for(const mutate of [p=>p.path='C:/private',p=>p.body.size=9*1024**2,p=>p.assets[0].url='https://example.test',
    p=>p.input_versions.token='secret',p=>p.assets.push({...p.assets[0]}),p=>p.paper_id='local-paper']) {
    const bad=structuredClone(data.payload); mutate(bad); assert.throws(()=>validateArtifact(bad,id));
  }
});
test('closed deck rejects unknown sources, inactive image choices, path fields and account receipts',async()=>{
  const data=await fixture(); validateDeck(data.body,data.payload);
  for(const mutate of [b=>b.deck.slides[0].sources=['unknown'],b=>b.deck.figures[0].file='secret.png',
    b=>b.deck.generation.token='secret',b=>b.deck.slides[0].elements=[],b=>b.deck.slides[0].elements=[{kind:'text',x:0,y:0,w:50,h:40,text:'x',color:'url(secret)'}]]) {
    const bad=structuredClone(data.body); mutate(bad); assert.throws(()=>validateDeck(bad,data.payload));
  }
});
test('PNG validation requires actual decompressible complete image bytes',async()=>{
  assert.deepEqual(await validatePNG(PNG),{width:2,height:2});
  const corrupt=PNG.slice(); corrupt[corrupt.length-5]^=1;
  await assert.rejects(validatePNG(corrupt));
  await assert.rejects(validatePNG(PNG.subarray(0,PNG.length-12)));
});
test('manifest history advances before bytes; complete verified deck reads offline after reopen',async()=>{
  const state=await setup(), item=await fixture(), id=await publish(state,item);
  const before=await state.store.read(); assert.equal(projection(before).decks[0].id,id);
  await assert.rejects(state.engine.deck(id),/artifact_unavailable/);
  await state.engine.downloadArtifact(id);
  state.engine.disconnect();
  const reopened=new Engine(new MemoryStore('demo-workspace','demo-phone',await state.store.read()));
  const deck=await reopened.deck(id);
  assert.equal(deck.body.deck.title,'Original'); assert.equal(deck.awaiting,false);
  assert.deepEqual(deck.blobs.get(item.payload.assets[0].sha256),PNG);
});
test('new manifest retains old applied deck until all updated files validate',async()=>{
  const state=await setup(), id=await publish(state,await fixture()); await state.engine.downloadArtifact(id);
  const updated=await fixture('Updated'); await publish(state,updated,'deck-two');
  let result=await state.engine.deck(id); assert.equal(result.body.deck.title,'Original'); assert.equal(result.awaiting,true);
  await state.engine.downloadArtifact(id); result=await state.engine.deck(id);
  assert.equal(result.body.deck.title,'Updated'); assert.equal(result.awaiting,false);
});
test('bad image closure never replaces old applied deck even with matching image SHA',async()=>{
  const state=await setup(), id=await publish(state,await fixture()); await state.engine.downloadArtifact(id);
  const corrupt=PNG.slice(); corrupt[corrupt.length-5]^=1;
  await publish(state,await fixture('Broken',corrupt),'deck-two');
  await assert.rejects(state.engine.downloadArtifact(id));
  assert.equal((await state.engine.deck(id)).body.deck.title,'Original');
});
test('duplicate artifact download shares one authenticated job',async()=>{
  const state=await setup(), id=await publish(state,await fixture());
  const first=state.engine.downloadArtifact(id), second=state.engine.downloadArtifact(id);
  assert.equal(first,second); await first;
  assert.equal(state.transport.calls.filter(row=>row[0]==='blob').length,2);
});
test('session switch cancels a late streamed asset without activation',async()=>{
  const state=await setup(), item=await fixture(), id=await publish(state,item);
  const original=state.transport.blob_read.bind(state.transport);
  let release, started; const gate=new Promise(resolve=>{release=resolve;}), pending=new Promise(resolve=>{started=resolve;});
  state.transport.blob_read=async(...args)=>{const data=await original(...args);if(args[1]===item.payload.assets[0].sha256){started();await gate;}return data;};
  const job=state.engine.downloadArtifact(id); await pending; state.engine.disconnect(); release();
  await assert.rejects(job,/cancelled/);
  assert.deepEqual((await state.store.read()).appliedArtifacts,{});
});
test('late asset completion cannot activate a superseded manifest',async()=>{
  const state=await setup(), id=await publish(state,await fixture());
  const original=state.transport.blob_read.bind(state.transport);
  let release, started; const gate=new Promise(resolve=>{release=resolve;}), pending=new Promise(resolve=>{started=resolve;});
  state.transport.blob_read=async(...args)=>{const data=await original(...args);started();await gate;return data;};
  const job=state.engine.downloadArtifact(id); await pending;
  await publish(state,await fixture('Newer'),'deck-two'); release();
  await assert.rejects(job,/stale_artifact/);
  assert.deepEqual((await state.store.read()).appliedArtifacts,{});
});
test('revoked session cannot download assets but retains previously verified offline deck',async()=>{
  const state=await setup(), id=await publish(state,await fixture()); await state.engine.downloadArtifact(id);
  state.transport.revoked=true;
  await assert.rejects(state.engine.downloadArtifact(id),/session_denied/);
  assert.equal((await state.engine.deck(id)).body.deck.title,'Original');
});
test('tampered cached bytes are rejected before exposing a supposedly verified deck',async()=>{
  const state=await setup(), item=await fixture(), id=await publish(state,item); await state.engine.downloadArtifact(id);
  await state.store.update(next=>{next.artifactFiles[item.payload.body.sha256].chunks[0][10]^=1;});
  await assert.rejects(state.engine.deck(id),/corrupt_file/);
});
test('explicit artifact retirement hides prior applied content',async()=>{
  const state=await setup(), id=await publish(state,await fixture()); await state.engine.downloadArtifact(id);
  const old=state.transport.state.entities['research_file/'+id];
  const op=operation('research_file',id,{}, {operationId:'deck-delete',device:'demo-phone',action:'delete',
    parents:[ref('paper',PAPER)],incarnation:old.operation.incarnation,base:old.revision,
    structure:state.transport.state.graph['research_file/'+id].structure_revision});
  await state.transport.push('fixture-token',op); await state.engine.sync();
  assert.deepEqual(projection(await state.store.read()).decks,[]);
  await assert.rejects(state.engine.deck(id),/artifact_unavailable/);
});
test('file operation validation stays fail-closed on unknown body format',async()=>{
  const item=await fixture(); item.payload.format_version=2;
  const op=operation('research_file',fileId(PAPER,'notes'),item.payload,{parents:[ref('paper',PAPER)]});
  assert.throws(()=>validateOperation(op,'demo-workspace'));
  const retired=operation('research_file','local-id',{}, {action:'delete',parents:[ref('paper',PAPER)]});
  assert.throws(()=>validateOperation(retired,'demo-workspace'));
});

test('interrupted body transfer resumes persisted chunks without reactivating partial content',async()=>{
  const state=await setup(), item=await fixture();
  item.body.deck.coverage=Array(100).fill('x'.repeat(3500));
  const raw=bytes(item.body), hash=await digest(raw);
  item.payload.body={sha256:hash,size:raw.length,media_type:'application/json'};item.blobs.set(hash,raw);
  const id=await publish(state,item), original=state.transport.blob_read.bind(state.transport);
  let failed=false;
  state.transport.blob_read=async(...args)=>{
    if(args[1]===hash && args[3]>0 && !failed){failed=true;throw new Error('connection_failed');}
    return original(...args);
  };
  await assert.rejects(state.engine.downloadArtifact(id),/connection_failed/);
  const partial=(await state.store.read()).artifactFiles[hash];
  assert.equal(partial.verified,false); assert.equal(partial.chunks.length,1);
  await assert.rejects(state.engine.deck(id),/artifact_unavailable/);
  state.transport.calls=[]; await state.engine.downloadArtifact(id);
  assert.equal(state.transport.calls.find(row=>row[0]==='blob')[2],256*1024);
  assert.equal((await state.engine.deck(id)).body.deck.title,'Original');
});
test('storage failure while fetching an updated closure retains old applied deck',async()=>{
  const state=await setup(), id=await publish(state,await fixture()); await state.engine.downloadArtifact(id);
  await publish(state,await fixture('Updated'),'deck-two'); state.store.failure='storage_write_failed';
  await assert.rejects(state.engine.downloadArtifact(id),/storage_write_failed/); state.store.failure=null;
  assert.equal((await state.engine.deck(id)).body.deck.title,'Original');
});


test('recorded deck input scope survives authenticated sync and offline reopen without rebasing',async()=>{
  const state=await setup(), item=await fixture();
  item.payload.input_versions={...structuredClone(versions),schema_version:2,workspace_id:'earlier-workspace'};
  const id=await publish(state,item);
  await state.engine.downloadArtifact(id); state.engine.disconnect();
  const reopened=new Engine(new MemoryStore('demo-workspace','demo-phone',await state.store.read()));
  const deck=await reopened.deck(id);
  assert.deepEqual(deck.operation.payload.input_versions,item.payload.input_versions);
  assert.equal(deck.body.deck.title,'Original');
  for(const mutate of [v=>delete v.workspace_id,v=>v.workspace_id='https://untrusted.invalid',
    v=>v.schema_version=true,v=>v.token='not-a-permitted-field']) {
    const bad=structuredClone(item.payload); mutate(bad.input_versions);
    assert.throws(()=>validateArtifact(bad,id));
  }
});
