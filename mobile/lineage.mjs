/** Closed saved-only Lineage metadata. No source activation or semantic certification. */
import {claimHash,normalizeClaimText,validateEvidenceLocation,validateEvidenceText} from './claims.mjs';
const HASH=/^[0-9a-f]{64}$/;
const UUID=/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;
const STAGES=['prior_gap','current_change','later_development'];
const RECIPE='bounded-lineage.v1';
const copy=v=>JSON.parse(JSON.stringify(v));
const bytes=v=>new TextEncoder().encode(JSON.stringify(v)).length;
function ok(v){if(!v)throw new Error('unsupported_lineage');}
function closed(v,keys){ok(v&&typeof v==='object'&&!Array.isArray(v));ok(Object.keys(v).length===keys.length&&keys.every(k=>Object.hasOwn(v,k)));}
function hash(v,nullable=false){ok((nullable&&v===null)||(typeof v==='string'&&HASH.test(v)));}
function uuid(v){ok(typeof v==='string'&&UUID.test(v));}
const same=(a,b)=>claimHash(a)===claimHash(b);
const text=(v,max,nullable=false)=>validateEvidenceText(v,max,nullable);
function requirements(focal,item){
 const own=item.passages.some(p=>p.source_id===item.subject&&['own_characterization','change_evidence'].includes(p.role)&&p.location.state==='located');
 const [citing,cited]=item.stage==='prior_gap'?[focal,item.subject]:[item.subject,focal];
 const relation=item.stage!=='current_change';
 const context=item.passages.some(p=>p.source_id===citing&&p.role==='citing_context'&&p.cites===cited&&p.location.state==='located');
 return {own_source_passage:own?'located':'missing',citing_passage:relation?(context?'located':'missing'):'not_required',citation_identity:relation?'unresolved':'not_required',semantic_validation:'not_performed'};
}
export function validateLineageBody(body){
 closed(body,['format','corpus_id','inputs','generation','report','bindings']);
 ok(body.format==='paperfact.lineage-set.v1'&&bytes(body)<=230*1024);uuid(body.corpus_id);
 closed(body.inputs,['dive','close_reading']);Object.values(body.inputs).forEach(v=>hash(v,true));
 const g=body.generation;closed(g,['task','backend','requested_model','returned_model']);
 ok(g.task==='lineage');text(g.backend,64);text(g.requested_model,512,true);text(g.returned_model,512,true);
 const r=body.report;closed(r,['format','recipe','verification_scope','normalization','focal','sources','statements','coverage','id']);
 ok(r.format==='paperfact.lineage-report.v1'&&r.recipe===RECIPE&&r.verification_scope==='original_snapshots'&&r.normalization==='nfkc-whitespace-soft-hyphen-wrap.v1');
 ok(Array.isArray(r.sources)&&r.sources.length>=1&&r.sources.length<=4);
 const sources=new Map();let pages=0;
 for(const s of r.sources){
  closed(s,['id','identity','identity_authority','document_hash','availability','page_count']);
  closed(s.identity,['title','doi','arxiv_id','s2_id']);text(s.identity.title,2000);
  for(const key of ['doi','arxiv_id','s2_id'])text(s.identity[key],1000,true);
  ok(s.identity_authority==='selected_workspace_record');
  if(s.availability==='available'){hash(s.document_hash);ok(Number.isInteger(s.page_count)&&s.page_count>=1&&s.page_count<=96);pages+=s.page_count;}
  else ok(s.availability==='unavailable'&&s.document_hash===null&&s.page_count===null);
  ok(s.id===claimHash(['lineage-source.v1',s.identity,s.document_hash])&&!sources.has(s.id));sources.set(s.id,s);
 }
 ok(pages<=96&&sources.get(r.focal)?.availability==='available');
 ok(Array.isArray(body.bindings)&&body.bindings.length===r.sources.length);
 const owners=new Set();body.bindings.forEach((b,i)=>{
  closed(b,['source_id','paper_id']);uuid(b.paper_id);ok(!owners.has(b.paper_id)&&b.source_id===r.sources[i].id);owners.add(b.paper_id);
 });ok(body.bindings[0].source_id===r.focal);
 ok(Array.isArray(r.statements)&&r.statements.length<=12);const statements=new Set();let passages=0;
 for(const item of r.statements){
  closed(item,['id','stage','subject','text','function','judgment','passages','requirements']);
  ok(STAGES.includes(item.stage)&&sources.has(item.subject));
  ok((item.stage==='current_change')===(item.subject===r.focal));text(item.text,2000);
  ok(['uses-method','uses-data','extends','compares','supports','contrasts','background','unresolved'].includes(item.function));
  closed(item.judgment,['status','reason','authority']);ok(['supported','inferred','unresolved'].includes(item.judgment.status)&&item.judgment.authority==='caller_proposal');text(item.judgment.reason,2000);
  ok(item.id===claimHash([RECIPE,r.focal,item.stage,item.subject,normalizeClaimText(item.text)])&&!statements.has(item.id));statements.add(item.id);
  ok(Array.isArray(item.passages));passages+=item.passages.length;ok(passages<=48);const ids=new Set();
  for(const p of item.passages){
   closed(p,['id','source_id','role','cites','quote','location']);ok(sources.has(p.source_id)&&['own_characterization','citing_context','change_evidence'].includes(p.role));
   ok(p.cites===null||sources.has(p.cites));ok((p.role==='citing_context')===(p.cites!==null));text(p.quote,4000);
   const source=sources.get(p.source_id);
   if(source.availability==='available')validateEvidenceLocation(p.location,source.page_count);
   else ok(same(p.location,{state:'source_unavailable',reason:'original_unavailable',anchor:null,page:null,candidates:[],truncated:false}));
   ok(p.id===claimHash([RECIPE,p.source_id,p.role,p.cites,normalizeClaimText(p.quote),p.location])&&!ids.has(p.id));ids.add(p.id);
  }
  ok(same(item.requirements,requirements(r.focal,item)));
 }
 const coverage=Object.fromEntries([...STAGES].sort().map(stage=>[stage,r.statements.some(s=>s.stage===stage)?'proposed':'no_statement']));
 ok(same(r.coverage,coverage));const {id,...rest}=r;ok(id===claimHash(rest));
 return body;
}
export function lineageSourceHash(body){
 return claimHash(['paperfact.lineage-set.v1',body.corpus_id,body.inputs,body.report.sources.map(s=>({id:s.id,document_hash:s.document_hash}))]);
}
function checkedProjection(rows,paperId,papers,stamp){
 uuid(paperId);for(const id of papers)uuid(id);
 ok(Array.isArray(rows)&&rows.length>=1&&rows.length<=64);const seen=new Set();
 for(const row of rows){
  closed(row,['body','source_hash','document_hash','written_at']);const body=validateLineageBody(row.body);
  ok(!seen.has(body.corpus_id));seen.add(body.corpus_id);
  ok(body.bindings[0].paper_id===paperId&&body.bindings.every(b=>papers.has(b.paper_id)));
  hash(row.source_hash);hash(row.document_hash);stamp(row.written_at);
  ok(row.source_hash===lineageSourceHash(body)&&row.document_hash===body.report.sources[0].document_hash);
 }
 return copy(rows);
}

export function validateLineageProjection(rows,paperId,papers,stamp){
 try{return checkedProjection(rows,paperId,papers,stamp);}
 catch{throw new Error('unsupported_lineage');}
}
