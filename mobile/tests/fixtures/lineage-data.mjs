/** Pure synthetic Lineage data; importing it registers no test cases. */
import {claimHash,normalizeClaimText} from '../../claims.mjs';
import {lineageSourceHash} from '../../lineage.mjs';
export const PAPER='11111111-1111-4111-8111-111111111111';
export const CORPUS='22222222-2222-4222-8222-222222222222';
export function lineageRow(){
 const identity={title:'Synthetic focal paper',doi:null,arxiv_id:null,s2_id:null},document_hash='a'.repeat(64);
 const source={id:claimHash(['lineage-source.v1',identity,document_hash]),identity,identity_authority:'selected_workspace_record',document_hash,availability:'available',page_count:1};
 const location={state:'located',reason:null,anchor:{p0:0,o0:0,p1:0,o1:4},page:1,candidates:[],truncated:false};
 const passage={source_id:source.id,role:'change_evidence',cites:null,quote:'A synthetic focal observation.',location};
 passage.id=claimHash(['bounded-lineage.v1',passage.source_id,passage.role,null,normalizeClaimText(passage.quote),location]);
 const item={stage:'current_change',subject:source.id,text:'A proposed observation.',function:'unresolved',judgment:{status:'unresolved',reason:'Semantic validation was not performed.',authority:'caller_proposal'},passages:[passage],requirements:{own_source_passage:'located',citing_passage:'not_required',citation_identity:'not_required',semantic_validation:'not_performed'}};
 item.id=claimHash(['bounded-lineage.v1',source.id,item.stage,item.subject,normalizeClaimText(item.text)]);
 const report={format:'paperfact.lineage-report.v1',recipe:'bounded-lineage.v1',verification_scope:'original_snapshots',normalization:'nfkc-whitespace-soft-hyphen-wrap.v1',focal:source.id,sources:[source],statements:[item],coverage:{current_change:'proposed',later_development:'no_statement',prior_gap:'no_statement'}};
 report.id=claimHash(report);
 const body={format:'paperfact.lineage-set.v1',corpus_id:CORPUS,inputs:{dive:null,close_reading:null},generation:{task:'lineage',backend:'fixture',requested_model:null,returned_model:null},report,bindings:[{source_id:source.id,paper_id:PAPER}]};
 return {body,source_hash:lineageSourceHash(body),document_hash,written_at:'2026-11-13T00:00:00+00:00'};
}
