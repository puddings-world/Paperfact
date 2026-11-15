import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {lineageRow,PAPER} from './fixtures/lineage-data.mjs';
import {claimHash,normalizeClaimText} from '../claims.mjs';
import {lineageSourceHash} from '../lineage.mjs';
import {contentId} from '../ids.mjs';
import {sourceFileId} from '../artifacts.mjs';
import {digest} from '../artifact-engine.mjs';
import {receive,stable,projection,enqueue} from '../domain.mjs';
import {MemoryStore} from '../store.mjs';
import {Engine} from '../engine.mjs';
import {FixtureTransport,operation,ref} from '../fixture.mjs';
import {openLineageSource,lineageSourceForDelivery,lineageSourceAvailable} from '../lineage-originals.mjs';
const golden=JSON.parse(readFileSync(new URL('../../tests/fixtures/original-source.json',import.meta.url),'utf8'));
const bytes=Uint8Array.from(Buffer.from(golden.blobs[golden.payload.slot],'base64'));
const event=(op,sequence)=>({sequence,outcome:'accepted',operation:structuredClone(op),head:{revision:sequence,operation:structuredClone(op)}});
async function setup(){
 const hash=await digest(bytes),row=lineageRow(),report=row.body.report,source=report.sources[0];
 source.document_hash=hash;source.id=claimHash(['lineage-source.v1',source.identity,hash]);
 report.focal=source.id;row.body.bindings[0].source_id=source.id;
 const item=report.statements[0],passage=item.passages[0];item.subject=source.id;passage.source_id=source.id;
 passage.id=claimHash(['bounded-lineage.v1',source.id,passage.role,null,normalizeClaimText(passage.quote),passage.location]);
 item.id=claimHash(['bounded-lineage.v1',source.id,item.stage,item.subject,normalizeClaimText(item.text)]);
 delete report.id;report.id=claimHash(report);row.document_hash=hash;row.source_hash=lineageSourceHash(row.body);
 const body=new TextEncoder().encode(stable({version:1,paper_id:PAPER,document_hash:hash})),bodyHash=await digest(body);
 const payload=structuredClone(golden.payload);
 Object.assign(payload,{paper_id:PAPER,slot:hash,source_document_hash:hash,
  body:{sha256:bodyHash,size:body.length,media_type:'application/json'},
  assets:[{id:'original',role:'original_pdf',sha256:hash,size:bytes.length,media_type:'application/pdf'}]});
 const paper=operation('paper',PAPER,{title:source.identity.title,authors:[],year:2026,venue:'Fixture',abstract:null,doi:null,arxiv_id:null,s2_id:null,page_url:null,pdf_url:null,source:'fixture'});
 const file=operation('research_file',sourceFileId(PAPER,hash),payload,{parents:[ref('paper',PAPER)]});
 const sciencePayload={scope:{kind:'paper',id:PAPER},feature:'lineage',key:row.body.corpus_id,
  source_document_hash:hash,data:{body_json:row.body,source_hash:row.source_hash,document_hash:hash,written_at:row.written_at}};
 const science={...operation('research_content',contentId(sciencePayload.scope,'lineage',row.body.corpus_id),sciencePayload,{parents:[ref('paper',PAPER)]}),
  content_address:{feature:'lineage',key:row.body.corpus_id},source_dependencies:[{source_id:source.id,paper_id:PAPER,file_id:file.entity_id,incarnation:file.incarnation}]};
 const transport=new FixtureTransport({events:[event(paper,1),event(file,2),event(science,3)]});
 transport.blobs.set(hash,bytes);transport.blobs.set(bodyHash,body);
 const store=new MemoryStore('demo-workspace','demo-phone'),engine=new Engine(store,{transport});
 await engine.connect('fixture-token');await engine.sync();
 return {engine,store,transport,row,source,file,science};
}
async function opened(s){return openLineageSource(s.engine,PAPER,s.row,s.source.id,{download:true});}

test('explicit download opens exact verified source without replacing primary PDF or research',async()=>{
 const s=await setup(),before=await s.store.read();
 await assert.rejects(openLineageSource(s.engine,PAPER,s.row,s.source.id),/artifact_unavailable/);
 assert(!s.transport.calls.some(c=>c[0]==='blob'));
 const lease=await opened(s),delivered=await lineageSourceForDelivery(s.engine,lease);
 assert.deepEqual(delivered,bytes);assert.equal(lease.sha256,await digest(bytes));
 const after=await s.store.read();assert.deepEqual(after.outbox,before.outbox);assert.deepEqual(after.entities,before.entities);
 assert.deepEqual(after.files,before.files);assert.deepEqual(projection(after).papers,projection(before).papers);
 delivered.fill(0);assert.deepEqual(await lineageSourceForDelivery(s.engine,lease),bytes);
});
test('verified original reopens offline without a network call',async()=>{
 const s=await setup();await opened(s);const calls=s.transport.calls.length;
 const offline=new Engine(s.store),lease=await openLineageSource(offline,PAPER,s.row,s.source.id);
 assert.deepEqual(await lineageSourceForDelivery(offline,lease),bytes);assert.equal(s.transport.calls.length,calls);
});
test('saved-only projection cannot grant original bytes even when matching cache exists',async()=>{
 const s=await setup();await opened(s);const before=await s.store.read();
 await s.store.update(state=>{state.readProjection={papers:projection(state).papers};state.entities={};state.graph={};});
 await assert.rejects(openLineageSource(s.engine,PAPER,s.row,s.source.id,{download:true}),/lineage_source_unavailable/);
 assert.deepEqual((await s.store.read()).artifactFiles,before.artifactFiles);
});
for(const change of ['source','paper','report'])test('known retirement blocks cached source and an existing lease: '+change,async()=>{
 const s=await setup(),lease=await opened(s);
 await s.store.update(state=>{const key=change==='source'?'research_file/'+s.file.entity_id:change==='paper'?'paper/'+PAPER:'research_content/'+s.science.entity_id;state.graph[key].active=false;});
 await assert.rejects(lineageSourceForDelivery(s.engine,lease),/lineage_source_unavailable/);
 await assert.rejects(openLineageSource(s.engine,PAPER,s.row,s.source.id),/lineage_source_unavailable/);
});
test('same hash with a new source incarnation does not reactivate the old report',async()=>{
 const s=await setup(),lease=await opened(s);
 await s.store.update(state=>{state.graph['research_file/'+s.file.entity_id].incarnation='restored-original';});
 await assert.rejects(lineageSourceForDelivery(s.engine,lease),/lineage_source_unavailable/);
});
for(const change of ['account','view','cancel'])test('delayed source completion cannot enter changed scope: '+change,async()=>{
 const s=await setup();await opened(s);let release,started;
 const hold=new Promise(r=>release=r),admitted=new Promise(r=>started=r),read=s.engine.originalSource.bind(s.engine);
 s.engine.originalSource=async id=>{const result=await read(id);started();await hold;return result;};
 let current=true;const controller=new AbortController();
 const pending=openLineageSource(s.engine,PAPER,s.row,s.source.id,{current:()=>current,signal:controller.signal});
 await admitted;if(change==='account')s.engine.disconnect();if(change==='view')current=false;if(change==='cancel')controller.abort();release();
 await assert.rejects(pending,/cancelled|stale_lineage_scope/);
});
test('a changed source operation between verification and delivery rejects stale bytes',async()=>{
 const s=await setup(),lease=await opened(s),changed={...s.file,operation_id:'updated-source',base_revision:2};
 await s.store.update(state=>receive(state,[event(changed,4)]));
 await assert.rejects(lineageSourceForDelivery(s.engine,lease),/stale_lineage_source/);
});
test('a changed report cannot reuse a prior saved row to open its source',async()=>{
 const s=await setup(),changed={...s.science,operation_id:'updated-report',base_revision:3,payload:structuredClone(s.science.payload)};
 changed.payload.data.written_at='2026-11-13T01:00:00+00:00';
 await s.store.update(state=>receive(state,[event(changed,4)]));
 await assert.rejects(openLineageSource(s.engine,PAPER,s.row,s.source.id),/stale_lineage_source/);
});
test('a lease cannot cross engine identities or be fabricated',async()=>{
 const s=await setup(),lease=await opened(s);
 await assert.rejects(lineageSourceForDelivery(new Engine(s.store),lease),/stale_lineage_scope/);
 await assert.rejects(lineageSourceForDelivery(s.engine,{...lease}),/stale_lineage_scope/);
});
test('corrupt cached original remains an error and never triggers a replacement download',async()=>{
 const s=await setup();await opened(s);const calls=s.transport.calls.length;
 await s.store.update(state=>state.artifactFiles[s.source.document_hash].chunks[0].fill(0));
 await assert.rejects(openLineageSource(s.engine,PAPER,s.row,s.source.id,{download:true}),/corrupt_file/);
 assert.equal(s.transport.calls.length,calls);
});

test('pending local source retirement refuses cached bytes before remote acceptance',async()=>{
 const s=await setup(),lease=await opened(s);
 await s.store.update(state=>enqueue(state,{...s.file,device_id:'demo-phone',operation_id:'local-retirement',action:'delete',payload:{},base_revision:2}));
 assert.equal(lineageSourceAvailable(await s.store.read(),PAPER,s.row,s.source.id),false);
 await assert.rejects(lineageSourceForDelivery(s.engine,lease),/lineage_source_unavailable/);
});

test('a selected peer opens its own exact original, never the focal bytes',async()=>{
 const s=await setup(),peer='33333333-3333-4333-8333-333333333333',peerBytes=new Uint8Array([...bytes,10]);
 const hash=await digest(peerBytes),row=structuredClone(s.row),source={...structuredClone(s.source),identity:{...s.source.identity,title:'Selected peer original'},document_hash:hash};
 source.id=claimHash(['lineage-source.v1',source.identity,hash]);row.body.report.sources.push(source);row.body.corpus_id='44444444-4444-4444-8444-444444444444';
 row.body.bindings.push({source_id:source.id,paper_id:peer});delete row.body.report.id;row.body.report.id=claimHash(row.body.report);row.source_hash=lineageSourceHash(row.body);
 const body=new TextEncoder().encode(stable({version:1,paper_id:peer,document_hash:hash})),bodyHash=await digest(body);
 const parent=operation('paper',peer,{...s.transport.state.entities['paper/'+PAPER].operation.payload,title:source.identity.title});
 const payload={...structuredClone(s.file.payload),paper_id:peer,slot:hash,source_document_hash:hash,
  body:{sha256:bodyHash,size:body.length,media_type:'application/json'},assets:[{id:'original',role:'original_pdf',sha256:hash,size:peerBytes.length,media_type:'application/pdf'}]};
 const file=operation('research_file',sourceFileId(peer,hash),payload,{parents:[ref('paper',peer)]});
 const science={...s.science,entity_id:contentId({kind:'paper',id:PAPER},'lineage',row.body.corpus_id),content_address:{feature:'lineage',key:row.body.corpus_id},operation_id:'selected-peer-report',incarnation:'selected-peer-report',base_revision:0,parents:[...s.science.parents,ref('paper',peer)],
  payload:{...s.science.payload,key:row.body.corpus_id,data:{...s.science.payload.data,body_json:row.body,source_hash:row.source_hash}},
  source_dependencies:[...s.science.source_dependencies,{source_id:source.id,paper_id:peer,file_id:file.entity_id,incarnation:file.incarnation}]};
 s.transport.blobs.set(hash,peerBytes);s.transport.blobs.set(bodyHash,body);
 for(const op of [parent,file,science])assert.equal((await s.transport.push('fixture-token',{...op,device_id:'demo-phone'})).outcome,'accepted');
 await s.engine.sync();const lease=await openLineageSource(s.engine,PAPER,row,source.id,{download:true});
 const actual=await lineageSourceForDelivery(s.engine,lease);assert.deepEqual(actual,peerBytes);assert.notDeepEqual(actual,bytes);
 assert.equal(lease.sha256,hash);assert.deepEqual((await s.store.read()).files,{});assert.equal(projection(await s.store.read()).papers.find(p=>p.id===PAPER).lineage.length,2);
 await primary(s);const prepared=await s.engine.prepareOffline(PAPER);
 assert.equal(prepared.ready,true);assert.equal(prepared.total_targets,3);
 const offline=new Engine(s.store),cached=await openLineageSource(offline,PAPER,row,source.id);
 assert.deepEqual(await lineageSourceForDelivery(offline,cached),peerBytes);
 assert.equal(Object.keys((await s.store.read()).files).length,1);
});


async function primary(s) {
 const doc=operation('paper_document',PAPER,{paper_id:PAPER,sha256:await digest(bytes),
  size:bytes.length,media_type:'application/pdf'},{operationId:'offline-reading-primary',parents:[ref('paper',PAPER)]});
 assert.equal((await s.transport.push('fixture-token',{...doc,device_id:'demo-phone'})).outcome,'accepted');
 await s.engine.sync();
}
test('one offline-reading action verifies primary and pinned originals, deduplicates and reopens offline',async()=>{
 const s=await setup();await primary(s);const before=await s.store.read(),events=[];
 s.engine.onChange=(code,value)=>events.push([code,value]);
 const first=s.engine.prepareOffline(PAPER);
 assert.equal(s.engine.prepareOffline(PAPER),first);
 const result=await first;
 assert.equal(result.ready,true);assert.equal(result.verified_targets,2);
 assert.equal(result.total_targets,2);assert.equal(result.whole_workspace_offline_verified,false);
 const after=await s.store.read();
 assert.deepEqual(after.entities,before.entities);assert.deepEqual(after.outbox,before.outbox);
 assert.deepEqual(after.receipts,before.receipts);assert.equal(after.cursor,before.cursor);
 const lease=await openLineageSource(s.engine,PAPER,s.row,s.source.id);
 assert.deepEqual(await lineageSourceForDelivery(s.engine,lease),bytes);
 assert.equal(events.at(-1)[0],'reading_ready');
 assert(events.filter(([code])=>code==='reading_preparing').every(([,p])=>p.completed<=p.total));
 const calls=s.transport.calls.length,offline=new Engine(s.store);
 assert.equal((await offline.prepareOffline(PAPER)).ready,true);
 assert.equal(s.transport.calls.length,calls);
});
for(const change of ['paper','account','abort'])test('offline reading refuses a late result after '+change,async()=>{
 const s=await setup();await primary(s);const before=await s.store.read(),events=[];
 let release,started;const hold=new Promise(r=>release=r),admitted=new Promise(r=>started=r);
 const read=s.transport.blob_read.bind(s.transport);let current=true;
 s.transport.blob_read=async(...args)=>{const data=await read(...args);started();await hold;return data;};
 s.engine.onChange=code=>events.push(code);const controller=new AbortController();
 const pending=s.engine.prepareOffline(PAPER,{current:()=>current,signal:controller.signal});
 await admitted;
 if(change==='paper')current=false;if(change==='account')s.engine.disconnect();
 if(change==='abort')controller.abort();release();
 await assert.rejects(pending,/cancelled|stale_reading/);
 assert.deepEqual((await s.store.read()).files,before.files);
 assert(!events.includes('reading_ready'));
});
test('failed offline reading retains verified primary and retries sources without another PDF read',async()=>{
 const s=await setup();await primary(s);const read=s.transport.blob_read.bind(s.transport);let calls=0;
 s.transport.blob_read=async(...args)=>{if(++calls===2)throw Error('fixture_offline');return read(...args);};
 await assert.rejects(s.engine.prepareOffline(PAPER),/fixture_offline/);
 assert.deepEqual((await s.engine.pdf(PAPER)).bytes,bytes);
 s.transport.blob_read=read;const start=s.transport.calls.length;
 assert.equal((await s.engine.prepareOffline(PAPER)).ready,true);
 const later=s.transport.calls.slice(start).filter(call=>call[0]==='blob');
 assert(later.length>0);assert(later.length<3);
});
test('snapshot-only Lineage stays partial and cannot mint original access',async()=>{
 const s=await setup();await primary(s);
 await s.store.update(state=>{state.readProjection={papers:[{id:PAPER,lineage:[s.row]}]};
  delete state.entities['research_content/'+s.science.entity_id];delete state.graph['research_content/'+s.science.entity_id];});
 const result=await s.engine.prepareOffline(PAPER);
 assert.equal(result.ready,false);assert.equal(result.total_targets,1);
 assert(result.warnings.some(item=>item.reason==='unverified_snapshot_source'));
 assert.deepEqual((await s.store.read()).artifactFiles,{});
});


for(const change of ['document','source','report'])test('metadata changes invalidate the complete offline-reading scope: '+change,async()=>{
 const s=await setup();await primary(s);let release,started;
 const hold=new Promise(r=>release=r),admitted=new Promise(r=>started=r),read=s.transport.blob_read.bind(s.transport);
 s.transport.blob_read=async(...args)=>{const data=await read(...args);started();await hold;return data;};
 const pending=s.engine.prepareOffline(PAPER);await admitted;
 await s.store.update(state=>{
  const old=change==='source'?s.file:change==='report'?s.science:state.entities['paper_document/'+PAPER].operation;
  const changed={...structuredClone(old),operation_id:'reading-'+change+'-updated',
    base_revision:change==='source'?2:change==='report'?3:4};
  if(change==='report')changed.payload.data.written_at='2026-11-15T01:00:00+00:00';
  receive(state,[event(changed,5)]);
 });release();
 await assert.rejects(pending,/stale_reading|stale_document|stale_artifact/);
 assert.deepEqual((await s.store.read()).files,{});
});
