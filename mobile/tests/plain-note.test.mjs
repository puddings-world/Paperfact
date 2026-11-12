import {ReaderView,trackNoteObservation} from '../view.mjs';
import test from 'node:test';
import assert from 'node:assert/strict';
import {Engine} from '../engine.mjs';
import {MemoryStore} from '../store.mjs';
import {buildOperation,projection,receive} from '../domain.mjs';
import {demoTransport,PAPER,operation,ref} from '../fixture.mjs';

const stamp='2026-01-01T00:00:00+00:00';
async function setup(){
  const transport=await demoTransport(),store=new MemoryStore('demo-workspace','demo-phone'),engine=new Engine(store,{transport});
  await engine.connect('fixture-token');await engine.sync();
  const payload={paper_id:PAPER,body:'Desktop text',kind:'note',created_at:stamp,page:null,anchor:null};
  const op=operation('note','desktop-text',payload,{parents:[ref('paper',PAPER)]});
  await store.update(state=>receive(state,[{sequence:7,outcome:'accepted',operation:op,head:{revision:7,operation:op}}]));
  return {store,engine,payload};
}

test('desktop unpositioned note stays editable, saves once and preserves all non-body metadata',async()=>{
  const {store,engine,payload}=await setup();
  assert.equal(projection(await store.read()).notes.find(n=>n.id==='desktop-text').editable,true);
  const observed=await engine.observeNote('desktop-text',PAPER);
  await engine.draft('desktop-text','Offline draft',observed);engine.disconnect();
  const reopened=new MemoryStore('demo-workspace','demo-phone',await store.read());
  const offline=new Engine(reopened);
  const saved=await offline.saveNote('desktop-text',PAPER,'Offline draft');
  assert.deepEqual(saved.payload,{...payload,body:'Offline draft'});
  assert.equal((await offline.saveNote('desktop-text',PAPER,'Offline draft')).operation_id,saved.operation_id);
  assert.equal((await reopened.read()).outbox.length,1);
  assert(!Object.hasOwn((await reopened.read()).drafts,'desktop-text'));
});

test('plain text editor cannot flatten metadata or change creation, kind, position or parent',async()=>{
  const {store,payload}=await setup();const state=await store.read();
  for(const replacement of [
    {paper_id:PAPER,body:'Flattened'}, {...payload,created_at:'2025-01-01T00:00:00+00:00'},
    {...payload,kind:'quote'}, {...payload,page:1}, {...payload,anchor:{p0:0,o0:0,p1:0,o1:1}},
    {...payload,paper_id:'00000000-0000-4000-8000-000000000099'},
  ])assert.throws(()=>buildOperation(state,'note','desktop-text',replacement),/changed_note_metadata/);
  assert.equal((await store.read()).outbox.length,0);
  assert.equal(projection(await store.read()).notes.find(n=>n.id==='desktop-text').body,'Desktop text');
});

test('unpositioned desktop note delete creates one observed tombstone without flattening the original',async()=>{
  const {store,engine,payload}=await setup();const observed=await engine.observeNote('desktop-text',PAPER);
  const removed=await engine.deleteNote('desktop-text',{observed});
  assert.equal(removed.action,'delete');assert.deepEqual(removed.payload,{});
  assert.equal((await store.read()).outbox.length,1);
  assert.deepEqual((await store.read()).entities['note/desktop-text'].operation.payload,payload);
  assert(!projection(await store.read()).notes.some(n=>n.id==='desktop-text'));
});

test('clean note follows a newer base after save while a concurrently typed edit survives',()=>{
  const view=new ReaderView(),state={drafts:{}};
  view.edit('note','Saved body');view.saved('note','Saved body');
  assert(!Object.hasOwn(view.drafts,'note'));assert(!view.dirty.has('note'));
  view.observed.note={note_operation_id:'old'};
  trackNoteObservation(view,state,'note',{note_operation_id:'new'});
  assert.equal(view.observed.note.note_operation_id,'new');
  view.edit('note','New typing');view.saved('note','Saved body');
  trackNoteObservation(view,state,'note',{note_operation_id:'newer'});
  assert.equal(view.drafts.note,'New typing');assert(view.dirty.has('note'));
  assert.equal(view.observed.note.note_operation_id,'new');
});

test('persisted unsaved note keeps its old observed base across incoming revisions',()=>{
  const view=new ReaderView(),state={drafts:{note:'Retained draft'},draftBases:{note:{note_operation_id:'old'}}};
  view.refresh(state);
  trackNoteObservation(view,state,'note',{note_operation_id:'new'});
  assert.equal(view.drafts.note,'Retained draft');
  assert.equal(view.observed.note.note_operation_id,'old');
  assert.equal(state.drafts.note,'Retained draft');
});
