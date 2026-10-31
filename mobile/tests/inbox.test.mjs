import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {MemoryStore} from '../store.mjs';
import {Engine} from '../engine.mjs';
import {validateOperation,receive,validateProjection,projection,keyOf,buildOperation} from '../domain.mjs';
import * as old from './fixtures/pre-inbox-domain.mjs';
import {validateInbox,inboxDisplay} from '../inbox-schema.mjs';
import {captureInbox,saveInbox,draftInbox,inboxReport,observeInbox,resolveInbox} from '../inbox-ops.mjs';
const stamp='2026-10-30T12:00:00+00:00';
const payload=(text='Exact input',kind='idea',state='new')=>({kind,text,state,created_at:stamp,updated_at:stamp});
const uuid=()=>crypto.randomUUID();
const setup=()=>{const store=new MemoryStore('workspace','phone');return {store,engine:new Engine(store)};};
const event=(operation,sequence)=>({sequence,outcome:'accepted',operation,head:{revision:sequence,operation}});
const vectors=JSON.parse(readFileSync(new URL('../../tests/fixtures/inbox-contract.json',import.meta.url),'utf8'));
for(const value of vectors)test('independent Inbox contract '+value.name,()=>{
  if(value.valid)assert.deepEqual(validateInbox(value.payload),value.payload);
  else assert.throws(()=>validateInbox(value.payload));
});
test('capture keeps exact DOI text, has no paper/list parent, and never touches transport',async()=>{
  const {store,engine}=setup();engine.transport=new Proxy({},{get(){assert.fail('Inbox touched transport');}});
  const scope=await captureInbox(engine),requestId=uuid(),itemId=uuid(),data=payload('  DOI:10.1234/Mixed  ','doi');
  await draftInbox(engine,scope,{itemId,requestId,kind:'doi',text:data.text,state:'new'});
  const saved=await saveInbox(engine,{scope,requestId,itemId,payload:data});
  assert.equal(saved.status,'saved');const state=await store.read(),op=state.outbox[0].operation;
  assert.equal(op.entity_type,'inbox_item');assert.deepEqual(op.parents,[]);
  assert.equal(op.payload.text,data.text);assert.equal(inboxDisplay(data.kind,data.text),'10.1234/mixed');
  assert.equal(inboxReport(state).items[0].payload.text,data.text);assert.deepEqual(state.inboxDrafts,{});
});
test('same request after offline restart returns one receipt/outbox; changed retry refuses',async()=>{
  const {store,engine}=setup();let scope=await captureInbox(engine);
  const requestId=uuid(),itemId=uuid(),data=payload();
  const result=await saveInbox(engine,{scope,requestId,itemId,payload:data});
  const reopened=new MemoryStore('workspace','phone',await store.read()),next=new Engine(reopened);
  scope=await captureInbox(next);assert.deepEqual(await saveInbox(next,{scope,requestId,itemId,payload:data}),result);
  await assert.rejects(saveInbox(next,{scope,requestId,itemId,payload:payload('Changed')}));
  assert.equal((await reopened.read()).outbox.length,1);
});
test('duplicate text is independent explicit capture; no title/text/hash merge',async()=>{
  const {store,engine}=setup(),scope=await captureInbox(engine);
  for(let i=0;i<2;i++)await saveInbox(engine,{scope,requestId:uuid(),itemId:uuid(),payload:payload()});
  assert.equal(inboxReport(await store.read()).items.length,2);
});
test('stale edited draft is retained without overwriting newer triage',async()=>{
  const {store,engine}=setup(),scope=await captureInbox(engine),id=uuid();
  await saveInbox(engine,{scope,requestId:uuid(),itemId:id,payload:payload()});
  const observed=observeInbox(await store.read(),id);
  await saveInbox(engine,{scope,requestId:uuid(),itemId:id,payload:payload('Exact input','idea','kept'),observed});
  const requestId=uuid(),args={scope,requestId,itemId:id,payload:payload('Stale private thought'),observed};
  const result=await saveInbox(engine,args);assert.equal(result.status,'conflict');
  assert.deepEqual(await saveInbox(engine,args),result);
  const report=inboxReport(await store.read());assert.equal(report.items[0].payload.state,'kept');
  assert.equal(report.retained.length,1);assert.equal(report.retained[0].payload.text,'Stale private thought');
});
test('storage failure preserves durable draft and retry writes once',async()=>{
  const {store,engine}=setup(),scope=await captureInbox(engine),requestId=uuid(),itemId=uuid();
  await draftInbox(engine,scope,{itemId,requestId,kind:'idea',text:'Keep draft',state:'new'});
  store.failure='storage_write_failed';const args={scope,requestId,itemId,payload:payload('Keep draft')};
  await assert.rejects(saveInbox(engine,args));assert.equal((await store.read()).inboxDrafts.capture.text,'Keep draft');
  assert.equal((await store.read()).outbox.length,0);store.failure=null;
  await saveInbox(engine,args);assert.equal((await store.read()).outbox.length,1);
});
for(const change of ['close','workspace','device','account-generation'])test('pending capture rejects '+change,async()=>{
  const {store,engine}=setup(),scope=await captureInbox(engine);let current=true;
  const result=saveInbox(engine,{scope,current:()=>current,requestId:uuid(),itemId:uuid(),payload:payload()});
  if(change==='close')current=false;
  else if(change==='account-generation')engine.disconnect();
  else await store.update(state=>{state[change==='workspace'?'workspace':'device']='other';});
  await assert.rejects(result);assert.equal((await store.read()).outbox.length,0);
});
test('async capture freezes original payload rather than mutable editor object',async()=>{
  const {store,engine}=setup(),scope=await captureInbox(engine),data=payload('Original exact text');
  const result=saveInbox(engine,{scope,requestId:uuid(),itemId:uuid(),payload:data});data.text='Changed after click';
  await result;assert.equal((await store.read()).outbox[0].operation.payload.text,'Original exact text');
});
test('deletion retains old receipts and requires explicit fresh restore incarnation',async()=>{
  const {store,engine}=setup(),scope=await captureInbox(engine),id=uuid();
  await saveInbox(engine,{scope,requestId:uuid(),itemId:id,payload:payload()});
  let state=await store.read(),created=state.outbox[0].operation;
  await store.update(next=>receive(next,[event(created,1)]));
  let observed=observeInbox(await store.read(),id);
  await saveInbox(engine,{scope,requestId:uuid(),itemId:id,action:'delete',observed});
  state=await store.read();const deleted=state.outbox[0].operation;
  await store.update(next=>receive(next,[event(deleted,2)]));
  observed=observeInbox(await store.read(),id);
  await assert.rejects(saveInbox(engine,{scope,requestId:uuid(),itemId:id,payload:payload(),observed}));
  await saveInbox(engine,{scope,requestId:uuid(),itemId:id,payload:payload(),observed,restore:true});
  const restored=(await store.read()).outbox[0].operation;
  assert.notEqual(restored.incarnation,created.incarnation);assert.equal(restored.incarnation,restored.operation_id);
});
function projected(id=uuid()) {
  return {schema_version:2,workspace_id:'workspace',cursor:0,capabilities:{sync_bootstrap:false},local_state:{},
    lists:[],papers:[],notes:[],highlights:[],decks:[],assets:[],required_capabilities:['inbox'],
    inbox:{items:[{id,payload:payload(),active:true,version:'version',incarnation:'created',sync_state:'local'}],retained:0}};
}
test('conditional exact capability/read-only projection never fabricates root editing authority',async()=>{
  const {store,engine}=setup(),id=uuid(),value=projected(id);
  await engine.importProjection(value);const scope=await captureInbox(engine);
  assert.equal(projection(await store.read()).inbox.items[0].editable,false);
  await assert.rejects(saveInbox(engine,{scope,requestId:uuid(),itemId:id,payload:payload()}));
  for(const bad of [undefined,[],['unknown'],['inbox','inbox']]) {
    const copy=structuredClone(value);if(bad===undefined)delete copy.required_capabilities;else copy.required_capabilities=bad;
    assert.throws(()=>validateProjection(copy,'workspace'));
  }
  assert.throws(()=>validateProjection({...value,inbox:{items:[],retained:0}},'workspace'));
});
test('actual older parser plus atomic store rejects new kind/capability without any cursor/data changes',async()=>{
  const store=new MemoryStore('workspace','phone'),state=await store.read(),id=uuid();
  const inbox={version:2,operation_id:'inbox-create',workspace_id:'workspace',device_id:'peer',entity_type:'inbox_item',entity_id:id,
    action:'put',base_revision:0,depends_on:null,payload:payload(),incarnation:'inbox-create',parents:[],structure_revision:0};
  validateOperation(inbox,'workspace');
  const list={...inbox,operation_id:'list-create',entity_type:'list',entity_id:'list',payload:{name:'Known list',note:null},incarnation:'list-create'};
  await assert.rejects(store.update(next=>old.receive(next,[event(list,1),event(inbox,2)])));
  assert.deepEqual(await store.read(),state);
  await assert.rejects(store.update(next=>{next.readProjection=old.validateProjection(projected(),'workspace');}));
  assert.deepEqual(await store.read(),state);
});

test('local retained proposal keep-current is explicit, retry-safe and never queues replay',async()=>{
 const {store,engine}=setup(),scope=await captureInbox(engine),id=uuid();
 await saveInbox(engine,{scope,requestId:uuid(),itemId:id,payload:payload()});
 const old=observeInbox(await store.read(),id);
 await saveInbox(engine,{scope,requestId:uuid(),itemId:id,payload:payload('Newer'),observed:old});
 await saveInbox(engine,{scope,requestId:uuid(),itemId:id,payload:payload('Retained draft'),observed:old});
 const state=await store.read(),record=inboxReport(state).retained[0],requestId=uuid(),expected=observeInbox(state,id),count=state.outbox.length;
 const args={scope,requestId,choice:'canonical',observed:expected};
 const result=await resolveInbox(engine,record.id,args);assert.equal(result.status,'resolved');
 assert.deepEqual(await resolveInbox(engine,record.id,args),result);
 assert.equal((await store.read()).outbox.length,count);assert.equal(inboxReport(await store.read()).retained.length,0);
 assert.equal(inboxReport(await store.read()).items[0].payload.text,'Newer');
});
test('displayed retained resolution never silently adopts a newer canonical version',async()=>{
 const {store,engine}=setup(),scope=await captureInbox(engine),id=uuid();
 await saveInbox(engine,{scope,requestId:uuid(),itemId:id,payload:payload()});const old=observeInbox(await store.read(),id);
 await saveInbox(engine,{scope,requestId:uuid(),itemId:id,payload:payload('Newer'),observed:old});
 await saveInbox(engine,{scope,requestId:uuid(),itemId:id,payload:payload('Retained'),observed:old});
 const selected=inboxReport(await store.read()).retained[0],displayed=observeInbox(await store.read(),id);
 await saveInbox(engine,{scope,requestId:uuid(),itemId:id,payload:payload('Changed during review'),observed:displayed});
 await assert.rejects(resolveInbox(engine,selected.id,{scope,requestId:uuid(),choice:'canonical',observed:displayed}));
 assert.equal(inboxReport(await store.read()).items[0].payload.text,'Changed during review');assert.equal(inboxReport(await store.read()).retained.length,1);
});
