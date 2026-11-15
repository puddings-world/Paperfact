/** Strict source-aware survey records. Retained locations do not certify semantics. */
import {claimHash,normalizeClaimText,validateEvidenceLocation,validateEvidenceText} from './claims.mjs';
const enc=new TextEncoder(), HASH=/^[0-9a-f]{64}$/, LIFE=/^[0-9a-f]{32}$/;
export const SURVEY_MAX_BYTES=1024*1024;
const ok=value=>{if(!value)throw Error('invalid_survey');};
const closed=(value,fields)=>ok(value&&typeof value==='object'&&!Array.isArray(value)&&
  Object.keys(value).length===fields.length&&fields.every(key=>Object.hasOwn(value,key)));
const array=(value,max,min=0)=>ok(Array.isArray(value)&&value.length>=min&&value.length<=max);
const integer=(value,min,max)=>ok(Number.isSafeInteger(value)&&value>=min&&value<=max);
const hash=value=>ok(typeof value==='string'&&HASH.test(value));
const life=value=>ok(typeof value==='string'&&LIFE.test(value));
const canonical=value=>Array.isArray(value)?'['+value.map(canonical).join(',')+']':value&&typeof value==='object'?
  '{'+Object.keys(value).sort().map(key=>JSON.stringify(key)+':'+canonical(value[key])).join(',')+'}':JSON.stringify(value);
const sha=async bytes=>[...new Uint8Array(await crypto.subtle.digest('SHA-256',bytes))]
  .map(value=>value.toString(16).padStart(2,'0')).join('');
const compare=(a,b)=>{const aa=[...a],bb=[...b];for(let i=0;i<Math.min(aa.length,bb.length);i++){
  const d=aa[i].codePointAt(0)-bb[i].codePointAt(0);if(d)return d;}return aa.length-bb.length;};
export const renderSurvey=report=>report.sections.map(section=>'## '+section.heading+'\n\n'+
  section.statements.map(item=>item.text).join('\n\n')).join('\n\n');
export async function validateSurveyBody(raw,body,payload){
  ok(raw instanceof Uint8Array&&raw.length<=SURVEY_MAX_BYTES+1024);
  closed(body,['format','list_id','report']);
  ok(body.format==='paperfact.survey-artifact.v1'&&body.list_id===payload.list_id);
  // Survey numbers are bounded integers. Do not silently coerce Python float lexemes.
  ok(new TextDecoder('utf-8',{fatal:true}).decode(raw)===canonical(body));
  const report=body.report;
  closed(report,['format','recipe','inputs','generation','sources','sections','source_check',
    'semantic_validation','body_hash','id']);
  ok(enc.encode(canonical(report)).length<=SURVEY_MAX_BYTES);
  ok(report.format==='paperfact.survey-evidence.v1'&&report.recipe==='list-survey-sources.v1'&&
    report.source_check==='quote_location_only'&&report.semantic_validation==='not_performed');
  const inputs=report.inputs;
  closed(inputs,['list_id','list_name','list_lifecycle','prompt_hash','members']);
  validateEvidenceText(inputs.list_id,4096);validateEvidenceText(inputs.list_name,2000);
  life(inputs.list_lifecycle);hash(inputs.prompt_hash);
  ok(inputs.prompt_hash===payload.input_versions.inputs_sha256);
  array(inputs.members,2000,1);const members=new Set();let previous=null;
  for(const member of inputs.members){
    closed(member,['paper_id','paper_lifecycle','position','input_hash','title']);
    validateEvidenceText(member.paper_id,4096);validateEvidenceText(member.title,2000);
    life(member.paper_lifecycle);hash(member.input_hash);integer(member.position,-2147483648,2147483647);
    ok(!members.has(member.paper_id));members.add(member.paper_id);
    ok(!previous||previous.position<member.position||previous.position===member.position&&compare(previous.paper_id,member.paper_id)<=0);
    previous=member;
  }
  const g=report.generation;closed(g,['task','backend','requested_model','returned_model']);
  ok(g.task==='survey'&&typeof g.backend==='string'&&/^[a-z][a-z0-9_-]{0,63}$/.test(g.backend));
  validateEvidenceText(g.requested_model,512,true);validateEvidenceText(g.returned_model,512,true);
  array(report.sources,2000,1);ok(report.sources.length===inputs.members.length);
  const sources=new Map();
  report.sources.forEach((source,index)=>{
    closed(source,['id','paper_id','paper_lifecycle','document_hash','page_count','state']);
    const member=inputs.members[index];
    ok(source.paper_id===member.paper_id&&source.paper_lifecycle===member.paper_lifecycle);
    if(source.document_hash!==null)hash(source.document_hash);
    ok(['captured','unavailable','not_selected'].includes(source.state));
    if(source.state==='captured'){hash(source.document_hash);integer(source.page_count,1,500);}
    else ok(source.page_count===null);
    ok(source.id===claimHash(['survey-source.v1',source.paper_id,source.paper_lifecycle,source.document_hash])&&!sources.has(source.id));
    sources.set(source.id,source);
  });
  const captured=report.sources.filter(source=>source.state==='captured');
  ok(captured.length===payload.source_bindings.length);
  captured.forEach((source,i)=>ok(source.id===payload.source_bindings[i].source_id&&
    source.document_hash===payload.source_bindings[i].document_hash));
  array(report.sections,16,1);let statements=0,passages=0;const identities=new Set();
  report.sections.forEach((section,sectionIndex)=>{
    closed(section,['heading','statements']);validateEvidenceText(section.heading,200);
    ok(!/[\r\n]/.test(section.heading));array(section.statements,96,1);
    section.statements.forEach((item,index)=>{
      statements++;closed(item,['id','text','interpretation','passages']);validateEvidenceText(item.text,12000);
      ok(item.id===claimHash(['survey-statement.v1',sectionIndex,index,normalizeClaimText(item.text)])&&!identities.has(item.id));
      identities.add(item.id);ok(['reported','synthesis','inference'].includes(item.interpretation));
      array(item.passages,16);const seen=new Set();
      for(const passage of item.passages){
        passages++;closed(passage,['source_id','quote','location']);
        validateEvidenceText(passage.source_id,64);validateEvidenceText(passage.quote,4000);
        const source=sources.get(passage.source_id);ok(source);
        if(passage.location!==null){ok(source.state==='captured');validateEvidenceLocation(passage.location,source.page_count);}
        const id=claimHash(passage);ok(!seen.has(id));seen.add(id);
      }
    });
  });
  ok(statements<=96&&passages<=384);hash(report.body_hash);hash(report.id);
  const text=renderSurvey(report);ok(enc.encode(text).length<=200*1024);
  ok(await sha(enc.encode(text))===report.body_hash);
  const {id,...rest}=report;ok(await sha(enc.encode(canonical(rest)))===id);
  return body;
}
/** Accepted native operations must name exact active source owners at receipt. */
export function surveyReceived(state,operation,active){
  if(operation.entity_type!=='research_file'||operation.action!=='put'||operation.payload.feature!=='survey')return;
  for(const pin of operation.payload.source_bindings){
    const paper=state.graph['paper/'+pin.paper_id],file=state.graph['research_file/'+pin.file_id];
    ok(paper?.incarnation===pin.paper_incarnation&&active(state,'paper',pin.paper_id));
    ok(file?.incarnation===pin.incarnation&&active(state,'research_file',pin.file_id)&&file.parents.length===1&&
      file.parents[0].kind==='paper'&&file.parents[0].id===pin.paper_id&&file.parents[0].incarnation===pin.paper_incarnation);
  }
}
