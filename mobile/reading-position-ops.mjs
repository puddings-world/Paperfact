/** Explicit entered pages for existing exact originals. No automatic viewport tracking. */
import {active,enqueue,keyOf,optimistic,requireThat,stable,validateOperation} from './domain.mjs';
import {validateContentTimestamp} from './content.mjs';
import {copy,own,put} from './store.mjs';
import {artifactTarget} from './artifact-engine.mjs';
import {contentId} from './ids.mjs';
import {sourceFileId} from './artifacts.mjs';
import {countPDFPages,requirePDFPageProof} from './pdf-page-count.mjs';
import {validatePositionData} from './reading-position-schema.mjs';
import {primaryReference,preparePrimaryRetention,admitPrimaryRetention,readPrimaryRetention,registerPositionIntent} from './primary-source-retention.mjs';
import {markRecoveryReviewed,recoveryRow} from './position-recovery.mjs';
const captures=new WeakSet(),captureData=new WeakMap(),reviews=new WeakMap(),UUID=/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;
const positionId=(paper,hash)=>contentId({kind:'paper',id:paper},'reading_position',hash);
export function observePosition(state,paper,hash) {
  const view=optimistic(state),source=artifactTarget(view,sourceFileId(paper,hash)),
    position=view.entities[keyOf('research_content',positionId(paper,hash))]?.operation;
  return {paper_incarnation:view.graph[keyOf('paper',paper)]?.incarnation??null,
    source_operation_id:source?.operation_id??null,source_incarnation:source?.incarnation??null,
    position_operation_id:position?.operation_id??null,position_incarnation:position?.incarnation??null,
    position_action:position?.action??null};
}
function currentSource(state,paper,hash) {
  const view=optimistic(state),source=artifactTarget(view,sourceFileId(paper,hash));
  requireThat(active(view,'paper',paper) && source?.payload.feature==='original_source' &&
    source.payload.paper_id===paper && source.payload.slot===hash && source.parents.length===1 &&
    source.parents[0].incarnation===view.graph[keyOf('paper',paper)].incarnation,'position_source_unavailable');
  return source;
}
function check(engine,state,captured,current) {
  requireThat(captures.has(captured),'position_capture_required');
  requireThat(captureData.get(captured)?.engine===engine,'stale_position_scope');
  const scope=JSON.parse(captured.json);engine.check(scope.generation);
  requireThat(current() && state.workspace===scope.workspace && state.device===scope.device,'stale_position_scope');
  if(scope.primary_document) {
    const reference=primaryReference(state,scope.primary_document,scope.paper);
    requireThat(reference.hash===scope.hash && reference.parent.incarnation===scope.observed.paper_incarnation,'stale_position_source');
    return scope;
  }
  const source=currentSource(state,scope.paper,scope.hash);
  requireThat(source.operation_id===scope.observed.source_operation_id &&
    source.incarnation===scope.observed.source_incarnation &&
    source.parents[0].incarnation===scope.observed.paper_incarnation,'stale_position_source');
  return scope;
}
function captureResult(engine,state,generation,paper,hash,bytes,proof,source,document=null) {
  const id=positionId(paper,hash),snapshot=state.readProjection?.reading_positions?.some(row=>row.paper_id===paper && row.document_hash===hash);
  requireThat(!snapshot || own(state.entities,keyOf('research_content',id)),'position_history_required');
  requirePDFPageProof(proof,hash,1);
  const captured=Object.freeze({json:stable({generation,workspace:state.workspace,device:state.device,paper,hash,
    primary_document:document?copy(document):null,observed:observePosition(state,paper,hash)}),proof});
  captures.add(captured);captureData.set(captured,{engine,bytes,document:document?copy(document):null});
  return {captured,bytes,source:source?copy(source):null,document:document?copy(document):null,pageCount:proof.pageCount};
}
async function sourceCount(engine,generation,bytes,hash,signal) {
  engine.check(generation);const session=engine.controller.signal;
  if(!signal || signal===session)return countPDFPages({bytes,sha256:hash},{signal:session});
  const linked=new AbortController(),abort=()=>linked.abort();
  session.addEventListener('abort',abort,{once:true});signal.addEventListener('abort',abort,{once:true});
  if(session.aborted || signal.aborted)linked.abort();
  try {return await countPDFPages({bytes,sha256:hash},{signal:linked.signal});}
  finally {session.removeEventListener('abort',abort);signal.removeEventListener('abort',abort);}
}
export async function openPrimaryPositionSource(engine,paper,{current=()=>true,signal,document=null}={}) {
  const generation=engine.generation,initial=await engine.store.read();engine.check(generation);
  requireThat(current() && !signal?.aborted,'stale_position_scope');
  const selected=copy(document??initial.entities[keyOf('paper_document',paper)]?.operation);
  const reference=primaryReference(initial,selected,paper);let bytes;
  if(document===null) {
    const result=await engine.pdf(paper);engine.check(generation);
    requireThat(result.sha256===reference.hash,'stale_position_source');bytes=result.bytes;
  } else {
    const file=own(initial.files,reference.hash)??own(initial.artifactFiles??{},reference.hash);
    requireThat(file?.verified && file.size===reference.size && file.size<=32*1024**2,'file_unavailable');
    bytes=new Uint8Array(file.size);let offset=0;
    for(const chunk of file.chunks) {
      requireThat(chunk instanceof Uint8Array && offset+chunk.length<=bytes.length,'corrupt_file');
      bytes.set(chunk,offset);offset+=chunk.length;
    }
    requireThat(offset===bytes.length,'corrupt_file');
  }
  const proof=await sourceCount(engine,generation,bytes,reference.hash,signal);engine.check(generation);
  const now=await engine.store.read();engine.check(generation);requireThat(current()&&!signal?.aborted,'stale_position_scope');
  primaryReference(now,selected,paper);
  if(document===null)requireThat(stable(now.entities[keyOf('paper_document',paper)]?.operation)===stable(selected),'stale_position_source');
  return captureResult(engine,now,generation,paper,reference.hash,bytes,proof,null,selected);
}
export async function openPositionSource(engine,paper,hash,{current=()=>true,signal,download=false}={}) {
  const generation=engine.generation,initial=await engine.store.read();engine.check(generation);
  requireThat(current() && !signal?.aborted,'stale_position_scope');
  const id=sourceFileId(paper,hash),retention=own(initial.positionRetentions??{},id);
  if(retention)primaryReference(initial,retention.document,paper);
  const target=retention?artifactTarget(optimistic(initial),id):currentSource(initial,paper,hash);
  let original;
  try {original=await engine.originalSource(id);}
  catch(error) {
    if(retention && error.message==='artifact_unavailable')original=await readPrimaryRetention(initial,id);
    else {
    if(!download || error.message!=='artifact_unavailable')throw error;
    await engine.downloadArtifact(id);engine.check(generation);
    requireThat(current() && !signal?.aborted,'stale_position_scope');
    original=await engine.originalSource(id);
    }
  }
  if(target)requireThat(stable(original.operation)===stable(target) && !original.awaiting,'stale_position_source');
  engine.check(generation);
  const bytes=original.blobs.get(hash),proof=await sourceCount(engine,generation,bytes,hash,signal);
  engine.check(generation);requireThat(current() && !signal?.aborted,'stale_position_scope');
  const now=await engine.store.read();engine.check(generation);
  requireThat(current(),'stale_position_scope');
  if(retention) {
    primaryReference(now,retention.document,paper);
    requireThat(stable(own(now.positionRetentions??{},id))===stable(retention),'stale_position_source');
  } else requireThat(stable(currentSource(now,paper,hash))===stable(target),'stale_position_source');
  requireThat(proof.size===original.operation.payload.assets[0].size,'stale_position_source');
  return captureResult(engine,now,generation,paper,hash,bytes,proof,target,retention?.document??null);
}
function budget(state) {
  requireThat(Object.keys(state.positionRequests??{}).length<=1000 && Object.keys(state.positionCandidates??{}).length<=500 &&
    new TextEncoder().encode(stable([state.positionRequests??{},state.positionCandidates??{},state.positionDrafts??{}])).length<=2*1024**2,'position_history_limit');
}
function observation(value) {
  const fields=['paper_incarnation','source_operation_id','source_incarnation','position_operation_id','position_incarnation','position_action'];
  requireThat(value && typeof value==='object' && Object.keys(value).length===fields.length && fields.every(key=>Object.hasOwn(value,key)),'invalid_position_observation');
  for(const key of fields.filter(key=>key!=='position_action'))requireThat(value[key]===null || (typeof value[key]==='string' && /^[A-Za-z0-9_.:-]{1,128}$/.test(value[key])),'invalid_position_observation');
  requireThat([null,'put','delete'].includes(value.position_action),'invalid_position_observation');
}
export async function draftPosition(engine,captured,{pageText,requestId,recordedAt,observed=null},{current=()=>true}={}) {
  requireThat(typeof pageText==='string' && pageText.length<=16 && UUID.test(requestId),'invalid_position_draft');
  validateContentTimestamp(recordedAt);if(observed!==null)observation(observed);
  requireThat(captures.has(captured) && captureData.get(captured)?.engine===engine,'position_capture_required');
  const privateView=captureData.get(captured),scope=JSON.parse(captured.json);
  const prepared=scope.primary_document?await preparePrimaryRetention(privateView.document,privateView.bytes,captured.proof):null;
  return engine.store.update(state=>{
    const scope=check(engine,state,captured,current);state.positionDrafts??={};
    if(prepared)admitPrimaryRetention(state,prepared,requestId,{publish:false});
    put(state.positionDrafts,scope.paper+'/'+scope.hash,{pageText,requestId,recordedAt,observed:copy(observed??scope.observed),
      primary_document:scope.primary_document?copy(scope.primary_document):null});
    budget(state);
  });
}
export async function saveEnteredPosition(engine,captured,{page,recordedAt,requestId,observed=null,
  restore=false,resolutionOf=null,candidateId=null,recoveryOf=null,current=()=>true,notify=true}) {
  requireThat(UUID.test(requestId) && typeof restore==='boolean','invalid_position_request');
  const scopeInitial=JSON.parse(captured?.json??'null');
  requireThat(captures.has(captured),'position_capture_required');
  requireThat(captureData.get(captured)?.engine===engine,'stale_position_scope');
  requirePDFPageProof(captured.proof,scopeInitial.hash,page);
  const data={page,recorded_at:recordedAt,method:'entered'};validatePositionData(data,validateContentTimestamp);
  const expected=copy(observed??scopeInitial.observed);observation(expected);
  const privateView=captureData.get(captured);
  const primaryPrepared=scopeInitial.primary_document?
    await preparePrimaryRetention(privateView.document,privateView.bytes,captured.proof):null;
  const request={paper:scopeInitial.paper,hash:scopeInitial.hash,data,observed:expected,restore,resolutionOf,candidateId,recoveryOf,
    primary_document_id:scopeInitial.primary_document?.operation_id??null};
  const fingerprint=[...new Uint8Array(await crypto.subtle.digest('SHA-256',new TextEncoder().encode(stable(request))))]
    .map(value=>value.toString(16).padStart(2,'0')).join('');
  const result=await engine.store.update(state=>{
    const scope=check(engine,state,captured,current),id=positionId(scope.paper,scope.hash),key=keyOf('research_content',id);
    state.positionRequests??={};state.positionCandidates??={};
    const prior=own(state.positionRequests,requestId);
    if(prior){requireThat(prior.fingerprint===fingerprint,'changed_position_retry');return prior.result;}
    if(recoveryOf) {
      const recovered=recoveryRow(state,recoveryOf.archive_id,recoveryOf.row_id).row;
      requireThat(recovered.paper_id===scope.paper && recovered.document_hash===scope.hash && requestId!==recovered.id,
        'invalid_recovery_review');
    }
    let result;
    if(stable(observePosition(state,scope.paper,scope.hash))!==stable(expected)) {
      if(primaryPrepared)admitPrimaryRetention(state,primaryPrepared,requestId,{publish:false});
      put(state.positionCandidates,requestId,{paper_id:scope.paper,document_hash:scope.hash,data:copy(data),observed:expected,resolvedBy:null});
      result={status:'retained',request_id:requestId,entity_id:id,candidate_id:requestId};
    } else {
      const retentionId=primaryPrepared?admitPrimaryRetention(state,primaryPrepared,requestId):null;
      const view=optimistic(state),previous=view.entities[key]?.operation,graph=view.graph[key];
      const live=active(view,'research_content',id);
      if(previous && !live)requireThat(restore,'explicit_restore_required');
      if(restore)requireThat(previous && !live,'invalid_position_restore');
      if(resolutionOf) {
        const conflict=own(state.conflicts,resolutionOf);
        requireThat(conflict && !conflict.resolvedBy && conflict.event.operation.entity_type==='research_content' &&
          conflict.event.operation.entity_id===id,'unknown_position_conflict');
      }
      if(candidateId) {
        const candidate=own(state.positionCandidates,candidateId);
        requireThat(candidate && !candidate.resolvedBy && candidate.paper_id===scope.paper && candidate.document_hash===scope.hash &&
          candidate.observed.paper_incarnation===scope.observed.paper_incarnation,'unknown_position_candidate');
      }
      if(!resolutionOf && live && previous.payload.data.page===page && previous.payload.data.method==='entered') {
        result={status:'unchanged',request_id:requestId,entity_id:id,candidate_id:null};
      } else {
        const pending=[...state.outbox].reverse().find(item=>keyOf(item.operation.entity_type,item.operation.entity_id)===key);
        const operation={version:2,operation_id:requestId,workspace_id:state.workspace,device_id:state.device,
          entity_type:'research_content',entity_id:id,action:'put',base_revision:state.entities[key]?.revision??0,
          depends_on:pending?.operation.operation_id??null,payload:{scope:{kind:'paper',id:scope.paper},feature:'reading_position',
            key:scope.hash,source_document_hash:scope.hash,data:copy(data)},
          incarnation:(!previous||restore)?requestId:previous.incarnation,
          parents:[{kind:'paper',id:scope.paper,incarnation:scope.observed.paper_incarnation}],structure_revision:graph?.structure_revision??0};
        if(resolutionOf)operation.resolution_of=resolutionOf;
        validateOperation(operation,state.workspace);enqueue(state,operation);
        registerPositionIntent(state,operation,currentSource(state,scope.paper,scope.hash),expected,retentionId);
        result={status:'saved',request_id:requestId,entity_id:id,candidate_id:null};
      }
      if(candidateId)state.positionCandidates[candidateId].resolvedBy=requestId;
      if(state.positionDrafts?.[scope.paper+'/'+scope.hash]?.requestId===requestId)delete state.positionDrafts[scope.paper+'/'+scope.hash];
    }
    if(recoveryOf && result.status!=='retained')markRecoveryReviewed(state,recoveryOf,scope.paper,scope.hash,requestId);
    put(state.positionRequests,requestId,{fingerprint,result:copy(result)});budget(state);return result;
  });
  if(notify)engine.onChange(result.status==='retained'?'conflict':'saved_locally');return result;
}
export {positionReport} from './reading-position-report.mjs';

export async function prepareRecoveryReview(engine,archiveId,rowId,{current=()=>true,signal}={}) {
  const generation=engine.generation;await engine.authenticated(generation);
  const state=await engine.store.read();engine.check(generation);
  const recovered=recoveryRow(state,archiveId,rowId),{row,source}=recovered;
  const view=optimistic(state),parent=source.parents[0];
  requireThat(current() && active(view,'paper',row.paper_id) &&
    view.graph[keyOf('paper',row.paper_id)].incarnation===parent.incarnation,'primary_parent_changed');
  // The export's receipt is historical evidence. Only the current receiver's
  // independently received receipt/source may authorize a new local request.
  let opened;
  if(source.primary_receipt) {
    const document=source.primary_receipt.operation;
    primaryReference(state,document,row.paper_id);
    opened=await openPrimaryPositionSource(engine,row.paper_id,{current,signal,document});
  } else {
    const live=currentSource(state,row.paper_id,row.document_hash);
    requireThat(stable(live.payload)===stable(source.manifest) && stable(live.parents)===stable(source.parents),'stale_position_source');
    opened=await openPositionSource(engine,row.paper_id,row.document_hash,{current,signal});
  }
  engine.check(generation);requireThat(current()&&!signal?.aborted,'cancelled');
  const token=Object.freeze({});reviews.set(token,{engine,generation,archiveId,rowId,opened,current});
  return {token,bytes:opened.bytes,pageCount:opened.pageCount,row:copy(row)};
}
export async function saveRecoveryReview(engine,token,{page,recordedAt,requestId,restore=false,current=()=>true}) {
  const ready=reviews.get(token);requireThat(ready?.engine===engine,'position_recovery_review_required');
  engine.check(ready.generation);requireThat(ready.current()&&current(),'stale_position_scope');
  await engine.authenticated(ready.generation);
  return saveEnteredPosition(engine,ready.opened.captured,{page,recordedAt,requestId,restore,
    recoveryOf:{archive_id:ready.archiveId,row_id:ready.rowId},current:()=>ready.current()&&current()});
}

export async function positionPageHint(engine,captured,page,{loadedHash,current=()=>true,blocked=()=>false}={}) {
  requireThat(!blocked(),'position_draft_or_busy');
  const state=await engine.store.read(),scope=check(engine,state,captured,current);
  requireThat(loadedHash===scope.hash,'position_source_not_loaded');
  requireThat(!blocked(),'position_draft_or_busy');
  requirePDFPageProof(captured.proof,scope.hash,page);
  requireThat(stable(observePosition(state,scope.paper,scope.hash))===stable(scope.observed),'stale_position_record');
  const view=optimistic(state),op=view.entities[keyOf('research_content',positionId(scope.paper,scope.hash))]?.operation;
  requireThat(op?.action==='put' && active(view,'research_content',op.entity_id) && op.payload.data.page===page,'stale_position_record');
  return page; // A native object may ignore this explicit hint; no viewport claim.
}
