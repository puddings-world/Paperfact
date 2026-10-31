import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {MemoryStore} from '../store.mjs';
import {Engine} from '../engine.mjs';
import {validateProjection} from '../domain.mjs';
import * as old from './fixtures/pre-position-domain.mjs';
const snapshot=JSON.parse(readFileSync(new URL('../../tests/fixtures/reading-position-snapshot.json',import.meta.url),'utf8'));
test('actual Python snapshot preserves A distinct B and exact three-capability union as read-only metadata',async()=>{
  const value=validateProjection(snapshot,snapshot.workspace_id),store=new MemoryStore(snapshot.workspace_id,'phone');
  const engine=new Engine(store);await engine.importProjection(snapshot);
  const state=await store.read();assert.equal(state.cursor,0);assert.deepEqual(state.outbox,[]);
  assert.deepEqual(value.required_capabilities,['inbox','queue_pin','reading_position']);
  assert.deepEqual(value.reading_positions,snapshot.reading_positions);
  assert.deepEqual(state.readProjection.reading_positions,snapshot.reading_positions);
  assert.deepEqual(value.assets,snapshot.assets);
  assert.deepEqual(state.readProjection.assets,snapshot.assets);
  const position=value.reading_positions[0];
  assert.notEqual(value.papers[0].pdf_asset_id,'sha256:'+position.document_hash);
  assert.deepEqual(state.artifactFiles,{});assert.deepEqual(state.appliedArtifacts,{});
});
for(const change of ['capability-missing','capability-extra','capability-order','missing-source','wrong-source','wrong-parent','wrong-asset','duplicate','unknown','version1'])test('snapshot '+change+' refuses atomically before state/cursor',async()=>{
  const value=structuredClone(snapshot),row=value.reading_positions[0];
  if(change==='capability-missing')value.required_capabilities.pop();
  if(change==='capability-extra')value.required_capabilities.push('unknown');
  if(change==='capability-order')value.required_capabilities.reverse();
  if(change==='missing-source')delete row.source;
  if(change==='wrong-source')row.source.manifest.source_document_hash='a'.repeat(64);
  if(change==='wrong-parent')row.source.parents[0].id='00000000-0000-4000-8000-000000000001';
  if(change==='wrong-asset')value.assets.find(asset=>asset.sha256===row.document_hash).size++;
  if(change==='duplicate')value.reading_positions.push(structuredClone(row));
  if(change==='unknown')row.page_count=20;
  if(change==='version1')value.schema_version=1;
  const store=new MemoryStore(value.workspace_id,'phone'),engine=new Engine(store),before=await store.read();
  await assert.rejects(engine.importProjection(value));assert.deepEqual(await store.read(),before);
});
test('previous actual mobile validator refuses the earlier unknown envelope field atomically',async()=>{
  const store=new MemoryStore(snapshot.workspace_id,'phone');
  await store.update(state=>{state.drafts.note='Keep draft';});const before=await store.read();
  await assert.rejects(store.update(state=>{
    state.readProjection=old.validateProjection(snapshot,snapshot.workspace_id);
  }),/^Error: invalid_data$/);
  assert.deepEqual(await store.read(),before);
});
test('previous validator refuses the later capability when its envelope is otherwise known',()=>{
  const value=structuredClone(snapshot);delete value.reading_positions;
  assert.throws(()=>old.validateProjection(value,value.workspace_id),/^Error: unsupported_capability$/);
});
