/** Typed Lineage receive/projection contract. Metadata is never a PDF byte grant. */
import {validateLineageBody,lineageSourceHash} from './lineage.mjs';
import {validateContentTimestamp} from './content.mjs';
import {contentId} from './ids.mjs';
import {sourceFileId} from './artifacts.mjs';
const UUID=/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;
const ID=/^[A-Za-z0-9_.:-]{1,128}$/;
const HASH=/^[0-9a-f]{64}$/;
const key=(kind,id)=>`${kind}/${id}`;
const clone=v=>structuredClone(v);
const equal=(a,b)=>JSON.stringify(a)===JSON.stringify(b);
function ok(value,code='invalid_lineage_operation'){if(!value)throw new Error(code);}
function closed(value,fields){ok(value&&typeof value==='object'&&!Array.isArray(value));ok(Object.keys(value).length===fields.length&&fields.every(k=>Object.hasOwn(value,k)));}
export function lineageOperation(op){return Boolean(op&&(Object.hasOwn(op,'content_address')||Object.hasOwn(op,'source_dependencies')||op.payload?.feature==='lineage'));}
export function validateLineageOperation(op){
 ok(op.version===2&&op.entity_type==='research_content');
 closed(op.content_address,['feature','key']);const corpus=op.content_address.key;
 ok(op.content_address.feature==='lineage'&&typeof corpus==='string'&&UUID.test(corpus));
 ok(Array.isArray(op.parents)&&op.parents.length>=1&&op.parents.length<=4);
 const seen=new Set();for(const p of op.parents){closed(p,['kind','id','incarnation']);ok(p.kind==='paper'&&typeof p.id==='string'&&UUID.test(p.id)&&typeof p.incarnation==='string'&&ID.test(p.incarnation)&&!seen.has(p.id));seen.add(p.id);}
 ok(op.entity_id===contentId({kind:'paper',id:op.parents[0].id},'lineage',corpus));
 ok(Array.isArray(op.source_dependencies));
 if(op.action==='delete'){closed(op.payload,[]);ok(op.source_dependencies.length===0);return op;}
 ok(op.action==='put');const p=op.payload;
 closed(p,['scope','feature','key','data','source_document_hash']);closed(p.scope,['kind','id']);
 ok(p.feature==='lineage'&&p.key===corpus&&p.scope.kind==='paper'&&p.scope.id===op.parents[0].id);
 const d=p.data;closed(d,['body_json','source_hash','document_hash','written_at']);
 const body=validateLineageBody(d.body_json);
 ok(body.corpus_id===corpus&&equal(body.bindings.map(b=>b.paper_id),op.parents.map(p=>p.id)));
 ok(typeof d.source_hash==='string'&&HASH.test(d.source_hash)&&d.source_hash===lineageSourceHash(body));
 ok(typeof d.document_hash==='string'&&HASH.test(d.document_hash)&&d.document_hash===body.report.sources[0].document_hash&&p.source_document_hash===d.document_hash);
 validateContentTimestamp(d.written_at);
 ok(new TextEncoder().encode(JSON.stringify(p)).length<=240*1024);
 const available=body.report.sources.map((s,i)=>({s,b:body.bindings[i]})).filter(v=>v.s.availability==='available');
 ok(op.source_dependencies.length===available.length);
 for(let i=0;i<available.length;i++){
  const pin=op.source_dependencies[i],{s,b}=available[i];closed(pin,['source_id','paper_id','file_id','incarnation']);
  ok(pin.source_id===s.id&&pin.paper_id===b.paper_id&&pin.file_id===sourceFileId(b.paper_id,s.document_hash)&&typeof pin.incarnation==='string'&&ID.test(pin.incarnation));
 }
 return op;
}
export function lineageActive(state,op,active,trail){
 if(!lineageOperation(op)||op.action==='delete')return true;
 return op.source_dependencies.every(pin=>{
  const file=state.graph[key('research_file',pin.file_id)];
  const parent=op.parents.find(p=>p.id===pin.paper_id);
  return file?.active&&file.incarnation===pin.incarnation&&file.parents.length===1&&
   file.parents[0].kind===parent.kind&&file.parents[0].id===parent.id&&file.parents[0].incarnation===parent.incarnation&&
   active(state,'research_file',pin.file_id,trail);
 });
}
export function lineageReceived(state,op,active){
 const previous=state.graph[key(op.entity_type,op.entity_id)];
 if(!lineageOperation(op)&&!previous?.content_address)return;
 validateLineageOperation(op);
 if(previous){
  ok(previous.content_address?.feature===op.content_address.feature&&previous.content_address?.key===op.content_address.key,'changed_lineage_address');
  ok(equal(previous.parents.map(p=>[p.kind,p.id]),op.parents.map(p=>[p.kind,p.id])),'changed_lineage_parents');
  if(op.action==='delete')ok(previous.incarnation===op.incarnation,'changed_lineage_incarnation');
  else if(previous.active&&equal(previous.parents.map(p=>p.incarnation),op.parents.map(p=>p.incarnation)))ok(previous.incarnation===op.incarnation,'changed_lineage_incarnation');
 }
 if(op.action==='put'){
  ok(op.parents.every(p=>state.graph[key('paper',p.id)]?.incarnation===p.incarnation&&active(state,'paper',p.id)),'stale_lineage_parent');
  ok(lineageActive(state,op,active,new Set()),'stale_lineage_source');
 }
}
export function projectLineage(papers,heads,visible){
 for(const {operation:op} of heads){
  if(!lineageOperation(op))continue;
  const paper=papers.find(p=>p.id===op.parents[0].id);if(!paper)continue;
  paper.lineage=(paper.lineage??[]).filter(row=>row.body.corpus_id!==op.content_address.key);
 }
 for(const {operation:op} of visible){
  if(!lineageOperation(op))continue;
  const paper=papers.find(p=>p.id===op.parents[0].id);if(!paper)continue;
  const d=op.payload.data;
  paper.lineage??=[];paper.lineage.push({body:clone(d.body_json),source_hash:d.source_hash,document_hash:d.document_hash,written_at:d.written_at});
 }
}
