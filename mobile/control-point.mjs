/** Device-local control knowledge; no credential or research content. */
export function controlPoint(value) {
 if(!value || typeof value!=='object' || Array.isArray(value) ||
  Object.keys(value).sort().join(',')!=='authority_id,sequence,sha256' ||
  typeof value.authority_id!=='string' || !/^[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}$/.test(value.authority_id) ||
  !Number.isSafeInteger(value.sequence) || value.sequence<1 || value.sequence>10000 ||
  typeof value.sha256!=='string' || !/^[a-f0-9]{64}$/.test(value.sha256))throw Error('sync_history_unavailable');
 return {authority_id:value.authority_id,sequence:value.sequence,sha256:value.sha256};
}
export function sameControl(a,b) {
 return a===null || b===null ? a===b : a.authority_id===b.authority_id &&
  a.sequence===b.sequence && a.sha256===b.sha256;
}
export function controlRecord(value,workspace,device) {
 if(value===undefined || value===null)return null;
 if(!value || typeof value!=='object' || Array.isArray(value) ||
  Object.keys(value).sort().join(',')!=='checkpoint,device,format,workspace' ||
  value.format!=='paperfact.device-control-knowledge.v1' || value.workspace!==workspace ||
  value.device!==device)throw Error('sync_history_unavailable');
 return controlPoint(value.checkpoint);
}
export function savedControl(point,workspace,device) {
 return {format:'paperfact.device-control-knowledge.v1',workspace,device,checkpoint:controlPoint(point)};
}

export function advanceControl(current,point,previous) {
 point=controlPoint(point);if(previous!==null)previous=controlPoint(previous);
 if(!sameControl(current,previous) && !sameControl(current,point))throw Error('sync_history_unavailable');
 if(current!==null && (current.authority_id!==point.authority_id || point.sequence<current.sequence ||
   point.sequence===current.sequence && !sameControl(current,point)))throw Error('sync_history_unavailable');
 return point;
}
