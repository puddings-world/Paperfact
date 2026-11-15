import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {claimHash,normalizeClaimText} from '../claims.mjs';
import {artifactJSON,listFileId,sourceFileId,validateArtifact} from '../artifacts.mjs';
import {validateSurveyBody} from '../survey-artifacts.mjs';
import {digest} from '../artifact-engine.mjs';
import {projection,stable,validateOperation,receive} from '../domain.mjs';
import {MemoryStore} from '../store.mjs';
import {Engine} from '../engine.mjs';
import {demoTransport,operation,PAPER,ref} from '../fixture.mjs';
import {SHELL} from '../sw-policy.mjs';
const bytes=value=>new TextEncoder().encode(typeof value==='string'?value:stable(value));
const golden=JSON.parse(readFileSync(new URL('../../tests/fixtures/original-source.json',import.meta.url),'utf8'));
async function fixture(){
  const source=structuredClone(golden.payload);source.paper_id=PAPER;
  const original=bytes({version:1,paper_id:PAPER,document_hash:source.slot});
  source.body={sha256:await digest(original),size:original.length,media_type:'application/json'};
  const pin={source_id:claimHash(['survey-source.v1','local-input','a'.repeat(32),source.slot]),
    paper_id:PAPER,paper_incarnation:PAPER+'-created',document_hash:source.slot,
    file_id:sourceFileId(PAPER,source.slot),incarnation:'survey-source'};
  const text='A retained interpretation for review.';
  const report={format:'paperfact.survey-evidence.v1',recipe:'list-survey-sources.v1',
    inputs:{list_id:'demo-list',list_name:'A field',list_lifecycle:'b'.repeat(32),prompt_hash:'c'.repeat(64),
      members:[{paper_id:'local-input',paper_lifecycle:'a'.repeat(32),position:0,input_hash:'d'.repeat(64),title:'Input'},
        {paper_id:'unavailable-input',paper_lifecycle:'d'.repeat(32),position:1,input_hash:'e'.repeat(64),title:'Missing original'}]},
    generation:{task:'survey',backend:'codex',requested_model:'fixture',returned_model:null},
    sources:[{id:pin.source_id,paper_id:'local-input',paper_lifecycle:'a'.repeat(32),
      document_hash:source.slot,page_count:1,state:'captured'},
      {id:claimHash(['survey-source.v1','unavailable-input','d'.repeat(32),null]),paper_id:'unavailable-input',
        paper_lifecycle:'d'.repeat(32),document_hash:null,page_count:null,state:'unavailable'}],
    sections:[{heading:'Field',statements:[{id:claimHash(['survey-statement.v1',0,0,normalizeClaimText(text)]),
      text,interpretation:'inference',passages:[{source_id:pin.source_id,quote:'A quote',location:null}]}]}],
    source_check:'quote_location_only',semantic_validation:'not_performed',
    body_hash:await digest(bytes('## Field\n\n'+text))};
  report.id=await digest(bytes(report));
  const body={format:'paperfact.survey-artifact.v1',list_id:'demo-list',report},raw=bytes(body);
  const payload={list_id:'demo-list',feature:'survey',slot:'overview',format_version:1,source_document_hash:null,
    input_versions:{schema_version:2,workspace_id:'demo-workspace',complete:false,documents:[],
      inputs_sha256:report.inputs.prompt_hash,entities:[
        ['list','demo-list','demo-list-created'],['paper',PAPER,PAPER+'-created'],
        ['research_file',pin.file_id,pin.incarnation]].map(([kind,id,incarnation])=>({kind,id,incarnation,revision:0,depends_on:null}))},
    source_bindings:[pin],body:{sha256:await digest(raw),size:raw.length,media_type:'application/json'},assets:[]};
  return {source,pin,payload,body,raw,original};
}
async function setup(){
  const item=await fixture(),transport=await demoTransport(),store=new MemoryStore('demo-workspace','demo-phone');
  const engine=new Engine(store,{transport});await engine.connect('fixture-token');await engine.sync();
  const source=operation('research_file',item.pin.file_id,item.source,
    {operationId:'survey-source',device:'demo-phone',parents:[ref('paper',PAPER)]});
  assert.equal((await transport.push('fixture-token',source)).outcome,'accepted');
  const id=listFileId('demo-list');transport.blobs.set(item.payload.body.sha256,item.raw);
  const report=operation('research_file',id,item.payload,
    {operationId:'survey-report',device:'demo-phone',parents:[ref('list','demo-list')]});
  assert.equal((await transport.push('fixture-token',report)).outcome,'accepted');await engine.sync();
  return {item,transport,store,engine,id,report};
}
test('closed list artifact keeps native identity, owner, workspace and source lifetimes explicit',async()=>{
  const item=await fixture(),id=listFileId('demo-list');
  validateArtifact(item.payload,id,[ref('list','demo-list')]);
  assert(SHELL.includes('./survey-artifacts.mjs'));
  for(const mutate of [p=>p.paper_id=PAPER,p=>p.list_id='foreign',p=>p.source_bindings[0].paper_id='foreign',
    p=>p.source_bindings[0].incarnation='wrong',p=>p.assets.push({}),p=>p.body.size=1024*1024+1025]){
    const bad=structuredClone(item.payload);mutate(bad);assert.throws(()=>validateArtifact(bad,id));
  }
  const op=operation('research_file',id,item.payload,{parents:[ref('list','demo-list')]});
  op.payload.input_versions.workspace_id='foreign';assert.throws(()=>validateOperation(op,'demo-workspace'),/wrong_workspace/);
  const retired=operation('research_file',id,{}, {action:'delete',parents:[ref('list','demo-list')]});
  validateOperation(retired,'demo-workspace');retired.entity_id=item.pin.file_id;
  assert.throws(()=>validateOperation(retired,'demo-workspace'));
});
test('report digest, exact prose, missing source declarations and semantic scope cannot be substituted',async()=>{
  const item=await fixture();await validateSurveyBody(item.raw,artifactJSON(item.raw),item.payload);
  for(const mutate of [b=>b.report.sections[0].statements[0].text='Invented',b=>b.report.id='f'.repeat(64),
    b=>b.report.source_check='verified_semantics',b=>b.report.sources[0].document_hash='e'.repeat(64),
    b=>b.report.sections[0].statements[0].passages[0].source_id='unknown',b=>b.list_id='foreign']){
    const body=structuredClone(item.body);mutate(body);
    await assert.rejects(validateSurveyBody(bytes(body),body,item.payload));
  }
  const raw=bytes(stable(item.body).replace('"page_count":1','"page_count":1.0'));
  await assert.rejects(validateSurveyBody(raw,artifactJSON(raw),item.payload));
});
test('offline report is independent of original PDFs and corrupted cached bytes fail closed',async()=>{
  const s=await setup();assert.equal(projection(await s.store.read()).surveys[0].id,s.id);
  const first=s.engine.downloadArtifact(s.id);assert.equal(first,s.engine.downloadArtifact(s.id));await first;
  await assert.rejects(s.engine.originalSource(s.item.pin.file_id),/artifact_unavailable/);
  const saved=await s.store.read(),offline=new Engine(new MemoryStore('demo-workspace','demo-phone',saved));
  assert.equal((await offline.survey(s.id)).body.report.id,s.item.body.report.id);
  assert.equal((await offline.survey(s.id)).semantic_validation,'not_performed');
  assert.equal((await offline.survey(s.id)).body.report.sources[1].state,'unavailable');
  await s.store.update(next=>{next.artifactFiles[s.item.payload.body.sha256].chunks[0][1]^=1;});
  await assert.rejects(s.engine.survey(s.id),/corrupt_file/);
});
test('accepted stale-source forgery and delayed download after list retirement cannot change visible state',async()=>{
  const s=await setup(),before=await s.store.read(),bad=structuredClone(s.report);
  bad.operation_id='forged-accepted';bad.payload.source_bindings[0].incarnation='wrong-source';
  bad.payload.input_versions.entities.find(row=>row.kind==='research_file').incarnation='wrong-source';
  const event={sequence:before.cursor+1,outcome:'accepted',operation:bad,head:{revision:before.cursor+1,operation:bad}};
  await assert.rejects(s.store.update(next=>receive(next,[event])),/invalid_survey/);
  assert.deepEqual(await s.store.read(),before);
  const real=s.transport.blob_read.bind(s.transport);let started,release;
  const gate=new Promise(resolve=>{release=resolve;}),pending=new Promise(resolve=>{started=resolve;});
  s.transport.blob_read=async(...args)=>{const raw=await real(...args);started();await gate;return raw;};
  const job=s.engine.downloadArtifact(s.id);await pending;
  const graph=s.transport.state.graph['list/demo-list'],head=s.transport.state.entities['list/demo-list'];
  const retired=operation('list','demo-list',{}, {operationId:'retire-list',device:'demo-phone',action:'delete',
    incarnation:graph.incarnation,base:head.revision,structure:graph.structure_revision});
  assert.equal((await s.transport.push('fixture-token',retired)).outcome,'accepted');await s.engine.sync();release();
  await assert.rejects(job,/stale_artifact/);assert.deepEqual((await s.store.read()).appliedArtifacts,{});
  assert.deepEqual(projection(await s.store.read()).surveys,[]);
});

test('goal-aware recipe retains exact Unicode purpose and refuses silent v1 extension',async()=>{
  const item=await fixture();
  for(const goal of [null,'','Compare assumptions <script>literal goal</script>','\u{1f9ea}'.repeat(2000)]){
    const body=structuredClone(item.body),payload=structuredClone(item.payload);
    body.report.recipe='list-survey-sources.v2';body.report.inputs.goal=goal;
    delete body.report.id;body.report.id=await digest(bytes(body.report));
    await validateSurveyBody(bytes(body),body,payload);
    for(const invalid of [42,[],{},'x'.repeat(2001)]){
      const bad=structuredClone(body);bad.report.inputs.goal=invalid;delete bad.report.id;
      bad.report.id=await digest(bytes(bad.report));
      await assert.rejects(validateSurveyBody(bytes(bad),bad,payload));
    }
    const old=structuredClone(body);old.report.recipe='list-survey-sources.v1';delete old.report.id;
    old.report.id=await digest(bytes(old.report));
    await assert.rejects(validateSurveyBody(bytes(old),old,payload));
    const missing=structuredClone(body);delete missing.report.inputs.goal;delete missing.report.id;
    missing.report.id=await digest(bytes(missing.report));
    await assert.rejects(validateSurveyBody(bytes(missing),missing,payload));
  }
});
