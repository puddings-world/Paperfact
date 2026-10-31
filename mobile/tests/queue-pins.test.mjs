import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {validateContent,projectContent,suppressSnapshotContent} from '../content.mjs';
import {renderLegacyWorkflow} from '../legacy-view.mjs';
import {translator} from '../i18n.mjs';
const cases=JSON.parse(readFileSync(new URL('../../tests/fixtures/queue-pins.json',import.meta.url)));
for(const item of cases)test('Python/mobile queue pin: '+item.name,()=>{
  const call=()=>validateContent(item.payload,item.entity_id,item.parents);
  if(item.valid)assert.doesNotThrow(call);else assert.throws(call);
});
test('saved orphan pin displays without queue/list or mutation and canonical delete hides it',()=>{
  const example=cases[0],paper={id:example.payload.scope.id};
  projectContent([paper],[],[{operation:{payload:example.payload,entity_id:example.entity_id},revision:1}]);
  assert.deepEqual(paper.queue_pin,example.payload.data);assert.equal(paper.legacy_queue,undefined);
  class Node {
    constructor(tag,attrs,children){this.tag=tag;this.children=children.flat();}
    append(...children){this.children.push(...children);}
    get text(){return this.children.map(c=>c instanceof Node?c.text:String(c)).join(' ');}
    set innerHTML(_){throw Error('executable HTML');}
  }
  const el=(tag,attrs={},...children)=>new Node(tag,attrs,children);
  for(const lang of ['en','zh-TW']) {
    const panel=el('div');renderLegacyWorkflow(panel,paper,el,translator(lang));
    assert(panel.text.includes(translator(lang)('queuePin')));assert(panel.text.includes(example.payload.data.pinned_at));
    assert.equal(panel.children.length,1);
  }
  // A retained tombstone is resolved through its original typed put receipt.
  const op={entity_type:'research_content',entity_id:example.entity_id,action:'delete',payload:{},parents:example.parents};
  suppressSnapshotContent([paper],[],[{operation:op,revision:2}],
    [{outcome:'accepted',sequence:1,operation:{...op,action:'put',payload:example.payload}}],[]);
  assert.equal(paper.queue_pin,null);
});


import {validateProjection} from '../domain.mjs';
import {MemoryStore} from '../store.mjs';
import {Engine} from '../engine.mjs';
import {LegacyProjectionImporter} from './fixtures/pre-queue-pin-projection.mjs';
function snapshot(pinned=true) {
  return {schema_version:1,workspace_id:'pin-workspace',cursor:57,capabilities:{sync_bootstrap:false},local_state:{},
    lists:[],papers:[{id:'p',title:'Paper',authors:[],year:2026,doi:null,url:null,pdf_asset_id:null,
      ...(pinned?{queue_pin:{pinned_at:'2026-10-30T12:34:56+08:00'}}:{})}],notes:[],highlights:[],decks:[],assets:[],
    ...(pinned?{required_capabilities:['queue_pin']}:{})};
}
test('actual old snapshot validator rejects required queue pins before persisted state or cursor; absent stays compatible',async()=>{
  const store=new MemoryStore('pin-workspace','phone'),legacy=new LegacyProjectionImporter(store);
  const before=await store.read();await assert.rejects(legacy.importProjection(snapshot()));
  assert.deepEqual(await store.read(),before);
  await legacy.importProjection(snapshot(false));assert.equal((await store.read()).cursor,0);
  assert.equal((await store.read()).readProjection.papers[0].queue_pin,undefined);
  const engine=new Engine(store);await engine.importProjection(snapshot());
  assert.deepEqual((await store.read()).readProjection.papers[0].queue_pin,snapshot().papers[0].queue_pin);
  assert.equal((await store.read()).cursor,0);assert.deepEqual((await store.read()).outbox,[]);
});
for(const [name,caps] of [['missing',undefined],['empty',[]],['unknown',['future']],['extra',['queue_pin','future']],['duplicate',['queue_pin','queue_pin']]])
 test('snapshot capabilities fail closed: '+name,()=>{
   const value=snapshot();if(caps===undefined)delete value.required_capabilities;else value.required_capabilities=caps;
   assert.throws(()=>validateProjection(value,'pin-workspace'));
 });
test('unused capability and malformed queue-pin snapshot fail closed',()=>{
  const extra=snapshot(false);extra.required_capabilities=['queue_pin'];assert.throws(()=>validateProjection(extra,'pin-workspace'));
  for(const pin of [null,[],{}, {pinned_at:['2026-10-30T12:34:56+08:00']},{pinned_at:'2026-10-30T12:34:56'},
    {pinned_at:'2026-10-30T12:34:56+08:00',secret:'never accepted'}]) {
    const value=snapshot();value.papers[0].queue_pin=pin;assert.throws(()=>validateProjection(value,'pin-workspace'));
  }
});

test('snapshot timestamp mirror rejects impossible dates and preserves supported ISO spelling verbatim',()=>{
  const invalid=snapshot();invalid.papers[0].queue_pin.pinned_at='2026-02-30T12:34:56+08:00';
  assert.throws(()=>validateProjection(invalid,'pin-workspace'));
  const basic=snapshot();basic.papers[0].queue_pin.pinned_at='20261030T123456+0800';
  assert.equal(validateProjection(basic,'pin-workspace').papers[0].queue_pin.pinned_at,'20261030T123456+0800');
});

test('known canonical put overrides stale pin snapshot and keeps independent list pin display',()=>{
  const value=snapshot();value.lists=[{id:'reading',name:'Reading',note:'',members:[{id:'member',paper_id:'p',position:0,state:'pending',pinned:true,pinned_at:'2026-10-30T12:34:56+08:00'}]}];
  const parsed=validateProjection(value,'pin-workspace');assert.equal(parsed.lists[0].members[0].pinned,true);
  assert.equal(parsed.papers[0].queue_pin.pinned_at,value.papers[0].queue_pin.pinned_at);
  const example=cases[0],paper={id:example.payload.scope.id,queue_pin:{pinned_at:'2020-01-01T00:00:00+00:00'}};
  const put={entity_type:'research_content',entity_id:example.entity_id,action:'put',payload:example.payload,parents:example.parents};
  suppressSnapshotContent([paper],[],[{operation:put,revision:3}],[],[]);
  assert.equal(paper.queue_pin,null);
  projectContent([paper],[],[{operation:put,revision:3}]);assert.deepEqual(paper.queue_pin,example.payload.data);
});
