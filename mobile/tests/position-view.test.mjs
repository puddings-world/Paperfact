import test from 'node:test';
import assert from 'node:assert/strict';
import {POSITION_COPY,choiceLabel,positionChoices} from '../position-view.mjs';
import {demoTransport,operation,ref,PAPER} from '../fixture.mjs';
import {emptyState,copy} from '../store.mjs';
import {receive,stable} from '../domain.mjs';
import {sourceFileId} from '../artifacts.mjs';
import {contentId} from '../ids.mjs';
const event=(operation,sequence)=>({sequence,outcome:'accepted',operation,head:{revision:sequence,operation}});
async function setup(){const state=emptyState('demo-workspace','demo-phone');receive(state,(await demoTransport()).events);return state;}
test('source choices use human labels and actual records, never cache flags as count/viewport proof',async()=>{
  assert.deepEqual(Object.keys(POSITION_COPY.en).sort(),Object.keys(POSITION_COPY['zh-TW']).sort());
  const state=await setup(),before=stable(state),view=positionChoices(state,PAPER),source=view.options[0];
  assert(view.writable);assert(source.current);assert(!Object.hasOwn(source,'pageCount'));
  for(const locale of ['en','zh-TW']){assert.equal(choiceLabel(source,locale),POSITION_COPY[locale].current);assert(!choiceLabel(source,locale).includes(source.hash));}
  assert.equal(stable(state),before);
});
test('current C arrival keeps a selected accepted B distinct and does not manufacture opened/page history',async()=>{
  const state=await setup(),selected=positionChoices(state,PAPER).options[0],C=copy(selected.document);
  C.operation_id='new-current-C';C.payload.sha256='c'.repeat(64);receive(state,[event(C,state.cursor+1)]);
  const view=positionChoices(state,PAPER,{selected}),B=view.options.find(row=>row.hash===selected.hash);
  assert(B && !B.current && B.held);assert.equal(view.default_hash,C.payload.sha256);
  assert.equal(view.positions.length,0);assert.equal(Object.keys(state.positionDrafts??{}).length,0);
});
test('a unique explicitly kept B page draft reopens without choosing current C or inferring last viewport',async()=>{
  const state=await setup(),selected=positionChoices(state,PAPER).options[0],hash=selected.hash;
  state.positionDrafts={[PAPER+'/'+hash]:{pageText:'2',requestId:crypto.randomUUID(),recordedAt:'2026-10-31T01:00:00Z',
    observed:{paper_incarnation:selected.document.parents[0].incarnation},primary_document:selected.document}};
  const result=positionChoices(state,PAPER);assert.equal(result.default_hash,hash);assert.equal(result.options[0].draft.pageText,'2');
});
for(const change of ['retired','parent-replaced','paper-deleted'])test('selected source is not revived after '+change,async()=>{
  const state=await setup(),selected=positionChoices(state,PAPER).options[0];
  if(change==='retired')state.graph['research_file/'+sourceFileId(PAPER,selected.hash)]={active:false};
  if(change==='parent-replaced')state.graph['paper/'+PAPER].incarnation='other-lifetime';
  if(change==='paper-deleted')state.graph['paper/'+PAPER].active=false;
  assert(!positionChoices(state,PAPER,{selected}).options.some(row=>row.hash===selected.hash));
});
test('snapshot positions stay labelled read-only and known deleted page needs explicit restore',async()=>{
  const state=await setup(),source=positionChoices(state,PAPER).options[0],id=contentId({kind:'paper',id:PAPER},'reading_position',source.hash);
  const original=operation('research_content',id,{scope:{kind:'paper',id:PAPER},feature:'reading_position',key:source.hash,
    source_document_hash:source.hash,data:{page:2,recorded_at:'2026-10-31T01:00:00Z',method:'entered'}},
    {operationId:'old-position',parents:[ref('paper',PAPER)]});
  state.receipts[original.operation_id]=event(original,20);state.cursor=21;
  state.entities['research_content/'+id]={operation:{...original,operation_id:'position-delete',action:'delete',payload:{}},revision:21,created:20};
  state.graph['research_content/'+id]={active:false,incarnation:original.incarnation,parents:original.parents,structure_revision:21};
  assert.equal(positionChoices(state,PAPER).options[0].deleted,true);
  const snapshot=emptyState('demo-workspace','demo-phone');snapshot.readProjection={reading_positions:[{paper_id:PAPER,
    document_hash:source.hash,page:2,recorded_at:'2026-10-31T01:00:00Z',method:'entered'}]};
  const view=positionChoices(snapshot,PAPER);assert(!view.writable);assert(view.options[0].read_only);assert(view.positions[0].read_only);
});
test('an unproven tombstone never becomes a typed deleted-page claim or writable restore choice',async()=>{
  const state=await setup(),source=positionChoices(state,PAPER).options[0],id=contentId({kind:'paper',id:PAPER},'reading_position',source.hash);
  state.entities['research_content/'+id]={operation:operation('research_content',id,{},
    {action:'delete',operationId:'unknown-delete',incarnation:'missing-origin',parents:[ref('paper',PAPER)]}),revision:20,created:20};
  state.graph['research_content/'+id]={active:false,incarnation:'missing-origin',parents:[ref('paper',PAPER)],structure_revision:20};
  const view=positionChoices(state,PAPER);assert.equal(view.options[0].deleted,false);assert.equal(view.options[0].read_only,true);
});
