import test from 'node:test';
import assert from 'node:assert/strict';
import {createHash} from 'node:crypto';
import {readFileSync} from 'node:fs';
import {claimHash,normalizeClaimText,validateClaims,renderClaimSet} from '../claims.mjs';
import {validateAnnotations,renderAnnotations} from '../annotations.mjs';
import {validateContent,projectContent,suppressSnapshotContent} from '../content.mjs';
import {contentId} from '../ids.mjs';
import {translator} from '../i18n.mjs';
import {MemoryStore} from '../store.mjs';
import {Engine} from '../engine.mjs';
import {projection,receive} from '../domain.mjs';
import {demoTransport,PAPER,operation,ref} from '../fixture.mjs';
import {SHELL,cacheable} from '../sw-policy.mjs';
const examples=JSON.parse(readFileSync(new URL('../../tests/fixtures/claim-sets.json',import.meta.url)));
const good=examples.find(example=>example.valid).body;
const clone=()=>structuredClone(good);
const reseal=body=>{body.report.id=claimHash(Object.fromEntries(Object.entries(body.report).filter(([key])=>key!=='id')));return body;};
const envelope=body=>({scope:{kind:'paper',id:PAPER},feature:'claims',key:'main',data:{body_json:body,
  source_hash:'a'.repeat(64),document_hash:body.report.source.document_hash,written_at:'2026-10-30T00:00:00+00:00'},
  source_document_hash:body.report.source.document_hash});
for(const example of examples) test('Python claim golden: '+example.name,()=>{
  if(example.valid) { assert.equal(validateClaims(example.body),example.body); assert.equal(validateAnnotations('claims',example.body),example.body); }
  else assert.throws(()=>validateClaims(example.body));
});
test('bounded synchronous claim digests agree with SHA256 and Python whitespace normalization',()=>{
  for(const input of ['',[],{a:'Chinese 中文😀',b:1},['claim',{document_hash:'a'.repeat(64),paper_id:'p'},'text']]) {
    const canonical=value=>Array.isArray(value)?'['+value.map(canonical).join(',')+']':value&&typeof value==='object'?'{'+Object.keys(value).sort().map(k=>JSON.stringify(k)+':'+canonical(value[k])).join(',')+'}':JSON.stringify(value);
    assert.equal(claimHash(input),createHash('sha256').update(canonical(input)).digest('hex'));
  }
  assert.equal(normalizeClaimText('Ｆoo\u00ad - \n bar\u0085 baz\u001c qux'),'Foo bar baz qux');
  assert.equal(normalizeClaimText('a\ufeffb'),'a\ufeffb');
});
test('portable claims require the same non-null row, envelope and original report source',()=>{
  const payload=envelope(clone()), id=contentId(payload.scope,'claims','main'), parents=[ref('paper',PAPER)];
  validateContent(payload,id,parents);
  for(const mismatch of [null,'b'.repeat(64)]) {
    const changed=structuredClone(payload);changed.source_document_hash=mismatch;changed.data.document_hash=mismatch;
    assert.throws(()=>validateContent(changed,id,parents));
  }
  const changed=structuredClone(payload);changed.data.document_hash='b'.repeat(64);
  assert.throws(()=>validateContent(changed,id,parents));
});
for(const change of [
  body=>{body.report.claims[0].semantic_validation='verified';},
  body=>{body.report.claims[0].judgment.authority='system';},
  body=>{body.report.claims[0].atomicity='verified_atomic';},
  body=>{body.report.claims[0].id+='\n';},
  body=>{body.report.claims[0].passages[0].location.anchor.o1=-1;},
  body=>{body.report.claims[0].passages[0].location.candidates=[{p0:0,o0:0,p1:0,o1:1}];},
  body=>{body.report.claims[0].passages[0].citation_identity={state:'resolved',reason:null,proposed:null};},
  body=>{body.generation.account='private';},
  body=>{body.report.claims[0].passages.push(structuredClone(body.report.claims[0].passages[0]));}
]) test('closed claims reject mutation '+change.toString(),()=>{const body=clone();change(body);reseal(body);assert.throws(()=>validateClaims(body));});
test('research receive/retry/offline restart preserves claim bodies without AI or upload',async()=>{
  const transport=await demoTransport(), store=new MemoryStore('demo-workspace','demo-phone');
  await store.update(state=>receive(state,transport.events));
  const payload=envelope(clone()), id=contentId(payload.scope,'claims','main');
  const op=operation('research_content',id,payload,{operationId:'claims-created',parents:[ref('paper',PAPER)]});
  const event={sequence:7,outcome:'accepted',operation:op,head:{revision:7,operation:op}};
  await store.update(state=>receive(state,[event]));await store.update(state=>receive(state,[event]));
  const current=await store.read(), row=projection(current).papers[0].research_content.find(row=>row.feature==='claims');
  assert.deepEqual(row.data.body_json,good);assert.deepEqual(current.outbox,[]);
  const reopened=new MemoryStore('demo-workspace','demo-phone',JSON.parse(JSON.stringify(current)));
  const offline=new Engine(reopened,{transport:new Proxy({}, {get(){throw Error('Offline claim read attempted network');}})});
  assert.deepEqual(projection(await offline.store.read()).papers[0].research_content.find(row=>row.feature==='claims'),row);
});
test('canonical claim deletion suppresses stale read projections without destroying imported text',()=>{
  const payload=envelope(clone()), id=contentId(payload.scope,'claims','main');
  const old={sequence:1,outcome:'accepted',operation:{entity_type:'research_content',entity_id:id,action:'put',payload}};
  const removed={revision:2,operation:{entity_type:'research_content',entity_id:id,action:'delete'}};
  const imported={feature:'claims',data:payload.data,source_document_hash:payload.source_document_hash};
  const paper={id:PAPER,research_content:[structuredClone(imported)]};
  suppressSnapshotContent([paper],[],[removed],[old],[]);
  assert.deepEqual(paper.research_content,[]);assert.deepEqual(imported.data.body_json,good);
  projectContent([paper],[],[{operation:{entity_id:id,payload},revision:3}]);
  assert.deepEqual(paper.research_content[0].data.body_json,good);
});
const node=(tag,attrs={},...children)=>({tag,attrs,children,append(...items){this.children.push(...items);}});
const strings=part=>typeof part==='string'?[part]:part.children.flatMap(strings);
test('read-only cards label proposals and original snapshot locations without semantic certification',()=>{
  const body=clone();body.report.claims[0].judgment.status='supported';reseal(body);
  const payload=envelope(body), panel=node('main');
  renderAnnotations(panel,{research_content:[{feature:'claims',data:payload.data,source_document_hash:payload.source_document_hash}]},node,translator('en'));
  const text=strings(panel);
  assert(text.includes('Proposed judgment: supported'));
  assert(text.some(value=>value.includes('Semantic support has not been verified')));
  assert(text.some(value=>value.includes('original snapshot')));
  assert(!text.includes('supported'));assert(!JSON.stringify(panel).includes('onclick'));
});
test('claim strings stay inert and missing evidence cannot activate a source link',()=>{
  const body=clone(), claim=body.report.claims[0], passage=claim.passages[0];
  claim.text='<script>claim()</script>';claim.id=claimHash(['claim',body.report.source,normalizeClaimText(claim.text)]);
  passage.quote='<img src=x onerror=alert(1)>';passage.id=passage.proposal_id;
  passage.location={state:'missing',reason:'quote_not_found',anchor:null,page:null,candidates:[],truncated:false};reseal(body);
  const row={data:{body_json:body,document_hash:body.report.source.document_hash},source_document_hash:body.report.source.document_hash};
  const panel=node('main');renderClaimSet(panel,row,node,translator('en'));
  assert(strings(panel).includes(claim.text)&&strings(panel).includes(passage.quote));
  const attrs=part=>typeof part==='string'?[]:[Object.keys(part.attrs),...part.children.flatMap(attrs)];
  assert(!attrs(panel).flat().some(name=>['href','src','onclick','innerHTML'].includes(name)));
});
test('claim module is an exact static shell entry, never an authenticated research cache',()=>{
  assert(SHELL.includes('./claims.mjs'));
  assert(cacheable(new Request('https://app.example/claims.mjs'),'https://app.example/'));
  assert(!cacheable(new Request('https://app.example/claims.mjs',{headers:{authorization:'Bearer secret'}}),'https://app.example/'));
  assert(!cacheable(new Request('https://app.example/v1/research/claims'),'https://app.example/'));
});

test('Traditional Chinese claim notices are readable and explain proposed semantics',()=>{
  assert.equal(translator('zh-TW')('research_claims'),'\u7814\u7a76\u4e3b\u5f35\u8207\u5f15\u6587\u4f9d\u64da');
  assert(translator('zh-TW')('claimNoSemanticValidation').includes('\u5c1a\u672a\u9a57\u8b49'));
});
test('distinct proposed quotes cannot reuse the same located anchor',()=>{
  const body=clone(), passage=structuredClone(body.report.claims[0].passages[0]);
  passage.quote='Another full proposed passage';
  passage.id=claimHash(['located-passage',body.report.source,normalizeClaimText(passage.quote),passage.location.anchor]);
  body.report.claims[0].passages.push(passage);reseal(body);
  assert.throws(()=>validateClaims(body));
});

test('location state must be a scalar string even when array coercion names a valid state',()=>{
  const body=clone(), passage=body.report.claims[0].passages[0];
  passage.id=passage.proposal_id;
  passage.location={state:['missing'],reason:'quote_not_found',anchor:null,page:null,candidates:[],truncated:false};
  reseal(body);assert.throws(()=>validateClaims(body));
});

test('invalid incoming claim source preserves the last projection and cursor for explicit retry',async()=>{
  const transport=await demoTransport(), store=new MemoryStore('demo-workspace','demo-phone');
  await store.update(state=>receive(state,transport.events));
  const payload=envelope(clone()), id=contentId(payload.scope,'claims','main');
  const initial=operation('research_content',id,payload,{operationId:'claims-created',parents:[ref('paper',PAPER)]});
  await store.update(state=>receive(state,[{sequence:7,outcome:'accepted',operation:initial,head:{revision:7,operation:initial}}]));
  const before=await store.read();
  const bad=structuredClone(payload);bad.source_document_hash=null;bad.data.document_hash=null;
  const changed=operation('research_content',id,bad,{operationId:'claims-updated',base:7,incarnation:initial.incarnation,parents:[ref('paper',PAPER)]});
  const event={sequence:8,outcome:'accepted',operation:changed,head:{revision:8,operation:changed}};
  await assert.rejects(()=>store.update(state=>receive(state,[event])));
  assert.deepEqual(await store.read(),before);
  changed.payload=payload;
  await store.update(state=>receive(state,[event]));
  assert.equal((await store.read()).cursor,8);
  assert.deepEqual(projection(await store.read()).papers[0].research_content.find(item=>item.feature==='claims').data.body_json,good);
});
