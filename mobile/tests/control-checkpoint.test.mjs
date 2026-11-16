import test from 'node:test';
import assert from 'node:assert/strict';
import {HttpTransport} from '../transport.mjs';
import {Engine} from '../engine.mjs';
import {MemoryStore} from '../store.mjs';
const identity={workspace_id:'work',device_id:'phone'};
const point=sequence=>({authority_id:'11111111-1111-4111-8111-111111111111',sequence,sha256:String(sequence).repeat(64)});
function fixture() {
 const state={sequence:1,supported:true,private:0,requests:[]};
 const fetch=async(url,options)=>{
  const path=new URL(url).pathname,body=JSON.parse(options.body);state.requests.push(path);
  const headers={'content-type':'application/json','X-Paperfact-Sync-Instance':'b'.repeat(32)};
  if(state.supported)headers['X-Paperfact-Control-History']='1';
  let value,status=200;
  if(path.endsWith('/session/info'))value=identity;
  else if(path.endsWith('/control/checkpoint')) {
   if(body.checkpoint && body.checkpoint.sequence>state.sequence){status=412;value={error:'sync_history_unavailable'};}
   else value={version:1,identity,accepted:body.checkpoint,checkpoint:point(state.sequence)};
  } else {
   const known=JSON.parse(atob(options.headers['X-Paperfact-Control-Checkpoint'].replaceAll('-','+').replaceAll('_','/')));
   assert.deepEqual(known,point(state.sequence));state.private++;value=[];
  }
  return new Response(JSON.stringify(value),{status,headers});
 };
 return {state,transport:()=>new HttpTransport('https://example.org',{fetch})};
}
test('control knowledge is saved separately without copying the research cache for private requests',async()=>{
 const fixtureValue=fixture(),store=new MemoryStore('work','phone');
 store.value.drafts.note='Unsent local note';const before=structuredClone(store.value);
 const transport=fixtureValue.transport(),engine=new Engine(store,{transport});
 await engine.connect('synthetic-token');assert.deepEqual(await store.readControlCheckpoint(),point(1));
 assert.deepEqual(store.value,before);
 store.read=async()=>{throw Error('bulk research/cache read');};
 await transport.pull('synthetic-token');assert.equal(fixtureValue.state.private,1);
 assert.deepEqual(store.value,before);
});
test('reconnect rejects rollback and removal of control support while preserving local notes and knowledge',async()=>{
 for(const change of ['rollback','downgrade']) {
  const fixtureValue=fixture(),store=new MemoryStore('work','phone');store.value.drafts.note='Saved offline';
  const first=new Engine(store,{transport:fixtureValue.transport()});await first.connect('synthetic-token');
  fixtureValue.state.sequence=2;await first.authenticated(first.generation);first.disconnect();
  const before=structuredClone(store.value);assert.deepEqual(await store.readControlCheckpoint(),point(2));
  if(change==='rollback')fixtureValue.state.sequence=1;else fixtureValue.state.supported=false;
  const reopened=new Engine(store,{transport:fixtureValue.transport()});
  await assert.rejects(reopened.connect('synthetic-token'),/sync_history_unavailable/);
  assert.deepEqual(await store.readControlCheckpoint(),point(2));assert.deepEqual(store.value,before);
  assert.equal(fixtureValue.state.private,0);
 }
});
test('failed persistence prevents authentication and stale control writes cannot replace newer knowledge',async()=>{
 const fixtureValue=fixture(),store=new MemoryStore('work','phone'),engine=new Engine(store,{transport:fixtureValue.transport()});
 store.failure='synthetic storage failure';await assert.rejects(engine.connect('synthetic-token'),/storage failure/);
 assert.equal(await store.readControlCheckpoint(),null);assert.equal(fixtureValue.state.private,0);
 store.failure=null;await engine.connect('synthetic-token');
 await store.writeControlCheckpoint(point(2),point(1));
 await assert.rejects(store.writeControlCheckpoint(point(1),null),/sync_history_unavailable/);
 assert.deepEqual(await store.readControlCheckpoint(),point(2));
});


test('concurrent control saves use compare-and-swap and never overwrite the winning prefix',async()=>{
 const store=new MemoryStore('work','phone');
 const results=await Promise.allSettled([
  store.writeControlCheckpoint(point(1),null),store.writeControlCheckpoint(point(2),null)]);
 assert.deepEqual(results.map(value=>value.status),['fulfilled','rejected']);
 assert.deepEqual(await store.readControlCheckpoint(),point(1));
 await store.writeControlCheckpoint(point(2),point(1));
 await assert.rejects(store.writeControlCheckpoint(point(1),point(2)),/sync_history_unavailable/);
 assert.deepEqual(await store.readControlCheckpoint(),point(2));
});

test('a replacement transport cannot silently remove a cached workspace control capability',async()=>{
 const store=new MemoryStore('work','phone');await store.writeControlCheckpoint(point(1),null);
 let calls=0;const engine=new Engine(store,{transport:{session_info:async()=>{calls++;return identity;}}});
 await assert.rejects(engine.connect('synthetic-token'),/sync_history_unavailable/);
 assert.equal(calls,0);assert.deepEqual(await store.readControlCheckpoint(),point(1));
});
