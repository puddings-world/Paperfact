import test from 'node:test';
import assert from 'node:assert/strict';
import {validateAnchor,validateRichNote} from '../content.mjs';
import {MemoryStore} from '../store.mjs';
import {projection,receive} from '../domain.mjs';
import {demoTransport,PAPER,operation,ref} from '../fixture.mjs';
import {Engine} from '../engine.mjs';

const hash='a'.repeat(64);
const note=()=>({paper_id:PAPER,body:'My interpretation',kind:'note',
  created_at:'2026-11-01T00:00:00+00:00',page:1,
  anchor:{p0:0,o0:0,p1:0,o1:3,document_hash:hash,selection:{version:1,
    quote:'A verified source paper',extractor:{name:'paperfact.level_words',engine:'pymupdf',version:'1.26.4'}}}});

test('reviewed passage and extractor survive independent mobile receipt and reload',async()=>{
  const value=note(); validateRichNote(value);
  assert.throws(()=>validateAnchor(value.anchor));
  const store=new MemoryStore('demo-workspace','demo-phone');
  const engine=new Engine(store,{transport:await demoTransport()});
  await engine.connect('fixture-token'); await engine.sync();
  const op=operation('note','reviewed-source-note',value,{parents:[ref('paper',PAPER)]});
  await store.update(state=>receive(state,[{sequence:7,outcome:'accepted',operation:op,head:{revision:7,operation:op}}]));
  const reload=new MemoryStore('demo-workspace','demo-phone',await store.read());
  const saved=projection(await reload.read()).notes.find(n=>n.id==='reviewed-source-note');
  assert.deepEqual(saved.anchor,value.anchor);
  assert.equal(saved.pdf_hash,hash);
});

test('mobile refuses missing provenance, unsupported versions, extra fields and excessive quotes',()=>{
  for(const mutate of [
    a=>{a.document_hash=null;}, a=>{a.selection.version=true;},
    a=>{a.selection.quote='字'.repeat(11000);}, a=>{a.selection.extractor.engine='model';},
    a=>{a.selection.extractor.extra=true;},a=>{a.p1=100;},
    a=>{a.selection.extractor.version='1.26.4\n';},
    a=>{a.selection.extractor.version='1.26.4\n';}
  ]) {
    const value=note(); mutate(value.anchor);
    assert.throws(()=>validateRichNote(value));
  }
});
