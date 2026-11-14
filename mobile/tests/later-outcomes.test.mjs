import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {validateLaterBody,laterOutcomeText} from '../later-outcomes.mjs';
import {validateContent,validateContentTimestamp,initialAnnotationDeletion,suppressSnapshotContent} from '../content.mjs';
import {validateProjection} from '../domain.mjs';
import {Engine} from '../engine.mjs';
import {MemoryStore} from '../store.mjs';
import * as old from './fixtures/pre-position-domain.mjs';
import {contentId} from '../ids.mjs';
import {operation,ref,PAPER} from '../fixture.mjs';
import {SHELL,cacheable} from '../sw-policy.mjs';
const stamp='2026-11-01T00:00:00+00:00',hash='b'.repeat(64);
function body(available=false){return {format:'paperfact.later-outcome.v1',state:'queried_no_judged_inputs',policy:'followups.empty-query.v1',input_hash:'a'.repeat(64),query:{request_id:'11111111-1111-4111-8111-111111111111',queried_at:stamp,lookup:{title:'Paper',doi:null,s2_id:null,arxiv_id:null},providers:{openalex:'queried_empty',semantic_scholar:'unknown'}},source:{availability:available?'available':'unavailable',document_hash:available?hash:null,desired_hash:null}};}
function value(available=false){return {body:body(available),document_hash:available?hash:null,written_at:stamp};}
function payload(available=false){const v=value(available);return {scope:{kind:'paper',id:PAPER},feature:'later_outcome',key:'main',source_document_hash:v.document_hash,data:{body_json:v.body,document_hash:v.document_hash,written_at:stamp}};}
function snapshot(){const v=JSON.parse(readFileSync(new URL('../../tests/fixtures/reading-position-snapshot.json',import.meta.url),'utf8'));v.papers[0].later_outcome=value(true);v.required_capabilities=['inbox','later_outcome','queue_pin','reading_position'];return v;}
for(const available of [false,true])test('closed later content and source-separated neutral text '+available,()=>{
 const p=payload(available),id=contentId(p.scope,p.feature,p.key),parents=[ref('paper',PAPER)];
 assert.doesNotThrow(()=>validateContent(p,id,parents));
 for(const lang of ['en','zh-TW']){const text=laterOutcomeText(value(available),lang,available?hash:null);assert(text.length>12);assert(!text.includes('\u2713'));}
 assert.match(laterOutcomeText(value(true),'en','c'.repeat(64)),/another original version/);
 assert.match(laterOutcomeText(value(true),'en',null),/not currently loaded or verified/);
 assert.match(laterOutcomeText(value(false),'en',hash),/predates the available original/);
});
for(const change of ['future','unknown-query','failed-query','missing-hash','extra','huge','naive-time','string-body','wrong-envelope'])test('malformed outcome refuses '+change,()=>{
 const p=payload(true),b=p.data.body_json;
 if(change==='future')b.state='future';
 if(change==='unknown-query')b.query.providers.openalex='unknown';
 if(change==='failed-query')b.query.providers.openalex='failed';
 if(change==='missing-hash')b.source.document_hash=null;
 if(change==='extra')b.summary='fake';
 if(change==='huge')b.query.lookup.title='x'.repeat(32769);
 if(change==='naive-time')b.query.queried_at='2026-11-01';
 if(change==='string-body')p.data.body_json=JSON.stringify(b);
 if(change==='wrong-envelope')p.source_document_hash='c'.repeat(64);
 assert.throws(()=>validateContent(p,contentId(p.scope,p.feature,p.key),[ref('paper',PAPER)]));
});
test('four actual capabilities persist as read-only projection without cursor/outbox mutation',async()=>{
 const v=snapshot(),store=new MemoryStore(v.workspace_id,'phone'),engine=new Engine(store);
 await engine.importProjection(v);const state=await store.read();
 assert.deepEqual(state.readProjection.required_capabilities,['inbox','later_outcome','queue_pin','reading_position']);
 assert.deepEqual(state.readProjection.papers[0].later_outcome,v.papers[0].later_outcome);
 assert.equal(state.cursor,0);assert.deepEqual(state.outbox,[]);
});
for(const change of ['missing','unknown','duplicate','unsorted','unused','body'])test('invalid capability/body import is atomic '+change,async()=>{
 const v=snapshot();if(change==='missing')v.required_capabilities.splice(1,1);if(change==='unknown')v.required_capabilities.push('future');if(change==='duplicate')v.required_capabilities.push('later_outcome');if(change==='unsorted')v.required_capabilities.reverse();if(change==='unused')delete v.papers[0].later_outcome;if(change==='body')v.papers[0].later_outcome.body.query.providers.openalex='unknown';
 const store=new MemoryStore(v.workspace_id,'phone'),engine=new Engine(store);await store.update(s=>{s.drafts.note='Keep draft';});const before=await store.read();
 await assert.rejects(engine.importProjection(v));assert.deepEqual(await store.read(),before);
});
test('old receiver rejects new required capability before write; no-outcome snapshot remains compatible',async()=>{
 const v=snapshot(),store=new MemoryStore(v.workspace_id,'old-phone'),before=await store.read();
 await assert.rejects(store.update(s=>{s.readProjection=old.validateProjection(v,v.workspace_id);}));assert.deepEqual(await store.read(),before);
 const plain={schema_version:1,workspace_id:'old-workspace',cursor:0,capabilities:{sync_bootstrap:false},local_state:{},lists:[],papers:[],notes:[],highlights:[],decks:[],assets:[]};
 assert.deepEqual(validateProjection(plain,plain.workspace_id),old.validateProjection(plain,plain.workspace_id));
});
test('initial exact typed tombstone suppresses stale snapshot, foreign incarnation never does',()=>{
 const parent=operation('paper',PAPER,{title:'Paper',authors:[],year:null,venue:null,abstract:null,doi:null,arxiv_id:null,s2_id:null,page_url:null,pdf_url:null,source:null});
 const op=operation('research_content',contentId({kind:'paper',id:PAPER},'later_outcome','main'),{},{parents:[ref('paper',PAPER)],action:'delete'});
 const event=(operation,sequence)=>({sequence,outcome:'accepted',operation,head:{revision:sequence,operation}}),heads=[event(parent,1),event(op,2)];
 assert.equal(initialAnnotationDeletion(op,heads).feature,'later_outcome');
 const papers=[{id:PAPER,later_outcome:value()}];suppressSnapshotContent(papers,[],heads,[],[]);assert(!Object.hasOwn(papers[0],'later_outcome'));
 assert.equal(initialAnnotationDeletion({...op,parents:[ref('paper',PAPER,'other-incarnation')]},heads),null);
 assert.equal(initialAnnotationDeletion({...op,entity_id:contentId({kind:'paper',id:PAPER},'future','main')},heads),null);
});
test('new static dependency is exact offline shell member; dynamic/private URLs stay excluded',()=>{
 const scope='https://example.org/mobile/',url=scope+'later-outcomes.mjs';assert(SHELL.includes('./later-outcomes.mjs'));
 assert(cacheable(new Request(url),scope));assert(!cacheable(new Request(url+'?private=1'),scope));assert(!cacheable(new Request(url,{headers:{Authorization:'Bearer fake'}}),scope));
 assert.match(readFileSync(new URL('../sw.mjs',import.meta.url),'utf8'),/paperfact-mobile-shell-v19/);
 for(const path of SHELL)if(!path.includes('/vendor/'))assert.doesNotThrow(()=>readFileSync(new URL(path==='./'?'../index.html':'../'+path.slice(2),import.meta.url)));
 assert.doesNotThrow(()=>validateLaterBody(body(),validateContentTimestamp));
});

for(const language of ['en','zh-TW'])test('recorded timestamp and readable provider status '+language,()=>{
 for(const [v,loaded] of [[value(true),hash],[value(true),null],[value(true),'c'.repeat(64)],[value(false),null],[value(false),hash]]){
  const text=laterOutcomeText(v,language,loaded);assert(text.includes(stamp));
  assert(text.includes('OpenAlex:')&&text.includes('Semantic Scholar:'));
  assert(!text.includes('queried_empty')&&!text.includes('unknown')&&!text.includes('\u2713'));
  if(language==='en')assert(text.includes('queried, no results')&&text.includes('not established'));
  else assert(text.includes('\u5df2\u67e5\u8a62\uff0c\u7121\u7d50\u679c')&&text.includes('\u5c1a\u672a\u78ba\u8a8d'));
 }
});
