import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {MemoryStore} from '../store.mjs';
import {Engine} from '../engine.mjs';
import {projection,stable,validateOperation} from '../domain.mjs';
import {demoTransport,PAPER,operation,ref} from '../fixture.mjs';
import {artifactJSON,sourceFileId,validateArtifact,validateOriginalSource,MAX_ORIGINAL_PDF} from '../artifacts.mjs';
import {digest,ARTIFACT_CACHE_BYTES} from '../artifact-engine.mjs';
const golden=JSON.parse(readFileSync(new URL('../../tests/fixtures/original-source.json',import.meta.url),'utf8'));
const bytes=value=>new TextEncoder().encode(stable(value));
const originalPDF=Uint8Array.from(Buffer.from(golden.blobs[golden.payload.slot],'base64'));
async function source(pdf=originalPDF) {
  const sha=await digest(pdf), body={version:1,paper_id:PAPER,document_hash:sha}, raw=bytes(body), bodyHash=await digest(raw);
  const payload=structuredClone(golden.payload);
  Object.assign(payload,{paper_id:PAPER,slot:sha,source_document_hash:sha,
    body:{sha256:bodyHash,size:raw.length,media_type:'application/json'},
    assets:[{id:'original',role:'original_pdf',sha256:sha,size:pdf.length,media_type:'application/pdf'}]});
  return {payload,body,blobs:new Map([[sha,pdf],[bodyHash,raw]])};
}
async function setup() {
  const transport=await demoTransport(),store=new MemoryStore('demo-workspace','demo-phone');
  const engine=new Engine(store,{transport});await engine.connect('fixture-token');await engine.sync();
  return {transport,store,engine};
}
async function publish(state,item,request='source-a') {
  const id=sourceFileId(PAPER,item.payload.slot),old=state.transport.state.entities['research_file/'+id];
  for(const [sha,raw] of item.blobs)state.transport.blobs.set(sha,raw);
  const op=operation('research_file',id,item.payload,{operationId:request,device:'demo-phone',parents:[ref('paper',PAPER)],
    incarnation:old?.operation.incarnation??request,base:old?.revision??0});
  assert.equal((await state.transport.push('fixture-token',op)).outcome,'accepted');
  await state.engine.sync();return id;
}

test('Python golden original-source identity and canonical body are accepted without extending deck identity',()=>{
  const payload=golden.payload,id=sourceFileId(payload.paper_id,payload.slot);
  validateArtifact(payload,id,[ref('paper',payload.paper_id)]);
  const raw=Uint8Array.from(Buffer.from(golden.blobs[payload.body.sha256],'base64'));
  assert.equal(validateOriginalSource(raw,payload).document_hash,payload.slot);
  assert.equal(artifactJSON(raw).paper_id,payload.paper_id);
});

test('closed source wire rejects unknowns, path/account data, wrong identity, parents, source and bounds',async()=>{
  const item=await source(),id=sourceFileId(PAPER,item.payload.slot);
  for(const change of [p=>p.feature='source_v2',p=>p.format_version=true,p=>p.slot='notes',
    p=>p.source_document_hash=null,p=>p.assets[0].sha256='a'.repeat(64),p=>p.assets[0].id='another',
    p=>p.assets[0].role='figure',p=>p.assets[0].media_type='text/html',p=>p.assets[0].size=true,
    p=>p.assets[0].size=MAX_ORIGINAL_PDF+1,p=>p.assets.push({...p.assets[0]}),
    p=>p.body.size=1025,p=>p.body.media_type='text/plain',p=>p.path='C:/private/original.pdf',
    p=>p.input_versions.complete=true,p=>p.input_versions.inputs_sha256='a'.repeat(64),
    p=>p.input_versions.entities.push({kind:'paper',id:PAPER,incarnation:'paper',revision:0,depends_on:null}),
    p=>p.input_versions.token='secret']) {
    const bad=structuredClone(item.payload);change(bad);assert.throws(()=>validateArtifact(bad,id));
  }
  assert.throws(()=>validateArtifact(item.payload,'00000000-0000-4000-8000-000000000000'));
  assert.throws(()=>validateArtifact(item.payload,id,[ref('paper','22222222-2222-4222-8222-222222222222')]));
});

test('source150MiB wire bound is separate from unchanged128MiB local cache and64MiB deck bounds',async()=>{
  const item=await source();item.payload.assets[0].size=MAX_ORIGINAL_PDF;
  validateArtifact(item.payload,sourceFileId(PAPER,item.payload.slot));
  assert.equal(ARTIFACT_CACHE_BYTES,128*1024**2);
  const state=await setup(),id=await publish(state,item);
  state.transport.calls=[];
  await assert.rejects(state.engine.downloadArtifact(id),/storage_quota/);
  assert(!state.transport.calls.some(call=>call[0]==='blob'));
  await assert.rejects(state.engine.originalSource(id),/artifact_unavailable/);
  assert.deepEqual((await state.store.read()).appliedArtifacts,{});
  // A restored/copied applied record cannot bypass the current device's capacity check.
  await state.store.update(next=>{next.appliedArtifacts[id]={operation:structuredClone(next.entities['research_file/'+id].operation)};});
  await assert.rejects(state.engine.originalSource(id),/storage_quota/);
});

test('metadata receive distinguishes original sources from decks and never implies offline availability',async()=>{
  const state=await setup(),before=await state.store.read(),item=await source(),id=await publish(state,item);
  const after=await state.store.read(),view=projection(after);
  assert.deepEqual(view.decks,[]);
  assert.deepEqual(view.original_sources,[{id,paper_id:PAPER,document_hash:item.payload.slot,operation_id:'source-a',editable:false}]);
  assert.deepEqual(after.files,before.files);assert.deepEqual(after.artifactFiles,{});
  await assert.rejects(state.engine.originalSource(id),/artifact_unavailable/);
  await assert.rejects(state.engine.deck(id),/artifact_unavailable/);
});

test('explicit verified original closure survives offline restart and leaves current primary PDF untouched',async()=>{
  const state=await setup();await state.engine.download(PAPER);
  const primary=await state.engine.pdf(PAPER),before=await state.store.read(),item=await source(),id=await publish(state,item);
  await state.engine.downloadArtifact(id);
  const result=await state.engine.originalSource(id);
  assert.equal(result.verification_scope,'exact_bytes');assert.equal(result.awaiting,false);
  assert.deepEqual(result.blobs.get(result.body.document_hash),originalPDF);
  assert.equal(result.body.paper_id,PAPER);
  assert.deepEqual(await state.engine.pdf(PAPER),primary);
  assert.deepEqual((await state.store.read()).files,before.files);
  state.engine.disconnect();
  const offline=new Engine(new MemoryStore('demo-workspace','demo-phone',await state.store.read()),
    {transport:new Proxy({}, {get(){throw Error('Offline read attempted network');}})});
  assert.equal(stable((await offline.originalSource(id)).body),stable(item.body));
  assert.deepEqual(await offline.pdf(PAPER),primary);
  assert(!JSON.stringify(await offline.store.read()).includes('fixture-token'));
});

test('body closure rejects owner/hash/version changes, duplicate keys and float version even with matching blob hashes',async()=>{
  for(const mutate of [b=>b.paper_id='22222222-2222-4222-8222-222222222222',
    b=>b.document_hash='a'.repeat(64),b=>b.version=2,b=>b.path='private']) {
    const state=await setup(),item=await source();mutate(item.body);
    const raw=bytes(item.body),sha=await digest(raw);item.payload.body={sha256:sha,size:raw.length,media_type:'application/json'};
    item.blobs.set(sha,raw);const id=await publish(state,item);
    await assert.rejects(state.engine.downloadArtifact(id));
    await assert.rejects(state.engine.originalSource(id),/artifact_unavailable/);
  }
  const item=await source(),valid=new TextDecoder().decode(bytes(item.body));
  for(const bad of [valid.replace('"version":1','"version":1.0'),valid.replace('"version":1','"version":true'),
    valid.replace('"version":1','"version":1,"version":1'),valid.replace(':1',': 1')])
    assert.throws(()=>validateOriginalSource(new TextEncoder().encode(bad),item.payload));
});

test('invalid PDF format cannot activate a hash-matching original-source closure',async()=>{
  const state=await setup(),item=await source(new TextEncoder().encode('not a PDF but hashed exactly')),
    id=await publish(state,item);
  await assert.rejects(state.engine.downloadArtifact(id),/invalid_pdf/);
  await assert.rejects(state.engine.originalSource(id),/artifact_unavailable/);
});

test('repeated download shares one job; revocation preserves previously verified offline source',async()=>{
  const state=await setup(),id=await publish(state,await source());
  const first=state.engine.downloadArtifact(id),second=state.engine.downloadArtifact(id);
  assert.equal(first,second);await first;
  assert.equal(state.transport.calls.filter(call=>call[0]==='blob').length,2);
  state.transport.revoked=true;
  await assert.rejects(state.engine.downloadArtifact(id),/session_denied/);
  assert.equal((await state.engine.originalSource(id)).verification_scope,'exact_bytes');
});

test('account/session switch during source download prevents late activation',async()=>{
  const state=await setup(),item=await source(),id=await publish(state,item),read=state.transport.blob_read.bind(state.transport);
  let started,release;const pending=new Promise(resolve=>{started=resolve;}),gate=new Promise(resolve=>{release=resolve;});
  state.transport.blob_read=async(...args)=>{const raw=await read(...args);if(args[1]===item.payload.slot){started();await gate;}return raw;};
  const job=state.engine.downloadArtifact(id);await pending;state.engine.disconnect();release();
  await assert.rejects(job,/cancelled/);assert.deepEqual((await state.store.read()).appliedArtifacts,{});
});

for(const change of ['inactive','replaced']) test(`late source transfer cannot activate after observed paper becomes ${change}`,async()=>{
  const state=await setup(),id=await publish(state,await source()),read=state.transport.blob_read.bind(state.transport);
  let started,release;const pending=new Promise(resolve=>{started=resolve;}),gate=new Promise(resolve=>{release=resolve;});
  state.transport.blob_read=async(...args)=>{const raw=await read(...args);started();await gate;return raw;};
  const job=state.engine.downloadArtifact(id);await pending;
  await state.store.update(next=>{
    if(change==='inactive')next.graph['paper/'+PAPER].active=false;
    else next.graph['paper/'+PAPER].incarnation='new-paper-epoch';
  });release();
  await assert.rejects(job,/stale_artifact/);assert.deepEqual(projection(await state.store.read()).original_sources,[]);
  await assert.rejects(state.engine.originalSource(id),/artifact_unavailable/);
});

test('cached original bytes are rehashed before offline exposure',async()=>{
  const state=await setup(),item=await source(),id=await publish(state,item);await state.engine.downloadArtifact(id);
  await state.store.update(next=>{next.artifactFiles[item.payload.slot].chunks[0][10]^=1;});
  await assert.rejects(state.engine.originalSource(id),/corrupt_file/);
});

test('source retirement hides cached closure without changing primary document',async()=>{
  const state=await setup(),id=await publish(state,await source());await state.engine.downloadArtifact(id);
  const before=await state.store.read(),head=state.transport.state.entities['research_file/'+id],graph=state.transport.state.graph['research_file/'+id];
  const del=operation('research_file',id,{}, {operationId:'source-retired',device:'demo-phone',action:'delete',
    parents:[ref('paper',PAPER)],incarnation:head.operation.incarnation,base:head.revision,structure:graph.structure_revision});
  await state.transport.push('fixture-token',del);await state.engine.sync();
  assert.deepEqual(projection(await state.store.read()).original_sources,[]);
  assert.deepEqual((await state.store.read()).entities['paper_document/'+PAPER],before.entities['paper_document/'+PAPER]);
  await assert.rejects(state.engine.originalSource(id),/artifact_unavailable/);
});

test('unknown source metadata stops receive without advancing cursor or replacing prior projection',async()=>{
  const state=await setup(),id=await publish(state,await source());const before=await state.store.read();
  const event=structuredClone(state.transport.events.at(-1));
  event.sequence++;event.operation.operation_id='unsupported-source';event.operation.payload.format_version=2;
  event.head={revision:event.sequence,operation:structuredClone(event.operation)};
  state.transport.events.push(event);
  await assert.rejects(state.engine.sync());
  const after=await state.store.read();assert.equal(after.cursor,before.cursor);
  assert.deepEqual(projection(after).original_sources,projection(before).original_sources);
  assert.equal(projection(after).original_sources[0].id,id);
  assert.throws(()=>validateOperation(event.operation,'demo-workspace'));
});
