/** Typed retention of already-owned accepted primary bytes; never a PDF uploader. */
import {active,enqueue,keyOf,optimistic,requireThat,stable,validateEvent,validateOperation} from './domain.mjs';
import {copy,own,put} from './store.mjs';
import {sourceFileId,validateArtifact} from './artifacts.mjs';
import {ARTIFACT_CACHE_BYTES,artifactTarget,digest,verifyOriginalCache} from './artifact-engine.mjs';
import {uuid5Name} from './ids.mjs';
import {CHUNK} from './transport.mjs';
import {countPDFPages,requirePDFPageProof} from './pdf-page-count.mjs';
const preparations=new WeakMap(),counts=new WeakMap();
const UUID=/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;
const ID=/^[A-Za-z0-9_.:-]{1,128}$/;
function closed(value,keys) {
  requireThat(value && typeof value==='object' && !Array.isArray(value) && Object.keys(value).length===keys.length &&
    keys.every(key=>Object.hasOwn(value,key)),'invalid_primary_retention');
}
export function primaryReference(state,document,expectedPaper=document?.entity_id) {
  validateOperation(document,state.workspace);
  requireThat(document.version===2 && document.entity_type==='paper_document' && document.action==='put' &&
    document.entity_id===document.payload.paper_id && document.entity_id===expectedPaper,'invalid_primary_reference');
  const event=own(state.receipts,document.operation_id);
  requireThat(event?.outcome==='accepted' && stable(event.operation)===stable(document),'primary_receipt_required');
  validateEvent(event,state.workspace);
  const view=optimistic(state),paper=document.entity_id,parent=document.parents[0];
  requireThat(parent?.kind==='paper' && parent.id===paper && active(view,'paper',paper) &&
    view.graph[keyOf('paper',paper)].incarnation===parent.incarnation,'primary_parent_changed');
  const id=sourceFileId(paper,document.payload.sha256),graph=state.graph[keyOf('research_file',id)];
  requireThat(!graph || active(state,'research_file',id),'position_original_retired');
  return {paper,hash:document.payload.sha256,size:document.payload.size,parent:copy(parent),id};
}
export async function preparePrimaryRetention(document,bytes,proof) {
  const hash=document.payload.sha256,paper=document.payload.paper_id;
  requirePDFPageProof(proof,hash,1);
  requireThat(bytes instanceof Uint8Array && bytes.length===proof.size && bytes.length===document.payload.size,'invalid_primary_bytes');
  const exact=new Uint8Array(bytes);
  requireThat(await digest(exact)===hash,'corrupt_file');
  const body=new TextEncoder().encode(stable({version:1,paper_id:paper,document_hash:hash})),bodyHash=await digest(body);
  const manifest={paper_id:paper,feature:'original_source',slot:hash,format_version:1,source_document_hash:hash,
    input_versions:{schema_version:1,complete:false,entities:[],documents:[],inputs_sha256:null},
    body:{sha256:bodyHash,size:body.length,media_type:'application/json'},
    assets:[{id:'original',role:'original_pdf',sha256:hash,size:exact.length,media_type:'application/pdf'}]};
  validateArtifact(manifest,sourceFileId(paper,hash),document.parents);
  const chunks=[];for(let at=0;at<exact.length;at+=CHUNK)chunks.push(exact.slice(at,at+CHUNK));
  const token=Object.freeze({});preparations.set(token,{document:copy(document),manifest,body,chunks});return token;
}
export function retentionBudget(state) {
  requireThat(Object.keys(state.positionRetentions??{}).length<=500 && Object.keys(state.positionIntents??{}).length<=1000 &&
    new TextEncoder().encode(stable([state.positionRetentions??{},state.positionIntents??{}])).length<=2*1024**2,'position_retention_limit');
}
export function admitPrimaryRetention(state,prepared,requestId,{publish=true}={}) {
  const ready=preparations.get(prepared);requireThat(ready && UUID.test(requestId),'primary_preparation_required');
  const reference=primaryReference(state,ready.document),view=optimistic(state),existing=artifactTarget(view,reference.id);
  if(existing)requireThat(stable(existing.payload)===stable(ready.manifest) && stable(existing.parents)===stable(ready.document.parents),'conflicting_original_source');
  state.positionRetentions??={};state.artifactFiles??={};
  const previous=own(state.positionRetentions,reference.id);
  if(previous)validateRetention(state,reference.id,previous);
  let source=existing;
  if(!source && publish) {
    const operationId=uuid5Name('paperfact:position-original:'+requestId);
    source={version:2,operation_id:operationId,workspace_id:state.workspace,device_id:state.device,
      entity_type:'research_file',entity_id:reference.id,action:'put',base_revision:0,depends_on:null,
      payload:copy(ready.manifest),incarnation:operationId,parents:copy(ready.document.parents),structure_revision:0};
    validateOperation(source,state.workspace);enqueue(state,source);
  }
  const used=Object.entries(state.artifactFiles).filter(([hash])=>![reference.hash,ready.manifest.body.sha256].includes(hash))
    .reduce((total,[,file])=>total+file.chunks.reduce((sum,chunk)=>{
      requireThat(chunk instanceof Uint8Array && chunk.length<=CHUNK,'invalid_retention_cache');return sum+chunk.length;
    },0),0);
  requireThat(used+reference.size+ready.body.length<=ARTIFACT_CACHE_BYTES,'storage_quota');
  put(state.artifactFiles,reference.hash,{size:reference.size,chunks:copy(ready.chunks),verified:true});
  put(state.artifactFiles,ready.manifest.body.sha256,{size:ready.body.length,chunks:[new Uint8Array(ready.body)],verified:true});
  const retention={version:1,document:copy(previous?.document??ready.document),manifest:copy(ready.manifest),
    source_operation_id:source?.operation_id??null,source_operation:copy(source??null)};
  put(state.positionRetentions,reference.id,retention);retentionBudget(state);
  return reference.id;
}
export function validateRetention(state,id,entry) {
  closed(entry,['version','document','manifest','source_operation_id','source_operation']);
  requireThat(entry.version===1 && (entry.source_operation_id===null ||
    (typeof entry.source_operation_id==='string' && ID.test(entry.source_operation_id))),'invalid_primary_retention');
  const reference=primaryReference(state,entry.document);
  requireThat(id===reference.id,'invalid_primary_retention');
  validateArtifact(entry.manifest,id,entry.document.parents);
  requireThat(entry.manifest.feature==='original_source' && entry.manifest.paper_id===reference.paper &&
    entry.manifest.slot===reference.hash && entry.manifest.assets[0].size===reference.size,'invalid_primary_retention');
  requireThat((entry.source_operation===null)===(entry.source_operation_id===null),'invalid_primary_retention');
  if(entry.source_operation!==null) {
    validateOperation(entry.source_operation,state.workspace);
    requireThat(entry.source_operation.operation_id===entry.source_operation_id && entry.source_operation.entity_type==='research_file' &&
      entry.source_operation.entity_id===id && entry.source_operation.action==='put' &&
      stable(entry.source_operation.payload)===stable(entry.manifest) &&
      stable(entry.source_operation.parents)===stable(entry.document.parents),'invalid_primary_retention');
  }
  return reference;
}
function cacheTarget(state,id,entry) {
  const ref=validateRetention(state,id,entry),view=optimistic(state),source=artifactTarget(view,id);
  if(source) {
    requireThat(stable(source.payload)===stable(entry.manifest) && stable(source.parents)===stable(entry.document.parents),'stale_position_original');
    return source;
  }
  return {version:2,operation_id:entry.source_operation_id??entry.document.operation_id,
    workspace_id:state.workspace,device_id:state.device,entity_type:'research_file',entity_id:ref.id,action:'put',
    base_revision:0,depends_on:null,payload:copy(entry.manifest),incarnation:entry.source_operation_id??entry.document.operation_id,
    parents:copy(entry.document.parents),structure_revision:0};
}
export async function readPrimaryRetention(state,id) {
  const entry=own(state.positionRetentions??{},id);requireThat(entry,'artifact_unavailable');
  const target=cacheTarget(state,id,entry),verified=await verifyOriginalCache(state,target);
  return {...verified,operation:target,document:copy(entry.document),awaiting:false};
}
export function registerPositionIntent(state,operation,source,observed,retentionId=null) {
  validateOperation(operation,state.workspace);
  validateOperation(source,state.workspace);
  requireThat(operation.entity_type==='research_content' && operation.payload.feature==='reading_position' &&
    operation.payload.data.method==='entered' && source.entity_type==='research_file' && source.action==='put' && source.payload.feature==='original_source' &&
    source.payload.paper_id===operation.payload.scope.id && source.payload.slot===operation.payload.key &&
    stable(source.parents)===stable(operation.parents),'invalid_position_intent');
  validateArtifact(source.payload,source.entity_id,source.parents);
  validateObservation(observed);
  requireThat(retentionId===null || retentionId===source.entity_id,'invalid_position_intent');
  state.positionIntents??={};
  put(state.positionIntents,operation.operation_id,{version:1,operation:copy(operation),source_id:source.entity_id,
    manifest:copy(source.payload),parents:copy(source.parents),observed:copy(observed),retention_id:retentionId});
  retentionBudget(state);
}
function validateObservation(value) {
  const fields=['paper_incarnation','source_operation_id','source_incarnation','position_operation_id','position_incarnation','position_action'];
  closed(value,fields);
  for(const key of fields.filter(key=>key!=='position_action'))requireThat(value[key]===null ||
    (typeof value[key]==='string' && ID.test(value[key])),'invalid_position_observation');
  requireThat([null,'put','delete'].includes(value.position_action),'invalid_position_observation');
}
function intentSource(state,intent) {
  closed(intent,['version','operation','source_id','manifest','parents','observed','retention_id']);
  requireThat(intent.version===1,'invalid_position_intent');validateOperation(intent.operation,state.workspace);
  validateObservation(intent.observed);
  const op=intent.operation;
  requireThat(op.entity_type==='research_content' && op.action==='put' && op.payload.feature==='reading_position' &&
    op.payload.data.method==='entered' && intent.source_id===sourceFileId(op.payload.scope.id,op.payload.key),'invalid_position_intent');
  validateArtifact(intent.manifest,intent.source_id,intent.parents);
  requireThat(intent.manifest.feature==='original_source' && intent.manifest.slot===op.payload.key &&
    intent.manifest.paper_id===op.payload.scope.id && stable(intent.parents)===stable(op.parents),'invalid_position_intent');
  const view=optimistic(state),parent=op.parents[0];
  requireThat(active(view,'paper',parent.id) && view.graph[keyOf('paper',parent.id)].incarnation===parent.incarnation,'primary_parent_changed');
  if(intent.retention_id!==null) {
    requireThat(intent.retention_id===intent.source_id,'invalid_position_intent');
    validateRetention(state,intent.retention_id,own(state.positionRetentions??{},intent.retention_id));
  }
  const retention=own(state.positionRetentions??{},intent.retention_id??'');
  let expected=intent.observed.source_incarnation;
  const retained=retention?.source_operation;
  if(expected===null && retained) {
    // Older closed private intents captured the original's absence before
    // admitting their own deterministic source pair. Only that exact pair
    // proves the source lifetime; a later mutable retention entry cannot.
    const ownId=uuid5Name('paperfact:position-original:'+op.operation_id);
    if(retained.operation_id===ownId && retained.incarnation===ownId && retained.device_id===op.device_id)
      expected=ownId;
  }
  requireThat(typeof expected==='string' && (!retained || retained.incarnation===expected),
    'position_source_lifetime_changed');
  const matchingLifetime=source=>requireThat(typeof expected==='string' && source.incarnation===expected &&
    (!retained || retained.incarnation===expected),'position_source_lifetime_changed');
  const queued=state.outbox.find(row=>row.operation.operation_id===retention?.source_operation_id);
  const acknowledgement=queued?.acknowledged;
  if(acknowledgement?.outcome==='conflict')return null;
  const canonical=artifactTarget(state,intent.source_id);
  if(canonical) {
    requireThat(stable(canonical.payload)===stable(intent.manifest) && stable(canonical.parents)===stable(intent.parents),
      'stale_position_original');
    matchingLifetime(canonical);
    validateOperation(canonical,state.workspace);return canonical;
  }
  const graph=state.graph[keyOf('research_file',intent.source_id)];
  requireThat(!graph || active(state,'research_file',intent.source_id),'position_original_retired');
  if(acknowledgement?.outcome==='accepted') {
    validateEvent(acknowledgement,state.workspace);
    requireThat(stable(acknowledgement.operation)===stable(queued.operation) &&
      stable(queued.operation.payload)===stable(intent.manifest) && stable(queued.operation.parents)===stable(intent.parents),'invalid_position_prerequisite');
    matchingLifetime(queued.operation);
    return queued.operation;
  }
  return null;
}
export function reconcilePositionIntents(state) {
  for(const [id,entry] of Object.entries(state.positionRetentions??{})) {
    try {validateRetention(state,id,entry);}
    catch(error) {
      if(!['primary_parent_changed','position_original_retired'].includes(error.message))throw error;
      state.outbox=state.outbox.filter(row=>row.operation.operation_id!==entry.source_operation_id || row.acknowledged);
    }
  }
  for(const [id,intent] of Object.entries(state.positionIntents??{})) {
    const queued=state.outbox.find(row=>row.operation.operation_id===id && !row.acknowledged);
    if(!queued)continue;
    requireThat(stable(queued.operation)===stable(intent.operation),'changed_position_intent');
    let blocked=false;
    try {
      const source=intentSource(state,intent);
      const retention=own(state.positionRetentions??{},intent.retention_id??'');
      const receipt=retention && own(state.receipts,retention.source_operation_id??'');
      blocked=!source && receipt?.outcome==='conflict';
    } catch(error) {
      if(!['primary_parent_changed','position_original_retired','conflicting_original_source','stale_position_original',
        'position_source_lifetime_changed'].includes(error.message))throw error;
      blocked=true;
    }
    if(!blocked)continue;
    state.positionCandidates??={};
    put(state.positionCandidates,id,{paper_id:intent.operation.payload.scope.id,document_hash:intent.operation.payload.key,
      data:copy(intent.operation.payload.data),observed:copy(intent.observed),resolvedBy:null,reason:'source_unavailable'});
    const retention=own(state.positionRetentions??{},intent.retention_id??'');
    state.outbox=state.outbox.filter(row=>row.operation.operation_id!==id &&
      (row.operation.operation_id!==retention?.source_operation_id || row.acknowledged));
  }
}
export async function preparePositionPush(engine,operation,token,generation) {
  const state=await engine.store.read();engine.check(generation);
  const sourceEntry=Object.entries(state.positionRetentions??{}).find(([,entry])=>entry.source_operation_id===operation.operation_id);
  if(sourceEntry && operation.entity_type==='research_file') {
    const [id,entry]=sourceEntry;validateRetention(state,id,entry);
    requireThat(stable(operation)===stable(entry.source_operation),'changed_primary_retention');
    const closure=await readPrimaryRetention(state,id);engine.check(generation);
    await engine.authenticated(generation);
    await engine.transport.uploadOriginalBody(token,entry.manifest,closure.blobs.get(entry.manifest.body.sha256),engine.controller.signal);
    engine.check(generation);
    const latest=await engine.store.read();engine.check(generation);
    validateRetention(latest,id,entry);
    return true;
  }
  if(operation.entity_type!=='research_content' || operation.payload?.feature!=='reading_position')return true;
  const intent=own(state.positionIntents??{},operation.operation_id);
  requireThat(intent && stable(intent.operation)===stable(operation),'position_intent_required');
  const target=intentSource(state,intent);if(!target)return false;
  const closure=await verifyOriginalCache(state,target);engine.check(generation);
  const hash=operation.payload.key;let byHash=counts.get(engine);
  if(!byHash || byHash.generation!==generation){byHash={generation,proofs:new Map()};counts.set(engine,byHash);}
  let proof=byHash.proofs.get(hash);
  if(!proof){proof=await countPDFPages({bytes:closure.blobs.get(hash),sha256:hash},{signal:engine.controller.signal});engine.check(generation);byHash.proofs.set(hash,proof);}
  requirePDFPageProof(proof,hash,operation.payload.data.page);
  const latest=await engine.store.read();engine.check(generation);
  return intentSource(latest,intent)!==null;
}
