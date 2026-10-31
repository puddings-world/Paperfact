/** Closed, bounded private recovery. Archived operations never enter a live queue. */
import {closed,identifier,integer,requireThat,stable,validateEvent,validateOperation} from './domain.mjs';
import {copy,own,put} from './store.mjs';
import {sourceFileId,validateArtifact} from './artifacts.mjs';
import {digest,verifyOriginalCache,ARTIFACT_CACHE_BYTES} from './artifact-engine.mjs';
import {countPDFPages,requirePDFPageProof} from './pdf-page-count.mjs';
import {validatePositionData} from './reading-position-schema.mjs';
import {validateContentTimestamp} from './content.mjs';
import {CHUNK} from './transport.mjs';
import {parsePositionJSON} from './position-json.mjs';

export const MAX_RECOVERY_SOURCES=32*1024**2,MAX_RECOVERY_BYTES=64*1024**2;
const HASH=/^[0-9a-f]{64}$/,UUID=/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;
const encoder=new TextEncoder(),pendingImports=new WeakMap();
const archiveKeys=['id','workspace','device','cursor','outbox','conflicts','drafts','draftBases','positions','sources'];
const observationKeys=['paper_incarnation','source_operation_id','source_incarnation','position_operation_id','position_incarnation','position_action'];
function observation(value) {
  closed(value,observationKeys);
  for(const key of observationKeys.filter(key=>key!=='position_action'))if(value[key]!==null)identifier(value[key]);
  requireThat([null,'put','delete'].includes(value.position_action),'invalid_position_observation');
}
function map(value,limit=1000) {
  requireThat(value && typeof value==='object' && !Array.isArray(value) && Object.keys(value).length<=limit,'invalid_position_recovery');
  return Object.entries(value);
}
export function legacyRecovery(state) {
  return {format:'paperfact-mobile-recovery',version:1,workspace:state.workspace,device:state.device,cursor:state.cursor,
    outbox:copy(state.outbox),conflicts:copy(state.conflicts),drafts:copy(state.drafts),draftBases:copy(state.draftBases??{})};
}
function accepted(event,workspace,operation=null) {
  validateEvent(event,workspace);
  requireThat(event.outcome==='accepted' && (!operation || stable(event.operation)===stable(operation)),'invalid_recovery_provenance');
  return event.operation;
}
function source(value,workspace) {
  closed(value,['id','reference','parents','manifest','primary_receipt','source_receipt','source_operation']);
  validateArtifact(value.manifest,value.id,value.parents);
  requireThat(value.manifest.feature==='original_source' && value.parents.length===1,'invalid_recovery_source');
  const hash=value.manifest.slot,paper=value.manifest.paper_id;
  requireThat(value.id===sourceFileId(paper,hash) && value.reference===value.id+'/'+value.parents[0].incarnation,'invalid_recovery_source');
  if(value.source_operation!==null) {
    validateOperation(value.source_operation,workspace);
    requireThat(value.source_operation.action==='put' && value.source_operation.entity_type==='research_file' &&
      value.source_operation.entity_id===value.id && stable(value.source_operation.payload)===stable(value.manifest) &&
      stable(value.source_operation.parents)===stable(value.parents),'invalid_recovery_source');
  }
  requireThat(value.primary_receipt!==null || value.source_receipt!==null,'recovery_provenance_required');
  if(value.primary_receipt!==null) {
    const doc=accepted(value.primary_receipt,workspace);
    requireThat(doc.entity_type==='paper_document' && doc.action==='put' && doc.entity_id===paper &&
      doc.payload.sha256===hash && doc.payload.size===value.manifest.assets[0].size &&
      stable(doc.parents)===stable(value.parents),'invalid_recovery_provenance');
  }
  if(value.source_receipt!==null) {
    requireThat(value.source_operation!==null,'invalid_recovery_provenance');
    accepted(value.source_receipt,workspace,value.source_operation);
  }
  return value;
}
function row(value,sources,workspace) {
  closed(value,['id','kind','paper_id','document_hash','data','page_text','recorded_at','observed','operation','resolved_by','reason','source_id']);
  identifier(value.id);requireThat(UUID.test(value.paper_id) && HASH.test(value.document_hash),'invalid_position_recovery');
  requireThat(['intent','candidate','draft'].includes(value.kind),'invalid_position_recovery');
  observation(value.observed);if(value.resolved_by!==null)identifier(value.resolved_by);
  requireThat([null,'source_unavailable','stale_observation'].includes(value.reason) &&
    (value.kind==='candidate' || value.reason===null),'invalid_position_recovery');
  const declared=sources.find(item=>item.reference===value.source_id);
  requireThat(declared && declared.manifest.paper_id===value.paper_id && declared.manifest.slot===value.document_hash &&
    declared.parents[0].incarnation===value.observed.paper_incarnation,'invalid_recovery_source');
  if(value.kind==='draft') {
    requireThat(value.data===null && value.operation===null && value.resolved_by===null &&
      typeof value.page_text==='string' && value.page_text.length<=16,'invalid_position_draft');
    validateContentTimestamp(value.recorded_at);
  } else {
    requireThat(value.page_text===null && value.recorded_at===null,'invalid_position_recovery');
    validatePositionData(value.data,validateContentTimestamp);
    if(value.kind==='intent') {
      validateOperation(value.operation,workspace);
      requireThat(value.operation.operation_id===value.id && value.operation.action==='put' &&
        value.operation.entity_type==='research_content' && value.operation.payload.feature==='reading_position' &&
        value.operation.payload.scope.id===value.paper_id && value.operation.payload.key===value.document_hash &&
        stable(value.operation.payload.data)===stable(value.data) &&
        stable(value.operation.parents)===stable(declared.parents),'invalid_position_recovery');
    } else requireThat(value.operation===null,'invalid_position_recovery');
  }
}
function archive(value) {
  closed(value,archiveKeys);requireThat(HASH.test(value.id),'invalid_position_recovery');
  identifier(value.workspace);identifier(value.device);integer(value.cursor);
  requireThat(Array.isArray(value.outbox) && value.outbox.length<=1000,'invalid_position_recovery');
  for(const item of value.outbox) {
    closed(item,['operation','acknowledged']);validateOperation(item.operation,value.workspace);
    requireThat(item.operation.device_id===value.device,'invalid_position_recovery');
    if(item.acknowledged!==null){validateEvent(item.acknowledged,value.workspace);
      requireThat(stable(item.acknowledged.operation)===stable(item.operation),'invalid_position_recovery');}
  }
  for(const [id,item] of map(value.conflicts)) {
    identifier(id);closed(item,['event','resolvedBy']);validateEvent(item.event,value.workspace);
    requireThat(item.event.outcome==='conflict' && item.event.operation.operation_id===id,'invalid_position_recovery');
    if(item.resolvedBy!==null)identifier(item.resolvedBy);
  }
  for(const [id,text] of map(value.drafts)) {
    identifier(id);requireThat(typeof text==='string' && encoder.encode(text).length<=1024**2,'invalid_position_recovery');
  }
  for(const [id,base] of map(value.draftBases)) {
    identifier(id);closed(base,['paper_id','paper_incarnation','note_operation_id','note_incarnation','action','base_revision','depends_on']);
    identifier(base.paper_id);integer(base.base_revision);
    for(const key of ['paper_incarnation','note_operation_id','note_incarnation','depends_on'])if(base[key]!==null)identifier(base[key]);
    requireThat([null,'put','delete'].includes(base.action),'invalid_position_recovery');
  }
  requireThat(Array.isArray(value.positions) && value.positions.length<=500 && Array.isArray(value.sources) &&
    value.sources.length<=500,'position_recovery_limit');
  const ids=new Set();for(const item of value.sources){source(item,value.workspace);requireThat(!ids.has(item.reference),'duplicate_recovery_source');ids.add(item.reference);}
  const rows=new Set();for(const item of value.positions){row(item,value.sources,value.workspace);
    const key=item.kind+'/'+item.id;requireThat(!rows.has(key),'duplicate_recovery_position');rows.add(key);}
  requireThat(value.sources.every(item=>value.positions.some(row=>row.source_id===item.reference)),'unused_recovery_source');
}
async function archiveId(value) {const {id,...metadata}=value;return digest(encoder.encode(stable(metadata)));}
function origin(state,id) {
  const current=own(state.entities,'research_file/'+id)?.operation;
  if(current?.action==='put')return current;
  return current?own(state.receipts,current.incarnation)?.operation:null;
}
function declaration(state,paper,hash,observed,document=null) {
  const id=sourceFileId(paper,hash),stored=own(state.positionRetentions??{},id);
  const retention=stored?.document.parents[0].incarnation===observed.paper_incarnation?stored:null;
  const witnessed=observed.source_operation_id?own(state.receipts,observed.source_operation_id)?.operation:null;
  const operation=retention?.source_operation??witnessed??origin(state,id),manifest=retention?.manifest??operation?.payload;
  requireThat(manifest,'recovery_source_unavailable');
  const primary=retention?.document??document??null,parents=copy(primary?.parents??operation?.parents);
  const primaryReceipt=primary?own(state.receipts,primary.operation_id):null;
  const sourceReceipt=operation?own(state.receipts,operation.operation_id):null;
  return source({id,reference:id+'/'+parents[0].incarnation,parents,manifest:copy(manifest),
    primary_receipt:primaryReceipt?.outcome==='accepted'?copy(primaryReceipt):null,
    source_receipt:sourceReceipt?.outcome==='accepted'?copy(sourceReceipt):null,source_operation:copy(operation??null)},state.workspace);
}
function currentArchive(state) {
  const old=legacyRecovery(state),positions=[],sources=[];
  const add=(value,document=null)=>{
    const declared=declaration(state,value.paper_id,value.document_hash,value.observed,document);value.source_id=declared.reference;
    const previous=sources.find(item=>item.reference===declared.reference);
    if(previous)requireThat(stable(previous)===stable(declared),'conflicting_recovery_source');else sources.push(declared);
    positions.push(value);
  };
  for(const [id,intent] of map(state.positionIntents??{}))add({id,kind:'intent',paper_id:intent.operation.payload.scope.id,
    document_hash:intent.operation.payload.key,data:copy(intent.operation.payload.data),page_text:null,recorded_at:null,
    observed:copy(intent.observed),operation:copy(intent.operation),resolved_by:null,reason:null});
  for(const [id,candidate] of map(state.positionCandidates??{},500))add({id,kind:'candidate',paper_id:candidate.paper_id,
    document_hash:candidate.document_hash,data:copy(candidate.data),page_text:null,recorded_at:null,
    observed:copy(candidate.observed),operation:null,resolved_by:candidate.resolvedBy,reason:candidate.reason??'stale_observation'});
  for(const [scope,draft] of map(state.positionDrafts??{},500)) {
    const [paper,hash]=scope.split('/');add({id:draft.requestId,kind:'draft',paper_id:paper,document_hash:hash,data:null,
      page_text:draft.pageText,recorded_at:draft.recordedAt,observed:copy(draft.observed),operation:null,resolved_by:null,reason:null},draft.primary_document);
  }
  const {format,version,...base}=old;
  return {id:'0'.repeat(64),...base,positions,sources};
}
function base64(bytes) {
  let result='';for(let at=0;at<bytes.length;at+=12288)result+=btoa(String.fromCharCode(...bytes.subarray(at,at+12288)));
  return result;
}
function decode(value) {
  closed(value,['sha256','size','base64']);requireThat(HASH.test(value.sha256) && Number.isSafeInteger(value.size) &&
    value.size>0 && value.size<=MAX_RECOVERY_SOURCES && typeof value.base64==='string' &&
    value.base64.length===4*Math.ceil(value.size/3) && /^[A-Za-z0-9+/]*={0,2}$/.test(value.base64),
  'invalid_recovery_blob');
  const text=atob(value.base64),bytes=Uint8Array.from(text,char=>char.charCodeAt(0));
  requireThat(bytes.length===value.size && base64(bytes)===value.base64,'invalid_recovery_blob');return bytes;
}
function target(declared,workspace) {
  return declared.source_operation??{version:2,operation_id:'private-recovery-verification',workspace_id:workspace,
    device_id:'private-recovery',entity_type:'research_file',entity_id:declared.id,action:'put',base_revision:0,depends_on:null,
    payload:copy(declared.manifest),incarnation:'private-recovery-verification',parents:copy(declared.parents),structure_revision:0};
}
export async function exportPositionRecovery(state) {
  const current=currentArchive(state),archives=[];
  const retained=Object.keys(state.positionRecoveries??{}).length>0;
  if(current.positions.length || (retained && (current.outbox.length || Object.keys(current.conflicts).length ||
    Object.keys(current.drafts).length || Object.keys(current.draftBases).length))) {
    current.id=await archiveId(current);archives.push(current);
  }
  for(const [,entry] of map(state.positionRecoveries??{},16)) {
    closed(entry,['archive','reviewed']);map(entry.reviewed,500);archive(entry.archive);
    if(!archives.some(item=>item.id===entry.archive.id))archives.push(copy(entry.archive));
  }
  if(!archives.length)return legacyRecovery(state);
  requireThat(archives.length<=16,'position_recovery_limit');
  const blobs=new Map();let sourceBytes=0;
  for(const item of archives) {
    archive(item);requireThat(item.workspace===state.workspace,'wrong_recovery_workspace');
    for(const declared of item.sources) {
      const added=[declared.manifest.body,...declared.manifest.assets].filter(descriptor=>!blobs.has(descriptor.sha256))
        .reduce((sum,descriptor)=>sum+descriptor.size,0);
      requireThat(sourceBytes+added<=MAX_RECOVERY_SOURCES,'position_recovery_source_limit');
      const closure=await verifyOriginalCache(state,target(declared,item.workspace));
      for(const descriptor of [declared.manifest.body,...declared.manifest.assets])if(!blobs.has(descriptor.sha256)) {
        sourceBytes+=descriptor.size;requireThat(sourceBytes<=MAX_RECOVERY_SOURCES,'position_recovery_source_limit');
        blobs.set(descriptor.sha256,{sha256:descriptor.sha256,size:descriptor.size,base64:base64(closure.blobs.get(descriptor.sha256))});
      }
    }
  }
  const result={format:'paperfact-mobile-recovery',version:2,required_capabilities:['reading_position'],archives,blobs:[...blobs.values()]};
  requireThat(encoder.encode(stable({...result,blobs:[]})).length<=2*1024**2,'position_recovery_limit');
  requireThat(encoder.encode(JSON.stringify(result)).length<=MAX_RECOVERY_BYTES,'position_recovery_size_limit');return result;
}
export async function preparePositionRecovery(engine,text,{signal,current=()=>true}={}) {
  const generation=engine.generation,initial=await engine.store.read();engine.check(generation);
  requireThat(typeof text==='string' && text.length<=MAX_RECOVERY_BYTES && encoder.encode(text).length<=MAX_RECOVERY_BYTES,'position_recovery_size_limit');
  const value=parsePositionJSON(text,{maxBytes:MAX_RECOVERY_BYTES});
  closed(value,['format','version','required_capabilities','archives','blobs']);
  requireThat(value.format==='paperfact-mobile-recovery' && value.version===2 &&
    stable(value.required_capabilities)===stable(['reading_position']),'unsupported_recovery_capability');
  requireThat(Array.isArray(value.archives) && value.archives.length>0 && value.archives.length<=16 &&
    Array.isArray(value.blobs) && value.blobs.length<=1000,'position_recovery_limit');
  const metadata={...value,blobs:[]};requireThat(encoder.encode(stable(metadata)).length<=2*1024**2,'position_recovery_limit');
  const descriptors=new Map(),ids=new Set();
  for(const item of value.archives) {
    archive(item);requireThat(item.workspace===initial.workspace,'wrong_recovery_workspace');
    requireThat(!ids.has(item.id) && await archiveId(item)===item.id,'invalid_recovery_archive');ids.add(item.id);
    for(const declared of item.sources)for(const descriptor of [declared.manifest.body,...declared.manifest.assets]) {
      const previous=descriptors.get(descriptor.sha256);
      requireThat(!previous || previous.size===descriptor.size,'conflicting_recovery_source');descriptors.set(descriptor.sha256,descriptor);
    }
  }
  requireThat(value.archives.some(item=>item.positions.length>0),'unsupported_recovery_capability');
  const files={},proofs=new Map();let used=0;
  for(const item of value.blobs) {
    requireThat(!Object.hasOwn(files,item.sha256),'duplicate_recovery_blob');
    const descriptor=descriptors.get(item.sha256);requireThat(descriptor?.size===item.size,'undeclared_recovery_blob');
    used+=item.size;requireThat(used<=MAX_RECOVERY_SOURCES,'position_recovery_source_limit');
    const bytes=decode(item);requireThat(await digest(bytes)===item.sha256,'corrupt_file');
    const chunks=[];for(let at=0;at<bytes.length;at+=CHUNK)chunks.push(bytes.slice(at,at+CHUNK));
    put(files,item.sha256,{size:item.size,chunks,verified:true});
  }
  requireThat(Object.keys(files).length===descriptors.size,'missing_recovery_blob');
  const privateState={artifactFiles:files},linked=new AbortController(),session=engine.controller.signal,abort=()=>linked.abort();
  session.addEventListener('abort',abort,{once:true});signal?.addEventListener('abort',abort,{once:true});
  if(session.aborted || signal?.aborted)linked.abort();
  try {
    for(const item of value.archives)for(const declared of item.sources) {
      requireThat(current()&&!linked.signal.aborted,'cancelled');engine.check(generation);
      const closure=await verifyOriginalCache(privateState,target(declared,item.workspace)),hash=declared.manifest.slot;
      if(!proofs.has(hash))proofs.set(hash,await countPDFPages({bytes:closure.blobs.get(hash),sha256:hash},{signal:linked.signal}));
      for(const position of item.positions.filter(row=>row.source_id===declared.reference && row.data!==null))
        requirePDFPageProof(proofs.get(hash),hash,position.data.page);
    }
  } finally {session.removeEventListener('abort',abort);signal?.removeEventListener('abort',abort);}
  engine.check(generation);requireThat(current()&&!signal?.aborted,'cancelled');
  const token=Object.freeze({});pendingImports.set(token,{engine,generation,workspace:initial.workspace,device:initial.device,
    archives:copy(value.archives),files,current,signal});return token;
}
export async function importPositionRecovery(engine,prepared) {
  const ready=pendingImports.get(prepared);requireThat(ready?.engine===engine,'position_recovery_preparation_required');
  engine.check(ready.generation);requireThat(ready.current()&&!ready.signal?.aborted,'cancelled');
  const result=await engine.store.update(state=>{
    engine.check(ready.generation);requireThat(ready.current()&&!ready.signal?.aborted &&
      state.workspace===ready.workspace && state.device===ready.device,'stale_position_scope');
    state.positionRecoveries??={};state.artifactFiles??={};
    for(const item of ready.archives) {
      const previous=own(state.positionRecoveries,item.id);
      if(previous)requireThat(stable(previous.archive)===stable(item),'changed_recovery_archive');
      else put(state.positionRecoveries,item.id,{archive:copy(item),reviewed:{}});
    }
    requireThat(Object.keys(state.positionRecoveries).length<=16,'position_recovery_limit');
    requireThat(encoder.encode(stable(state.positionRecoveries)).length<=2*1024**2,'position_recovery_limit');
    let used=0;
    for(const [hash,file] of Object.entries(state.artifactFiles))if(!Object.hasOwn(ready.files,hash))used+=file.size;
    for(const [hash,file] of Object.entries(ready.files)){used+=file.size;put(state.artifactFiles,hash,copy(file));}
    requireThat(used<=ARTIFACT_CACHE_BYTES,'storage_quota');
    return ready.archives.map(item=>item.id);
  });
  engine.onChange('position_recovery_retained');return result;
}
export function recoveryRow(state,archiveId,rowId) {
  const entry=own(state.positionRecoveries??{},archiveId);requireThat(entry,'unknown_position_recovery');
  archive(entry.archive);requireThat(entry.archive.workspace===state.workspace,'wrong_recovery_workspace');
  const value=entry.archive.positions.find(row=>row.kind+'/'+row.id===rowId);
  requireThat(value && value.resolved_by===null && !own(entry.reviewed,rowId),'unknown_position_recovery');
  return {row:copy(value),source:copy(entry.archive.sources.find(item=>item.reference===value.source_id))};
}
export function markRecoveryReviewed(state,reference,paper,hash,requestId) {
  closed(reference,['archive_id','row_id']);const {row}=recoveryRow(state,reference.archive_id,reference.row_id);
  requireThat(row.paper_id===paper && row.document_hash===hash && requestId!==row.id,'invalid_recovery_review');
  const archive=state.positionRecoveries[reference.archive_id].archive;
  const oldIds=[...archive.outbox.map(item=>item.operation.operation_id),...Object.keys(archive.conflicts),
    ...archive.positions.map(item=>item.id),...archive.sources.flatMap(item=>
      [item.source_operation?.operation_id,item.primary_receipt?.operation.operation_id])];
  requireThat(!oldIds.includes(requestId),'archived_request_id');
  put(state.positionRecoveries[reference.archive_id].reviewed,reference.row_id,requestId);
}
export function recoveryReport(state) {
  return Object.entries(state.positionRecoveries??{}).flatMap(([archiveId,entry])=>entry.archive.positions.map(row=>
    ({archive_id:archiveId,row_id:row.kind+'/'+row.id,paper_id:row.paper_id,document_hash:row.document_hash,
      kind:row.kind,data:copy(row.data),page_text:row.page_text,reason:row.reason,reviewed_by:own(entry.reviewed,row.kind+'/'+row.id)??null})));
}
