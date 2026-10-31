import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {MemoryStore} from '../store.mjs';
import {Engine} from '../engine.mjs';
import {demoTransport,PAPER} from '../fixture.mjs';
import {validateOperation,receive,projection,stable} from '../domain.mjs';
import {parsePositionJSON} from '../position-json.mjs';
import * as old from './fixtures/pre-position-domain.mjs';
const vectors=JSON.parse(readFileSync(new URL('../../tests/fixtures/reading-position-wire.json',import.meta.url),'utf8'));
for(const row of vectors.cases)test('independent Python raw-wire verdict '+row.name,()=>{
  const validate=()=>validateOperation(parsePositionJSON(row.wire),'demo-workspace');
  if(row.valid)validate();else assert.throws(validate);
});
const valid=()=>structuredClone(vectors.cases[0].operation);
const event=(operation,sequence)=>({sequence,outcome:'accepted',operation,head:{revision:sequence,operation}});
async function setup() {
  const transport=await demoTransport(),store=new MemoryStore('demo-workspace','demo-phone'),engine=new Engine(store);
  await store.update(state=>receive(state,transport.events));return {store,engine};
}
test('domain integers are ordinary JS values; lexical 1.0 and exponent aliases are rejected only at raw ingress',()=>{
  const op=valid();op.payload.data.page=1.0;validateOperation(op,'demo-workspace');
  for(const token of ['1.0','1e0','1E+0','-0'])assert.throws(()=>parsePositionJSON(JSON.stringify(op).replace('"page":1,','"page":'+token+',')));
  const raw=' { "note":"escaped \\\"page\\\":1.0", "rank":1.0,"negative":-2.75,"large":1e21,"small":-1e-7, "operation":'+
    JSON.stringify(op).replace('"page":1,','"p\\u0061ge":1,')+' } ';
  assert.equal(parsePositionJSON(raw).operation.payload.data.page,1);
  assert.equal(parsePositionJSON(raw).small,-1e-7);
  assert.throws(()=>parsePositionJSON(raw.replace('"p\\u0061ge":1,','"p\\u0061ge":1.0,')));
});
test('old receiver refuses the new content before atomic store/cursor mutation',async()=>{
  const {store}=await setup(),before=await store.read(),op=valid();
  await assert.rejects(store.update(state=>old.receive(state,[event(op,state.cursor+1)])));
  assert.deepEqual(await store.read(),before);
});
test('received position remains source-pinned, with normal known deletion and fresh restore',async()=>{
  const {store}=await setup(),op=valid();
  await store.update(state=>receive(state,[event(op,state.cursor+1)]));
  let paper=projection(await store.read()).papers.find(row=>row.id===PAPER);
  assert.equal(paper.research_content.find(row=>row.feature==='reading_position').key,op.payload.key);
  const deletion={...op,operation_id:'position-deleted',action:'delete',payload:{}};
  await store.update(state=>receive(state,[event(deletion,state.cursor+1)]));
  paper=projection(await store.read()).papers.find(row=>row.id===PAPER);
  assert(!paper.research_content?.some(row=>row.feature==='reading_position'));
  const restore={...op,operation_id:'position-restored',incarnation:'position-restored'};
  await store.update(state=>receive(state,[event(restore,state.cursor+1)]));
  assert(projection(await store.read()).papers.find(row=>row.id===PAPER).research_content.some(row=>row.feature==='reading_position'));
});
for(const change of ['parent','same-incarnation-restore','active-new-incarnation','delete-closure'])test('typed lifecycle refuses '+change+' atomically',async()=>{
  const {store}=await setup(),op=valid();
  await store.update(state=>receive(state,[event(op,state.cursor+1)]));
  const next={...structuredClone(op),operation_id:'next-position'};
  if(change==='parent')next.parents[0].incarnation='other-parent';
  if(change==='active-new-incarnation')next.incarnation=next.operation_id;
  if(change==='delete-closure'){next.action='delete';next.payload={};next.parents[0].incarnation='other-parent';}
  if(change==='same-incarnation-restore') {
    const deletion={...op,operation_id:'position-deleted',action:'delete',payload:{}};
    await store.update(state=>receive(state,[event(deletion,state.cursor+1)]));
  }
  const before=await store.read();
  await assert.rejects(store.update(state=>receive(state,[event(next,state.cursor+1)])));
  assert.equal(stable(await store.read()),stable(before));
});
