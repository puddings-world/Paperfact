/** Saved-only list overview. All research strings become literal text nodes. */
export const SURVEY_COPY={
  "en": {
    "title": "List research overview",
    "notSaved": "Report not downloaded.",
    "download": "Save report offline",
    "working": "Downloading report...",
    "ready": "Report saved offline",
    "update": "Saved report - update available",
    "retry": "Could not load the report. Retry when connected.",
    "sourceNote": "Retained excerpts; original PDFs download separately.",
    "sources": "Source records",
    "passages": "Source excerpts",
    "captured": "Original captured for this report",
    "unavailable": "Original unavailable",
    "not_selected": "Original not selected",
    "located": "Retained location",
    "missing": "Location unresolved"
  },
  "zh-TW": {
    "title": "\u6e05\u55ae\u7814\u7a76\u7d9c\u89bd",
    "notSaved": "\u5831\u544a\u5c1a\u672a\u4e0b\u8f09\u3002",
    "download": "\u5132\u5b58\u5831\u544a\u4f9b\u96e2\u7dda\u95b1\u8b80",
    "working": "\u6b63\u5728\u4e0b\u8f09\u5831\u544a...",
    "ready": "\u5831\u544a\u5df2\u5132\u5b58\uff0c\u53ef\u96e2\u7dda\u95b1\u8b80",
    "update": "\u5df2\u5132\u5b58\u5831\u544a\uff1b\u6709\u66f4\u65b0\u53ef\u4e0b\u8f09",
    "retry": "\u7121\u6cd5\u8f09\u5165\u5831\u544a\uff0c\u9023\u7dda\u5f8c\u8acb\u91cd\u8a66\u3002",
    "sourceNote": "\u6b64\u8655\u4fdd\u7559\u5f15\u7528\u6458\u9304\uff1b\u539f\u6587 PDF \u9700\u53e6\u5916\u4e0b\u8f09\u3002",
    "sources": "\u4f86\u6e90\u7d00\u9304",
    "passages": "\u5f15\u7528\u6458\u9304",
    "captured": "\u6b64\u5831\u544a\u5df2\u64f7\u53d6\u539f\u6587",
    "unavailable": "\u539f\u6587\u7121\u6cd5\u53d6\u5f97",
    "not_selected": "\u672a\u9078\u53d6\u539f\u6587",
    "located": "\u5df2\u8a18\u9304\u7684\u5f15\u7528\u4f4d\u7f6e",
    "missing": "\u5c1a\u672a\u5b9a\u4f4d\u5f15\u7528"
  }
};
Object.assign(SURVEY_COPY.en,{goal:'Research goal for this report',
  goalEmpty:'No research goal was provided.',goalUnknown:'This older report did not record a research goal.'});
Object.assign(SURVEY_COPY['zh-TW'],{goal:'\u9019\u4efd\u5831\u544a\u7684\u7814\u7a76\u76ee\u6a19',
  goalEmpty:'\u7576\u6642\u672a\u63d0\u4f9b\u7814\u7a76\u76ee\u6a19\u3002',
  goalUnknown:'\u820a\u5831\u544a\u672a\u8a18\u9304\u7576\u6642\u7684\u7814\u7a76\u76ee\u6a19\u3002'});
export function renderSurveys(panel,collection,rows,el,options={}){
  if(!collection)return;
  const selected=(rows??[]).filter(row=>row.list_id===collection.id);
  if(!selected.length)return;
  const t=SURVEY_COPY[options.language]??SURVEY_COPY.en;
  for(const row of selected){
    const status=el('p',{class:'muted','aria-live':'polite'},t.notSaved);
    const body=el('div',{}),button=el('button',{type:'button'},t.download);
    button.disabled=!options.canDownload;
    const card=el('section',{class:'card'},el('h2',{},t.title),status,button,body);
    panel.append(card);let pending=false;
    const current=()=>options.current?.()!==false;
    const show=result=>{
      if(!current())return;
      const report=result.body.report,names=new Map(report.inputs.members.map(member=>[member.paper_id,member.title]));
      status.replaceChildren(result.awaiting?t.update:t.ready);button.hidden=!result.awaiting;
      const goal=Object.hasOwn(report.inputs,'goal')?(report.inputs.goal||t.goalEmpty):t.goalUnknown;
      const contents=[el('h3',{},t.goal),el('p',{class:'prose'},goal),el('p',{class:'muted'},t.sourceNote)];
      for(const section of report.sections){
        const block=el('article',{},el('h3',{},section.heading));
        for(const item of section.statements){
          block.append(el('p',{class:'prose'},item.text));
          if(item.passages.length){
            const excerpts=el('details',{},el('summary',{},t.passages+' ('+item.passages.length+')'));
            for(const passage of item.passages)excerpts.append(el('blockquote',{class:'prose'},passage.quote),
              el('p',{class:'muted'},passage.location?.state==='located'?
                t.located+' - '+passage.location.page:t.missing));
            block.append(excerpts);
          }
        }
        contents.push(block);
      }
      const sources=el('details',{},el('summary',{},t.sources+' ('+report.sources.length+')'));
      let populated=false;sources.addEventListener('toggle',()=>{
        if(!sources.open||populated||!current())return;populated=true;
        for(const source of report.sources)sources.append(el('p',{},names.get(source.paper_id)??source.paper_id),
          el('p',{class:'muted'},t[source.state]));
      });contents.push(sources);body.replaceChildren(...contents);
    };
    if(options.read)void options.read(row.id).then(show).catch(()=>{});
    button.addEventListener('click',async()=>{
      if(pending||!options.canDownload||!current())return;
      pending=true;button.disabled=true;status.replaceChildren(t.working);
      try{await options.download(row.id);if(current())show(await options.read(row.id));}
      catch{if(current())status.replaceChildren(t.retry);}
      finally{pending=false;if(current())button.disabled=!options.canDownload;}
    });
  }
}
