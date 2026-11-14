/** Saved-only research lineage. Untrusted research is always rendered as text. */
export const LINEAGE_COPY={
 en:{title:'Research lineage',recorded:'Saved original snapshots. Research claims have not been independently verified.',
  sourceNote:'Use the desktop app to inspect these original versions.',corpus:'Reading context',sources:'sources',
  prior_gap:'Earlier gap',current_change:'Current contribution',later_development:'Later development',
  empty:'No statement proposed in this saved report.',proposal:'Proposed judgment',
  supported:'supported',inferred:'inferred',unresolved:'unresolved',
  passages:'Original passages',page:'Page',located:'Quote located',missing:'Quote not located',
  ambiguous:'Multiple possible locations',invalid_page:'Page needs review',invalid_anchor:'Location needs review',
  source_unavailable:'Original unavailable',references:'Proposed citation',version:'Original version',
  captured:'Original captured for this analysis',unavailable:'No original captured',"relation": "Proposed role", "function_unresolved": "Relation not established", "function_uses-method": "Uses a method", "function_uses-data": "Uses data", "function_extends": "Extends earlier work", "function_compares": "Compares", "function_supports": "Supports", "function_contrasts": "Contrasts", "function_background": "Background", "role_own_characterization": "Author's characterization", "role_citing_context": "Citation context", "role_change_evidence": "Change evidence", "ownMissing": "An original passage for this claim is still missing.", "citingMissing": "A passage establishing the proposed citation context is still missing.", "identityUnresolved": "The proposed citation identity has not been independently resolved."},
 'zh-TW':{
  "title": "\u7814\u7a76\u8108\u7d61",
  "recorded": "\u4ee5\u4e0b\u5167\u5bb9\u4f9d\u64da\u4fdd\u5b58\u7684\u539f\u6587\u7248\u672c\uff1b\u7814\u7a76\u4e3b\u5f35\u5c1a\u672a\u7d93\u7368\u7acb\u9a57\u8b49\u3002",
  "sourceNote": "\u8acb\u5728\u684c\u9762\u7248\u6838\u5c0d\u9019\u4e9b\u539f\u6587\u7248\u672c\u3002",
  "corpus": "\u95b1\u8b80\u8108\u7d61",
  "sources": "\u7bc7\u4f86\u6e90",
  "prior_gap": "\u5148\u524d\u7814\u7a76\u7684\u7f3a\u53e3",
  "current_change": "\u672c\u7bc7\u7684\u6539\u8b8a",
  "later_development": "\u5f8c\u7e8c\u767c\u5c55",
  "empty": "\u9019\u4efd\u5831\u544a\u5c1a\u672a\u63d0\u51fa\u6b64\u90e8\u5206\u7684\u6558\u8ff0\u3002",
  "proposal": "\u63d0\u8b70\u7684\u5224\u65b7",
  "supported": "\u6709\u652f\u6301",
  "inferred": "\u63a8\u8ad6",
  "unresolved": "\u5c1a\u672a\u78ba\u5b9a",
  "passages": "\u539f\u6587\u5f15\u53e5",
  "page": "\u9801",
  "located": "\u5df2\u5b9a\u4f4d\u539f\u53e5",
  "missing": "\u5c1a\u672a\u5b9a\u4f4d\u539f\u53e5",
  "ambiguous": "\u5b58\u5728\u591a\u500b\u53ef\u80fd\u4f4d\u7f6e",
  "invalid_page": "\u9801\u78bc\u5f85\u6838\u5c0d",
  "invalid_anchor": "\u4f4d\u7f6e\u5f85\u6838\u5c0d",
  "source_unavailable": "\u672a\u53d6\u5f97\u539f\u6587",
  "references": "\u63d0\u8b70\u7684\u5f15\u7528\u5c0d\u8c61",
  "version": "\u539f\u6587\u7248\u672c",
  "captured": "\u6b64\u5206\u6790\u5df2\u4fdd\u5b58\u539f\u6587",
  "unavailable": "\u6b64\u5206\u6790\u672a\u4fdd\u5b58\u539f\u6587",
  "relation": "\u63d0\u8b70\u7684\u95dc\u4fc2",
  "function_unresolved": "\u95dc\u4fc2\u5c1a\u672a\u78ba\u5b9a",
  "function_uses-method": "\u4f7f\u7528\u65b9\u6cd5",
  "function_uses-data": "\u4f7f\u7528\u8cc7\u6599",
  "function_extends": "\u5ef6\u4f38\u5148\u524d\u7814\u7a76",
  "function_compares": "\u6bd4\u8f03",
  "function_supports": "\u652f\u6301",
  "function_contrasts": "\u5c0d\u6bd4",
  "function_background": "\u80cc\u666f",
  "role_own_characterization": "\u4f5c\u8005\u5c0d\u81ea\u8eab\u7814\u7a76\u7684\u63cf\u8ff0",
  "role_citing_context": "\u5f15\u7528\u4e0a\u4e0b\u6587",
  "role_change_evidence": "\u6539\u8b8a\u7684\u8b49\u64da",
  "ownMissing": "\u6b64\u4e3b\u5f35\u4ecd\u7f3a\u5c11\u5c0d\u61c9\u7684\u539f\u6587\u5f15\u53e5\u3002",
  "citingMissing": "\u4ecd\u7f3a\u5c11\u80fd\u78ba\u8a8d\u63d0\u8b70\u5f15\u7528\u95dc\u4fc2\u7684\u4e0a\u4e0b\u6587\u3002",
  "identityUnresolved": "\u63d0\u8b70\u7684\u5f15\u7528\u5c0d\u8c61\u5c1a\u672a\u7d93\u7368\u7acb\u6838\u5be6\u3002"
}
};
export function renderLineage(panel,paper,el,language='en',actions=null){
 const rows=paper.lineage??[];if(!rows.length)return;
 const t=LINEAGE_COPY[language]??LINEAGE_COPY.en;
 const card=el('section',{class:'card lineage-card','aria-label':t.title},el('h2',{},t.title),
  el('p',{class:'notice'},t.recorded));panel.append(card);
 rows.forEach((row,index)=>{
  const report=row.body.report,sources=new Map(report.sources.map(s=>[s.id,s]));
  const corpus=el('details',{class:'lineage-corpus',...(index===0?{open:''}:{})},
   el('summary',{},t.corpus+' '+(index+1)+' \u00b7 '+report.sources.length+' '+t.sources),
   el('p',{class:'muted'},row.written_at));card.append(corpus);
  for(const stage of ['prior_gap','current_change','later_development']){
   const section=el('section',{class:'lineage-stage'},el('h3',{},t[stage]));corpus.append(section);
   const items=report.statements.filter(s=>s.stage===stage);
   if(!items.length)section.append(el('p',{class:'muted'},t.empty));
   for(const item of items){
    const article=el('article',{},el('p',{class:'prose'},item.text),
     el('p',{class:'muted'},t.proposal+' \u00b7 '+t[item.judgment.status]),
     el('p',{class:'prose'},item.judgment.reason),
     el('p',{class:'muted'},t.relation+': '+t['function_'+item.function]));section.append(article);
    if(item.requirements.own_source_passage==='missing')article.append(el('p',{class:'muted'},t.ownMissing));
    if(item.requirements.citing_passage==='missing')article.append(el('p',{class:'muted'},t.citingMissing));
    if(item.requirements.citation_identity==='unresolved')article.append(el('p',{class:'muted'},t.identityUnresolved));
    const passages=el('details',{class:'lineage-passages'},el('summary',{},t.passages+' ('+item.passages.length+')'));article.append(passages);
    for(const p of item.passages){
     const source=sources.get(p.source_id),location=p.location;
     const entry=el('div',{class:'lineage-passage'},el('p',{class:'lineage-source'},source.identity.title),
      el('p',{class:'muted'},t['role_'+p.role]),el('blockquote',{},p.quote),el('p',{class:'muted'},t[location.state]+(location.state==='located'?' ? '+t.page+' '+location.page:'')));
     if(p.cites!==null)entry.append(el('p',{class:'muted'},t.references+': '+sources.get(p.cites).identity.title));
     if(actions&&source.availability==='available')entry.append(el('button',{type:'button',disabled:!actions.available(row,source.id)?'':null,onclick:()=>actions.open(row,source.id,location.state==='located'?location.page:null)},actions.label));
     passages.append(entry);
    }
   }
  }
  const originals=el('details',{class:'lineage-originals'},el('summary',{},report.sources.length+' '+t.sources),
   el('p',{class:'muted'},actions?actions.note:t.sourceNote));corpus.append(originals);
  for(const source of report.sources){const entry=el('div',{class:'lineage-passage'},
   el('p',{class:'lineage-source'},source.identity.title),el('p',{class:'muted'},source.availability==='available'?t.captured:t.unavailable),
   ...(source.document_hash?[el('p',{class:'muted'},t.version),el('code',{class:'lineage-version'},source.document_hash)]:[]));
   if(actions&&source.availability==='available')entry.append(el('button',{type:'button',disabled:!actions.available(row,source.id)?'':null,onclick:()=>actions.open(row,source.id,null)},actions.label));originals.append(entry);
  }
 });
}
