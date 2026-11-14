import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {lineageRow,PAPER} from './fixtures/lineage-data.mjs';
import {contentId} from '../ids.mjs';
import {sourceFileId} from '../artifacts.mjs';
import {validateOperation,receive,projection,active,enqueue} from '../domain.mjs';
import {emptyState,MemoryStore} from '../store.mjs';
import {Engine} from '../engine.mjs';
import {translator} from '../i18n.mjs';
import {claimHash} from '../claims.mjs';
import {lineageSourceHash} from '../lineage.mjs';
import {operation,ref} from '../fixture.mjs';
import {SHELL} from '../sw-policy.mjs';
import * as old from './fixtures/pre-position-domain.mjs';
const WORKSPACE='demo-workspace';
function paper(){return operation('paper',PAPER,{title:'Synthetic focal paper',authors:[],year:2026,venue:'Fixture',abstract:null,doi:null,arxiv_id:null,s2_id:null,page_url:null,pdf_url:null,source:'fixture'});}
function original(){
 const sha='a'.repeat(64),body='b'.repeat(64),id=sourceFileId(PAPER,sha);
 const payload={paper_id:PAPER,feature:'original_source',slot:sha,format_version:1,source_document_hash:sha,input_versions:{schema_version:1,complete:false,entities:[],documents:[],inputs_sha256:null},body:{sha256:body,size:160,media_type:'application/json'},assets:[{id:'original',role:'original_pdf',sha256:sha,size:256,media_type:'application/pdf'}]};
 return operation('research_file',id,payload,{parents:[ref('paper',PAPER)]});
}
function lineage(){
 const row=lineageRow(),{body,source_hash,document_hash,written_at}=row;
 const payload={scope:{kind:'paper',id:PAPER},feature:'lineage',key:body.corpus_id,source_document_hash:document_hash,data:{body_json:body,source_hash,document_hash,written_at}};
 const id=contentId(payload.scope,'lineage',body.corpus_id),file=original();
 return {...operation('research_content',id,payload,{parents:[ref('paper',PAPER)]}),content_address:{feature:'lineage',key:body.corpus_id},source_dependencies:[{source_id:body.report.sources[0].id,paper_id:PAPER,file_id:file.entity_id,incarnation:file.incarnation}]};
}
function accepted(op,sequence){return {sequence,outcome:'accepted',operation:structuredClone(op),head:{revision:sequence,operation:structuredClone(op)}};}
function initial(){const state=emptyState(WORKSPACE,'phone');receive(state,[accepted(paper(),1),accepted(original(),2),accepted(lineage(),3)]);return state;}
function retire(file=original()){return {...file,action:'delete',payload:{},operation_id:'retire-source',base_revision:2};}
function restore(file=original()){return {...file,operation_id:'restore-source',incarnation:'restore-source',base_revision:4};}

test('accepted exact scientific content reaches the existing read-only cards without file grants',()=>{
 const state=initial(),view=projection(state),row=lineageRow();
 assert.deepEqual(view.papers[0].lineage,[row]);
 assert.equal(state.cursor,3);assert.equal(state.outbox.length,0);assert.deepEqual(state.artifactFiles,{});assert.deepEqual(state.appliedArtifacts,{});
 assert.deepEqual(state.graph['research_content/'+lineage().entity_id].content_address,lineage().content_address);
 assert.equal(view.papers[0].lineage[0].body.report.statements[0].judgment.status,'unresolved');
 view.papers[0].lineage[0].body.report.statements[0].text='UI copy';
 assert.deepEqual(state.entities['research_content/'+lineage().entity_id].operation.payload,lineage().payload);
 receive(state,[accepted(lineage(),3)]);assert.equal(Object.keys(state.receipts).length,3);
});
for(const change of ['missing-address','unknown-address','missing-pins','extra-pins','wrong-source','wrong-owner','wrong-file','bad-incarnation','reordered-parent','extra-parent','scope','key','body-hash','source-hash','document-hash','untyped-delete','pins-on-delete','extra-envelope','naive-time'])test('closed Lineage operation rejects '+change,()=>{
 const op=lineage();
 if(change==='missing-address')delete op.content_address;
 if(change==='unknown-address')op.content_address.feature='future';
 if(change==='missing-pins')delete op.source_dependencies;
 if(change==='extra-pins')op.source_dependencies.push(structuredClone(op.source_dependencies[0]));
 if(change==='wrong-source')op.source_dependencies[0].source_id='c'.repeat(64);
 if(change==='wrong-owner')op.source_dependencies[0].paper_id='22222222-2222-4222-8222-222222222222';
 if(change==='wrong-file')op.source_dependencies[0].file_id=PAPER;
 if(change==='bad-incarnation')op.source_dependencies[0].incarnation='contains whitespace';
 if(change==='reordered-parent')op.parents[0].id='22222222-2222-4222-8222-222222222222';
 if(change==='extra-parent')op.parents.push(structuredClone(op.parents[0]));
 if(change==='scope')op.payload.scope.id='22222222-2222-4222-8222-222222222222';
 if(change==='key')op.payload.key=PAPER;
 if(change==='body-hash')op.payload.data.body_json.report.id='c'.repeat(64);
 if(change==='source-hash')op.payload.data.source_hash='c'.repeat(64);
 if(change==='document-hash')op.payload.data.document_hash='c'.repeat(64);
 if(change==='untyped-delete'){op.action='delete';op.payload={};delete op.content_address;}
 if(change==='pins-on-delete'){op.action='delete';op.payload={};}
 if(change==='extra-envelope')op.future='unknown';
 if(change==='naive-time')op.payload.data.written_at='2026-11-13';
 assert.throws(()=>validateOperation(op,WORKSPACE));
});

test('file retirement hides the report and same-hash restoration cannot revive its old pin',()=>{
 const state=initial(),science=structuredClone(state.entities['research_content/'+lineage().entity_id]);
 receive(state,[accepted(retire(),4)]);assert.equal(active(state,'research_content',lineage().entity_id),false);
 assert.deepEqual(projection(state).papers[0].lineage,[]);
 receive(state,[accepted(restore(),5)]);assert.deepEqual(projection(state).papers[0].lineage,[]);
 assert.deepEqual(state.entities['research_content/'+lineage().entity_id],science);
 const revised=lineage();revised.operation_id='rechecked-lineage';revised.base_revision=3;revised.source_dependencies[0].incarnation='restore-source';
 receive(state,[accepted(revised,6)]);assert.deepEqual(projection(state).papers[0].lineage,[lineageRow()]);
});

test('typed deletion works after source retirement and retains immutable put history',()=>{
 const state=initial(),op={...lineage(),action:'delete',payload:{},source_dependencies:[],operation_id:'retire-lineage',base_revision:3};
 receive(state,[accepted(retire(),4),accepted(op,5)]);
 assert.deepEqual(projection(state).papers[0].lineage,[]);
 assert.deepEqual(state.receipts[lineage().operation_id].operation,lineage());
 assert.equal(state.cursor,5);
});

test('known one-parent typed address cannot be stripped by a generic empty deletion',async()=>{
 const state=initial(),store=new MemoryStore(WORKSPACE,'phone',state),before=await store.read();
 const op={...lineage(),action:'delete',payload:{},operation_id:'stripped-retirement'};
 delete op.content_address;delete op.source_dependencies;
 assert.doesNotThrow(()=>validateOperation(op,WORKSPACE));
 await assert.rejects(store.update(draft=>receive(draft,[accepted(op,4)])),/invalid_lineage/);
 assert.deepEqual(await store.read(),before);
 op.device_id='phone';assert.throws(()=>enqueue(state,op));assert.deepEqual(state,before);
});
for(const change of ['missing-file','deleted-file','restored-file','wrong-file-parent','changed-paper'])test('stale source accepted event is refused atomically '+change,async()=>{
 const state=initial();
 if(change==='missing-file')delete state.graph['research_file/'+original().entity_id];
 if(change==='deleted-file')state.graph['research_file/'+original().entity_id].active=false;
 if(change==='restored-file')state.graph['research_file/'+original().entity_id].incarnation='restored';
 if(change==='wrong-file-parent')state.graph['research_file/'+original().entity_id].parents[0].incarnation='other-parent';
 if(change==='changed-paper')state.graph['paper/'+PAPER].incarnation='other-parent';
 const store=new MemoryStore(WORKSPACE,'phone',state),before=await store.read(),op=lineage();op.operation_id='later-lineage';
 await assert.rejects(store.update(draft=>receive(draft,[accepted(op,4)])),/stale_lineage/);
 assert.deepEqual(await store.read(),before);
});

test('known scientific incarnation cannot change through an unrequested active restore or stale retirement',()=>{
 for(const action of ['put','delete']){
  const state=initial(),before=structuredClone(state),op={...lineage(),action,operation_id:'changed-incarnation',incarnation:'changed-incarnation'};
  if(action==='delete'){op.payload={};op.source_dependencies=[];}
  assert.throws(()=>receive(state,[accepted(op,4)]),/changed_lineage_incarnation/);assert.deepEqual(state,before);
 }
});

test('live corpus retirement suppresses the matching saved snapshot without mutating it',()=>{
 const state=initial();state.readProjection={papers:[{id:PAPER,lineage:[lineageRow()]}],highlights:[],notes:[]};
 const before=structuredClone(state.readProjection),op={...lineage(),action:'delete',payload:{},source_dependencies:[],operation_id:'retire-lineage'};
 receive(state,[accepted(op,4)]);assert.deepEqual(projection(state).papers[0].lineage,[]);assert.deepEqual(state.readProjection,before);
});

test('newer consumer rejects malformed pages before any cursor, draft or outbox changes',async()=>{
 const store=new MemoryStore(WORKSPACE,'phone');await store.update(s=>{s.drafts.note='Keep this draft';});
 const before=await store.read(),bad=lineage();delete bad.source_dependencies;
 await assert.rejects(store.update(s=>receive(s,[accepted(paper(),1),accepted(original(),2),accepted(bad,3)])));
 assert.deepEqual(await store.read(),before);
});

test('mobile shell carries its new receiver and old consumers reject typed Lineage',()=>{
 assert(SHELL.includes('./lineage-ops.mjs'));assert.match(readFileSync(new URL('../sw.mjs',import.meta.url),'utf8'),/paperfact-mobile-shell-v19/);
 assert.throws(()=>old.validateOperation(lineage(),WORKSPACE));
});

test('engine foreground sync persists scientific updates without invoking a model or downloading PDF bytes',async()=>{
 const {FixtureTransport}=await import('../fixture.mjs');
 const events=[accepted(paper(),1),accepted(original(),2),accepted(lineage(),3)];
 const transport=new FixtureTransport({workspace:WORKSPACE,device:'phone',events}),store=new MemoryStore(WORKSPACE,'phone'),engine=new Engine(store,{transport});
 await engine.connect('fixture-token');const first=engine.sync();assert.strictEqual(engine.sync(),first);await first;await engine.sync();const state=await store.read();
 assert.deepEqual(projection(state).papers[0].lineage,[lineageRow()]);assert.deepEqual(state.files,{});assert.deepEqual(state.artifactFiles,{});
 assert.equal(state.cursor,3);engine.disconnect();
});


test('four selected sources require all ordered pins while unavailable peers require none',()=>{
 const op=lineage(),body=op.payload.data.body_json;
 for(let i=2;i<=4;i++){
  const paper=`${i}`.repeat(8)+'-'+`${i}`.repeat(4)+'-4'+`${i}`.repeat(3)+'-8'+`${i}`.repeat(3)+'-'+`${i}`.repeat(12),hash=`${i}`.repeat(64);
  const identity={title:'Selected peer '+i,doi:null,arxiv_id:null,s2_id:null};
  const source={id:claimHash(['lineage-source.v1',identity,hash]),identity,identity_authority:'selected_workspace_record',document_hash:hash,availability:'available',page_count:1};
  body.report.sources.push(source);body.bindings.push({source_id:source.id,paper_id:paper});op.parents.push(ref('paper',paper));
  op.source_dependencies.push({source_id:source.id,paper_id:paper,file_id:sourceFileId(paper,hash),incarnation:paper+'-source'});
 }
 const {id,...r}=body.report;body.report.id=claimHash(r);op.payload.data.source_hash=lineageSourceHash(body);
 assert.doesNotThrow(()=>validateOperation(op,WORKSPACE));
 const wrong=structuredClone(op);wrong.source_dependencies.reverse();assert.throws(()=>validateOperation(wrong,WORKSPACE));
 const unavailable=body.report.sources.at(-1);unavailable.document_hash=null;unavailable.availability='unavailable';unavailable.page_count=null;
 unavailable.id=claimHash(['lineage-source.v1',unavailable.identity,null]);body.bindings.at(-1).source_id=unavailable.id;
 const {id:oldId,...next}=body.report;body.report.id=claimHash(next);op.payload.data.source_hash=lineageSourceHash(body);
 assert.throws(()=>validateOperation(op,WORKSPACE));op.source_dependencies.pop();assert.doesNotThrow(()=>validateOperation(op,WORKSPACE));
});

test('closing a held foreground receive preserves local drafts and never installs late science',async()=>{
 const {FixtureTransport}=await import('../fixture.mjs');
 const transport=new FixtureTransport({workspace:WORKSPACE,device:'phone',events:[accepted(paper(),1),accepted(original(),2),accepted(lineage(),3)]});
 let release,enter;const held=new Promise(r=>{release=r;}),entered=new Promise(r=>{enter=r;}),pull=transport.pull.bind(transport);
 transport.pull=async(...args)=>{enter();await held;return pull(...args);};
 const store=new MemoryStore(WORKSPACE,'phone'),engine=new Engine(store,{transport});await store.update(s=>{s.drafts.note='Keep draft';});
 await engine.connect('fixture-token');const before=await store.read(),running=engine.sync();await entered;
 engine.disconnect();release();await assert.rejects(running);assert.deepEqual(await store.read(),before);
});

test('Lineage receive errors have clear text in both languages without encoding replacements',()=>{
 for(const lang of ['en','zh-TW'])for(const code of ['invalid_lineage_operation','stale_lineage_parent','stale_lineage_source','changed_lineage_address','changed_lineage_parents','changed_lineage_incarnation']){
  const text=translator(lang)(code);assert.notEqual(text,code);assert(!text.includes('?'));assert(!text.includes('\uFFFD'));
 }
});
