/** Independent closed position contract. No parser, storage, network or viewport claims. */
import {contentId} from './ids.mjs';
import {sourceFileId,validateArtifact} from './artifacts.mjs';
const HASH=/^[0-9a-f]{64}$/,UUID=/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/,
  ID=/^[A-Za-z0-9_.:-]{1,128}$/;
export const MAX_POSITION_PAGE=1000001,MAX_POSITIONS=500;
export const requirePosition=(value,code='invalid_reading_position')=>{if(!value)throw Error(code);};
function closed(value,fields) {
  requirePosition(value && typeof value==='object' && !Array.isArray(value) &&
    Object.keys(value).length===fields.length && fields.every(key=>Object.hasOwn(value,key)));
}
export function validatePositionData(data,stamp) {
  closed(data,['page','recorded_at','method']);
  requirePosition(Number.isSafeInteger(data.page) && data.page>=1 && data.page<=MAX_POSITION_PAGE);
  stamp(data.recorded_at);
  requirePosition(['observed','entered'].includes(data.method));
  return data;
}
export function validatePositionContent(payload,id,parents,stamp) {
  closed(payload,['scope','feature','key','source_document_hash','data']);
  closed(payload.scope,['kind','id']);
  requirePosition(payload.feature==='reading_position' && payload.scope.kind==='paper' && UUID.test(payload.scope.id));
  requirePosition(typeof payload.key==='string' && HASH.test(payload.key) && payload.source_document_hash===payload.key);
  requirePosition(id===contentId(payload.scope,'reading_position',payload.key));
  requirePosition(Array.isArray(parents) && parents.length===1);
  closed(parents[0],['kind','id','incarnation']);
  requirePosition(parents[0].kind==='paper' && parents[0].id===payload.scope.id && ID.test(parents[0].incarnation));
  validatePositionData(payload.data,stamp);
}
export function validatePositionProjection(rows,papers,assets,stamp) {
  requirePosition(Array.isArray(rows) && rows.length>0 && rows.length<=MAX_POSITIONS);
  const owners=new Set(papers.map(p=>p.id)),seen=new Set();let previous='';
  const assetIds=new Set();
  for(const asset of assets) {
    closed(asset,['id','sha256','size','media_type','availability']);
    requirePosition(HASH.test(asset.sha256) && asset.id==='sha256:'+asset.sha256 && !assetIds.has(asset.id));
    assetIds.add(asset.id);
    requirePosition(Number.isSafeInteger(asset.size) && asset.size>=1 && asset.size<=150*1024**2 &&
      asset.media_type==='application/pdf' && ['unchecked','available'].includes(asset.availability));
  }
  for(const row of rows) {
    closed(row,['paper_id','document_hash','page','recorded_at','method','source']);
    requirePosition(UUID.test(row.paper_id) && owners.has(row.paper_id) && HASH.test(row.document_hash));
    validatePositionData({page:row.page,recorded_at:row.recorded_at,method:row.method},stamp);
    const key=row.paper_id+'/'+row.document_hash;
    requirePosition(!seen.has(key) && (!previous || previous<key));seen.add(key);previous=key;
    const source=row.source;closed(source,['id','parents','manifest']);
    requirePosition(source.id===sourceFileId(row.paper_id,row.document_hash));
    requirePosition(Array.isArray(source.parents) && source.parents.length===1);
    closed(source.parents[0],['kind','id','incarnation']);
    requirePosition(source.parents[0].kind==='paper' && source.parents[0].id===row.paper_id && ID.test(source.parents[0].incarnation));
    validateArtifact(source.manifest,source.id,source.parents);
    requirePosition(source.manifest.feature==='original_source' && source.manifest.slot===row.document_hash &&
      source.manifest.paper_id===row.paper_id);
    const declared=source.manifest.assets[0],matches=assets.filter(asset=>asset.id==='sha256:'+row.document_hash);
    requirePosition(matches.length===1);
    const asset=matches[0];
    requirePosition(asset.sha256===row.document_hash && asset.size===declared.size && asset.media_type==='application/pdf' &&
      ['unchecked','available'].includes(asset.availability));
  }
  return structuredClone(rows);
}

/** Typed known lifecycle checks; no new inference for unknown generic deletions. */
export function positionReceived(state,op,isActive,stable) {
  if(op.entity_type!=='research_content')return;
  const previous=state.entities['research_content/'+op.entity_id]?.operation;
  const origin=previous?.action==='delete' ? state.receipts[previous.incarnation]?.operation : previous;
  const known=origin?.action==='put' && origin.payload?.feature==='reading_position';
  const incoming=op.action==='put' && op.payload?.feature==='reading_position';
  if(!known && !incoming)return;
  if(previous) {
    requirePosition(known,'position_origin_unavailable');
    if(op.action==='delete' || isActive(state,'research_content',op.entity_id)) {
      requirePosition(op.incarnation===previous.incarnation && stable(op.parents)===stable(previous.parents),
        'invalid_position_lifecycle');
    } else {
      requirePosition(op.incarnation===op.operation_id && op.incarnation!==previous.incarnation &&
        stable(op.parents.map(({kind,id})=>({kind,id})))===stable(previous.parents.map(({kind,id})=>({kind,id}))),
        'invalid_position_lifecycle');
    }
  } else requirePosition(op.action==='put' && op.incarnation===op.operation_id,'invalid_position_lifecycle');
  if(op.action==='put') {
    const parent=op.parents[0];
    requirePosition(isActive(state,'paper',parent.id) &&
      state.graph['paper/'+parent.id].incarnation===parent.incarnation,'position_parent_unavailable');
  }
}
