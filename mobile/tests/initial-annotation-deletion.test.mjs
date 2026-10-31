import test from 'node:test';
import assert from 'node:assert/strict';
import { initialAnnotationDeletion, suppressSnapshotContent } from '../content.mjs';
import { ANNOTATION_FEATURES } from '../annotations.mjs';
import { contentId } from '../ids.mjs';
import { operation, PAPER, ref } from '../fixture.mjs';
import { emptyState } from '../store.mjs';
import { receive, projection, validateOperation } from '../domain.mjs';

function events(feature) {
  const parent = operation('paper',PAPER,{title:'Research paper',authors:[],year:null,
    venue:null,abstract:null,doi:null,arxiv_id:null,s2_id:null,page_url:null,pdf_url:null,source:null});
  const deletion = operation('research_content',contentId({kind:'paper',id:PAPER},feature,'main'),{},
    {operationId:'initial-'+feature,parents:[ref('paper',PAPER)],action:'delete'});
  const event=(op,sequence)=>({sequence,outcome:'accepted',operation:op,head:{revision:sequence,operation:op}});
  return [event(parent,1),event(deletion,2)];
}
for(const feature of ANNOTATION_FEATURES) test(`initial ${feature} tombstone suppresses stale snapshot without invented content`,()=>{
  const rows=events(feature);
  validateOperation(rows[1].operation,'demo-workspace');
  const inferred=initialAnnotationDeletion(rows[1].operation,rows);
  assert.deepEqual(inferred,{scope:{kind:'paper',id:PAPER},feature,key:'main'});
  const papers=[{id:PAPER,research_content:[{feature,data:{body:'old cached content'}},{feature:'citation',data:{title:'preserved'}}]}];
  const mark={paper_id:PAPER,origin:'ai',quote:'cached mark'};
  const result=suppressSnapshotContent(papers,[],rows,[],[mark]);
  assert.deepEqual(papers[0].research_content.map(row=>row.feature),['citation']);
  if(feature==='highlight_analysis') {
    assert.equal(papers[0].highlight_analysis_known,true);
    assert.deepEqual(result.archived,[mark]);
  } else assert.deepEqual(result.live,[mark]);
  const state=emptyState('demo-workspace','phone');
  receive(state,rows);
  const view=projection(state);
  assert.equal(view.papers.length,1);
  assert.equal(view.papers[0].research_content?.length ?? 0,0);
  assert.equal(state.graph['research_content/'+rows[1].operation.entity_id].active,false);
});

test('unknown singleton ID, wrong parent and payload never authorize inference',()=>{
  const rows=events('claims'),op=rows[1].operation;
  for(const bad of [
    {...op,entity_id:contentId({kind:'paper',id:PAPER},'dive','main')},
    {...op,parents:[ref('paper',PAPER,'other-incarnation')]},
    {...op,parents:[ref('list','list')]},
    {...op,payload:{feature:'claims'}},
    {...op,payload:[]},
    {...op,version:3},
  ]) assert.equal(initialAnnotationDeletion(bad,rows),null);
  assert.equal(initialAnnotationDeletion(op,[]),null);
});
