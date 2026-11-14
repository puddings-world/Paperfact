/** Exact live Lineage source leases. Saved report metadata never grants PDF access. */
import {active,keyOf,optimistic,stable,validateOperation} from './domain.mjs';
import {artifactTarget} from './artifact-engine.mjs';
import {contentId} from './ids.mjs';
import {validateLineageOperation} from './lineage-ops.mjs';
import {validateLineageBody} from './lineage.mjs';
const leases=new WeakMap();
const requireThat=(value,code='lineage_source_unavailable')=>{if(!value)throw new Error(code);};
function targetIn(state,paper,row,sourceId){
 state=optimistic(state);
 const body=validateLineageBody(row.body),source=body.report.sources.find(s=>s.id===sourceId);
 requireThat(body.bindings[0].paper_id===paper && source?.availability==='available');
 const id=contentId({kind:'paper',id:paper},'lineage',body.corpus_id);
 const operation=state.entities[keyOf('research_content',id)]?.operation;
 requireThat(operation?.action==='put' && active(state,'research_content',id));
 validateOperation(operation,state.workspace);validateLineageOperation(operation);
 requireThat(stable(operation.payload.data)===stable({body_json:row.body,
  source_hash:row.source_hash,document_hash:row.document_hash,written_at:row.written_at}),'stale_lineage_source');
 const pin=operation.source_dependencies.find(p=>p.source_id===sourceId),
  binding=body.bindings.find(b=>b.source_id===sourceId);
 requireThat(pin && binding && pin.paper_id===binding.paper_id);
 const target=artifactTarget(state,pin.file_id),parent=operation.parents.find(p=>p.id===pin.paper_id);
 requireThat(target?.action==='put' && target.incarnation===pin.incarnation &&
  target.payload.feature==='original_source' && target.payload.paper_id===pin.paper_id &&
  target.payload.slot===source.document_hash && target.payload.source_document_hash===source.document_hash &&
  stable(target.parents)===stable([parent]));
 validateOperation(target,state.workspace);
 return {operation,target,source};
}
export function lineageSourceAvailable(state,paper,row,sourceId){
 try{targetIn(state,paper,row,sourceId);return true;}catch{return false;}
}
function live(engine,generation,current,signal){
 engine.check(generation);requireThat(current()&&!signal?.aborted,'stale_lineage_scope');
}
export async function openLineageSource(engine,paper,row,sourceId,
 {download=false,current=()=>true,signal}={}){
 requireThat(typeof download==='boolean' && typeof current==='function');
 const generation=engine.generation,initial=await engine.store.read();
 live(engine,generation,current,signal);
 const observed=targetIn(initial,paper,row,sourceId);
 let original;
 try {original=await engine.originalSource(observed.target.entity_id);}
 catch(error){
  if(!download||error.message!=='artifact_unavailable')throw error;
  live(engine,generation,current,signal);
  const now=targetIn(await engine.store.read(),paper,row,sourceId);
  live(engine,generation,current,signal);
  requireThat(stable(now)===stable(observed),'stale_lineage_source');
  await engine.downloadArtifact(observed.target.entity_id);
  live(engine,generation,current,signal);
  original=await engine.originalSource(observed.target.entity_id);
 }
 live(engine,generation,current,signal);
 requireThat(!original.awaiting && stable(original.operation)===stable(observed.target),'stale_lineage_source');
 const bytes=original.blobs.get(observed.source.document_hash);
 requireThat(bytes instanceof Uint8Array && bytes.length===observed.target.payload.assets[0].size);
 const now=targetIn(await engine.store.read(),paper,row,sourceId);
 live(engine,generation,current,signal);
 requireThat(stable(now)===stable(observed),'stale_lineage_source');
 const receipt=Object.freeze({source_id:sourceId,sha256:observed.source.document_hash,
  page_count:observed.source.page_count});
 leases.set(receipt,{engine,generation,paper,row:structuredClone(row),sourceId,
  observed:stable(observed),bytes:new Uint8Array(bytes)});
 return receipt;
}
export async function lineageSourceForDelivery(engine,receipt,{current=()=>true,signal}={}){
 const lease=leases.get(receipt);requireThat(lease?.engine===engine,'stale_lineage_scope');
 live(engine,lease.generation,current,signal);
 const now=targetIn(await engine.store.read(),lease.paper,lease.row,lease.sourceId);
 live(engine,lease.generation,current,signal);
 requireThat(stable(now)===lease.observed,'stale_lineage_source');
 return new Uint8Array(lease.bytes);
}
