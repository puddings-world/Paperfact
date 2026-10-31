/** Read-only current positions and exact original declarations; no viewport inference. */
import {active,keyOf,optimistic,statusFor} from './domain.mjs';
import {copy,own} from './store.mjs';
import {contentId} from './ids.mjs';
const positionId=(paper,hash)=>contentId({kind:'paper',id:paper},'reading_position',hash);
export function positionReport(state,paper) {
  const view=optimistic(state),live=active(view,'paper',paper),rows=[],sources=[];
  if(!live) {
    const snapshot=own(view.graph,keyOf('paper',paper))?[]:(state.readProjection?.reading_positions??[]).filter(row=>row.paper_id===paper);
    return {positions:snapshot.map(row=>({...copy(row),id:positionId(paper,row.document_hash),status:'local',read_only:true})),
      sources:[],retained:[],drafts:{}};
  }
  for(const {operation:op} of Object.values(view.entities)) {
    if(op.action!=='put' || !active(view,op.entity_type,op.entity_id))continue;
    if(op.entity_type==='research_file' && op.payload.feature==='original_source' && op.payload.paper_id===paper)
      sources.push({id:op.entity_id,document_hash:op.payload.slot,operation_id:op.operation_id});
    if(op.entity_type==='research_content' && op.payload.feature==='reading_position' && op.payload.scope.id===paper)
      rows.push({paper_id:paper,document_hash:op.payload.key,...copy(op.payload.data),id:op.entity_id,status:statusFor(state,'research_content',op.entity_id),read_only:false});
  }
  for(const row of state.readProjection?.reading_positions??[])if(row.paper_id===paper &&
      !own(view.entities,keyOf('research_content',positionId(paper,row.document_hash))) &&
      row.source.parents[0].incarnation===view.graph[keyOf('paper',paper)].incarnation)
    rows.push({...copy(row),id:positionId(paper,row.document_hash),status:'local',read_only:true});
  const retained=Object.entries(state.positionCandidates??{}).filter(([,row])=>row.paper_id===paper&&!row.resolvedBy &&
    row.observed.paper_incarnation===view.graph[keyOf('paper',paper)].incarnation)
    .map(([id,row])=>({id,...copy(row),source:'local'}));
  for(const [id,conflict] of Object.entries(state.conflicts)) {
    const op=conflict.event.operation;
    if(!conflict.resolvedBy && op.action==='put' && op.entity_type==='research_content' && op.payload.feature==='reading_position' && op.payload.scope.id===paper &&
      op.parents[0].incarnation===view.graph[keyOf('paper',paper)].incarnation)
      retained.push({id,paper_id:paper,document_hash:op.payload.key,data:copy(op.payload.data),source:'remote'});
  }
  return {positions:rows.sort((a,b)=>a.document_hash.localeCompare(b.document_hash)),sources:sources.sort((a,b)=>a.document_hash.localeCompare(b.document_hash)),
    retained,drafts:copy(state.positionDrafts??{})};
}

