import test from 'node:test';
import assert from 'node:assert/strict';
import { contentId } from '../ids.mjs';
import { validateContent, suppressSnapshotContent } from '../content.mjs';
import { active, keyOf, projection, receive, validateOperation } from '../domain.mjs';
import { MemoryStore } from '../store.mjs';
import { demoTransport, operation, PAPER, ref } from '../fixture.mjs';
const TARGET = '00000000-0000-4000-8000-000000000002';
const payload = (source=PAPER,target=TARGET,value=1) => ({scope:{kind:'paper',id:source},
  feature:'reference_edge',key:target,data:{influential:value},source_document_hash:null});
const edge = (source=PAPER,target=TARGET,options={}) => {
  const item=payload(source,target);
  return operation('research_content',contentId(item.scope,item.feature,item.key),item,
    {parents:source===target?[ref('paper',source)]:[ref('paper',source),ref('paper',target)],...options});
};
async function fixture() {
  const transport = await demoTransport();
  const paper=transport.events.find(event=>event.operation.entity_type==='paper').operation.payload;
  await transport.push('fixture-token',operation('paper',TARGET,{...paper,title:'Target'},
    {device:'demo-phone'}));
  const op=edge(PAPER,TARGET,{device:'demo-phone'});
  await transport.push('fixture-token',op);
  const store = new MemoryStore('demo-workspace','demo-reader');
  await store.update(state=>receive(state,transport.events));
  return {transport,op,store};
}

test('two-paper portable edge survives offline restart and retries',async()=>{
  const {transport,store}=await fixture();
  const before=await store.read(), view=projection(before);
  assert.deepEqual(view.papers.find(p=>p.id===PAPER).references,[{paper_id:TARGET,influential:1,revision:8}]);
  assert.equal(before.graph[keyOf('paper',PAPER)].structure_revision,8);
  assert.equal(before.graph[keyOf('paper',TARGET)].structure_revision,8);
  const reopened=new MemoryStore(before.workspace,before.device,before);
  await reopened.update(state=>receive(state,transport.events));
  assert.deepEqual(projection(await reopened.read()),view);
});

for(const endpoint of [PAPER,TARGET]) for(const state of ['replaced','inactive'])
  test(`${endpoint} ${state} hides the dependent edge and keeps history`,async()=>{
    const {store,op}=await fixture();
    await store.update(value=>{
      const paper=value.graph[keyOf('paper',endpoint)];
      if(state==='replaced') paper.incarnation='replacement'; else paper.active=false;
    });
    const value=await store.read();
    assert.equal(active(value,'research_content',op.entity_id),false);
    const source=projection(value).papers.find(p=>p.id===PAPER);
    assert.ok(!source?.references?.length);
    assert.ok(value.receipts[op.operation_id]);
  });

test('self-edge uses one dependency and retains the original relation',async()=>{
  const transport=await demoTransport(), op=edge(PAPER,PAPER,{device:'demo-phone'});
  await transport.push('fixture-token',op);
  const store=new MemoryStore('demo-workspace','reader');
  await store.update(state=>receive(state,transport.events));
  assert.equal(op.parents.length,1);
  assert.equal(projection(await store.read()).papers.find(p=>p.id===PAPER).references[0].paper_id,PAPER);
});

for(const invalid of ['reversed','duplicate','missing','pdf-provenance','bad-flag','unknown-feature'])
  test(`closed edge rejects ${invalid} before state advances`,async()=>{
    const {store,op}=await fixture();
    const bad=structuredClone(op);
    if(invalid==='reversed') bad.parents.reverse();
    if(invalid==='duplicate') bad.parents[1]=structuredClone(bad.parents[0]);
    if(invalid==='missing') bad.parents.pop();
    if(invalid==='pdf-provenance') bad.payload.source_document_hash='a'.repeat(64);
    if(invalid==='bad-flag') bad.payload.data.influential=2;
    if(invalid==='unknown-feature') bad.payload.feature='future_reference_edge';
    const before=await store.read();
    assert.throws(()=>validateOperation(bad,'demo-workspace'));
    await assert.rejects(store.update(state=>receive(state,[{sequence:9,outcome:'accepted',operation:bad,
      head:{revision:9,operation:bad}}])));
    assert.deepEqual(await store.read(),before);
  });

test('delete removes one edge; explicit restore uses a new incarnation',async()=>{
  const {transport,store,op}=await fixture();
  const deleted={...op,operation_id:'edge-delete',action:'delete',payload:{},base_revision:8,structure_revision:8};
  await transport.push('fixture-token',deleted);
  await store.update(state=>receive(state,transport.events));
  assert.ok(!projection(await store.read()).papers.find(p=>p.id===PAPER).references?.length);
  const restored=edge(PAPER,TARGET,{device:'demo-phone',operationId:'edge-restore',base:9});
  await transport.push('fixture-token',restored);
  await store.update(state=>receive(state,transport.events));
  assert.equal(projection(await store.read()).papers.find(p=>p.id===PAPER).references.length,1);
  assert.notEqual(restored.incarnation,op.incarnation);
  const reversed={...deleted,parents:[...deleted.parents].reverse()};
  assert.throws(()=>validateOperation(reversed,'demo-workspace'));
});

test('typed content validator independently enforces both portable identities',()=>{
  const op=edge();
  assert.doesNotThrow(()=>validateContent(op.payload,op.entity_id,op.parents));
  assert.throws(()=>validateContent(op.payload,op.entity_id,[op.parents[0]]));
});

for(const action of ['put','delete']) test(`known ${action} suppresses a stale snapshot edge`,()=>{
  const op=edge();
  const papers=[{id:PAPER,references:[{paper_id:TARGET,influential:0},{paper_id:PAPER,influential:1}]}];
  const head={revision:2,operation:{...op,action,payload:action==='delete'?{}:op.payload}};
  const receipts=[{sequence:1,outcome:'accepted',operation:op}];
  suppressSnapshotContent(papers,[],[head],receipts,[]);
  assert.deepEqual(papers[0].references,[{paper_id:PAPER,influential:1}]);
});
