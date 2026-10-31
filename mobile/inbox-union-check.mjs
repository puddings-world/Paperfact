/** Actual Python union snapshot -> independent mobile validation, no network. */
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {validateProjection,stable} from './domain.mjs';
import {MemoryStore} from './store.mjs';
import {Engine} from './engine.mjs';
const fixture=JSON.parse(readFileSync(process.argv[2],'utf8'));
const {snapshot,pin_owner:pinOwner,pin,items}=fixture;
assert.deepEqual(snapshot.required_capabilities,['inbox','queue_pin']);
const raw=stable(snapshot),store=new MemoryStore(snapshot.workspace_id,'fixture-phone'),notices=[];
await store.update(state=>{state.cursor=73;state.drafts.reader='Unsent phone draft';});
const engine=new Engine(store,{transport:new Proxy({}, {get(){throw Error('No network allowed');}}),
  onChange:event=>notices.push(event)});
await engine.importProjection(snapshot);
const valid=await store.read();
assert.deepEqual(valid.readProjection.required_capabilities,['inbox','queue_pin']);
assert.deepEqual(valid.readProjection.papers.find(row=>row.id===pinOwner).queue_pin,{pinned_at:pin});
for(const [id,expected] of Object.entries(items)) {
 const item=valid.readProjection.inbox.items.find(row=>row.id===id);assert(item);
 assert.deepEqual(item.payload,expected.payload);assert.equal(item.active,expected.active);
}
assert.equal(valid.cursor,73);assert.equal(valid.drafts.reader,'Unsent phone draft');
assert.deepEqual(valid.outbox,[]);assert.deepEqual(valid.entities,{});assert.deepEqual(valid.receipts,{});
assert.equal(notices.length,1);assert.equal(stable(snapshot),raw);
const failures=[
 ['missing',s=>{delete s.required_capabilities;}],
 ['missing-inbox',s=>{s.required_capabilities=['queue_pin'];}],
 ['missing-pin',s=>{s.required_capabilities=['inbox'];}],
 ['empty',s=>{s.required_capabilities=[];}],
 ['extra',s=>{s.required_capabilities=['future','inbox','queue_pin'];}],
 ['duplicate',s=>{s.required_capabilities=['inbox','inbox','queue_pin'];}],
 ['unsorted',s=>{s.required_capabilities=['queue_pin','inbox'];}],
 ['unused-inbox',s=>{delete s.inbox;}],
 ['unused-pin',s=>{for(const row of s.papers)delete row.queue_pin;}],
];
for(const [name,mutate] of failures) {
 const bad=structuredClone(snapshot);mutate(bad);
 assert.throws(()=>validateProjection(bad,snapshot.workspace_id),undefined,name);
 await assert.rejects(engine.importProjection(bad),undefined,name);
 assert.deepEqual(await store.read(),valid,name+' changed state/cursor/draft/outbox');
 assert.equal(notices.length,1,name+' announced a false import');
}
console.log('PASS combined Python snapshot: exact Inbox+queue-pin capabilities, independent offline read, '+failures.length+' fail-closed capability cases preserve state/cursor/draft/outbox');
