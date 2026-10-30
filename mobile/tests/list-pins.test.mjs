import { SHELL } from '../sw-policy.mjs';
import { Engine } from '../engine.mjs';
import test from 'node:test';
import assert from 'node:assert/strict';
import {demoTransport, demoProjection, operation, ref, PAPER, MEMBER} from '../fixture.mjs';
import {MemoryStore} from '../store.mjs';
import {active,keyOf,projection,receive,validateOperation} from '../domain.mjs';
import {contentId} from '../ids.mjs';
import {pinBadge} from '../list-pins.mjs';
import {translator} from '../i18n.mjs';
const LIST='demo-list', STAMP='2026-10-30T00:00:00+00:00';
const payload=()=>({scope:{kind:'list',id:LIST},feature:'list_pin',key:PAPER,
  data:{pinned_at:STAMP},source_document_hash:null});
const pin=(options={})=>operation('research_content',contentId({kind:'list',id:LIST},'list_pin',PAPER),payload(),
 {device:'demo-phone',parents:[ref('list',LIST),ref('paper',PAPER),ref('membership',MEMBER)],...options});
async function fixture() {
  const transport=await demoTransport(),store=new MemoryStore('demo-workspace','reader');
  const op=pin(); await transport.push('fixture-token',op);
  await store.update(state=>receive(state,transport.events));
  return {transport,store,op};
}

test('pin is a visible localized member flag; ordering and selection stay unchanged',async()=>{
 const {store,transport}=await fixture(),state=await store.read();
 const before=projection(state).lists[0].members.map(member=>member.id);
 const member=projection(state).lists.find(list=>list.id===LIST).members.find(item=>item.paper_id===PAPER);
 assert.equal(member.pinned,true);assert.equal(member.pinned_at,STAMP);
 const el=(tag,attrs,...kids)=>({tag,attrs,kids});
 const badge=pinBadge(member,el,translator('en'));
 assert.equal(badge.attrs['aria-label'],'Pinned');
 assert.equal(pinBadge(member,el,translator('zh-TW')).attrs['aria-label'],'\u5df2\u91d8\u9078');
 assert.equal(pinBadge({pinned:false},el,translator('en')),null);
 const reopened=new MemoryStore(state.workspace,state.device,state);
 await reopened.update(value=>receive(value,transport.events));
 assert.deepEqual(projection(await reopened.read()).lists[0].members.map(item=>item.id),before);
 assert.deepEqual((await reopened.read()).selection,state.selection);
});

test('membership removal and recreation never reactivates its old pin',async()=>{
 const {transport,store,op}=await fixture();
 const head=transport.state.entities[keyOf('membership',MEMBER)],original=head.operation;
 const deleted={...original,operation_id:'remove-member',action:'delete',payload:{},base_revision:head.revision,
  structure_revision:transport.state.graph[keyOf('membership',MEMBER)].structure_revision,device_id:'demo-phone'};
 await transport.push('fixture-token',deleted);
 await store.update(value=>receive(value,transport.events));
 assert.equal(active(await store.read(),'research_content',op.entity_id),false);
 const restored={...original,operation_id:'restore-member',incarnation:'restore-member',
  base_revision:transport.events.length,device_id:'demo-phone'};
 await transport.push('fixture-token',restored);
 await store.update(value=>receive(value,transport.events));
 const member=projection(await store.read()).lists.find(list=>list.id===LIST).members.find(item=>item.paper_id===PAPER);
 assert.notEqual(member.pinned,true);
 const newPin=pin({operationId:'restore-current-pin',base:7,parents:[ref('list',LIST),ref('paper',PAPER),ref('membership',MEMBER,'restore-member')]});
 await transport.push('fixture-token',newPin);
 await store.update(value=>receive(value,transport.events));
 assert.equal(projection(await store.read()).lists.find(list=>list.id===LIST).members.find(item=>item.paper_id===PAPER).pinned,true);
 assert.ok((await store.read()).receipts[op.operation_id]);
});

for(const kind of ['member','roots','order','missing','pdf','queue']) test(`pin rejects malformed ${kind} atomically`,async()=>{
 const {store,op}=await fixture(),bad=structuredClone(op);
 if(kind==='member')bad.parents[2].id=PAPER;
 if(kind==='roots')bad.parents[1].id='00000000-0000-4000-8000-000000000002';
 if(kind==='order')bad.parents.reverse();
 if(kind==='missing')bad.parents.pop();
 if(kind==='pdf')bad.payload.source_document_hash='a'.repeat(64);
 if(kind==='queue')bad.payload.scope.id='queue';
 const before=await store.read();
 assert.throws(()=>validateOperation(bad,'demo-workspace'));
 await assert.rejects(store.update(value=>receive(value,[{sequence:8,outcome:'accepted',operation:bad,head:{revision:8,operation:bad}}])));
 assert.deepEqual(await store.read(),before);
});

function snapshot() {
 const value=structuredClone(demoProjection);
 value.lists=[{id:LIST,name:'Snapshot',note:'',members:[{id:MEMBER,paper_id:PAPER,position:0,
   state:'pending',pinned:true,pinned_at:STAMP}]}];
 return value;
}

test('read-only snapshot cannot revive a pin after newer canonical membership removal/restoration',async()=>{
 const transport=await demoTransport(),store=new MemoryStore('demo-workspace','reader');
 const engine=new Engine(store);
 await engine.importProjection(snapshot());
 assert.equal(projection(await store.read()).lists[0].members[0].pinned,true);
 assert.equal((await store.read()).cursor,0);
 await store.update(state=>receive(state,transport.events));
 assert.notEqual(projection(await store.read()).lists[0].members[0].pinned,true);
 const op=pin();await transport.push('fixture-token',op);
 await store.update(state=>receive(state,transport.events));
 assert.equal(projection(await store.read()).lists[0].members[0].pinned,true);
 const original=transport.state.entities[keyOf('membership',MEMBER)].operation;
 const deleted={...original,operation_id:'snapshot-remove',action:'delete',payload:{},base_revision:3,
  structure_revision:transport.state.graph[keyOf('membership',MEMBER)].structure_revision,device_id:'demo-phone'};
 await transport.push('fixture-token',deleted);
 const restored={...original,operation_id:'snapshot-restore',incarnation:'snapshot-restore',
  base_revision:8,device_id:'demo-phone'};
 await transport.push('fixture-token',restored);
 await store.update(state=>receive(state,transport.events));
 assert.notEqual(projection(await store.read()).lists[0].members[0].pinned,true);
 await engine.importProjection(snapshot());
 assert.notEqual(projection(await store.read()).lists[0].members[0].pinned,true);
});

for(const bad of [{pinned:'true',pinned_at:STAMP},{pinned:true},{pinned:true,pinned_at:'yesterday'},
 {pinned:false,pinned_at:STAMP},{pinned_at:STAMP}]) test('snapshot pin boolean/timestamp relation rejects malformed values',async()=>{
 const store=new MemoryStore('demo-workspace','reader'),engine=new Engine(store),value=snapshot();
 value.lists[0].members[0]={id:MEMBER,paper_id:PAPER,position:0,state:'pending',...bad};
 await assert.rejects(engine.importProjection(value));
 assert.equal((await store.read()).readProjection,null);
});

test('pin badge module is available on offline shell restart',()=>{ assert.ok(SHELL.includes('./list-pins.mjs')); });
