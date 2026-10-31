/** Closed legacy workflow metadata and Markdown; observations grant no job authority. */
import {contentId,uuid5Name,asciiJSON} from './ids.mjs';
export const LEGACY_FIELDS = {
  queue_entry:'rank state role parent_id reason queued_at delivered_at read_at',
  reading_event:'delivered_at role note brief'
};
export const MAX_BRIEF = 8 * 1024 ** 2;
const UUID=/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;
const HASH=/^[0-9a-f]{64}$/;
const ID=/^[A-Za-z0-9_.:-]{1,128}$/;
const encoder=new TextEncoder();
export function requireLegacy(value,code='invalid_legacy_workflow') { if(!value) throw Error(code); }
function closed(value,fields) {
  requireLegacy(value && typeof value==='object' && !Array.isArray(value) &&
    Object.keys(value).length===fields.length && fields.every(key=>Object.hasOwn(value,key)));
}
function text(value,max,nullable=false) {
  requireLegacy((nullable && value===null) ||
    (typeof value==='string' && !/[\uD800-\uDFFF]/u.test(value) && encoder.encode(value).length<=max));
}
export function briefDescriptor(value) {
  closed(value,['sha256','size','media_type']);
  requireLegacy(typeof value.sha256==='string' && HASH.test(value.sha256) &&
    Number.isSafeInteger(value.size) && value.size>0 && value.size<=MAX_BRIEF &&
    value.media_type==='text/markdown');
  return value;
}
export const legacyBriefId=(paper,event)=>uuid5Name('paperfact:research-file:'+
  asciiJSON([paper,'legacy_brief',event]));
export function queueClosure(op) {
  if(op.entity_type!=='research_content') return false;
  if(op.action==='put') return op.payload?.feature==='queue_entry';
  const parent=op.parents?.[0];
  return parent?.kind==='paper' && UUID.test(parent.id) &&
    op.entity_id===contentId({kind:'paper',id:parent.id},'queue_entry','main');
}
export function queueParents(op) {
  requireLegacy(Array.isArray(op.parents) && op.parents.length>=1 && op.parents.length<=2);
  const ids=new Set();
  for(const parent of op.parents) {
    closed(parent,['kind','id','incarnation']);
    requireLegacy(parent.kind==='paper' && typeof parent.id==='string' && UUID.test(parent.id) &&
      typeof parent.incarnation==='string' && ID.test(parent.incarnation) && !ids.has(parent.id));
    ids.add(parent.id);
  }
  requireLegacy(op.entity_id===contentId({kind:'paper',id:op.parents[0].id},'queue_entry','main'));
}
export function validateWorkflow(payload,stamp) {
  const {feature,key,data,scope,source_document_hash:source}=payload;
  requireLegacy(Object.hasOwn(LEGACY_FIELDS,feature) && scope.kind==='paper' && UUID.test(scope.id) && source===null);
  closed(data,LEGACY_FIELDS[feature].split(' '));
  if(feature==='queue_entry') {
    requireLegacy(key==='main' && typeof data.rank==='number' && Number.isFinite(data.rank) &&
      ['pending','delivered','read','skipped','deferred'].includes(data.state));
    text(data.role,128); text(data.reason,200*1024,true);
    requireLegacy(data.parent_id===null || (typeof data.parent_id==='string' && UUID.test(data.parent_id)));
    for(const name of ['queued_at','delivered_at','read_at']) if(data[name]!==null) {text(data[name],64);stamp(data[name]);}
  } else {
    requireLegacy(typeof key==='string' && UUID.test(key));
    text(data.delivered_at,64);stamp(data.delivered_at); text(data.role,128,true); text(data.note,200*1024,true);
    if(data.brief!==null) briefDescriptor(data.brief);
  }
  // Python uses compact canonical UTF-8 for this feature, including finite floats.
  requireLegacy(encoder.encode(JSON.stringify(payload)).length<=240*1024);
}
export function validateLegacyManifest(payload,entityId,parents) {
  requireLegacy(payload.feature==='legacy_brief' && payload.format_version===1 &&
    typeof payload.slot==='string' && UUID.test(payload.slot) && payload.source_document_hash===null &&
    entityId===legacyBriefId(payload.paper_id,payload.slot));
  if(parents) requireLegacy(parents.length===1 && parents[0].kind==='paper' && parents[0].id===payload.paper_id);
  const versions=payload.input_versions;
  requireLegacy(versions.schema_version===1 && versions.complete===false && versions.entities.length===0 &&
    versions.documents.length===0 && versions.inputs_sha256===null);
  closed(payload.body,['sha256','size','media_type']);
  requireLegacy(typeof payload.body.sha256==='string' && HASH.test(payload.body.sha256) &&
    Number.isSafeInteger(payload.body.size) && payload.body.size>0 && payload.body.size<=4096 &&
    payload.body.media_type==='application/json');
  requireLegacy(Array.isArray(payload.assets) && payload.assets.length===1);
  const asset=payload.assets[0]; closed(asset,['id','role','sha256','size','media_type']);
  requireLegacy(asset.id==='markdown' && asset.role==='markdown');
  briefDescriptor({sha256:asset.sha256,size:asset.size,media_type:asset.media_type});
  return payload;
}
export function validateLegacyBody(body,payload) {
  closed(body,['version','paper_id','event_id','event_incarnation','legacy_day']);
  requireLegacy(body.version===1 && body.paper_id===payload.paper_id && body.event_id===payload.slot &&
    typeof body.event_incarnation==='string' && ID.test(body.event_incarnation));
  if(body.legacy_day!==null) {
    requireLegacy(typeof body.legacy_day==='string' && /^\d{4}-\d{2}-\d{2}$/.test(body.legacy_day));
    const [year,month,day]=body.legacy_day.split('-').map(Number),
      leap=year%4===0 && (year%100!==0 || year%400===0);
    requireLegacy(year>=1 && month>=1 && month<=12 && day>=1 &&
      day<=[31,leap?29:28,31,30,31,30,31,31,30,31,30,31][month-1]);
  }
  return body;
}
export function markdownText(bytes) {
  requireLegacy(bytes instanceof Uint8Array && bytes.length>0 && bytes.length<=MAX_BRIEF);
  const text=new TextDecoder('utf-8',{fatal:true,ignoreBOM:true}).decode(bytes);
  requireLegacy(!text.includes('\0'));
  return text;
}
