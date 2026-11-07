/** Closed recorded-query metadata. Never a current source or scientific verdict. */
const HASH=/^[0-9a-f]{64}$/;
const UUID=/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;
const size=v=>new TextEncoder().encode(typeof v==='string'?v:JSON.stringify(v)).length;
function ok(v){if(!v)throw new Error('unsupported_later_outcome');}
function closed(v,keys){ok(v&&typeof v==='object'&&!Array.isArray(v));ok(keys.length===Object.keys(v).length&&keys.every(k=>Object.hasOwn(v,k)));}
function hash(v){ok(v===null||(typeof v==='string'&&HASH.test(v)));}
export function validateLaterBody(body,stamp){
 closed(body,['format','state','policy','input_hash','query','source']);
 ok(size(body)<=32768);
 ok(body.format==='paperfact.later-outcome.v1'&&body.state==='queried_no_judged_inputs'&&body.policy==='followups.empty-query.v1');
 ok(typeof body.input_hash==='string'&&HASH.test(body.input_hash));
 const q=body.query;closed(q,['request_id','queried_at','lookup','providers']);
 ok(typeof q.request_id==='string'&&UUID.test(q.request_id));stamp(q.queried_at);
 closed(q.lookup,['title','doi','s2_id','arxiv_id']);
 for(const v of Object.values(q.lookup))ok(v===null||(typeof v==='string'&&size(v)<=8192));
 closed(q.providers,['openalex','semantic_scholar']);
 const states=Object.values(q.providers);
 ok(states.every(v=>['unknown','queried_empty'].includes(v))&&states.includes('queried_empty'));
 const s=body.source;closed(s,['availability','document_hash','desired_hash']);
 ok(['available','unavailable'].includes(s.availability));hash(s.document_hash);hash(s.desired_hash);
 ok((s.availability==='available')===(s.document_hash!==null));
 if(s.availability==='available')ok(s.desired_hash===null);
 return body;
}
export function validateLaterData(data,source,stamp){
 closed(data,['body_json','document_hash','written_at']);
 const body=validateLaterBody(data.body_json,stamp);hash(data.document_hash);
 ok(body.source.document_hash===data.document_hash&&source===data.document_hash);
 stamp(data.written_at);
 return data;
}
export function validateLaterProjection(value,stamp){
 closed(value,['body','document_hash','written_at']);
 validateLaterData({body_json:value.body,document_hash:value.document_hash,written_at:value.written_at},value.document_hash,stamp);
 return value;
}
const TEXT={
 en:{
  empty:'queried, no results',notEstablished:'not established',
  recorded:'Recorded query: no judged material was available for an overview.',
  unavailable:'Recorded query: no judged material was available; the original was unavailable.',
  different:'Recorded query belongs to another original version; it is not current completion.',
  missing:'Recorded query: its original is not currently loaded or verified.',
  appeared:'Recorded query predates the available original; check again explicitly.'
 },
 'zh-TW':{
  empty:'\u5df2\u67e5\u8a62\uff0c\u7121\u7d50\u679c',notEstablished:'\u5c1a\u672a\u78ba\u8a8d',
  recorded:'\u5df2\u8a18\u9304\u67e5\u8a62\uff1a\u7576\u6642\u5c1a\u7121\u53ef\u6574\u7406\u7684\u5df2\u5224\u8b80\u8cc7\u6599\u3002',
  unavailable:'\u5df2\u8a18\u9304\u67e5\u8a62\uff1a\u7576\u6642\u7121\u5df2\u5224\u8b80\u8cc7\u6599\uff0c\u4e14\u539f\u6587\u7121\u6cd5\u53d6\u5f97\u3002',
  different:'\u6b64\u67e5\u8a62\u5c6c\u65bc\u53e6\u4e00\u539f\u6587\u7248\u672c\uff0c\u4e0d\u4ee3\u8868\u76ee\u524d\u5df2\u5b8c\u6210\u3002',
  missing:'\u5df2\u8a18\u9304\u67e5\u8a62\uff1a\u76ee\u524d\u672a\u8f09\u5165\u6216\u9a57\u8b49\u8a72\u539f\u6587\u3002',
  appeared:'\u6b64\u67e5\u8a62\u65e9\u65bc\u76ee\u524d\u53ef\u7528\u7684\u539f\u6587\uff0c\u8acb\u660e\u78ba\u91cd\u65b0\u6aa2\u67e5\u3002'
 }
};
export function laterOutcomeText(value,language='en',loadedHash=null){
 const t=TEXT[language]??TEXT.en,s=value.body.source;
 const query=value.body.query;
 const status=key=>query.providers[key]==='queried_empty'?t.empty:t.notEstablished;
 const provenance=' ('+query.queried_at+'; OpenAlex: '+status('openalex')+
   '; Semantic Scholar: '+status('semantic_scholar')+')';
 if(s.availability==='unavailable')return (loadedHash?t.appeared:t.unavailable)+provenance;
 if(!loadedHash)return t.missing+provenance;
 return (loadedHash===s.document_hash?t.recorded:t.different)+provenance;
}
