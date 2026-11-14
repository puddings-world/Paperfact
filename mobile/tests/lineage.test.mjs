import test from 'node:test';
import assert from 'node:assert/strict';
import {claimHash,normalizeClaimText} from '../claims.mjs';
import {validateLineageBody,validateLineageProjection,lineageSourceHash} from '../lineage.mjs';
import {validateContentTimestamp} from '../content.mjs';
import {PAPER,CORPUS,lineageRow} from './fixtures/lineage-data.mjs';
function verify(row){return validateLineageProjection([row],PAPER,new Set([PAPER]),validateContentTimestamp);}
test('exact complete body and located passages round-trip without semantic certification',()=>{
 const row=lineageRow(),copy=verify(row);assert.deepEqual(copy,[row]);assert.notEqual(copy[0],row);
 assert.equal(copy[0].body.report.statements[0].requirements.semantic_validation,'not_performed');
 assert.equal(copy[0].body.report.statements[0].judgment.authority,'caller_proposal');
 assert.equal(validateLineageBody(row.body),row.body);
});
for(const change of ['extra','focal','owner','source-hash','document-hash','body-hash','naive-time','generation','scope','source-id','pages','passage-id','location','requirements','coverage','identity-authority','duplicate-source','oversize','empty-text'])test('closed saved Lineage rejects '+change,()=>{
 const row=lineageRow(),b=row.body,r=b.report,p=r.statements[0].passages[0];
 if(change==='extra')b.token='not-a-credential';
 if(change==='focal')r.focal='0'.repeat(64);
 if(change==='owner')b.bindings[0].paper_id=CORPUS;
 if(change==='source-hash')row.source_hash='0'.repeat(64);
 if(change==='document-hash')row.document_hash='0'.repeat(64);
 if(change==='body-hash')r.id='0'.repeat(64);
 if(change==='naive-time')row.written_at='2026-11-13';
 if(change==='generation')b.generation.task='future';
 if(change==='scope')r.verification_scope='current_sources';
 if(change==='source-id')r.sources[0].id='0'.repeat(64);
 if(change==='pages')r.sources[0].page_count=true;
 if(change==='passage-id')p.id='0'.repeat(64);
 if(change==='location')p.location.page=2;
 if(change==='requirements')r.statements[0].requirements.semantic_validation='passed';
 if(change==='coverage')r.coverage.prior_gap='proposed';
 if(change==='identity-authority')r.sources[0].identity_authority='verified';
 if(change==='duplicate-source')r.sources.push(structuredClone(r.sources[0]));
 if(change==='oversize')b.generation.requested_model='x'.repeat(513);
 if(change==='empty-text')r.statements[0].text='   ';
 assert.throws(()=>verify(row));
});
test('empty, duplicate and missing-owner corpus selections fail without mutating caller data',()=>{
 const row=lineageRow(),before=structuredClone(row);assert.throws(()=>validateLineageProjection([],PAPER,new Set([PAPER]),validateContentTimestamp));
 assert.throws(()=>validateLineageProjection([row,row],PAPER,new Set([PAPER]),validateContentTimestamp));
 assert.throws(()=>validateLineageProjection([row],PAPER,new Set(),validateContentTimestamp));
 assert.deepEqual(row,before);
});


import {validateProjection} from '../domain.mjs';
import {Engine} from '../engine.mjs';
import {MemoryStore} from '../store.mjs';
import * as old from './fixtures/pre-position-domain.mjs';
import {SHELL,cacheable} from '../sw-policy.mjs';
export function lineageSnapshot(){return {schema_version:2,workspace_id:'lineage-fixture',cursor:7,
 capabilities:{sync_bootstrap:false},local_state:{},lists:[],papers:[{id:PAPER,title:'Focal',authors:[],year:2026,doi:null,url:null,pdf_asset_id:null,analysis_sections:[],citations:[],lineage:[lineageRow()]}],notes:[],highlights:[],decks:[],assets:[],required_capabilities:['lineage']};}
test('read-only Lineage import retains complete science without cursor, graph, outbox or source grants',async()=>{
 const value=lineageSnapshot(),store=new MemoryStore(value.workspace_id,'phone'),engine=new Engine(store);
 await engine.importProjection(value);const state=await store.read();
 assert.deepEqual(state.readProjection.papers[0].lineage,value.papers[0].lineage);
 assert.equal(state.cursor,0);assert.deepEqual(state.entities,{});assert.deepEqual(state.outbox,[]);
 assert.deepEqual(state.graph,{});assert.deepEqual(state.readProjection.assets,[]);
});
for(const change of ['missing-capability','unused-capability','unknown-capability','duplicate-capability','schema-one','bad-body','empty-corpora','duplicate-corpora','unselected-peer','duplicate-paper','local-peer'])test('unsupported Lineage projection import is atomic '+change,async()=>{
 const value=lineageSnapshot();
 if(change==='duplicate-paper')value.papers.push(structuredClone(value.papers[0]));
 if(change==='local-peer')value.papers.push({id:'local-paper'});
 if(change==='missing-capability')delete value.required_capabilities;
 if(change==='unused-capability')delete value.papers[0].lineage;
 if(change==='unknown-capability')value.required_capabilities=['future','lineage'];
 if(change==='duplicate-capability')value.required_capabilities=['lineage','lineage'];
 if(change==='schema-one')value.schema_version=1;
 if(change==='bad-body')value.papers[0].lineage[0].body.report.statements[0].requirements.semantic_validation='passed';
 if(change==='empty-corpora')value.papers[0].lineage=[];
 if(change==='duplicate-corpora')value.papers[0].lineage.push(structuredClone(value.papers[0].lineage[0]));
 if(change==='unselected-peer')value.papers[0].lineage[0].body.bindings[0].paper_id='33333333-3333-4333-8333-333333333333';
 const store=new MemoryStore(value.workspace_id,'phone'),engine=new Engine(store);await store.update(s=>{s.drafts.note='Keep draft';});const before=await store.read();
 await assert.rejects(engine.importProjection(value));assert.deepEqual(await store.read(),before);
});
test('older projection receiver rejects required Lineage before mutating storage',async()=>{
 const value=lineageSnapshot(),store=new MemoryStore(value.workspace_id,'older-phone'),before=await store.read();
 await assert.rejects(store.update(s=>{s.readProjection=old.validateProjection(value,value.workspace_id);}));assert.deepEqual(await store.read(),before);
 const plain=lineageSnapshot();delete plain.required_capabilities;delete plain.papers[0].lineage;
 assert.deepEqual(validateProjection(plain,plain.workspace_id),old.validateProjection(plain,plain.workspace_id));
});
test('Lineage validator is a static offline dependency, never a private API route',()=>{
 const scope='https://paperfact.invalid/mobile/',url=new URL('./lineage.mjs',scope);
 assert(SHELL.includes('./lineage.mjs'));assert(cacheable(new Request(url),scope));
 assert(!cacheable(new Request(url.href+'?private=1'),scope));
 assert(!cacheable(new Request(url,{headers:{Authorization:'Bearer synthetic'}}),scope));
});


import {renderLineage,LINEAGE_COPY} from '../lineage-view.mjs';
class Element {
 constructor(tag,attrs={},children=[]){this.tag=tag;this.attrs=attrs;this.children=children.flat();}
 append(...children){this.children.push(...children);}
 set innerHTML(_value){assert.fail('Research must not become HTML');}
 get text(){return this.children.map(c=>c instanceof Element?c.text:String(c)).join(' ');}
 all(tag){return [...(this.tag===tag?[this]:[]),...this.children.filter(c=>c instanceof Element).flatMap(c=>c.all(tag))];}
}
const el=(tag,attrs={},...children)=>new Element(tag,attrs,children);
for(const language of ['en','zh-TW','unsupported-language'])test('read-only accessible saved Lineage view '+language,()=>{
 const row=lineageRow(),before=structuredClone(row),panel=el('div');
 renderLineage(panel,{lineage:[row]},el,language);
 const t=LINEAGE_COPY[language]??LINEAGE_COPY.en;
 assert(panel.text.includes(t.title));assert(panel.text.includes(t.recorded));
 assert(panel.text.includes(row.body.report.statements[0].passages[0].quote));
 assert.equal(panel.all('button').length,0);assert.equal(panel.all('a').length,0);
 assert.equal(panel.all('summary').length,3);assert.equal(panel.all('details')[0].attrs.open,'');
 assert(panel.text.includes(t.empty));assert(panel.text.includes(row.body.report.sources[0].document_hash));
 assert.deepEqual(row,before);
});
test('view keeps literal markup as text, never a URL, source activation or hidden control',()=>{
 const row=lineageRow(),payload='<img src=x onerror="run()">';
 row.body.report.statements[0].text=payload;row.body.report.statements[0].passages[0].quote=payload;
 const panel=el('div');renderLineage(panel,{lineage:[row]},el);
 assert(panel.text.includes(payload));assert.equal(panel.all('img').length,0);assert.equal(panel.all('script').length,0);
 assert.equal(panel.all('input').length,0);
});
test('no saved Lineage does not add an empty or misleading panel',()=>{
 for(const paper of [{},{lineage:[]}]){const panel=el('div');renderLineage(panel,paper,el);assert.deepEqual(panel.children,[]);}
 assert.deepEqual(Object.keys(LINEAGE_COPY.en).sort(),Object.keys(LINEAGE_COPY['zh-TW']).sort());
 assert(SHELL.includes('./lineage-view.mjs'));
});


import {readFileSync} from 'node:fs';
import {translator} from '../i18n.mjs';
test('combined existing snapshot capabilities retain all declarations and Lineage atomically',async()=>{
 const value=JSON.parse(readFileSync(new URL('../../tests/fixtures/reading-position-snapshot.json',import.meta.url),'utf8'));
 const row=lineageRow();row.body.bindings[0].paper_id=value.papers[0].id;value.papers[0].lineage=[row];
 value.required_capabilities=[...value.required_capabilities,'lineage'].sort();
 const store=new MemoryStore(value.workspace_id,'phone');await new Engine(store).importProjection(value);
 const state=await store.read();assert.deepEqual(state.readProjection.required_capabilities,value.required_capabilities);
 assert.deepEqual(state.readProjection.papers[0].lineage,[row]);assert.equal(state.cursor,0);
 assert.deepEqual(state.outbox,[]);assert.deepEqual(state.graph,{});
});
for(const state of ['missing','ambiguous'])test('valid unresolved quote location remains unresolved '+state,()=>{
 const row=lineageRow(),r=row.body.report,p=r.statements[0].passages[0];
 const anchor={p0:0,o0:0,p1:0,o1:4};
 p.location={state,reason:state==='missing'?'quote_not_found':'multiple_quote_locations',anchor:null,page:null,candidates:state==='missing'?[]:[anchor,{...anchor,o0:1}],truncated:false};
 p.id=claimHash(['bounded-lineage.v1',p.source_id,p.role,p.cites,normalizeClaimText(p.quote),p.location]);
 r.statements[0].requirements.own_source_passage='missing';const {id,...rest}=r;r.id=claimHash(rest);
 assert.equal(verify(row)[0].body.report.statements[0].passages[0].location.state,state);
});
test('friendly format errors and view text are available in both app languages',()=>{
 for(const lang of ['en','zh-TW'])for(const key of ['unsupported_lineage','lineage_capability_required','lineage_portable_owner_required'])assert.notEqual(translator(lang)(key),key);
 const row=lineageRow();row.body.report.statements[0].passages[0].location.page=2;
 assert.throws(()=>verify(row),{message:'unsupported_lineage'});
 assert.deepEqual([...LINEAGE_COPY['zh-TW'].title].map(c=>c.codePointAt(0)),[0x7814,0x7a76,0x8108,0x7d61]);
 for(const value of Object.values(LINEAGE_COPY['zh-TW']))assert(!value.includes('?'));
 for(const key of ['unsupported_lineage','lineage_capability_required','lineage_portable_owner_required'])assert(!translator('zh-TW')(key).includes('?'));
});


test('an unavailable selected peer retains missing evidence and never acquires a PDF action',()=>{
 const row=lineageRow(),r=row.body.report,peer='33333333-3333-4333-8333-333333333333';
 const identity={title:'Unavailable selected peer',doi:null,arxiv_id:null,s2_id:null};
 const source={id:claimHash(['lineage-source.v1',identity,null]),identity,identity_authority:'selected_workspace_record',document_hash:null,availability:'unavailable',page_count:null};
 r.sources.push(source);row.body.bindings.push({source_id:source.id,paper_id:peer});
 const location={state:'source_unavailable',reason:'original_unavailable',anchor:null,page:null,candidates:[],truncated:false};
 const p={source_id:source.id,role:'own_characterization',cites:null,quote:'A proposal without an original.',location};
 p.id=claimHash(['bounded-lineage.v1',p.source_id,p.role,p.cites,normalizeClaimText(p.quote),location]);
 const item={stage:'later_development',subject:source.id,text:'An unresolved later proposal.',function:'unresolved',judgment:{status:'unresolved',reason:'Original is unavailable.',authority:'caller_proposal'},passages:[p],requirements:{own_source_passage:'missing',citing_passage:'missing',citation_identity:'unresolved',semantic_validation:'not_performed'}};
 item.id=claimHash(['bounded-lineage.v1',r.focal,item.stage,item.subject,normalizeClaimText(item.text)]);
 r.statements.push(item);r.coverage.later_development='proposed';const {id,...rest}=r;r.id=claimHash(rest);row.source_hash=lineageSourceHash(row.body);
 assert.doesNotThrow(()=>validateLineageProjection([row],PAPER,new Set([PAPER,peer]),validateContentTimestamp));
 for(const lang of ['en','zh-TW']){const panel=el('div');renderLineage(panel,{lineage:[row]},el,lang);const t=LINEAGE_COPY[lang];
  for(const key of ['ownMissing','citingMissing','identityUnresolved','source_unavailable','role_own_characterization'])assert(panel.text.includes(t[key]));
  assert.equal(panel.all('a').length,0);assert.equal(panel.all('button').length,0);}
 const bad=structuredClone(row);bad.body.report.sources[1].document_hash='c'.repeat(64);
 assert.throws(()=>validateLineageProjection([bad],PAPER,new Set([PAPER,peer]),validateContentTimestamp));
});
