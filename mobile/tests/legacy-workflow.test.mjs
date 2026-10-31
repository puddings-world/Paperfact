import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {createHash} from 'node:crypto';
import {contentId} from '../ids.mjs';
import {initialAnnotationDeletion} from '../content.mjs';
import {validateOperation,projection,receive,stable} from '../domain.mjs';
import {validateArtifact} from '../artifacts.mjs';
import {digest} from '../artifact-engine.mjs';
import {legacyBriefId,markdownText,validateLegacyBody} from '../legacy-workflow.mjs';
import {MemoryStore,emptyState} from '../store.mjs';
import {Engine} from '../engine.mjs';
import {FixtureTransport,operation,ref} from '../fixture.mjs';
const raw=readFileSync(new URL('../../tests/fixtures/legacy-workflow.json',import.meta.url)),gold=JSON.parse(raw);
const P=gold.paper_id,Q=gold.queue.data.parent_id,E=gold.event_id,F=legacyBriefId(P,E);
const parents=[ref('paper',P),ref('paper',Q)],clone=structuredClone;
const cid=p=>contentId(p.scope,p.feature,p.key);
const cop=(p,id='content-put',extra={})=>operation('research_content',cid(p),extra.action==='delete'?{}:clone(p),
  {operationId:id,parents:p.feature==='queue_entry'?parents:[parents[0]],...extra});
const fop=(payload=gold.brief.payload,extra={})=>operation('research_file',F,clone(payload),
  {operationId:'brief-put',parents:[parents[0]],...extra});
const receipt=(op,n)=>({sequence:n,outcome:'accepted',operation:op,head:{revision:n,operation:op}});
async function setup({beforeEvent=false}={}) {
  const ops=[P,Q].map(id=>operation('paper',id,{title:id,authors:[],year:null,venue:null,doi:null,abstract:null,
    arxiv_id:null,s2_id:null,page_url:null,pdf_url:null,source:'fixture'}));
  ops.push(cop(gold.queue,'queue-put'));
  if(!beforeEvent)ops.push(cop(gold.event,'fixture-event-incarnation'));
  ops.push(fop());
  const transport=new FixtureTransport({events:ops.map((op,i)=>receipt(op,i+1))});
  for(const [sha,b64] of Object.entries(gold.brief.blobs))transport.blobs.set(sha,Uint8Array.from(Buffer.from(b64,'base64')));
  const store=new MemoryStore('demo-workspace','demo-phone'),engine=new Engine(store,{transport});
  await engine.connect('fixture-token');await engine.sync();return {store,engine,transport};
}
async function change(s,p,id='event-edit',extra={}) {
  const old=s.transport.state.entities['research_content/'+cid(p)];
  const graph=s.transport.state.graph['research_content/'+cid(p)];
  const op=cop(p,id,{device:'demo-phone',base:old?.revision??0,structure:graph?.structure_revision??0,
    incarnation:old?.operation.incarnation??id,...extra});
  assert.equal((await s.transport.push('fixture-token',op)).outcome,'accepted');await s.engine.sync();return op;
}
test('fixed Python golden bytes, ordered closures and numeric canonical compatibility',()=>{
  assert.equal(createHash('sha256').update(raw).digest('hex'),'a74e1ff5513d504efe5544bb3347bc310d8f50c0d28b2b3d76a807107bdef265');
  for(const rank of gold.rank_cases){const p=clone(gold.queue);p.data.rank=rank;validateOperation(cop(p),'demo-workspace');}
  validateOperation(cop(gold.event),'demo-workspace');validateOperation(fop(),'demo-workspace');
  validateArtifact(gold.brief.payload,F,[parents[0]]);validateLegacyBody(gold.brief.body,gold.brief.payload);
  const self=clone(gold.queue);self.data.parent_id=P;validateOperation(cop(self,'self',{parents:[parents[0]]}),'demo-workspace');
});
test('closed workflow rejects unknown fields, types, timestamps, paths and descriptor bounds',()=>{
  for(const mutate of [p=>p.data.rank=true,p=>p.data.rank=Infinity,p=>p.data.rank='1',p=>p.data.state='later',
    p=>p.data.role=null,p=>p.data.role='中'.repeat(43),p=>p.data.parent_id='sender-path',p=>p.data.queued_at='2026-10-30',
    p=>p.data.path='private',p=>p.source_document_hash='a'.repeat(64),p=>p.feature='opaque-workflow']) {
    const p=clone(gold.queue);mutate(p);assert.throws(()=>validateOperation(cop(p),'demo-workspace'));
  }
  for(const mutate of [p=>p.data.brief.size=0,p=>p.data.brief.size=8*1024**2+1,p=>p.data.brief.size=true,
    p=>p.data.brief.path='private',p=>p.data.brief.media_type='text/html',p=>p.data.delivered_at=null,p=>p.data.note='\ud800',
    p=>p.data.note='中'.repeat(70000),p=>p.data.extra=false]) {
    const p=clone(gold.event);mutate(p);assert.throws(()=>validateOperation(cop(p),'demo-workspace'));
  }
});
for(const shape of ['reversed','missing','duplicate','wrong-kind'])test('queue put and known delete reject '+shape+' ordered parents',()=>{
  let bad=clone(parents);if(shape==='reversed')bad.reverse();if(shape==='missing')bad.pop();
  if(shape==='duplicate')bad[1]=clone(bad[0]);if(shape==='wrong-kind')bad[1].kind='list';
  assert.throws(()=>validateOperation(cop(gold.queue,'bad',{parents:bad}),'demo-workspace'));
  // A deletion has no payload from which to infer a missing optional parent. Exact prior closure is checked on receipt.
  if(shape!=='missing')assert.throws(()=>validateOperation(cop(gold.queue,'bad-delete',{parents:bad,action:'delete'}),'demo-workspace'));
});
test('verified Markdown stays exact text offline, read-only, with no inferred list membership or jobs',async()=>{
  const s=await setup(),before=await s.store.read(),view=projection(before),paper=view.papers.find(p=>p.id===P);
  assert.deepEqual(paper.legacy_queue,gold.queue.data);assert.deepEqual(paper.reading_events[0].data,gold.event.data);
  assert.deepEqual(view.lists,[]);assert.deepEqual(before.outbox,[]);assert.deepEqual(before.appliedArtifacts,{});
  await assert.rejects(s.engine.legacyBrief(F),/artifact_unavailable/);
  const first=s.engine.downloadArtifact(F);assert.equal(first,s.engine.downloadArtifact(F));await first;
  assert.equal(s.transport.calls.filter(call=>call[0]==='blob').length,2);
  const result=await s.engine.legacyBrief(F),expected=Buffer.from(gold.brief.blobs[gold.event.data.brief.sha256],'base64');
  assert.deepEqual(Buffer.from(result.blobs.get(gold.event.data.brief.sha256)),expected);
  assert.equal(result.text,expected.toString('utf8'));assert(result.text.includes('<script>never executed</script>'));
  s.engine.disconnect();const offline=new Engine(new MemoryStore('demo-workspace','demo-phone',await s.store.read()),
    {transport:new Proxy({}, {get(){throw Error('offline network');}})});
  assert.equal((await offline.legacyBrief(F)).text,result.text);assert(!JSON.stringify(await s.store.read()).includes('fixture-token'));
});
test('metadata before reading event cannot activate; exact event later permits retry',async()=>{
  const s=await setup({beforeEvent:true});await assert.rejects(s.engine.downloadArtifact(F),/legacy_event_unavailable/);
  assert.deepEqual((await s.store.read()).appliedArtifacts,{});
  await change(s,gold.event,'fixture-event-incarnation');await s.engine.downloadArtifact(F);
  assert.equal((await s.engine.legacyBrief(F)).body.event_incarnation,'fixture-event-incarnation');
});
for(const mode of ['clear','delete','new-incarnation','descriptor'])test('cached brief hidden after event '+mode,async()=>{
  const s=await setup();await s.engine.downloadArtifact(F);const p=clone(gold.event);
  if(mode==='clear')p.data.brief=null;
  if(mode==='descriptor')p.data.brief.sha256='a'.repeat(64);
  if(mode==='delete'||mode==='new-incarnation')await change(s,p,'event-delete',{action:'delete'});
  if(mode==='new-incarnation')await change(s,p,'new-event',{incarnation:'new-event'});
  if(mode==='clear'||mode==='descriptor')await change(s,p);
  await assert.rejects(s.engine.legacyBrief(F),/legacy_event_unavailable/);
  const offline=new Engine(new MemoryStore('demo-workspace','demo-phone',await s.store.read()));
  await assert.rejects(offline.legacyBrief(F),/legacy_event_unavailable/);
});
test('same-incarnation event identity and queue closure changes reject atomically before cursor advancement',async()=>{
  for(const kind of ['time','parent','delete-closure']) {
    const s=await setup(),before=await s.store.read(),p=clone(kind==='time'?gold.event:gold.queue);
    if(kind==='time')p.data.delivered_at='2026-10-31T00:00:00Z';else p.data.parent_id=null;
    const old=before.entities['research_content/'+cid(p)],op=cop(p,'malformed',{base:old.revision,
      incarnation:old.operation.incarnation,parents:kind==='time'?[parents[0]]:[parents[0]],action:kind==='delete-closure'?'delete':'put'});
    await assert.rejects(s.store.update(next=>receive(next,[receipt(op,before.cursor+1)])));
    assert.equal(stable(await s.store.read()),stable(before));
  }
});
test('late event clear prevents activation after bytes finish and retry creates no jobs',async()=>{
  const s=await setup(),read=s.transport.blob_read.bind(s.transport);let start,release;
  const started=new Promise(r=>start=r),gate=new Promise(r=>release=r);
  s.transport.blob_read=async(...args)=>{const value=await read(...args);if(args[1]===gold.event.data.brief.sha256){start();await gate;}return value;};
  const pending=s.engine.downloadArtifact(F);await started;const p=clone(gold.event);p.data.brief=null;await change(s,p);release();
  await assert.rejects(pending,/legacy_event_unavailable/);assert.deepEqual((await s.store.read()).appliedArtifacts,{});
  assert.deepEqual((await s.store.read()).outbox,[]);
});
test('disconnect while transfer active discards late result',async()=>{
  const s=await setup(),read=s.transport.blob_read.bind(s.transport);let start,release;
  const started=new Promise(r=>start=r),gate=new Promise(r=>release=r);
  s.transport.blob_read=async(...args)=>{const value=await read(...args);start();await gate;return value;};
  const pending=s.engine.downloadArtifact(F);await started;s.engine.disconnect();release();
  await assert.rejects(pending,/cancelled/);assert.deepEqual((await s.store.read()).appliedArtifacts,{});
});
test('closed manifest and body reject tampering even where blobs hash correctly',async()=>{
  for(const mutate of [p=>p.assets[0].role='html',p=>p.assets[0].size=0,p=>p.assets.push(clone(p.assets[0])),
    p=>p.body.size=4097,p=>p.body.sha256=[p.body.sha256],p=>p.source_document_hash='a'.repeat(64),
    p=>p.input_versions.complete=true,p=>p.path='private']) {
    const p=clone(gold.brief.payload);mutate(p);assert.throws(()=>validateOperation(fop(p),'demo-workspace'));
  }
  for(const mutate of [b=>b.event_incarnation='different',b=>b.legacy_day='2026-02-30',b=>b.event_id=Q,b=>b.path='private']) {
    const s=await setup(),body=clone(gold.brief.body);mutate(body);const raw=new TextEncoder().encode(stable(body)),sha=await digest(raw);
    const p=clone(gold.brief.payload);p.body={...p.body,sha256:sha,size:raw.length};s.transport.blobs.set(sha,raw);
    const old=s.transport.state.entities['research_file/'+F];await s.transport.push('fixture-token',fop(p,
      {operationId:'new-body',device:'demo-phone',incarnation:'brief-put',base:old.revision}));await s.engine.sync();
    await assert.rejects(s.engine.downloadArtifact(F));assert.deepEqual((await s.store.read()).appliedArtifacts,{});
  }
});
test('Markdown rejects invalid UTF8 and NUL while preserving BOM, CRLF and literal markup',()=>{
  assert.equal(markdownText(new TextEncoder().encode('\ufeff# hi\r\n<script>x</script>')),'\ufeff# hi\r\n<script>x</script>');
  for(const bad of [new Uint8Array(),Uint8Array.of(255),Uint8Array.of(65,0)])assert.throws(()=>markdownText(bad));
});
test('new features do not expand inferred initial deletes or generic opaque parents',()=>{
  const heads=[{operation:operation('paper',P,{})}];
  assert.equal(initialAnnotationDeletion(cop(gold.queue,'delete',{action:'delete',parents:[parents[0]]}),heads),null);
  assert.equal(initialAnnotationDeletion(cop(gold.event,'delete',{action:'delete'}),heads),null);
  const opaque=operation('research_content','opaque',{}, {action:'delete',parents});
  assert.throws(()=>validateOperation(opaque,'demo-workspace'));
  assert.throws(()=>validateOperation(fop(gold.brief.payload,{parents}), 'demo-workspace'));
});
test('repeated known deletes retain exact original owner and incarnation without opaque-ID inference',async()=>{
  for(const feature of ['reading_event','queue_entry']) {
    const s=await setup(),p=clone(feature==='reading_event'?gold.event:gold.queue);
    await change(s,p,'first-delete',{action:'delete'});const before=await s.store.read(),head=before.entities['research_content/'+cid(p)];
    const changed=cop(p,'wrong-owner',{action:'delete',incarnation:head.operation.incarnation,base:head.revision,
      parents:feature==='reading_event'?[parents[1]]:[parents[0]]});
    await assert.rejects(s.store.update(next=>receive(next,[receipt(changed,before.cursor+1)])),/invalid_legacy_lifecycle/);
    assert.equal(stable(await s.store.read()),stable(before));
  }
});
test('fresh inactive queue restore cannot change prior closure without the explicit active transition',async()=>{
  const s=await setup(),p=clone(gold.queue);await change(s,p,'queue-delete',{action:'delete'});
  const before=await s.store.read(),head=before.entities['research_content/'+cid(p)];p.data.parent_id=null;
  const op=cop(p,'restore-reparent',{base:head.revision,parents:[parents[0]]});
  await assert.rejects(s.store.update(next=>receive(next,[receipt(op,before.cursor+1)])),/invalid_legacy_lifecycle/);
  assert.equal(stable(await s.store.read()),stable(before));
});
for(const mode of ['revision','dependency'])test('explicit active queue context transition requires fresh incarnation and exact '+mode+' CAS',async()=>{
  const s=await setup();await s.engine.downloadArtifact(F);
  const before=await s.store.read(),p=clone(gold.queue),key='research_content/'+cid(p),head=before.entities[key];
  p.data.parent_id=null;
  const op=cop(p,'context-change',{base:head.revision,structure:before.graph[key].structure_revision,parents:[parents[0]],
    ...(mode==='dependency'?{device:head.operation.device_id}:{})});
  if(mode==='dependency'){op.depends_on=head.operation.operation_id;op.structure_depends_on=head.operation.incarnation;op.base_revision=0;op.structure_revision=0;}
  await s.store.update(next=>receive(next,[receipt(op,before.cursor+1)]));
  const after=await s.store.read(),paper=projection(after).papers.find(p=>p.id===P);
  assert.equal(paper.legacy_queue.parent_id,null);assert.equal(after.graph[key].incarnation,'context-change');
  assert.equal(after.graph[key].structure_revision,before.cursor+1);
  assert.equal((await s.engine.legacyBrief(F)).text,Buffer.from(gold.brief.blobs[gold.event.data.brief.sha256],'base64').toString());
  assert.deepEqual(after.outbox,[]);
});
for(const fault of ['same-incarnation','same-context','stale-head','stale-structure','wrong-owner','owner-epoch',
  'inactive-prior-parent','missing-origin','unrelated-data-dependency','unrelated-structure-dependency','foreign-device-dependency'])
test('queue-only context transition rejects '+fault+' atomically',async()=>{
  const s=await setup(),p=clone(gold.queue),before=await s.store.read(),key='research_content/'+cid(p),head=before.entities[key];
  p.data.parent_id=null;const op=cop(p,'bad-context',{base:head.revision,structure:before.graph[key].structure_revision,parents:[parents[0]]});
  if(fault==='same-incarnation')op.incarnation=head.operation.incarnation;
  if(fault==='same-context'){op.payload=clone(gold.queue);op.parents=clone(parents);}
  if(fault==='stale-head')op.base_revision--;
  if(fault==='stale-structure')op.structure_revision--;
  if(fault==='wrong-owner'){op.payload.scope.id=Q;op.parents=[parents[1]];}
  if(fault==='owner-epoch')op.parents[0]={...parents[0],incarnation:'new-owner'};
  if(fault==='inactive-prior-parent')before.graph['paper/'+Q].active=false;
  if(fault==='missing-origin')delete before.receipts[head.operation.incarnation];
  if(fault==='unrelated-data-dependency')op.depends_on=Q+'-created';
  if(fault==='unrelated-structure-dependency')op.structure_depends_on=Q+'-created';
  if(fault==='foreign-device-dependency'){op.depends_on=head.operation.operation_id;op.device_id='another-device';}
  const store=new MemoryStore('demo-workspace','demo-phone',before),initial=await store.read();
  await assert.rejects(store.update(next=>receive(next,[receipt(op,before.cursor+1)])));
  assert.equal(stable(await store.read()),stable(initial));
});
for(const mode of ['missing','corrupt','invalid-utf8','nul','float-version','duplicate-key'])test('brief bytes never activate when '+mode,async()=>{
  const s=await setup(),payload=clone(gold.brief.payload),event=clone(gold.event);
  const asset=payload.assets[0],body=payload.body;
  if(mode==='missing')s.transport.blobs.delete(asset.sha256);
  if(mode==='corrupt')s.transport.blobs.set(asset.sha256,new Uint8Array(asset.size).fill(65));
  if(['invalid-utf8','nul'].includes(mode)) {
    const bytes=mode==='nul'?Uint8Array.of(65,0):Uint8Array.of(255),sha=await digest(bytes);
    Object.assign(asset,{sha256:sha,size:bytes.length});event.data.brief={sha256:sha,size:bytes.length,media_type:'text/markdown'};
    s.transport.blobs.set(sha,bytes);await change(s,event);
  }
  if(['float-version','duplicate-key'].includes(mode)) {
    const original=Buffer.from(gold.brief.blobs[body.sha256],'base64').toString();
    const bytes=new TextEncoder().encode(original.replace('"version":1',mode==='float-version'?'"version":1.0':'"version":1,"version":1'));
    const sha=await digest(bytes);Object.assign(body,{sha256:sha,size:bytes.length});s.transport.blobs.set(sha,bytes);
  }
  if(!['missing','corrupt'].includes(mode)) {
    const old=s.transport.state.entities['research_file/'+F];assert.equal((await s.transport.push('fixture-token',fop(payload,
      {operationId:'bad-bytes',device:'demo-phone',incarnation:'brief-put',base:old.revision}))).outcome,'accepted');await s.engine.sync();
  }
  await assert.rejects(s.engine.downloadArtifact(F));assert.deepEqual((await s.store.read()).appliedArtifacts,{});
  await assert.rejects(s.engine.legacyBrief(F),/artifact_unavailable/);
});
for(const change of ['inactive','replaced'])test('paper '+change+' hides queue, event and verified brief',async()=>{
  const s=await setup();await s.engine.downloadArtifact(F);
  await s.store.update(next=>{const graph=next.graph['paper/'+P];if(change==='inactive')graph.active=false;else graph.incarnation='new-paper';});
  assert(!projection(await s.store.read()).papers.find(p=>p.id===P)?.reading_events?.length);
  assert.deepEqual(projection(await s.store.read()).legacy_briefs,[]);await assert.rejects(s.engine.legacyBrief(F),/artifact_unavailable/);
});
const contextBytes=readFileSync(new URL('../../tests/fixtures/legacy-queue-context.json',import.meta.url)),contextGolden=JSON.parse(contextBytes);
test('Python queue context golden bytes are pinned independently of the original workflow fixture',()=>{
  assert.equal(createHash('sha256').update(contextBytes).digest('hex'),'64ea18553bc3d71f1a94e0dc652cd0bac367c0e1d7d5cbaf45922577d976a93c');
  assert.equal(contextGolden.format,'paperfact-legacy-queue-context-v1');
});
for(const item of contextGolden.cases)test('Python/mobile queue context verdict agrees: '+item.name,async()=>{
  const op=clone(item.operation),workspace=op.workspace_id,state=emptyState(workspace,'reader');
  if(item.expected.wire_valid)validateOperation(op,workspace);
  else assert.throws(()=>validateOperation(op,workspace));
  for(const row of item.state) {
    const key=row.kind+'/'+row.id;state.graph[key]=clone(row.metadata);
    if(row.kind==='paper')state.entities[key]={revision:1,operation:operation('paper',row.id,
      {title:row.id,authors:[],year:null,venue:null,doi:null,abstract:null,arxiv_id:null,s2_id:null,page_url:null,pdf_url:null,source:'fixture'},
      {operationId:row.metadata.incarnation,incarnation:row.metadata.incarnation})};
  }
  const key=item.head.operation.entity_type+'/'+item.head.operation.entity_id;state.entities[key]=clone(item.head);
  for(const event of item.receipts)state.receipts[event.operation.operation_id]=clone(event);
  state.cursor=Math.max(item.head.revision,...item.receipts.map(event=>event.sequence));
  const store=new MemoryStore(workspace,'reader',state),before=await store.read();
  const apply=()=>store.update(next=>receive(next,[receipt(op,state.cursor+1)]));
  if(item.expected.accepted) {
    await apply();const after=await store.read();assert.equal(after.graph[key].incarnation,op.incarnation);
    assert.deepEqual(projection(after).papers.find(p=>p.id===op.payload.scope.id).legacy_queue,op.payload.data);
    assert.deepEqual(after.outbox,[]);
  } else {
    await assert.rejects(apply());assert.equal(stable(await store.read()),stable(before));
  }
});
